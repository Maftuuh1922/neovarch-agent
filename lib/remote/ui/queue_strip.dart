// Antrean pesan (v1.4.7): messages sent while the agent works, held by the PC
// (phone and desktop show the same list). Each can be edited, removed or sent
// now (stops the running turn and goes next). Sits above the composer.
import 'package:flutter/cupertino.dart' show CupertinoIcons;
import 'package:flutter/material.dart';

import '../../theme/neovarch_mobile_theme.dart';
import '../l10n/strings.dart';
import '../message_queue.dart';

typedef QueueAction = Future<String?> Function(String action, {String? id, String? text});

class QueueStrip extends StatelessWidget {
  const QueueStrip({super.key, required this.queue, required this.onAction, this.onError});
  final MessageQueueState queue;
  final QueueAction onAction;
  final void Function(String message)? onError;

  Future<void> _run(String action, {String? id, String? text}) async {
    final err = await onAction(action, id: id, text: text);
    if (err != null) onError?.call(err);
  }

  Future<void> _edit(BuildContext context, QueuedMessage m) async {
    final c = TextEditingController(text: m.text);
    final next = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(tr('Edit pesan antrean')),
        content: TextField(key: const ValueKey('queue-edit-field'), controller: c, autofocus: true, minLines: 1, maxLines: 6),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: Text(tr('Batal'))),
          TextButton(key: const ValueKey('queue-edit-save'), onPressed: () => Navigator.pop(ctx, c.text), child: Text(tr('Simpan'))),
        ],
      ),
    );
    c.dispose();
    if (next != null && next.trim().isNotEmpty && next != m.text) await _run('edit', id: m.id, text: next);
  }

  @override
  Widget build(BuildContext context) {
    if (queue.isEmpty) return const SizedBox.shrink();
    final paused = queue.pausedLabel;
    return Container(
      key: const ValueKey('queue-strip'),
      margin: const EdgeInsets.fromLTRB(4, 2, 4, 6),
      padding: const EdgeInsets.fromLTRB(10, 6, 4, 6),
      decoration: BoxDecoration(
        color: NV.text.withValues(alpha: 0.06),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: NV.text.withValues(alpha: 0.12)),
      ),
      child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Icon(CupertinoIcons.clock, size: 14, color: NV.muted),
          const SizedBox(width: 6),
          Expanded(
            child: Text(queue.label,
                key: const ValueKey('queue-label'), style: NV.monoLabel(size: 10.5, color: NV.muted)),
          ),
          if (queue.paused)
            TextButton(
              key: const ValueKey('queue-resume'),
              onPressed: () => _run('resume'),
              child: Text(tr('Lanjutkan antrean'), style: const TextStyle(fontSize: 12)),
            ),
        ]),
        if (paused != null)
          Padding(
            padding: const EdgeInsets.only(bottom: 4),
            child: Text(paused, key: const ValueKey('queue-paused'), style: TextStyle(fontSize: 11.5, color: NV.muted, height: 1.3)),
          ),
        ConstrainedBox(
          constraints: const BoxConstraints(maxHeight: 132),
          child: ListView(shrinkWrap: true, padding: EdgeInsets.zero, children: [
            for (final m in queue.items)
              Row(key: ValueKey('queue-item-${m.id}'), children: [
                Expanded(
                  child: GestureDetector(
                    onTap: () => _edit(context, m),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(vertical: 6),
                      child: Text(
                        m.text.isNotEmpty ? m.text : tr('{n} lampiran', {'n': m.attachmentCount}),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(fontSize: 13.5, color: NV.text, height: 1.3),
                      ),
                    ),
                  ),
                ),
                IconButton(
                  key: ValueKey('queue-send-${m.id}'),
                  tooltip: tr('Kirim sekarang'),
                  visualDensity: VisualDensity.compact,
                  onPressed: () => _run('send_now', id: m.id),
                  icon: Icon(CupertinoIcons.arrow_up_circle, size: 18, color: NV.text),
                ),
                IconButton(
                  key: ValueKey('queue-edit-${m.id}'),
                  tooltip: tr('Edit pesan antrean'),
                  visualDensity: VisualDensity.compact,
                  onPressed: () => _edit(context, m),
                  icon: Icon(CupertinoIcons.pencil, size: 17, color: NV.muted),
                ),
                IconButton(
                  key: ValueKey('queue-remove-${m.id}'),
                  tooltip: tr('Hapus dari antrean'),
                  visualDensity: VisualDensity.compact,
                  onPressed: () => _run('remove', id: m.id),
                  icon: Icon(CupertinoIcons.xmark, size: 16, color: NV.muted),
                ),
              ]),
          ]),
        ),
      ]),
    );
  }
}
