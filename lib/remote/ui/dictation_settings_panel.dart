// Profil → Dikte suara (1.4.9): which way the mic turns speech into text
// (the phone's recogniser, or a recording transcribed by the PC's local free
// STT), whether the text is sent at once, and whether the PC has an engine.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../state/app_controller.dart' show settingsProvider;
import '../../theme/neovarch_mobile_theme.dart';
import '../l10n/strings.dart';
import '../remote_controller.dart';
import 'nv_widgets.dart';

class DictationSettingsPanel extends ConsumerStatefulWidget {
  const DictationSettingsPanel({super.key});
  @override
  ConsumerState<DictationSettingsPanel> createState() => _DictationSettingsPanelState();
}

class _DictationSettingsPanelState extends ConsumerState<DictationSettingsPanel> {
  String? _pc; // PC STT status line
  bool _checking = false;

  Future<void> _check() async {
    final gw = ref.read(remoteProvider).gateway;
    if (gw == null) {
      setState(() => _pc = tr('Belum terhubung ke PC.'));
      return;
    }
    setState(() => _checking = true);
    try {
      final st = await gw.sttStatus();
      if (!mounted) return;
      setState(() => _pc = st['available'] == true
          ? tr('STT PC siap: {engine} · model {model}', {'engine': st['engine'] ?? '', 'model': st['model'] ?? ''})
          : tr('PC belum punya mesin STT. Di PC jalankan: {cmd}', {'cmd': 'pip install faster-whisper'}));
    } catch (_) {
      if (mounted) setState(() => _pc = tr('PC belum mendukung transkripsi — perbarui aplikasi PC.'));
    } finally {
      if (mounted) setState(() => _checking = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(settingsProvider);
    Widget choice(String value, String title, String body) {
      final on = s.dictationEngine == value;
      return InkWell(
        key: ValueKey('dictation-engine-$value'),
        borderRadius: BorderRadius.circular(12),
        onTap: () => s.update((x) => x.dictationEngine = value),
        child: Container(
          margin: const EdgeInsets.only(bottom: 8),
          padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: on ? NV.red : NV.text.withValues(alpha: 0.14)),
            color: on ? NV.redWash : null,
          ),
          child: Row(children: [
            Icon(on ? Icons.radio_button_checked : Icons.radio_button_off, size: 18, color: on ? NV.red : NV.muted),
            const SizedBox(width: 10),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(tr(title), style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600, color: NV.text)),
                Text(tr(body), style: TextStyle(fontSize: 12, height: 1.3, color: NV.muted)),
              ]),
            ),
          ]),
        ),
      );
    }

    return NvPanel(
      key: const ValueKey('dictation-settings'),
      margin: const EdgeInsets.fromLTRB(16, 0, 16, 0),
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 14),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        choice('auto', 'Otomatis', 'Pengenal suara HP dulu; bila tidak ada, rekaman dikirim ke PC untuk ditranskripsi.'),
        choice('pc', 'Lewat PC', 'Selalu rekam di HP lalu transkripsi di PC (STT lokal gratis, tanpa Google).'),
        Row(children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(tr('Kirim otomatis'), style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600, color: NV.text)),
              Text(tr('Mati: teks masuk ke kolom dulu untuk dicek.'), style: TextStyle(fontSize: 12, color: NV.muted)),
            ]),
          ),
          Switch.adaptive(
            key: const ValueKey('dictation-autosend'),
            value: s.dictationAutoSend,
            activeTrackColor: NV.red,
            onChanged: (v) => s.update((x) => x.dictationAutoSend = v),
          ),
        ]),
        const SizedBox(height: 6),
        Row(children: [
          Expanded(
            child: Text(_pc ?? tr('Cek apakah PC sudah punya STT lokal.'),
                key: const ValueKey('dictation-pc-status'), style: TextStyle(fontSize: 12, height: 1.3, color: NV.muted)),
          ),
          TextButton(
            key: const ValueKey('dictation-pc-check'),
            onPressed: _checking ? null : _check,
            child: Text(tr(_checking ? 'Mengecek…' : 'Cek PC'), style: TextStyle(color: NV.red)),
          ),
        ]),
      ]),
    );
  }
}
