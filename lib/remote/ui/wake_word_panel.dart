// Profil → Hey Neo: the opt-in switch for the wake word (lib/remote/wake_word.dart).
import 'dart:async';

import 'package:flutter/cupertino.dart' show CupertinoIcons;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../theme/neovarch_mobile_theme.dart';
import '../wake_phrase.dart';
import '../wake_word.dart';
import 'nv_widgets.dart';

class WakeWordPanel extends ConsumerStatefulWidget {
  const WakeWordPanel({super.key});
  @override
  ConsumerState<WakeWordPanel> createState() => _WakeWordPanelState();
}

class _WakeWordPanelState extends ConsumerState<WakeWordPanel> with WidgetsBindingObserver {
  Timer? _poll;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      ref.read(wakeWordProvider).refresh();
      ref.read(wakeWordProvider).refreshBackground();
    });
    // live download progress / errors from the service (every second while on)
    _poll = Timer.periodic(const Duration(seconds: 1), (_) {
      if (!mounted) return;
      final w = ref.read(wakeWordProvider);
      if (w.status.enabled && !w.busy && (w.status.state != 'listening' || w.status.testing(DateTime.now()))) w.refresh();
    });
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Back from Settings: show the rows as granted.
    if (state == AppLifecycleState.resumed && mounted) ref.read(wakeWordProvider).refreshBackground();
  }

  Future<void> _open(WakeWordController w, {bool overlay = false}) async {
    final r = await w.openBackgroundSettings(overlay: overlay);
    if (r == null && mounted) {
      ScaffoldMessenger.maybeOf(context)?.showSnackBar(const SnackBar(
        content: Text('Tidak bisa membuka Pengaturan. Buka Setelan → Aplikasi → Neovarch Agent, lalu atur izinnya di sana.'),
      ));
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _poll?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final w = ref.watch(wakeWordProvider);
    final s = w.status;
    final failed = s.enabled && s.state.startsWith('error:');
    return NvPanel(
      key: const ValueKey('wake-panel'),
      margin: const EdgeInsets.fromLTRB(16, 0, 16, 0),
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 14),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Row(children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Panggil dengan "Hey Neo"', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: NV.text)),
            const SizedBox(height: 2),
            Text(s.label, key: const ValueKey('wake-state'), style: TextStyle(fontSize: 12.5, color: failed ? NV.redInk : NV.muted)),
          ]),
        ),
        Switch.adaptive(
          key: const ValueKey('wake-switch'),
          value: s.enabled,
          activeTrackColor: NV.red,
          onChanged: w.busy ? null : (v) => w.setEnabled(v),
        ),
      ]),
      if (s.enabled && s.downloading) ...[
        const SizedBox(height: 8),
        ClipRRect(
          borderRadius: BorderRadius.circular(99),
          child: LinearProgressIndicator(
            key: const ValueKey('wake-progress'),
            value: s.fraction,
            minHeight: 5,
            color: NV.red,
            backgroundColor: NV.text.withValues(alpha: 0.10),
          ),
        ),
      ],
      const SizedBox(height: 8),
      Text(
        'Opsional. Mikrofon didengarkan di HP (tanpa internet) hanya untuk kata "Hey Neo", lalu dikte Chat terbuka. '
        'Model suara ±40 MB diunduh saat pertama dinyalakan. Ada notifikasi tetap selama aktif dan baterai sedikit lebih boros. '
        'Setelah HP dinyalakan ulang, ketuk notifikasinya untuk menyalakan lagi.',
        style: TextStyle(fontSize: 12.5, height: 1.35, color: NV.muted),
      ),
      if (s.enabled && s.state == 'listening') ...[
        const SizedBox(height: 8),
        _TestBox(status: s, onTest: w.startTest),
      ],
      if (w.error != null) ...[
        const SizedBox(height: 8),
        Text(w.error!, key: const ValueKey('wake-error'), style: TextStyle(fontSize: 12.5, color: NV.redInk)),
      ],
      const SizedBox(height: 6),
      _Row(
        key: const ValueKey('wake-background'),
        icon: CupertinoIcons.bolt,
        title: 'Izinkan jalan di latar',
        body: w.background.battery
            ? (w.background.xiaomi ? 'Baterai sudah tanpa batasan. Di MIUI, nyalakan juga Mulai otomatis.' : 'Sudah diizinkan: baterai tanpa batasan.')
            : (w.background.xiaomi
                ? 'Xiaomi/MIUI: nyalakan Mulai otomatis dan Baterai → Tanpa batasan.'
                : 'Matikan pengoptimalan baterai untuk Neovarch Agent.'),
        granted: w.background.battery && !w.background.xiaomi,
        onTap: () => _open(w),
      ),
      _Row(
        key: const ValueKey('wake-overlay'),
        icon: CupertinoIcons.rectangle_on_rectangle,
        title: 'Tampil di atas aplikasi lain',
        body: w.background.overlay ? 'Sudah diizinkan.' : 'Supaya "Hey Neo" bisa membuka Chat saat HP di layar lain.',
        granted: w.background.overlay,
        onTap: () => _open(w, overlay: true),
      ),
    ]),
    );
  }
}

class _Row extends StatelessWidget {
  const _Row({super.key, required this.icon, required this.title, required this.body, required this.onTap, this.granted = false});
  final IconData icon;
  final String title, body;
  final bool granted;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(10),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: Row(children: [
            Icon(icon, size: 17, color: NV.red),
            const SizedBox(width: 10),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(title, style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600, color: NV.text)),
                Text(body, style: TextStyle(fontSize: 12, height: 1.3, color: NV.muted)),
              ]),
            ),
            Icon(granted ? CupertinoIcons.checkmark_alt : CupertinoIcons.chevron_right, size: granted ? 16 : 14, color: granted ? NV.red : NV.muted),
          ]),
        ),
      );
}

/// "Tes Hey Neo": live readout of what the background recogniser hears.
class _TestBox extends StatelessWidget {
  const _TestBox({required this.status, required this.onTest});
  final WakeWordStatus status;
  final VoidCallback onTest;
  @override
  Widget build(BuildContext context) {
    final testing = status.testing(DateTime.now());
    final heard = status.heard;
    final String line;
    if (!testing) {
      line = 'Ketuk Tes, lalu ucapkan "Hey Neo". Teks yang tertangkap mikrofon muncul di sini.';
    } else if (heard == null || heard.isEmpty) {
      line = 'Mendengarkan… belum ada suara yang tertangkap.';
    } else if (matchesWakePhrase(heard)) {
      line = 'Terdengar: "$heard" → cocok, Chat akan terbuka.';
    } else if (normalizeWakeText(heard) == 'unk') {
      line = 'Ada suara, tapi bukan "Hey Neo". Coba ucapkan lebih jelas: "Hey Ni-o".';
    } else {
      line = 'Terdengar: "$heard" (belum cocok).';
    }
    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Expanded(child: Text(line, key: const ValueKey('wake-test-text'), style: TextStyle(fontSize: 12.5, height: 1.35, color: NV.text))),
      const SizedBox(width: 8),
      OutlinedButton(key: const ValueKey('wake-test'), onPressed: onTest, child: Text(testing ? 'Ulangi tes' : 'Tes Hey Neo')),
    ]);
  }
}
