// Dictation status strip (1.4.8): sits in the composer above the input and
// says what the mic is doing — Mendengarkan… (live words + level),
// Memproses…, or an error with the button that fixes it (app settings for a
// permanently denied permission, the Speech Services page when the phone has
// no recogniser). Replaces the 2-second toasts that hid behind the nav bar.
import 'package:flutter/cupertino.dart' show CupertinoIcons;
import 'package:flutter/material.dart';

import '../../data/device_tools.dart' show deviceCall;
import '../../state/voice_service.dart';
import '../../theme/neovarch_mobile_theme.dart';
import '../../ui/widgets/common.dart' show confirmDialog;
import '../l10n/strings.dart';

class DictationStrip extends StatelessWidget {
  const DictationStrip({super.key, required this.voice, required this.onStop, required this.onAction});
  final VoiceService voice;

  /// Tap "Berhenti" while listening.
  final VoidCallback onStop;

  /// The error's fix button (or "Coba lagi").
  final void Function(DictationAction action) onAction;

  @override
  Widget build(BuildContext context) => ListenableBuilder(
        listenable: voice,
        builder: (context, _) {
          final s = voice.status;
          if (s.phase == DictationPhase.idle) return const SizedBox(key: ValueKey('dictation-strip-idle'), width: double.infinity);
          return Container(
            key: const ValueKey('dictation-strip'),
            margin: const EdgeInsets.fromLTRB(4, 2, 4, 6),
            padding: const EdgeInsets.fromLTRB(10, 8, 4, 8),
            decoration: BoxDecoration(
              color: s.isError ? NV.redWash : NV.text.withValues(alpha: 0.06),
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: s.isError ? NV.red.withValues(alpha: 0.55) : NV.text.withValues(alpha: 0.12)),
            ),
            child: s.isError ? _error(context, s) : _active(context, s),
          );
        },
      );

  Widget _active(BuildContext context, DictationStatus s) {
    final label = switch (s.phase) {
      DictationPhase.starting => tr('Menyiapkan mikrofon…'),
      DictationPhase.processing => tr('Memproses…'),
      _ => tr('Mendengarkan…'),
    };
    return Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Row(children: [
        if (s.phase == DictationPhase.listening)
          Container(width: 8, height: 8, decoration: BoxDecoration(color: NV.red, shape: BoxShape.circle))
        else
          SizedBox(width: 12, height: 12, child: CircularProgressIndicator(strokeWidth: 1.6, color: NV.muted)),
        const SizedBox(width: 8),
        Flexible(
          child: Text(label,
              key: const ValueKey('dictation-strip-label'),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: NV.monoLabel(size: 11, color: NV.text, weight: FontWeight.w600)),
        ),
        const SizedBox(width: 10),
        if (s.phase == DictationPhase.listening)
          Expanded(
            child: ClipRRect(
              borderRadius: BorderRadius.circular(3),
              child: Container(
                height: 4,
                color: NV.text.withValues(alpha: 0.10),
                alignment: Alignment.centerLeft,
                child: FractionallySizedBox(
                  key: const ValueKey('dictation-strip-level'),
                  widthFactor: s.level.clamp(0.04, 1.0).toDouble(),
                  child: Container(color: NV.red),
                ),
              ),
            ),
          )
        else
          const Spacer(),
        TextButton(
          key: const ValueKey('dictation-strip-stop'),
          onPressed: onStop,
          style: TextButton.styleFrom(foregroundColor: NV.text, padding: const EdgeInsets.symmetric(horizontal: 10), minimumSize: const Size(0, 30)),
          child: Text(s.phase == DictationPhase.listening ? tr('Berhenti') : tr('Batal'), style: const TextStyle(fontSize: 12.5)),
        ),
      ]),
      if (s.partial.isNotEmpty)
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 8, 0),
          child: Text(s.partial,
              key: const ValueKey('dictation-strip-partial'),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: 13, height: 1.35, color: NV.muted, fontStyle: FontStyle.italic)),
        ),
    ]);
  }

  Widget _error(BuildContext context, DictationStatus s) {
    final label = dictationActionLabel(s.action);
    return Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Padding(padding: const EdgeInsets.only(top: 1), child: Icon(CupertinoIcons.mic_slash, size: 15, color: NV.red)),
        const SizedBox(width: 8),
        Expanded(
          child: Text(tr(s.message ?? 'Dikte gagal.'),
              key: const ValueKey('dictation-strip-message'), style: TextStyle(fontSize: 13, height: 1.4, color: NV.text)),
        ),
        InkWell(
          key: const ValueKey('dictation-strip-close'),
          borderRadius: BorderRadius.circular(10),
          onTap: voice.dismissDictationError,
          child: Padding(padding: const EdgeInsets.all(4), child: Icon(CupertinoIcons.xmark, size: 14, color: NV.muted)),
        ),
      ]),
      if (label != null)
        Align(
          alignment: Alignment.centerRight,
          child: Padding(
            padding: const EdgeInsets.only(top: 4, right: 4),
            child: FilledButton(
              key: const ValueKey('dictation-strip-action'),
              onPressed: () => onAction(s.action),
              style: FilledButton.styleFrom(
                backgroundColor: NV.red,
                foregroundColor: NV.onRed,
                minimumSize: const Size(0, 32),
                padding: const EdgeInsets.symmetric(horizontal: 14),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(NV.rCtl)),
              ),
              child: Text(tr(label), style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600)),
            ),
          ),
        ),
    ]);
  }
}

/// Explains the microphone before Android's permission dialog.
Future<bool> micRationale(BuildContext context) => confirmDialog(
      context,
      title: tr('Izinkan mikrofon'),
      body: tr('Neovarch memakai mikrofon hanya saat kamu mengetuk tombol mik, untuk mengubah suaramu jadi teks di kolom chat. '
          'Setelah ini Android akan bertanya — pilih "Izinkan".'),
      confirm: tr('Lanjut'),
    );

/// Opens what the strip's button points at. Returns false when nothing could
/// be opened (the caller may say so).
Future<bool> openDictationFix(DictationAction a) async {
  try {
    switch (a) {
      case DictationAction.openAppSettings:
        return await deviceCall<bool>('openAppSettings') ?? false;
      case DictationAction.installSpeechServices:
        return await deviceCall<bool>('openSpeechServices', {'kind': 'install'}) ?? false;
      case DictationAction.openSpeechServices:
        return await deviceCall<bool>('openSpeechServices', {'kind': 'settings'}) ?? false;
      case DictationAction.retry:
      case DictationAction.none:
        return false;
    }
  } catch (_) {
    return false;
  }
}
