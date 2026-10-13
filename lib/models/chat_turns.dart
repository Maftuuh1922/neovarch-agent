// One bubble per agent turn (1.4.8): the transcript keeps one ChatMsg per
// model step (reasoning + tool calls + a short line of narration), which used
// to render as a stack of separate cards. These pure helpers fold the steps
// between two user messages into one turn with a timeline and a final answer.
// Pure Dart (no Flutter) so the grouping is unit-tested on its own.
import 'models.dart';

/// A row of the chat list: the person's message or one whole agent turn.
sealed class ChatItem {
  const ChatItem();

  /// Stable list key (the first message of the item).
  String get key;
}

class UserChatItem extends ChatItem {
  const UserChatItem(this.msg);
  final ChatMsg msg;
  @override
  String get key => msg.id;
}

enum TurnEntryKind { reasoning, narration, tool }

/// One line of a turn's timeline.
class TurnEntry {
  const TurnEntry._(this.kind, this.step, {this.tool, this.live = false, required this.key});

  final TurnEntryKind kind;

  /// The step (ChatMsg) this entry comes from.
  final ChatMsg step;

  /// Set for [TurnEntryKind.tool].
  final ToolActivity? tool;

  /// Reasoning still streaming (only meaningful for [TurnEntryKind.reasoning]).
  final bool live;

  /// Stable widget key, so expanded/collapsed state survives rebuilds.
  final String key;

  String get text => switch (kind) {
        TurnEntryKind.reasoning => step.reasoning,
        TurnEntryKind.narration => step.content,
        TurnEntryKind.tool => tool?.name ?? '',
      };
}

class AgentTurnItem extends ChatItem {
  AgentTurnItem(this.steps) : assert(steps.isNotEmpty);

  /// The agent's messages of this turn, oldest first (never empty).
  final List<ChatMsg> steps;

  @override
  String get key => steps.first.id;

  /// Still running: some step is streaming.
  bool get live => steps.any((s) => s.streaming);

  /// The step whose text is the turn's answer: the last step when it has text
  /// and no tool calls (text after the last tool). A finished turn whose last
  /// step still had tools keeps that step's text as the answer too; a running
  /// one shows it as narration until the agent is done.
  ChatMsg? get answerStep {
    final l = steps.last;
    if (l.content.trim().isEmpty) return null;
    if (l.tools.isNotEmpty && live) return null;
    return l;
  }

  String get answer => answerStep?.content ?? '';

  /// What "Salin" copies: the answer, else every line of narration.
  String get copyText {
    final a = answer;
    if (a.trim().isNotEmpty) return a;
    return [for (final s in steps) if (s.content.trim().isNotEmpty) s.content.trim()].join('\n\n');
  }

  /// The newest step that failed or was stopped (shown once, at the bottom).
  ChatMsg? get errorStep {
    for (var i = steps.length - 1; i >= 0; i--) {
      if (steps[i].error != null) return steps[i];
    }
    return null;
  }

  /// Timestamp of the turn (its newest step with one).
  int get ts {
    for (var i = steps.length - 1; i >= 0; i--) {
      if (steps[i].ts > 0) return steps[i].ts;
    }
    return 0;
  }

  /// Files the agent sent during the turn, in order, without duplicate ids.
  List<Map<String, dynamic>> get attachments {
    final seen = <String>{};
    return [
      for (final s in steps)
        for (final a in s.attachments)
          if (seen.add('${a['id'] ?? identityHashCode(a)}')) a,
    ];
  }

  /// The live timeline: per step its reasoning, its narration (text the model
  /// wrote before calling tools) and its tool calls. The answer's text is not
  /// part of it.
  List<TurnEntry> get timeline {
    final answer = answerStep;
    final out = <TurnEntry>[];
    for (final s in steps) {
      if (s.reasoning.trim().isNotEmpty) {
        out.add(TurnEntry._(TurnEntryKind.reasoning, s,
            live: s.streaming && s.content.isEmpty && s.tools.isEmpty, key: 'r-${s.id}'));
      }
      if (!identical(s, answer) && s.content.trim().isNotEmpty) {
        out.add(TurnEntry._(TurnEntryKind.narration, s, key: 'n-${s.id}'));
      }
      for (var i = 0; i < s.tools.length; i++) {
        final t = s.tools[i];
        out.add(TurnEntry._(TurnEntryKind.tool, s, tool: t, key: 't-${s.id}-$i-${t.id}'));
      }
    }
    return out;
  }
}

/// Folds a transcript into rows: every user message is its own row; all agent
/// messages (assistant, tool, system) up to the next user message form one turn.
List<ChatItem> groupTurns(List<ChatMsg> msgs) {
  final out = <ChatItem>[];
  List<ChatMsg>? open;
  for (final m in msgs) {
    if (m.role == 'user') {
      open = null;
      out.add(UserChatItem(m));
      continue;
    }
    if (open == null) {
      open = <ChatMsg>[m];
      out.add(AgentTurnItem(open));
    } else {
      open.add(m);
    }
  }
  return out;
}

/// A long timeline folds its older entries behind "+N langkah": with more than
/// [threshold] entries and not [expanded], only the newest [keepLast] show.
({int hidden, List<TurnEntry> visible}) foldTimeline(List<TurnEntry> entries,
    {bool expanded = false, int threshold = 6, int keepLast = 4}) {
  if (expanded || entries.length <= threshold) return (hidden: 0, visible: entries);
  final hidden = entries.length - keepLast;
  return (hidden: hidden, visible: entries.sublist(hidden));
}
