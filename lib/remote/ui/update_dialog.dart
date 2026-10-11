// "Pembaruan" dialog: the in-app APK update (download with progress and
// cancel → install permission → Android installer), falling back to the
// browser. Driven by [apkUpdateProvider], which outlives the dialog.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/legacy.dart';

import '../../state/settings_controller.dart';
import '../../theme/neovarch_mobile_theme.dart';
import '../apk_update.dart';

final apkUpdateProvider = ChangeNotifierProvider<ApkUpdateController>((ref) => ApkUpdateController());

/// Opens the dialog for [update] (the map from `UpdateChecker.check`). With
/// [autoStart] the download begins right away ("Perbarui" on the strip).
Future<void> showUpdateDialog(BuildContext context, Map<String, dynamic> update, {bool autoStart = false}) async {
  final container = ProviderScope.containerOf(context, listen: false);
  final c = container.read(apkUpdateProvider);
  if (autoStart && !c.busy && c.phase != ApkUpdatePhase.needsPermission) {
    // ignore: discarded_futures
    c.start(update);
  }
  await showDialog<void>(
    context: context,
    builder: (_) => UpdateDialog(update: update),
  );
  c.reset();
}

class UpdateDialog extends ConsumerStatefulWidget {
  const UpdateDialog({super.key, required this.update});
  final Map<String, dynamic> update;
  @override
  ConsumerState<UpdateDialog> createState() => _UpdateDialogState();
}

class _UpdateDialogState extends ConsumerState<UpdateDialog> with WidgetsBindingObserver {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Back from "Instal aplikasi tidak dikenal": carry on with the install.
    if (state == AppLifecycleState.resumed) ref.read(apkUpdateProvider).resume();
  }

  @override
  Widget build(BuildContext context) {
    final c = ref.watch(apkUpdateProvider);
    final u = widget.update;
    final latest = '${u['latest'] ?? c.version ?? ''}';
    final size = u['apk_size'] is int ? u['apk_size'] as int : null;
    final muted = TextStyle(color: NV.muted, fontSize: 13, height: 1.4);

    final String body;
    Widget? extra;
    final actions = <Widget>[];
    void close() => Navigator.of(context).pop();

    switch (c.phase) {
      case ApkUpdatePhase.idle:
        body = c.supported
            ? 'Versi v$latest siap dipasang (terpasang v${SettingsController.appVersion}). '
                'Berkas${size != null ? ' ${formatMb(size)} MB' : ''} diunduh di dalam aplikasi, lalu penginstal Android terbuka.'
            : 'Versi v$latest tersedia (terpasang v${SettingsController.appVersion}). Halaman unduhan dibuka di browser.';
        actions
          ..add(TextButton(onPressed: close, child: const Text('Nanti')))
          ..add(FilledButton(key: const ValueKey('nv-update-start'), onPressed: () => c.start(u), child: const Text('Perbarui')));
      case ApkUpdatePhase.downloading:
        final p = c.progress;
        body = 'Mengunduh v$latest…';
        extra = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const SizedBox(height: 14),
          ClipRRect(
            borderRadius: BorderRadius.circular(99),
            child: LinearProgressIndicator(key: const ValueKey('nv-update-progress'), value: p, minHeight: 6, color: NV.red, backgroundColor: NV.glassBorder),
          ),
          const SizedBox(height: 8),
          Text(
              p == null
                  ? '${formatMb(c.received)} MB'
                  : '${(p * 100).floor()}% · ${formatMb(c.received)} / ${formatMb(c.total!)} MB',
              style: muted),
        ]);
        actions
          ..add(TextButton(onPressed: close, child: const Text('Sembunyikan')))
          ..add(TextButton(key: const ValueKey('nv-update-cancel'), onPressed: c.cancel, style: TextButton.styleFrom(foregroundColor: NV.red), child: const Text('Batal')));
      case ApkUpdatePhase.needsPermission:
        body = 'Android perlu izin untuk memasang pembaruan dari Neovarch Agent. Di layar Pengaturan, aktifkan '
            '"Izinkan dari sumber ini", lalu kembali ke aplikasi — pemasangan dilanjutkan otomatis.';
        actions
          ..add(TextButton(onPressed: close, child: const Text('Nanti')))
          ..add(FilledButton(onPressed: c.openPermissionSettings, child: const Text('Buka Pengaturan')));
      case ApkUpdatePhase.installing:
        body = 'Membuka penginstal Android…';
        extra = const Padding(padding: EdgeInsets.only(top: 14), child: LinearProgressIndicator());
      case ApkUpdatePhase.done:
        body = 'Penginstal Android terbuka. Ketuk "Perbarui" atau "Instal" di sana untuk menyelesaikan; aplikasi akan ditutup sebentar lalu memakai versi baru.';
        actions.add(FilledButton(onPressed: close, child: const Text('Oke')));
      case ApkUpdatePhase.failed:
        body = 'Pembaruan di aplikasi gagal: ${c.error ?? 'kesalahan tidak dikenal'}.'
            '${c.openedBrowser ? ' Halaman unduhan sudah dibuka di browser.' : ''}';
        actions
          ..add(TextButton(onPressed: close, child: const Text('Tutup')))
          ..add(FilledButton(onPressed: () => c.start(u), child: const Text('Coba lagi')));
      case ApkUpdatePhase.cancelled:
        body = 'Unduhan dibatalkan.';
        actions
          ..add(TextButton(onPressed: close, child: const Text('Tutup')))
          ..add(FilledButton(onPressed: () => c.start(u), child: const Text('Unduh lagi')));
    }

    return AlertDialog(
      key: const ValueKey('nv-update-dialog'),
      title: Text('Pembaruan v$latest'),
      content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(body, key: const ValueKey('nv-update-body')),
        ?extra,
      ]),
      actions: actions,
    );
  }
}
