// Transcript pieces: user bubble, assistant message (markdown, reasoning
// disclosure, tool rows with structured summaries), failure card that names
// the failing layer, approval card.
import 'dart:convert';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../models/models.dart';
import '../../../remote/evidence.dart';
import '../../../remote/ui/glass/liquid_glass.dart' show GlassForeground;
import '../../../theme/app_theme.dart';
import '../../widgets/common.dart';
import '../../widgets/markdown_view.dart';
import '../../widgets/preview_sheet.dart';

typedef OpenFile = void Function(String path);

class UserBubble extends StatelessWidget {
  const UserBubble({super.key, required this.msg, required this.scale});
  final ChatMsg msg;
  final double scale;
  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerRight,
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: math.min(560, MediaQuery.sizeOf(context).width * 0.84)),
        child: Container(
          margin: const EdgeInsets.only(left: 40),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          decoration: BoxDecoration(
            color: context.hc.userBubble,
            border: Border.all(color: context.hc.userBubbleBorder),
            borderRadius: BorderRadius.circular(14),
          ),
          child: Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
            if (msg.images.isNotEmpty)
              Wrap(spacing: 6, runSpacing: 6, children: [
                for (final img in msg.images)
                  ClipRRect(
                    borderRadius: BorderRadius.circular(8),
                    child: _dataImage(img, 120),
                  ),
              ]),
            if (msg.images.isNotEmpty && msg.content.isNotEmpty) const SizedBox(height: 8),
            if (msg.content.isNotEmpty) SelectableText(msg.content, style: TextStyle(fontSize: 14.5 * scale, height: 1.45)),
          ]),
        ),
      ),
    );
  }
}

Widget _dataImage(String dataUrl, double size) {
  try {
    final b64 = dataUrl.substring(dataUrl.indexOf(',') + 1);
    return Image.memory(base64Decode(b64), width: size, height: size, fit: BoxFit.cover);
  } catch (_) {
    return SizedBox(width: size, height: size, child: const Icon(Icons.broken_image_outlined));
  }
}

class AssistantMessage extends StatelessWidget {
  const AssistantMessage({
    super.key,
    required this.msg,
    required this.scale,
    required this.showReasoning,
    this.autoCollapse = true,
    this.onRegenerate,
    required this.onLink,
    required this.onOpenFile,
    this.onSpeak,
    this.onRetry,
    this.onSwitchProvider,
    this.isLast = false,
  });
  final ChatMsg msg;
  final double scale;
  final bool showReasoning;
  final bool autoCollapse;
  final VoidCallback? onRegenerate;
  final void Function(String url) onLink;
  final OpenFile onOpenFile;
  final VoidCallback? onSpeak;
  final VoidCallback? onRetry;
  final VoidCallback? onSwitchProvider;
  final bool isLast;

  @override
  Widget build(BuildContext context) {
    // A finished report folds its evidence into a compact "Bukti" section.
    final ({String main, String? evidence}) parts =
        msg.streaming ? (main: msg.content, evidence: null) : splitEvidence(msg.content);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      if (showReasoning && msg.reasoning.trim().isNotEmpty)
        ReasoningBlock(text: msg.reasoning, streaming: msg.streaming && msg.content.isEmpty, autoCollapse: autoCollapse),
      for (final t in msg.tools) ToolRow(tool: t, onOpenFile: onOpenFile, onLink: onLink),
      if (msg.content.isNotEmpty) ...[
        if (msg.tools.isNotEmpty) const SizedBox(height: 6),
        MarkdownView(parts.main, onLink: onLink, scale: scale),
        if (parts.evidence != null) EvidenceBlock(text: parts.evidence!, onLink: onLink, scale: scale),
        if (msg.streaming) Padding(padding: const EdgeInsets.only(top: 2), child: Align(alignment: Alignment.centerLeft, child: BlinkingCaret(height: 15 * scale))),
      ],
      if (msg.streaming && msg.content.isEmpty && msg.tools.every((t) => !t.running) && msg.reasoning.isEmpty)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: Row(children: [
            const NvLoader(size: 16),
            const SizedBox(width: 10),
            const TypingDots(size: 5),
            const SizedBox(width: 8),
            ShimmerText('menyusun jawaban', style: context.tt.bodySmall),
          ]),
        ),
      if (msg.error != null) FailureCard(message: msg.error!, onRetry: onRetry, onSwitchProvider: onSwitchProvider),
      if (!msg.streaming && msg.content.isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(top: 2),
          child: Row(children: [
            _MiniAction(icon: Icons.copy_rounded, tip: 'Salin', onTap: () {
              Clipboard.setData(ClipboardData(text: msg.content));
              toast(context, 'Disalin');
            }),
            if (onSpeak != null) _MiniAction(icon: Icons.volume_up_outlined, tip: 'Bacakan', onTap: onSpeak!),
            if (onRegenerate != null) _MiniAction(icon: Icons.refresh, tip: 'Buat ulang', onTap: onRegenerate!)
            else if (isLast && onRetry != null) _MiniAction(icon: Icons.refresh, tip: 'Ulangi', onTap: onRetry!),
            const Spacer(),
            if (msg.ts > 0) Text(clockOf(msg.ts), style: context.tt.bodySmall?.copyWith(fontSize: 11)),
          ]),
        ),
    ]);
  }
}

class _MiniAction extends StatelessWidget {
  const _MiniAction({required this.icon, required this.tip, required this.onTap});
  final IconData icon;
  final String tip;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => IconButton(
        tooltip: tip,
        onPressed: onTap,
        iconSize: 16,
        visualDensity: VisualDensity.compact,
        color: context.hc.mutedForeground,
        icon: Icon(icon),
      );
}

/// "Bukti": the evidence, limitations and next step of a report, folded by default.
class EvidenceBlock extends StatefulWidget {
  const EvidenceBlock({super.key, required this.text, required this.onLink, required this.scale});
  final String text;
  final void Function(String url) onLink;
  final double scale;
  @override
  State<EvidenceBlock> createState() => _EvidenceBlockState();
}

class _EvidenceBlockState extends State<EvidenceBlock> {
  bool open = false;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        InkWell(
          key: const ValueKey('evidence-toggle'),
          onTap: () => setState(() => open = !open),
          borderRadius: BorderRadius.circular(12),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration: BoxDecoration(
              border: Border.all(color: context.hc.border),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.fact_check_outlined, size: 15, color: context.hc.mutedForeground),
              const SizedBox(width: 6),
              Text('Bukti', style: context.tt.bodySmall?.copyWith(fontWeight: FontWeight.w600)),
              AnimatedRotation(
                turns: open ? 0.5 : 0,
                duration: motionFast,
                child: Icon(Icons.expand_more, size: 16, color: context.hc.mutedForeground),
              ),
            ]),
          ),
        ),
        AnimatedSize(
          duration: reduceMotion(context) ? Duration.zero : motionBase,
          curve: motionCurve,
          alignment: Alignment.topLeft,
          child: open
              ? Container(
                  key: const ValueKey('evidence-body'),
                  margin: const EdgeInsets.only(top: 6),
                  padding: const EdgeInsets.only(left: 10),
                  decoration: BoxDecoration(border: Border(left: BorderSide(color: context.hc.border, width: 2))),
                  child: MarkdownView(widget.text, onLink: widget.onLink, scale: widget.scale * 0.94),
                )
              : const SizedBox(width: double.infinity),
        ),
      ]),
    );
  }
}

class ReasoningBlock extends StatefulWidget {
  const ReasoningBlock({super.key, required this.text, required this.streaming, this.autoCollapse = true});
  final String text;
  final bool streaming;
  final bool autoCollapse;
  @override
  State<ReasoningBlock> createState() => _ReasoningBlockState();
}

class _ReasoningBlockState extends State<ReasoningBlock> {
  bool open = false;
  final _sw = Stopwatch();
  int? _secs;

  @override
  void initState() {
    super.initState();
    if (widget.streaming) _sw.start();
  }

  @override
  void didUpdateWidget(ReasoningBlock old) {
    super.didUpdateWidget(old);
    if (old.streaming && !widget.streaming) {
      _sw.stop();
      _secs = (_sw.elapsedMilliseconds / 1000).round();
      // Desktop: the thought folds away when the answer starts (unless pinned).
      if (!widget.autoCollapse) open = true;
    }
  }

  @override
  Widget build(BuildContext context) {
    final show = open || widget.streaming;
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        InkWell(
          onTap: () => setState(() => open = !open),
          borderRadius: BorderRadius.circular(4),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              _PulseIcon(active: widget.streaming),
              const SizedBox(width: 6),
              if (widget.streaming)
                ShimmerText('Berpikir…', style: context.tt.bodySmall?.copyWith(fontWeight: FontWeight.w600))
              else
                Text(_secs != null && _secs! > 0 ? 'Berpikir selama $_secs dtk' : 'Penalaran', style: context.tt.bodySmall?.copyWith(fontWeight: FontWeight.w600)),
              AnimatedRotation(
                turns: show ? 0.5 : 0,
                duration: motionFast,
                child: Icon(Icons.expand_more, size: 16, color: context.hc.mutedForeground),
              ),
            ]),
          ),
        ),
        AnimatedSize(
          duration: reduceMotion(context) ? Duration.zero : motionBase,
          curve: motionCurve,
          alignment: Alignment.topLeft,
          child: show
              ? Container(
                  constraints: const BoxConstraints(maxHeight: 200),
                  padding: const EdgeInsets.only(left: 10),
                  decoration: BoxDecoration(border: Border(left: BorderSide(color: context.hc.border, width: 2))),
                  child: SingleChildScrollView(
                    reverse: widget.streaming,
                    child: Text(widget.text.trim(), style: context.tt.bodySmall?.copyWith(fontStyle: FontStyle.italic, height: 1.45)),
                  ),
                )
              : const SizedBox(width: double.infinity),
        ),
      ]),
    );
  }
}

/// Brain icon that breathes while the model is thinking.
class _PulseIcon extends StatefulWidget {
  const _PulseIcon({required this.active});
  final bool active;
  @override
  State<_PulseIcon> createState() => _PulseIconState();
}

class _PulseIconState extends State<_PulseIcon> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 1200));
  @override
  void initState() {
    super.initState();
    if (widget.active) _c.repeat(reverse: true);
  }

  @override
  void didUpdateWidget(_PulseIcon old) {
    super.didUpdateWidget(old);
    if (widget.active && !_c.isAnimating) _c.repeat(reverse: true);
    if (!widget.active) _c.stop();
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final icon = Icon(Icons.psychology_alt_outlined, size: 15, color: widget.active ? context.cs.primary : context.hc.mutedForeground);
    if (!widget.active || reduceMotion(context)) return icon;
    return ScaleTransition(scale: Tween(begin: 0.85, end: 1.12).animate(CurvedAnimation(parent: _c, curve: Curves.easeInOut)), child: icon);
  }
}

IconData toolIcon(String name) {
  if (name.startsWith('memory')) return Icons.bookmark_border;
  if (name.startsWith('office') || name.contains('agent')) return Icons.apartment_outlined;
  if (name.contains('meeting')) return Icons.groups_2_outlined;
  if (name.contains('cron')) return Icons.schedule_send_outlined;
  if (name.startsWith('device')) return Icons.smartphone;
  if (name.startsWith('clipboard')) return Icons.content_paste;
  if (name == 'open_intent') return Icons.open_in_new;
  if (name == 'notify') return Icons.notifications_none;
  if (name.startsWith('location')) return Icons.place_outlined;
  if (name.startsWith('contacts')) return Icons.contacts_outlined;
  if (name.startsWith('calendar')) return Icons.event_outlined;
  if (name.startsWith('apps')) return Icons.apps;
  if (name.startsWith('storage') || name == 'document_pick') return Icons.folder_open_outlined;
  if (name.startsWith('camera')) return Icons.photo_camera_outlined;
  if (name.contains('task')) return Icons.view_kanban_outlined;
  if (name.contains('web') || name.contains('fetch') || name.contains('browser')) return Icons.public;
  if (name.startsWith('file') || name.contains('read') || name.contains('write')) return Icons.description_outlined;
  if (name.contains('time')) return Icons.schedule;
  if (name.contains('skill')) return Icons.auto_awesome_motion_outlined;
  if (name.contains('terminal') || name.contains('shell') || name.contains('exec')) return Icons.terminal;
  if (name.contains('search')) return Icons.search;
  return Icons.build_outlined;
}

/// Output files a document tool reported (`pptx: /path/deck.pptx`,
/// `docx: …` from ppt_export / report_export), so the chat can offer them.
final _producedLine = RegExp(r'^(pptx|docx|pdf|md):\s*(\S.*?)\s*$', multiLine: true);

List<String> producedFiles(ToolActivity t) {
  if (t.running || t.failed || (t.name != 'ppt_export' && t.name != 'report_export')) return const [];
  return [for (final m in _producedLine.allMatches(t.result ?? '')) m.group(2)!];
}

/// One tool call: icon, name, structured summary, duration; expands to
/// arguments and output. A result may OFFER a preview — never opens it.
class ToolRow extends StatefulWidget {
  const ToolRow({super.key, required this.tool, required this.onOpenFile, required this.onLink});
  final ToolActivity tool;
  final OpenFile onOpenFile;
  final void Function(String url) onLink;
  @override
  State<ToolRow> createState() => _ToolRowState();
}

class _ToolRowState extends State<ToolRow> {
  bool open = false;

  Map<String, dynamic> get _args {
    try {
      final d = jsonDecode(widget.tool.args);
      return d is Map ? Map<String, dynamic>.from(d) : {};
    } catch (_) {
      return {};
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = widget.tool;
    final args = _args;
    final url = (t.name == 'web_fetch' || t.name.contains('browser')) ? args['url'] as String? : null;
    final path = (t.name == 'file_write' || t.name == 'file_read') ? args['path'] as String? : null;
    final color = t.failed ? context.hc.destructive : context.hc.mutedForeground;
    final summary = t.running ? _runningLabel(t.name, args) : (t.summary ?? (t.failed ? 'gagal' : 'selesai'));
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 1),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        InkWell(
          borderRadius: BorderRadius.circular(6),
          onTap: () => setState(() => open = !open),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 5, horizontal: 2),
            child: Row(children: [
              SizedBox(
                width: 18,
                height: 18,
                child: t.running
                    ? Padding(padding: const EdgeInsets.all(2), child: CircularProgressIndicator(strokeWidth: 1.6, color: context.cs.primary))
                    : Icon(t.failed ? Icons.error_outline : toolIcon(t.name), size: 16, color: color),
              ),
              const SizedBox(width: 8),
              Text(t.name, style: monoStyle(context, size: 12, color: context.cs.onSurface, weight: FontWeight.w600)),
              const SizedBox(width: 8),
              Expanded(
                child: AnimatedSwitcher(
                  duration: motionFast,
                  layoutBuilder: (cur, prev) => Stack(alignment: Alignment.centerLeft, children: [...prev, ?cur]),
                  child: t.running
                      ? ShimmerText(summary, key: const ValueKey('run'), style: context.tt.bodySmall)
                      : Text(summary, key: const ValueKey('done'), maxLines: 1, overflow: TextOverflow.ellipsis, style: context.tt.bodySmall?.copyWith(color: t.failed ? color : null)),
                ),
              ),
              if (t.durationS != null) Text(' ${t.durationS!.toStringAsFixed(1)}s', style: monoStyle(context, size: 10.5, color: context.hc.mutedForeground)),
              AnimatedRotation(turns: open ? 0.5 : 0, duration: motionFast, child: Icon(Icons.expand_more, size: 16, color: context.hc.mutedForeground)),
            ]),
          ),
        ),
        if (!t.running && (url != null || path != null))
          Padding(
            padding: const EdgeInsets.only(left: 26, bottom: 2),
            child: Align(
              alignment: Alignment.centerLeft,
              child: TextButton.icon(
                style: TextButton.styleFrom(visualDensity: VisualDensity.compact, padding: const EdgeInsets.symmetric(horizontal: 8)),
                onPressed: () => url != null ? widget.onLink(url) : widget.onOpenFile(path!),
                icon: Icon(url != null ? Icons.open_in_browser : Icons.visibility_outlined, size: 16),
                label: Text(url != null ? 'Pratinjau halaman' : 'Buka $path', style: const TextStyle(fontSize: 12.5)),
              ),
            ),
          ),
        for (final f in producedFiles(t))
          Padding(
            padding: const EdgeInsets.only(left: 26, bottom: 2),
            child: Align(
              alignment: Alignment.centerLeft,
              child: TextButton.icon(
                key: ValueKey('nv-produced-$f'),
                style: TextButton.styleFrom(visualDensity: VisualDensity.compact, padding: const EdgeInsets.symmetric(horizontal: 8)),
                onPressed: () => widget.onOpenFile(f),
                icon: Icon(f.toLowerCase().endsWith('.pptx') ? Icons.slideshow_outlined : Icons.download_outlined, size: 16),
                label: Text('Unduh ${f.split(RegExp(r'[\\/]')).last}', style: const TextStyle(fontSize: 12.5)),
              ),
            ),
          ),
        AnimatedSize(
          duration: reduceMotion(context) ? Duration.zero : motionBase,
          curve: motionCurve,
          alignment: Alignment.topLeft,
          child: !open
              ? const SizedBox(width: double.infinity)
              : Padding(
            padding: const EdgeInsets.only(left: 26, bottom: 6),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              if (t.args.isNotEmpty && t.args != '{}') ...[
                Text('argumen', style: context.tt.labelSmall),
                const SizedBox(height: 4),
                LogView(_pretty(t.args), maxHeight: 140),
                const SizedBox(height: 8),
              ],
              Text('keluaran', style: context.tt.labelSmall),
              const SizedBox(height: 4),
              LogView(t.result ?? '', maxHeight: 220, empty: t.running ? 'berjalan…' : '(tanpa keluaran)'),
              if ((t.result ?? '').length > 400)
                Align(
                  alignment: Alignment.centerLeft,
                  child: TextButton(
                    onPressed: () => showPreview(context, TextPreview('${t.name} · keluaran', t.result!)),
                    child: const Text('Buka di panel pratinjau'),
                  ),
                ),
            ]),
          ),
        ),
      ]),
    );
  }

  String _runningLabel(String name, Map<String, dynamic> a) => switch (name) {
        'web_fetch' => 'mengambil ${Uri.tryParse('${a['url'] ?? ''}')?.host ?? ''}…',
        'file_write' => 'menulis ${a['path'] ?? ''}…',
        'file_read' => 'membaca ${a['path'] ?? ''}…',
        'memory_write' => 'menyimpan ke memori…',
        'create_task' => 'membuat tugas…',
        _ => 'berjalan…',
      };

  String _pretty(String raw) {
    try {
      return const JsonEncoder.withIndent('  ').convert(jsonDecode(raw));
    } catch (_) {
      return raw;
    }
  }
}

/// Failed turns name the failing layer, with matching recovery actions.
class FailureCard extends StatelessWidget {
  const FailureCard({super.key, required this.message, this.onRetry, this.onSwitchProvider});
  final String message;
  final VoidCallback? onRetry;
  final VoidCallback? onSwitchProvider;

  (String, bool) get _layer {
    final m = message.toLowerCase();
    if (m.contains('401') || m.contains('kunci') || m.contains('api key') || m.contains('unauthorized')) return ('Autentikasi penyedia', true);
    if (m.contains('402') || m.contains('credit') || m.contains('billing') || m.contains('quota')) return ('Tagihan / kuota penyedia', true);
    if (m.contains('429') || m.contains('rate')) return ('Batas laju penyedia', true);
    if (m.contains('404') || m.contains('model')) return ('Model / endpoint', true);
    if (m.contains('gateway')) return ('Gateway', false);
    if (m.contains('belum diatur')) return ('Penyedia belum diatur', true);
    if (m.contains('terputus') || m.contains('menghubungi') || m.contains('socket') || m.contains('timeout') || m.contains('detik')) {
      return ('Koneksi streaming', false);
    }
    return ('Penyedia / model', true);
  }

  @override
  Widget build(BuildContext context) {
    final (layer, provider) = _layer;
    final c = context.hc.destructive;
    // On liquid glass (phone remote): neutral inset, only the icon is red.
    final glass = GlassForeground.maybeOf(context)?.tone;
    return Container(
      margin: const EdgeInsets.only(top: 6),
      padding: const EdgeInsets.fromLTRB(12, 10, 8, 4),
      decoration: BoxDecoration(
        color: glass != null ? glass.text.withValues(alpha: 0.06) : c.withValues(alpha: 0.06),
        border: Border.all(color: glass != null ? glass.text.withValues(alpha: 0.14) : c.withValues(alpha: 0.35)),
        borderRadius: BorderRadius.circular(glass != null ? 14 : 8),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Icon(Icons.error_outline, size: 17, color: c),
          const SizedBox(width: 8),
          Expanded(child: Text('Giliran gagal · $layer', style: context.tt.titleSmall)),
        ]),
        const SizedBox(height: 6),
        SelectableText(message, style: context.tt.bodySmall?.copyWith(color: context.cs.onSurface)),
        Wrap(spacing: 4, children: [
          if (onRetry != null) TextButton.icon(onPressed: onRetry, icon: const Icon(Icons.refresh, size: 16), label: const Text('Coba lagi')),
          if (provider && onSwitchProvider != null)
            TextButton.icon(onPressed: onSwitchProvider, icon: const Icon(Icons.swap_horiz, size: 16), label: const Text('Ganti penyedia')),
          TextButton.icon(
            onPressed: () {
              Clipboard.setData(ClipboardData(text: 'layer: $layer\n$message'));
              toast(context, 'Detail galat disalin');
            },
            icon: const Icon(Icons.copy_rounded, size: 16),
            label: const Text('Salin detail'),
          ),
        ]),
      ]),
    );
  }
}

class ApprovalCard extends StatelessWidget {
  const ApprovalCard({super.key, required this.command, required this.description, required this.choices, required this.onChoice});
  final String command;
  final String description;
  final List<String> choices;
  final void Function(String) onChoice;

  String _label(String c) => switch (c) {
        'once' => 'Izinkan sekali',
        'session' => 'Izinkan sesi ini',
        'always' => 'Selalu izinkan',
        'deny' => 'Tolak',
        _ => c,
      };

  @override
  Widget build(BuildContext context) => PaperScope(child: Builder(builder: _card));

  Widget _card(BuildContext context) => Container(
        margin: const EdgeInsets.fromLTRB(12, 0, 12, 8),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: context.hc.popover,
          borderRadius: BorderRadius.circular(context.hc.corner + 2),
          border: Border.all(color: context.hc.paper == null && !context.hc.brand ? context.hc.warning.withValues(alpha: 0.6) : context.cs.primary),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [
            Icon(Icons.shield_outlined, size: 18, color: context.hc.warning),
            const SizedBox(width: 8),
            Text('Perlu persetujuan', style: context.tt.titleSmall),
          ]),
          if (description.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 6), child: Text(description, style: context.tt.bodySmall)),
          const SizedBox(height: 8),
          LogView(command, maxHeight: 120),
          const SizedBox(height: 8),
          Wrap(spacing: 8, runSpacing: 6, children: [
            for (final c in choices)
              c == 'deny'
                  ? OutlinedButton(onPressed: () => onChoice(c), child: Text(_label(c)))
                  : FilledButton(onPressed: () => onChoice(c), child: Text(_label(c))),
          ]),
        ]),
      );
}
