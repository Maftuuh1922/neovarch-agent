// One gateway session as the phone shows it: the stored history from
// `session.resume`, plus live `message.* / reasoning.* / tool.*` events
// folded into ChatMsg rows the chat widgets already render. Pure Dart.
import 'dart:convert';

import '../data/gateway_client.dart';
import '../models/models.dart';

/// "langkah 9/30" while a turn runs. The core (Tempest v2, PR #39) grows the
/// limit before a step passes it and says so in a status message; an older
/// core could still report a step past its limit — then only the step shows
/// ("langkah 9"), never "9/3".
String? formatStepLabel(int? step, int? limit) {
  if (step == null || step <= 1) return null;
  if (limit != null && limit >= step) return 'langkah $step/$limit';
  return 'langkah $step';
}

/// The short counter for the compact bar: "9/30" or "9".
String? formatStepShort(int? step, int? limit) {
  if (step == null || step <= 1) return null;
  return limit != null && limit >= step ? '$step/$limit' : '$step';
}

/// What a stopped turn shows (same words as the desktop): title, one sentence,
/// and the one-tap "Lanjutkan".
const Map<String, dynamic> kStoppedInfo = {
  'code': 'stopped',
  'title': 'Dihentikan',
  'message': 'Dihentikan. Model, alat, dan perintah yang sedang berjalan sudah dibatalkan.',
  'action': 'continue',
  'action_label': 'Lanjutkan',
};

class RemoteTranscript {
  RemoteTranscript({List<ChatMsg>? history}) : messages = history ?? [];

  final List<ChatMsg> messages;
  ChatMsg? _cur;
  bool _afterTool = false;

  /// A turn is streaming (message.start seen, no message.complete yet).
  bool running = false;
  String? title;
  String? error;
  double? tokensPerSecond;
  int? contextPercent;

  /// Live step counter of the running turn (`turn.progress`, core ≥ 1.4.7).
  int? step;
  int? stepLimit;

  /// "langkah 27/150" while a long turn runs, else null.
  /// Never "9/3": a step past its limit (older cores) shows as "langkah 9".
  String? get stepLabel => running ? formatStepLabel(step, stepLimit) : null;
  String? get stepShort => running ? formatStepShort(step, stepLimit) : null;

  /// Live context use from `usage.update` (core ≥ 1.4.7), refreshed after every
  /// model call of the running turn, not only at turn end.
  int? contextTokens;
  int? contextWindow;
  int? sessionTokens;

  /// "konteks 42% · 54k/128k" (null until the PC reports usage).
  String? get contextLabel {
    final t = contextTokens, w = contextWindow;
    if (t == null || w == null || w <= 0) return null;
    String k(int n) => n >= 1000 ? '${(n / 1000).round()}k' : '$n';
    return 'konteks ${(100 * t / w).round()}% · ${k(t)}/${k(w)}';
  }

  ChatMsg _assistant() {
    final m = ChatMsg(
        id: 'a${DateTime.now().microsecondsSinceEpoch}', role: 'assistant', ts: DateTime.now().millisecondsSinceEpoch, streaming: true);
    messages.add(m);
    _cur = m;
    return m;
  }

  ChatMsg get _open => _cur ?? _assistant();

  /// Local echo of a prompt the phone just submitted.
  void addUser(String text, {List<Map<String, dynamic>> attachments = const []}) {
    _close();
    messages.add(ChatMsg(
        id: 'u${DateTime.now().microsecondsSinceEpoch}',
        role: 'user',
        content: text,
        ts: DateTime.now().millisecondsSinceEpoch,
        attachments: [...attachments]));
    running = true;
    error = null;
  }

  void _close() {
    final c = _cur;
    if (c != null) {
      c.streaming = false;
      for (final t in c.tools) {
        t.running = false;
      }
    }
    _cur = null;
    _afterTool = false;
  }

  /// Returns true when the frame changed what is shown.
  bool apply(GatewayEventFrame f) {
    final p = f.payload;
    switch (f.type) {
      case 'turn.progress':
        step = (p['step'] as num?)?.toInt() ?? step;
        stepLimit = (p['limit'] as num?)?.toInt() ?? stepLimit;
        running = true;
      case 'usage.update':
        contextTokens = (p['context_tokens'] as num?)?.toInt() ?? contextTokens;
        contextWindow = (p['context_window'] as num?)?.toInt() ?? contextWindow;
        contextPercent = (p['context_percent'] as num?)?.round() ?? contextPercent;
        final s = p['session'];
        if (s is Map) sessionTokens = (s['total'] as num?)?.toInt() ?? sessionTokens;
      case 'message.start':
        running = true;
        error = null;
        step = null;
        stepLimit = null;
        _close();
        _assistant();
      case 'message.delta':
        final t = '${p['text'] ?? ''}';
        if (t.isEmpty) return false;
        if (_afterTool) {
          _cur?.streaming = false;
          _assistant();
          _afterTool = false;
        }
        running = true;
        _open.content += t;
      case 'reasoning.delta' || 'thinking.delta':
        final t = '${p['text'] ?? ''}';
        if (t.isEmpty) return false;
        _open.reasoning += t;
      case 'tool.start':
        final args = p['args_text'] ?? p['preview'] ?? (p['args'] is Map ? jsonEncode(p['args']) : p['args']);
        _open.tools.add(ToolActivity(id: '${p['tool_id'] ?? ''}', name: '${p['name'] ?? 'alat'}', args: '${args ?? ''}'));
      case 'tool.complete':
        final id = '${p['tool_id'] ?? ''}';
        final cur = _open;
        final t = cur.tools.where((x) => x.id == id).firstOrNull;
        final result = (p['result_text'] ?? p['result'])?.toString();
        final summary = p['summary'] as String?;
        final failed = p['error'] != null || (summary ?? '').toLowerCase().startsWith('error');
        final dur = (p['duration_s'] as num?)?.toDouble();
        if (t != null) {
          t
            ..running = false
            ..summary = summary
            ..result = result
            ..failed = failed
            ..durationS = dur;
        } else {
          cur.tools.add(ToolActivity(
              id: id, name: '${p['name'] ?? 'alat'}', summary: summary, result: result, running: false, failed: failed, durationS: dur));
        }
        _afterTool = true;
      case 'message.attachment':
        // A file the PC agent sent into the chat (send_file): same schema as uploads.
        final a = p['attachment'];
        if (a is! Map) return false;
        return _addAgentAttachments([Map<String, dynamic>.from(a)], _open);
      case 'session.title':
        title = '${p['title'] ?? ''}';
      case 'message.complete':
        final text = p['text'] is String ? p['text'] as String : '';
        final stopped = p['status'] == 'interrupted' || p['error'] == 'interrupted';
        // Stop pressed (here or on the PC): a plain "Dihentikan" note with one tap to
        // continue, never the raw word "interrupted" as an error.
        final err = stopped ? kStoppedInfo['message'] as String : (p['error'] ?? p['failure_reason'])?.toString();
        final cur = _cur;
        if (text.isNotEmpty && (cur == null || (cur.content.isEmpty && !_afterTool))) {
          _open.content = text;
        } else if (text.isNotEmpty && _afterTool) {
          _assistant().content = text;
        }
        final info = stopped ? (p['error_info'] ?? kStoppedInfo) : p['error_info'];
        if (err != null && err.isNotEmpty && err != error) {
          // Not shown yet by an `error` event of this turn.
          error = err;
          _open.error = err;
          if (info is Map) _open.errorInfo = Map<String, dynamic>.from(info);
        } else if (info is Map) {
          final host = _lastWithError();
          if (host != null) host.errorInfo ??= Map<String, dynamic>.from(info);
        }
        final sent = [for (final a in (p['attachments'] as List? ?? const []).whereType<Map>()) Map<String, dynamic>.from(a)];
        if (sent.isNotEmpty) _addAgentAttachments(sent, _cur ?? _lastAssistant() ?? _open);
        final u = p['usage'];
        if (u is Map) {
          tokensPerSecond = (u['avg_tps'] as num?)?.toDouble() ?? tokensPerSecond;
          contextPercent = (u['context_percent'] as num?)?.toInt() ?? contextPercent;
        }
        running = false;
        _close();
        _dropEmptyTail();
      case 'error':
        final m = '${p['message'] ?? 'galat gateway'}';
        error = m;
        _open.error = m;
        if (p['code'] != null) _open.errorInfo = Map<String, dynamic>.from(p);
        running = false;
        _close();
      default:
        return false;
    }
    return true;
  }

  ChatMsg? _lastWithError() {
    for (var i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role == 'user') return null;
      if (messages[i].error != null) return messages[i];
    }
    return null;
  }

  ChatMsg? _lastAssistant() {
    for (var i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role == 'user') return null; // only this turn's reply
      if (messages[i].role == 'assistant') return messages[i];
    }
    return null;
  }

  /// Adds files the agent sent to [host], skipping ids already shown anywhere in
  /// this turn (the live `message.attachment` and the final `message.complete`
  /// both carry them).
  bool _addAgentAttachments(List<Map<String, dynamic>> atts, ChatMsg host) {
    final shown = {for (final m in messages) for (final a in m.attachments) '${a['id']}'};
    var changed = false;
    for (final a in atts) {
      final id = '${a['id'] ?? ''}';
      if (id.isEmpty || shown.contains(id)) continue;
      host.attachments.add(a);
      shown.add(id);
      changed = true;
    }
    return changed;
  }

  void _dropEmptyTail() {
    if (messages.isEmpty) return;
    final last = messages.last;
    if (last.role == 'assistant' && last.content.isEmpty && last.tools.isEmpty && last.reasoning.isEmpty && last.error == null &&
        last.attachments.isEmpty) {
      messages.removeLast();
    }
  }

  /// The connection dropped mid-turn: stop spinners (resume re-syncs).
  void interrupted() {
    running = false;
    _close();
    _dropEmptyTail();
  }

  /// `session.resume` / `session.create` `messages` → display rows. Tool
  /// rows attach to the assistant message before them.
  static List<ChatMsg> fromGatewayMessages(List<dynamic> raw) {
    final out = <ChatMsg>[];
    var i = 0;
    for (final m in raw.whereType<Map>()) {
      final role = '${m['role'] ?? ''}';
      var content = m['text'] ?? m['content'] ?? '';
      if (content is List) {
        content = content.whereType<Map>().map((p) => p['text'] ?? '').where((t) => '$t'.isNotEmpty).join('\n');
      }
      final ts = ((m['timestamp'] as num?)?.toDouble() ?? 0) * 1000;
      if (role == 'user') {
        final atts = [for (final a in (m['attachments'] as List? ?? const []).whereType<Map>()) Map<String, dynamic>.from(a)];
        out.add(ChatMsg(id: 'h${i++}', role: 'user', content: '$content', ts: ts.toInt(), attachments: atts));
      } else if (role == 'assistant') {
        final atts = [for (final a in (m['attachments'] as List? ?? const []).whereType<Map>()) Map<String, dynamic>.from(a)];
        out.add(ChatMsg(
            id: 'h${i++}', role: 'assistant', content: '$content', reasoning: '${m['reasoning'] ?? ''}', ts: ts.toInt(), attachments: atts));
      } else if (role == 'tool') {
        final host = out.isNotEmpty && out.last.role == 'assistant'
            ? out.last
            : (out..add(ChatMsg(id: 'h${i++}', role: 'assistant', ts: ts.toInt()))).last;
        final args = m['args'] is Map ? jsonEncode(m['args']) : '${m['context'] ?? ''}';
        final text = '$content';
        host.tools.add(ToolActivity(
          id: '${m['tool_call_id'] ?? 'h$i'}',
          name: '${m['name'] ?? 'alat'}',
          args: args,
          result: text,
          summary: text.length > 90 ? '${text.substring(0, 90)}…' : text,
          running: false,
        ));
      }
    }
    return out;
  }
}
