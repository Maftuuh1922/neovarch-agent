// About — version, optional update check against GitHub releases, data reset.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;
import 'package:url_launcher/url_launcher.dart';

import '../../../remote/apk_update.dart' show ApkUpdateController;
import '../../../remote/update_check.dart' show parseGithubRelease;
import '../../../remote/ui/update_dialog.dart';
import '../../../state/app_controller.dart';
import '../../../state/settings_controller.dart';
import '../../../theme/app_theme.dart';
import '../../widgets/common.dart';
import '../intro_screen.dart';

class AboutScreen extends ConsumerStatefulWidget {
  const AboutScreen({super.key});
  @override
  ConsumerState<AboutScreen> createState() => _AboutScreenState();
}

class _AboutScreenState extends ConsumerState<AboutScreen> {
  late final _repo = TextEditingController(text: ref.read(settingsProvider).updateRepo);
  String? result;
  String? releaseUrl;
  Map<String, dynamic>? update;
  bool busy = false;

  Future<void> _check() async {
    final repo = _repo.text.trim();
    ref.read(settingsProvider).update((x) => x.updateRepo = repo);
    if (!RegExp(r'^[\w.-]+/[\w.-]+$').hasMatch(repo)) {
      setState(() => result = 'Isi repositori dengan format pemilik/nama');
      return;
    }
    setState(() {
      busy = true;
      result = null;
      update = null;
    });
    try {
      final r = await http.get(Uri.parse('https://api.github.com/repos/$repo/releases/latest'), headers: {'Accept': 'application/vnd.github+json'});
      if (r.statusCode == 404) {
        result = 'Belum ada rilis di $repo';
      } else if (r.statusCode != 200) {
        result = r.statusCode == 403 ? 'GitHub API rate limit tercapai — coba lagi nanti' : 'GitHub membalas HTTP ${r.statusCode}';
      } else {
        final j = jsonDecode(r.body) as Map;
        final u = parseGithubRelease(j, SettingsController.appVersion);
        final tag = '${u?['latest'] ?? ''}';
        releaseUrl = '${j['html_url'] ?? ''}';
        update = u?['available'] == true ? u : null;
        result = u == null
            ? 'Rilis tanpa nomor versi'
            : u['available'] == true
                ? 'Versi baru tersedia: $tag (terpasang ${SettingsController.appVersion})'
                : 'Sudah versi terbaru ($tag)';
      }
    } catch (e) {
      result = 'Gagal memeriksa: $e';
    }
    if (mounted) setState(() => busy = false);
  }

  @override
  Widget build(BuildContext context) {
    final store = ref.watch(storeProvider);
    return Scaffold(
      appBar: AppBar(title: Text('Tentang', style: context.tt.titleMedium)),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        Row(children: [
          const LogoCard(height: 128),
          const SizedBox(width: 16),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Wordmark(height: 34),
              const SizedBox(height: 6),
              Text('Neovarch Agent', style: context.tt.titleLarge),
              Text('Versi ${SettingsController.appVersion} · NeovarchLabs', style: context.tt.bodySmall),
            ]),
          ),
        ]),
        const SizedBox(height: 14),
        Text(
            'Neovarch Agent untuk Android & iPhone: chat dengan alat dan memori, sesi, skill, berkas, proyek, kantor isometrik, Kanban, rapat multi-agent, dan cron — '
            'berjalan mandiri di ponsel, atau tersambung ke gateway Neovarch / server kantor.',
            style: context.tt.bodyMedium),
        const SectionLabel('Pembaruan', padding: EdgeInsets.fromLTRB(0, 22, 0, 8)),
        TextField(controller: _repo, decoration: const InputDecoration(labelText: 'Repositori GitHub rilis aplikasi', hintText: 'pemilik/neovrach_Agent')),
        const SizedBox(height: 10),
        Row(children: [
          OutlinedButton.icon(onPressed: busy ? null : _check, icon: const Icon(Icons.system_update_alt, size: 18), label: const Text('Periksa pembaruan')),
          // Android with an APK in the release: download + install in the app.
          if (update != null && ApkUpdateController.isApkUrl('${update!['download_url']}') && ref.read(apkUpdateProvider).supported) ...[
            const SizedBox(width: 8),
            FilledButton(onPressed: () => showUpdateDialog(context, update!, autoStart: true), child: const Text('Perbarui')),
          ] else if (releaseUrl != null && releaseUrl!.isNotEmpty) ...[
            const SizedBox(width: 8),
            TextButton(onPressed: () => launchUrl(Uri.parse(releaseUrl!), mode: LaunchMode.externalApplication), child: const Text('Buka rilis')),
          ],
        ]),
        if (result != null) Padding(padding: const EdgeInsets.only(top: 10), child: NoteBanner(result!)),
        const SectionLabel('Data di perangkat', padding: EdgeInsets.fromLTRB(0, 22, 0, 8)),
        Text('${store.sessions.length} sesi · ${store.memory.length} memori · ${store.skills.length} skill · ${store.files.length} berkas · ${store.tasks.length} tugas',
            style: context.tt.bodySmall),
        const SizedBox(height: 10),
        OutlinedButton.icon(
          style: OutlinedButton.styleFrom(foregroundColor: context.hc.destructive),
          onPressed: () async {
            if (!await confirmDialog(context,
                title: 'Kosongkan papan Kanban lokal?', body: 'Semua tugas, log, dan riwayat run di perangkat dihapus. Sesi, memori, dan berkas tetap.', confirm: 'Kosongkan', destructive: true)) {
              return;
            }
            store.tasks.clear();
            store.logs.clear();
            store.runs.clear();
            store.saveTasks();
            store.saveLogs();
            store.saveRuns();
            if (context.mounted) toast(context, 'Papan dikosongkan');
          },
          icon: const Icon(Icons.delete_sweep_outlined, size: 18),
          label: const Text('Kosongkan papan lokal'),
        ),
        const SizedBox(height: 8),
        OutlinedButton.icon(
          onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const IntroScreen(replay: true))),
          icon: const Icon(Icons.auto_stories_outlined, size: 18),
          label: const Text('Lihat intro lagi'),
        ),
        const SizedBox(height: 8),
        OutlinedButton.icon(
          onPressed: () => ref.read(settingsProvider).update((x) => x.onboarded = false),
          icon: const Icon(Icons.restart_alt, size: 18),
          label: const Text('Ulangi onboarding'),
        ),
        const SizedBox(height: 24),
        Text('Neovarch Agent oleh NeovarchLabs. Logo & ilustrasi milik NeovarchLabs. Huruf: Big Shoulders Display, IBM Plex Mono, Barlow (SIL OFL). Lisensi pihak ketiga ada di berkas NOTICE.', style: context.tt.bodySmall),
      ]),
    );
  }
}
