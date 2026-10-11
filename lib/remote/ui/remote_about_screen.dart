// "Tentang aplikasi" (Profil): phone app and PC core versions, links,
// licences, the changelog, and a manual "Periksa pembaruan".
import 'package:flutter/cupertino.dart' show CupertinoIcons;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../state/settings_controller.dart';
import '../../theme/neovarch_mobile_theme.dart';
import '../apk_update.dart' show ApkUpdateController;
import '../remote_controller.dart';
import '../update_check.dart' show githubRepo, releasesPage;
import 'changelog_screen.dart';
import 'nv_widgets.dart';
import 'update_dialog.dart';

const repoUrl = 'https://github.com/$githubRepo';
const landingUrl = 'https://maftuuh1922.github.io/neorachAgent_lp/';

/// Opens a link outside the app (tests swap it).
Future<bool> Function(Uri uri) aboutLinkOpener = (uri) => launchUrl(uri, mode: LaunchMode.externalApplication);

class RemoteAboutScreen extends ConsumerStatefulWidget {
  const RemoteAboutScreen({super.key});
  @override
  ConsumerState<RemoteAboutScreen> createState() => _RemoteAboutScreenState();
}

class _RemoteAboutScreenState extends ConsumerState<RemoteAboutScreen> {
  bool _checking = false;
  String? _result;

  Future<void> _check(RemoteController r) async {
    setState(() {
      _checking = true;
      _result = null;
    });
    await r.checkUpdate(force: true);
    if (!mounted) return;
    final u = r.update;
    setState(() {
      _checking = false;
      _result = u['latest'] == null
          ? 'Gagal memeriksa pembaruan. Periksa koneksi internet lalu coba lagi.'
          : u['available'] == true
              ? 'Versi baru tersedia: v${u['latest']}'
              : 'Sudah versi terbaru (v${u['latest']}).';
    });
  }

  @override
  Widget build(BuildContext context) {
    final r = ref.watch(remoteProvider);
    final up = ref.watch(apkUpdateProvider);
    final pcVersion = '${r.serverInfo['version'] ?? ''}'.trim();
    final u = r.update;
    final available = u['available'] == true && u['latest'] != null;
    final inApp = available && up.supported && ApkUpdateController.isApkUrl('${u['download_url'] ?? ''}');
    Widget chevron() => Icon(CupertinoIcons.chevron_right, size: 18, color: NV.faint);
    Widget link(String key, IconData icon, String title, String subtitle, String url) => NvRow(
          key: ValueKey('about-$key'),
          icon: icon,
          title: title,
          subtitle: subtitle,
          mono: true,
          trailing: Icon(CupertinoIcons.arrow_up_right, size: 16, color: NV.faint),
          onTap: () => aboutLinkOpener(Uri.parse(url)),
        );

    return Scaffold(
      body: ListView(
        key: const ValueKey('about-list'),
        padding: EdgeInsets.only(bottom: 24 + MediaQuery.paddingOf(context).bottom),
        children: [
          NvHeader(kicker: 'profil', title: 'Tentang aplikasi', onBack: () => Navigator.of(context).maybePop()),
          NvPanel(
            margin: const EdgeInsets.symmetric(horizontal: 16),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Neovarch Agent', style: NV.display(size: 30)),
              const SizedBox(height: 4),
              Text('Remote HP untuk agen Neovarch di PC · NeovarchLabs', style: TextStyle(fontSize: 13.5, color: NV.muted, height: 1.4)),
              const SizedBox(height: 12),
              Divider(height: 1, color: NV.border),
              const SizedBox(height: 8),
              NvKv('aplikasi hp', 'v${SettingsController.appVersion}', mono: true, key: const ValueKey('about-app-version')),
              NvKv('core di pc', pcVersion.isEmpty ? (r.connected ? '—' : '— (PC belum tersambung)') : 'v${pcVersion.replaceFirst(RegExp(r'^[vV]'), '')}',
                  mono: true, key: const ValueKey('about-pc-version')),
              if (r.desktop != null) NvKv('pc', r.desktop!.name),
            ]),
          ),
          const NvSection('pembaruan'),
          NvPanel(
            margin: const EdgeInsets.symmetric(horizontal: 16),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              if (_result != null || available)
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: Text(
                    _result ?? 'Versi baru tersedia: v${u['latest']}',
                    key: const ValueKey('about-update-result'),
                    style: TextStyle(fontSize: 14, color: NV.text, height: 1.4),
                  ),
                ),
              Row(children: [
                Expanded(
                  child: OutlinedButton.icon(
                    key: const ValueKey('about-check-update'),
                    onPressed: _checking ? null : () => _check(r),
                    icon: _checking
                        ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                        : const Icon(CupertinoIcons.arrow_clockwise, size: 18),
                    label: Text(_checking ? 'Memeriksa…' : 'Periksa pembaruan'),
                  ),
                ),
                if (available) ...[
                  const SizedBox(width: 10),
                  Expanded(
                    child: FilledButton(
                      key: const ValueKey('about-update-now'),
                      onPressed: () => inApp
                          ? showUpdateDialog(context, u, autoStart: true)
                          : aboutLinkOpener(Uri.parse('${u['url'] ?? releasesPage}')),
                      child: Text(inApp ? 'Perbarui' : 'Buka rilis'),
                    ),
                  ),
                ],
              ]),
            ]),
          ),
          const NvSection('info'),
          NvList(children: [
            NvRow(
              key: const ValueKey('about-changelog'),
              icon: CupertinoIcons.clock,
              title: 'Riwayat perubahan',
              subtitle: 'Yang baru di setiap versi',
              trailing: chevron(),
              onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const ChangelogScreen())),
            ),
            link('github', CupertinoIcons.chevron_left_slash_chevron_right, 'GitHub', 'github.com/$githubRepo', repoUrl),
            link('landing', CupertinoIcons.globe, 'Situs Neovarch Agent', 'maftuuh1922.github.io/neorachAgent_lp', landingUrl),
            link('releases', CupertinoIcons.cloud_download, 'Semua rilis', 'github.com/$githubRepo/releases', '$repoUrl/releases'),
            NvRow(
              key: const ValueKey('about-licenses'),
              icon: CupertinoIcons.doc_text,
              title: 'Lisensi',
              subtitle: 'Neovarch Agent (MIT), font, dan pustaka sumber terbuka',
              trailing: chevron(),
              onTap: () => showLicensePage(context: context, applicationName: 'Neovarch Agent', applicationVersion: SettingsController.appVersion),
            ),
          ]),
          const SizedBox(height: 24),
          Center(child: Text('NEOVARCH AGENT · V${SettingsController.appVersion} · MIT', style: NV.monoLabel(size: 9.5, color: NV.faint))),
        ],
      ),
    );
  }
}
