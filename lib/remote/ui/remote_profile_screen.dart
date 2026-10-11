// 1.4.4: Profil tab, compact and GitHub-profile-like. Top to bottom:
// [ProfileHeaderSlot] (photo + name/@login + bio, contribution graph, tech
// stack), then the settings folded into compact expandable groups: Tampilan
// (tema, aksen, wallpaper, sudut, mode ringan), Gaya kaca, Ikon aplikasi,
// Teman, then Aplikasi (Tentang aplikasi, Riwayat perubahan).
//
// The list reserves room for the floating nav bar (its height + gap + the
// system inset, via the shell's MediaQuery padding) so the last row always
// scrolls fully above the bar.
import 'package:flutter/cupertino.dart' show CupertinoIcons;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../state/settings_controller.dart';
import '../../theme/neovarch_mobile_theme.dart';
import '../../ui/widgets/motion.dart' show reduceMotion;
import 'app_icon_panel.dart';
import 'changelog_screen.dart' show ChangelogScreen;
import 'lite_mode_panel.dart';
import 'remote_about_screen.dart';
import 'brag_share_sheet.dart' show showBragShareSheet;
import 'appearance/appearance_section.dart' show NvAppearanceSection;
import 'glass_style_picker.dart';
import 'model_picker.dart';
import 'nv_widgets.dart';
import 'language_panel.dart';
import '../l10n/strings.dart';
import 'profile_header_slot.dart';
import 'token_usage_panel.dart';
import 'wake_word_panel.dart';
import '../wake_word.dart' show WakeWordController;
import 'remote_social_screen.dart' show SocialSection;

/// Floating nav bar height + gap (kept in sync with RemoteShell).
const profileNavReserve = 64.0 + 12.0;

class RemoteProfileScreen extends StatelessWidget {
  const RemoteProfileScreen({super.key, this.autoLoad = true});

  /// Tests: no refresh from the PC / GitHub on open.
  final bool autoLoad;

  @override
  Widget build(BuildContext context) {
    final mq = MediaQuery.of(context);
    // Inside the shell the padding already carries the nav reserve; outside
    // (or if an ancestor dropped it) never go below inset + bar + gap.
    final bottom = [mq.padding.bottom, mq.viewPadding.bottom + profileNavReserve].reduce((a, b) => a > b ? a : b) + 20;
    return Scaffold(
      body: ListView(
        key: const ValueKey('profile-list'),
        padding: EdgeInsets.only(bottom: bottom),
        children: [
          const NvHeader(kicker: 'hp ini', title: 'Profil'),
          ProfileHeaderSlot(autoLoad: autoLoad),
          const PamerkanButton(),
          const NvSection('pengaturan'),
          const ProfileGroup(
            id: 'model',
            icon: CupertinoIcons.sparkles,
            title: 'Model AI',
            subtitle: 'Model default agen di PC',
            children: [ModelSettingsPanel()],
          ),
          if (WakeWordController.supported)
            const ProfileGroup(
              id: 'wake',
              icon: CupertinoIcons.waveform,
              title: 'Hey Neo',
              subtitle: 'Panggil agen dengan suara (opsional)',
              children: [WakeWordPanel()],
            ),
          const ProfileGroup(
            id: 'tokens',
            icon: CupertinoIcons.chart_bar_alt_fill,
            title: 'Pemakaian token',
            subtitle: 'Hari ini, sesi ini, sepanjang waktu, per model',
            children: [TokenUsagePanel()],
          ),
          const ProfileGroup(
            id: 'appearance',
            icon: CupertinoIcons.paintbrush_fill,
            title: 'Tampilan',
            subtitle: 'Tema, aksen, wallpaper, sudut, mode ringan',
            children: [NvAppearanceSection(), SizedBox(height: 12), WallpaperColorsPanel(), SizedBox(height: 12), LiteModePanel()],
          ),
          const ProfileGroup(
            id: 'glass',
            icon: CupertinoIcons.drop_fill,
            title: 'Gaya kaca',
            subtitle: 'Reguler, bening, gelap, warna, tanpa',
            children: [GlassStylePicker()],
          ),
          const ProfileGroup(
            id: 'icon',
            icon: CupertinoIcons.app_fill,
            title: 'Ikon aplikasi',
            subtitle: 'Warna ikon di layar utama',
            children: [AppIconPanel()],
          ),
          const ProfileGroup(
            id: 'language',
            icon: CupertinoIcons.globe,
            title: 'Bahasa',
            subtitle: 'Bahasa Indonesia, English, atau ikuti sistem',
            children: [LanguagePanel()],
          ),
          ProfileGroup(
            id: 'friends',
            icon: CupertinoIcons.person_2_fill,
            title: 'Teman',
            subtitle: 'Teman GitHub & bagikan profil',
            children: [SocialSection(autoLoad: false, showProfile: false)],
          ),
          const NvSection('aplikasi'),
          NvList(children: [
            NvRow(
              key: const ValueKey('profile-about'),
              icon: CupertinoIcons.info_circle,
              title: tr('Tentang aplikasi'),
              subtitle: tr('v{v} · pembaruan, tautan, lisensi', {'v': SettingsController.appVersion}),
              trailing: Icon(CupertinoIcons.chevron_right, size: 17, color: NV.muted),
              onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const RemoteAboutScreen())),
            ),
            NvRow(
              key: const ValueKey('profile-changelog'),
              icon: CupertinoIcons.clock,
              title: tr('Riwayat perubahan'),
              subtitle: tr('Yang baru di setiap versi'),
              trailing: Icon(CupertinoIcons.chevron_right, size: 17, color: NV.muted),
              onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const ChangelogScreen())),
            ),
          ]),
        ],
      ),
    );
  }
}

/// One compact settings row that unfolds its content below it.
class ProfileGroup extends StatefulWidget {
  const ProfileGroup({super.key, required this.id, required this.icon, required this.title, required this.subtitle, required this.children, this.initiallyOpen = false});
  final String id;
  final IconData icon;
  final String title;
  final String subtitle;
  final List<Widget> children;
  final bool initiallyOpen;

  /// Tests / screenshots: groups open by id.
  static Set<String> debugOpen = {};

  @override
  State<ProfileGroup> createState() => _ProfileGroupState();
}

class _ProfileGroupState extends State<ProfileGroup> {
  late bool open = widget.initiallyOpen || ProfileGroup.debugOpen.contains(widget.id);

  @override
  Widget build(BuildContext context) {
    final dur = reduceMotion(context) ? Duration.zero : const Duration(milliseconds: 240);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
      NvPanel(
        key: ValueKey('profile-group-${widget.id}'),
        margin: const EdgeInsets.fromLTRB(16, 0, 16, 8),
        padding: const EdgeInsets.fromLTRB(12, 10, 10, 10),
        onTap: () => setState(() => open = !open),
        child: Semantics(
          button: true,
          expanded: open,
          child: Row(children: [
            Container(
              width: 32,
              height: 32,
              decoration: BoxDecoration(color: NV.redWash, borderRadius: BorderRadius.circular(9)),
              child: Icon(widget.icon, size: 17, color: NV.red),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(tr(widget.title), style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: NV.text)),
                Text(tr(widget.subtitle), maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 12.5, color: NV.muted)),
              ]),
            ),
            AnimatedRotation(
              turns: open ? 0.25 : 0,
              duration: dur,
              child: Icon(CupertinoIcons.chevron_right, size: 17, color: NV.muted),
            ),
          ]),
        ),
      ),
      AnimatedSize(
        duration: dur,
        curve: Curves.easeOutCubic,
        alignment: Alignment.topCenter,
        child: open
            ? Padding(
                key: ValueKey('profile-group-body-${widget.id}'),
                padding: const EdgeInsets.only(bottom: 12),
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: widget.children),
              )
            : const SizedBox(width: double.infinity),
      ),
    ]);
  }
}

/// "Pamerkan": opens the Kartu Neovarch sheet (shareable brag card).
class PamerkanButton extends ConsumerWidget {
  const PamerkanButton({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) => Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
        child: FilledButton.icon(
          key: const ValueKey('profile-pamerkan'),
          onPressed: () => showBragShareSheet(context, ref),
          icon: const Icon(CupertinoIcons.sparkles, size: 18),
          label: Text(tr('Pamerkan')),
        ),
      );
}
