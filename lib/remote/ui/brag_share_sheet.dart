// Kartu Neovarch sheet (Profil → "Pamerkan", Kantor → "Pamerkan"): swipe
// between the three styles ("1 dari 3"), pick Story 9:16 or Feed 1:1, hide the
// stats or the Kantor snapshot, then share. The share row lists only the apps
// that are installed (IG Story / Instagram / WhatsApp / TikTok / X / Facebook /
// Telegram); "Lainnya" opens the system share sheet, "Salin tautan" copies the
// landing link and "Unduh" saves the PNG to Pictures/Neovarch.
import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../theme/neovarch_mobile_theme.dart';
import '../../ui/widgets/common.dart' show toast;
import '../remote_controller.dart';
import '../share/brag_card_data.dart';
import '../share/share_targets.dart';
import 'brag_card.dart';
import 'nv_widgets.dart';
import 'profile_share_card.dart' show renderShareCardPng, shareChannel, writeShareFile;
import 'remote_office_3d.dart' show captureOfficeSnapshot;

/// Package names Android reports as installed among [kShareTargetPackages].
/// Test seam; empty off Android (only "Lainnya" is shown then).
Future<List<String>> Function() installedShareApps = () async {
  try {
    final r = await shareChannel('installedPackages', {'packages': kShareTargetPackages});
    return r is List ? [for (final p in r) '$p'] : const [];
  } catch (_) {
    return const [];
  }
};

String bragShareText(String link) => 'Kantor AI-ku di Neovarch. Coba juga: $link';

String _fileName() => 'kartu-neovarch-${DateTime.now().millisecondsSinceEpoch}.png';

/// Share [png] to [target] (null = system share sheet).
Future<void> shareBragPng(BuildContext context, Uint8List png, {ResolvedShareTarget? target, String link = kNeovarchLandingUrl}) async {
  try {
    final path = await writeShareFile(png, _fileName());
    final r = await shareChannel('shareImage', shareImageArgs(path: path, text: bragShareText(link), target: target));
    if (target != null && shareFellBack(r) && context.mounted) toast(context, '${target.label} tidak bisa dibuka, pakai menu bagikan');
  } catch (e) {
    if (context.mounted) toast(context, 'Gagal membagikan: $e');
  }
}

Future<void> saveBragPng(BuildContext context, Uint8List png) async {
  try {
    final path = await writeShareFile(png, _fileName());
    final r = await shareChannel('saveImageToGallery', {'path': path, 'name': path.split('/').last});
    if (context.mounted) toast(context, r is String && r.isNotEmpty ? 'Tersimpan di galeri (Pictures/Neovarch)' : 'Gagal menyimpan ke galeri');
  } catch (e) {
    if (context.mounted) toast(context, 'Gagal menyimpan: $e');
  }
}

/// Gather the card from the phone's state (GitHub profile from the PC, Office, Kanban, sessions, default model) and open the sheet.
/// [officeShot] is taken from the live Kantor 3D scene when not given.
Future<void> showBragShareSheet(BuildContext context, WidgetRef ref, {Uint8List? officeShot, Widget? debugBackground}) async {
  final r = ref.read(remoteProvider);
  // The GitHub profile always comes from the PC's sign-in (no phone login).
  final profile = r.socialSignedIn ? r.socialProfile : null;
  final shot = officeShot ?? await captureOfficeSnapshot();
  if (!context.mounted) return;
  final data = BragCardData.gather(
    profile: profile,
    office: r.office,
    board: r.board,
    sessions: r.sessions,
    defaultModel: r.models?.defaultModel,
    officeShot: shot,
  );
  await showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    showDragHandle: true,
    backgroundColor: NV.bg,
    builder: (ctx) => BragSharePreview(data: data, debugBackground: debugBackground),
  );
}

class BragSharePreview extends StatefulWidget {
  const BragSharePreview({super.key, required this.data, this.debugBackground, this.initialStyle = BragStyle.kaca, this.initialFormat = BragFormat.story});
  final BragCardData data;
  final Widget? debugBackground;
  final BragStyle initialStyle;
  final BragFormat initialFormat;
  @override
  State<BragSharePreview> createState() => _BragSharePreviewState();
}

class _BragSharePreviewState extends State<BragSharePreview> {
  late final PageController _pages = PageController(initialPage: widget.initialStyle.index, viewportFraction: 0.86);
  final _exportKey = GlobalKey();
  late BragStyle style = widget.initialStyle;
  late BragFormat format = widget.initialFormat;
  bool showStats = true;
  late bool showOffice = widget.data.officeShot != null;
  bool busy = false;
  List<ResolvedShareTarget> targets = const [];

  @override
  void initState() {
    super.initState();
    unawaited(installedShareApps().then((pkgs) {
      if (mounted) setState(() => targets = availableShareTargets(pkgs));
    }));
  }

  @override
  void dispose() {
    _pages.dispose();
    super.dispose();
  }

  Widget _card(BragStyle s, {Key? key}) => NeovarchBragCard(
        key: key,
        data: widget.data,
        style: s,
        format: format,
        showStats: showStats,
        showOffice: showOffice,
        background: widget.debugBackground,
      );

  Future<void> _export(Future<void> Function(Uint8List png) then) async {
    if (busy) return;
    setState(() => busy = true);
    try {
      await then(await renderShareCardPng(_exportKey));
    } catch (e) {
      if (mounted) toast(context, 'Gagal membuat gambar: $e');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = format.logical;
    final mq = MediaQuery.of(context);
    final maxH = mq.size.height * (format == BragFormat.story ? 0.50 : 0.36);
    final scale = math.min(mq.size.width * 0.86 / l.w, maxH / l.h);
    return SingleChildScrollView(
      key: const ValueKey('brag-sheet'),
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 0, 20, 10),
          child: NvSheetTitle(
            kicker: 'kartu · png',
            title: 'Pamerkan',
            trailing: Text('${style.index + 1} dari ${BragStyle.values.length}', key: const ValueKey('brag-page'), style: NV.monoLabel(size: 10, color: NV.muted)),
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: NvGlassSegmented(
            key: const ValueKey('brag-format'),
            labels: [for (final f in BragFormat.values) f.label],
            index: format.index,
            onChanged: (i) => setState(() => format = BragFormat.values[i]),
          ),
        ),
        const SizedBox(height: 12),
        // Hidden export copy: exact logical size, painted but clipped to 0×0.
        ClipRect(
          child: SizedBox.shrink(
            child: OverflowBox(
              alignment: Alignment.topLeft,
              maxWidth: l.w,
              maxHeight: l.h,
              child: RepaintBoundary(key: _exportKey, child: _card(style)),
            ),
          ),
        ),
        SizedBox(
          height: l.h * scale,
          child: PageView(
            key: const ValueKey('brag-pages'),
            controller: _pages,
            onPageChanged: (i) => setState(() => style = BragStyle.values[i]),
            children: [
              for (final s in BragStyle.values)
                Center(
                  child: SizedBox(
                    width: l.w * scale,
                    height: l.h * scale,
                    child: FittedBox(child: _card(s, key: ValueKey('brag-preview-${s.name}'))),
                  ),
                ),
            ],
          ),
        ),
        const SizedBox(height: 8),
        Row(mainAxisAlignment: MainAxisAlignment.center, children: [
          for (final s in BragStyle.values)
            GestureDetector(
              onTap: () => _pages.animateToPage(s.index, duration: const Duration(milliseconds: 260), curve: Curves.easeOutCubic),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 200),
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(999),
                    color: s == style ? NV.redWash : Colors.transparent,
                    border: Border.all(color: s == style ? NV.red : NV.glassBorder),
                  ),
                  child: Text(s.label, style: TextStyle(fontSize: 12, color: s == style ? NV.text : NV.muted)),
                ),
              ),
            ),
        ]),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 6, 16, 0),
          child: NvPanel(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 2),
            child: Column(children: [
              _Toggle(
                key: const ValueKey('brag-toggle-stats'),
                label: 'Tampilkan statistik',
                sub: 'Agen, tugas, sesi, model',
                value: showStats,
                onChanged: (v) => setState(() => showStats = v),
              ),
              _Toggle(
                key: const ValueKey('brag-toggle-office'),
                label: 'Cuplikan Kantor 3D',
                sub: widget.data.officeShot == null ? 'Buka tab Kantor (3D) dulu' : 'Gambar kantor saat ini',
                value: showOffice,
                onChanged: widget.data.officeShot == null ? null : (v) => setState(() => showOffice = v),
              ),
            ]),
          ),
        ),
        const SizedBox(height: 12),
        SizedBox(
          height: 78,
          child: ListView(
            key: const ValueKey('brag-targets'),
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 12),
            children: [
              for (final t in targets)
                _TargetButton(
                  key: ValueKey('brag-target-${t.id}'),
                  icon: _targetIcon(t.id),
                  label: t.label,
                  onTap: busy ? null : () => _export((png) => shareBragPng(context, png, target: t, link: widget.data.link)),
                ),
              _TargetButton(
                key: const ValueKey('brag-target-more'),
                icon: CupertinoIcons.ellipsis,
                label: 'Lainnya',
                onTap: busy ? null : () => _export((png) => shareBragPng(context, png, link: widget.data.link)),
              ),
            ],
          ),
        ),
        Padding(
          padding: EdgeInsets.fromLTRB(16, 4, 16, 16 + mq.padding.bottom),
          child: Row(children: [
            Expanded(
              flex: 4,
              child: FilledButton.icon(
                key: const ValueKey('brag-share'),
                style: _compact,
                onPressed: busy ? null : () => _export((png) => shareBragPng(context, png, link: widget.data.link)),
                icon: const Icon(CupertinoIcons.share, size: 17),
                label: const Text('Bagikan', maxLines: 1, softWrap: false, style: TextStyle(fontSize: 13.5)),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              flex: 5,
              child: OutlinedButton.icon(
                key: const ValueKey('brag-copy'),
                style: _compact,
                onPressed: () {
                  Clipboard.setData(ClipboardData(text: widget.data.link));
                  toast(context, 'Tautan disalin');
                },
                icon: const Icon(CupertinoIcons.link, size: 17),
                label: const Text('Salin tautan', maxLines: 1, softWrap: false, style: TextStyle(fontSize: 13.5)),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              flex: 4,
              child: OutlinedButton.icon(
                key: const ValueKey('brag-save'),
                style: _compact,
                onPressed: busy ? null : () => _export((png) => saveBragPng(context, png)),
                icon: const Icon(CupertinoIcons.arrow_down_to_line, size: 17),
                label: const Text('Unduh', maxLines: 1, softWrap: false, style: TextStyle(fontSize: 13.5)),
              ),
            ),
          ]),
        ),
      ]),
    );
  }
}

final _compact = ButtonStyle(
  padding: const WidgetStatePropertyAll(EdgeInsets.symmetric(horizontal: 10, vertical: 12)),
  visualDensity: VisualDensity.compact,
);

IconData _targetIcon(String id) => switch (id) {
      'ig-story' => CupertinoIcons.plus_circle_fill,
      'ig-feed' => CupertinoIcons.camera_fill,
      'whatsapp' => CupertinoIcons.chat_bubble_fill,
      'tiktok' => CupertinoIcons.music_note_2,
      'x' => CupertinoIcons.xmark,
      'facebook' => CupertinoIcons.person_2_fill,
      'telegram' => CupertinoIcons.paperplane_fill,
      _ => CupertinoIcons.share,
    };

class _Toggle extends StatelessWidget {
  const _Toggle({super.key, required this.label, required this.sub, required this.value, required this.onChanged});
  final String label, sub;
  final bool value;
  final ValueChanged<bool>? onChanged;
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Row(children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(label, style: TextStyle(fontSize: 14, fontWeight: FontWeight.w500, color: onChanged == null ? NV.muted : NV.text)),
              Text(sub, style: TextStyle(fontSize: 12, color: NV.muted)),
            ]),
          ),
          CupertinoSwitch(value: value, activeTrackColor: NV.red, onChanged: onChanged),
        ]),
      );
}

class _TargetButton extends StatelessWidget {
  const _TargetButton({super.key, required this.icon, required this.label, required this.onTap});
  final IconData icon;
  final String label;
  final VoidCallback? onTap;
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(horizontal: 4),
        child: InkWell(
          borderRadius: BorderRadius.circular(16),
          onTap: onTap,
          child: SizedBox(
            width: 68,
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Container(
                width: 48,
                height: 48,
                decoration: BoxDecoration(shape: BoxShape.circle, color: NV.surface, border: Border.all(color: NV.glassBorder)),
                child: Icon(icon, size: 21, color: NV.text),
              ),
              const SizedBox(height: 6),
              Text(label, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 11.5, color: NV.text)),
            ]),
          ),
        ),
      );
}
