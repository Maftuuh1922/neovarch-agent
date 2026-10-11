// "Riwayat perubahan" (bundled changelog), the one-time "Apa yang baru di
// vX" sheet after an update, and the release-notes block of the update
// dialog. Data: lib/remote/changelog.dart.
import 'package:flutter/cupertino.dart' show CupertinoIcons;
import 'package:flutter/material.dart';

import '../../state/settings_controller.dart';
import '../../theme/neovarch_mobile_theme.dart';
import '../changelog.dart';
import 'nv_widgets.dart';

/// Release notes (markdown-lite) as headings, bullets and text.
class ReleaseNotesView extends StatelessWidget {
  const ReleaseNotesView(this.notes, {super.key, this.maxHeight = 240});
  final String notes;
  final double maxHeight;
  @override
  Widget build(BuildContext context) {
    final lines = parseNoteLines(notes);
    if (lines.isEmpty) return const SizedBox.shrink();
    return ConstrainedBox(
      constraints: BoxConstraints(maxHeight: maxHeight),
      child: Scrollbar(
        child: SingleChildScrollView(
          key: const ValueKey('nv-release-notes'),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
            for (final (i, l) in lines.indexed) _noteLine(l, first: i == 0),
          ]),
        ),
      ),
    );
  }
}

Widget _noteLine(NoteLine l, {bool first = false}) {
  switch (l.kind) {
    case 'heading':
      return Padding(
        padding: EdgeInsets.only(top: first ? 0 : 10, bottom: 4),
        child: Text(l.text, style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w700, color: NV.text, height: 1.3)),
      );
    case 'bullet':
      return _Bullet(l.text);
    default:
      return Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Text(l.text, style: TextStyle(fontSize: 13, color: NV.muted, height: 1.4)),
      );
  }
}

class _Bullet extends StatelessWidget {
  const _Bullet(this.text);
  final String text;
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Padding(padding: const EdgeInsets.only(top: 6, right: 8), child: NvDot(NV.red, size: 5)),
          Expanded(child: Text(text, style: TextStyle(fontSize: 13, color: NV.text, height: 1.4))),
        ]),
      );
}

/// One release: version, date (or "belum dirilis"), summary, sections.
class ChangelogEntryView extends StatelessWidget {
  const ChangelogEntryView(this.entry, {super.key, this.current = SettingsController.appVersion, this.showHeader = true});
  final ChangelogEntry entry;
  final String current;
  final bool showHeader;
  @override
  Widget build(BuildContext context) {
    final upcoming = isUpcoming(entry, current);
    final installed = changelogFor(current)?.version == entry.version;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
      if (showHeader) ...[
        Row(children: [
          Flexible(child: Text('v${entry.version}', maxLines: 1, overflow: TextOverflow.ellipsis, style: NV.display(size: 26))),
          const SizedBox(width: 10),
          if (upcoming) NvPill('belum dirilis', color: NV.red) else if (installed) NvPill('terpasang', color: NV.red),
          const Spacer(),
          if (entry.date != null) Text(entry.date!, style: NV.monoLabel(size: 10, color: NV.muted)),
        ]),
        const SizedBox(height: 6),
      ],
      Text(entry.summary, style: TextStyle(fontSize: 14, color: NV.muted, height: 1.45)),
      for (final s in entry.sections) ...[
        const SizedBox(height: 12),
        Text(s.title.toUpperCase(), style: NV.monoLabel(size: 10, color: NV.redInk)),
        const SizedBox(height: 6),
        for (final item in s.items) _Bullet(item),
      ],
    ]);
  }
}

/// "Riwayat perubahan": every bundled release, newest first.
class ChangelogScreen extends StatelessWidget {
  const ChangelogScreen({super.key, this.current = SettingsController.appVersion});
  final String current;
  @override
  Widget build(BuildContext context) => Scaffold(
        body: ListView(
          key: const ValueKey('changelog-list'),
          padding: EdgeInsets.only(bottom: 24 + MediaQuery.paddingOf(context).bottom),
          children: [
            NvHeader(kicker: 'neovarch agent', title: 'Riwayat perubahan', onBack: () => Navigator.of(context).maybePop()),
            for (final e in changelog)
              NvPanel(
                key: ValueKey('changelog-${e.version}'),
                margin: const EdgeInsets.fromLTRB(16, 0, 16, 12),
                child: ChangelogEntryView(e, current: current),
              ),
          ],
        ),
      );
}

/// "Apa yang baru di vX": once after an update (see [WhatsNew]).
Future<void> showWhatsNewSheet(BuildContext context, ChangelogEntry entry) => showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      showDragHandle: true,
      builder: (ctx) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.7,
        maxChildSize: 0.92,
        minChildSize: 0.4,
        builder: (ctx, sc) => ListView(
          key: const ValueKey('whats-new-sheet'),
          controller: sc,
          padding: EdgeInsets.fromLTRB(20, 0, 20, 24 + MediaQuery.paddingOf(ctx).bottom),
          children: [
            Text('PEMBARUAN TERPASANG', style: NV.monoLabel(color: NV.redInk)),
            const SizedBox(height: 6),
            Text('Apa yang baru di v${entry.version}', style: NV.display(size: 30)),
            const SizedBox(height: 10),
            ChangelogEntryView(entry, showHeader: false),
            const SizedBox(height: 20),
            FilledButton(key: const ValueKey('whats-new-ok'), onPressed: () => Navigator.of(ctx).pop(), child: const Text('Oke')),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              key: const ValueKey('whats-new-history'),
              onPressed: () {
                Navigator.of(ctx).pop();
                Navigator.of(context).push(MaterialPageRoute(builder: (_) => const ChangelogScreen()));
              },
              icon: const Icon(CupertinoIcons.clock, size: 18),
              label: const Text('Riwayat perubahan'),
            ),
          ],
        ),
      ),
    );
