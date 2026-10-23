// Record-then-send dictation (1.4.9): the phone records, the PC's local free
// STT (faster-whisper / whisper.cpp behind /api/audio/transcribe) writes the
// text. Used when the phone has no working recogniser, or always when
// Profil → Dikte suara → "Lewat PC" is chosen.
import 'dart:typed_data';

import '../state/voice_service.dart';
import 'remote_gateway.dart';

/// The STT language hint for a recogniser locale (`id_ID` → `id`).
String sttLanguageOf(String locale) => locale.split(RegExp('[_-]')).first.toLowerCase();

/// A [PcTranscriber] bound to [gw]; null without a PC link.
PcTranscriber? pcTranscriberFor(RemoteGateway? gw) {
  if (gw == null) return null;
  return (Uint8List audio, String mime, String locale) async =>
      transcriptOf(await gw.transcribeAudio(audio, mime, language: sttLanguageOf(locale)));
}

/// The PC's answer → transcript, or [PcTranscriptionError] with its message.
String transcriptOf(Map<String, dynamic> r) {
  final t = r['transcript'];
  if (r['ok'] != false && t is String) return t;
  final msg = [r['error'], r['message']].whereType<String>().firstWhere((m) => m.trim().isNotEmpty, orElse: () => '');
  throw PcTranscriptionError(msg.isEmpty ? 'Transkripsi di PC gagal.' : msg, code: '${r['code'] ?? ''}');
}
