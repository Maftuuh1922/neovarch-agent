// Composer dictation state (1.4.8): what the mic is doing right now, shown in
// a strip above the chat input instead of a 2-second toast that hid behind
// the glass nav bar ("mik tidak bisa sama sekali" was really silent errors).
//
// Pure Dart: VoiceService drives it, the chat composer renders it, tests
// check the transitions and the Indonesian messages.
import 'package:flutter/foundation.dart';

enum DictationPhase {
  /// Nothing happening; the strip is hidden.
  idle,

  /// Mic tapped: permission / recogniser start-up.
  starting,

  /// Recording; partial words and the input level stream in.
  listening,

  /// Stopped; waiting for the recogniser's final text.
  processing,

  /// Failed; the strip keeps the message (and a fix button) until dismissed
  /// or the mic is tapped again.
  error,
}

/// Why dictation failed.
enum DictationIssue {
  /// RECORD_AUDIO refused this time (Android will ask again).
  permissionDenied,

  /// RECORD_AUDIO refused with "jangan tanya lagi" (or MIUI auto-deny):
  /// only the app's settings page can fix it.
  permissionPermanent,

  /// No SpeechRecognizer service and no other way to dictate on this phone.
  noRecognizer,

  /// Neovarch has the mic, but the speech service (Google app) does not.
  recognizerMicDenied,

  /// The recogniser heard nothing.
  noSpeech,

  /// Google's recogniser needs the internet (or an offline language pack).
  network,

  /// Another app holds the recogniser.
  busy,

  /// The microphone is in use (another app or "Hey Neo").
  audio,

  /// The chosen language is not available in the phone's recogniser.
  language,

  /// The recogniser never answered (init or listen watchdog).
  timeout,

  /// Anything else; [DictationStatus.message] carries the detail.
  failed,
}

/// The button the strip offers for an [DictationIssue].
enum DictationAction {
  none,

  /// Android app details page (permission denied permanently).
  openAppSettings,

  /// Play Store / GetApps page of "Speech Services by Google".
  installSpeechServices,

  /// Settings page of the phone's speech service (give IT the mic).
  openSpeechServices,

  /// Tap the mic again.
  retry,
}

/// Outcome of asking for RECORD_AUDIO.
enum MicPermission { granted, denied, permanent }

@immutable
class DictationStatus {
  const DictationStatus._(this.phase, {this.partial = '', this.level = 0, this.issue, this.message, this.toPc = false});

  static const idle = DictationStatus._(DictationPhase.idle);
  static const starting = DictationStatus._(DictationPhase.starting);

  factory DictationStatus.listening({String partial = '', double level = 0, bool toPc = false}) =>
      DictationStatus._(DictationPhase.listening, partial: partial, level: level.clamp(0.0, 1.0).toDouble(), toPc: toPc);
  factory DictationStatus.processing({String partial = '', bool toPc = false}) =>
      DictationStatus._(DictationPhase.processing, partial: partial, toPc: toPc);
  factory DictationStatus.error(DictationIssue issue, {String? detail}) =>
      DictationStatus._(DictationPhase.error, issue: issue, message: dictationMessage(issue, detail: detail));

  /// An error whose text is already written (keeps older specific messages).
  factory DictationStatus.errorText(DictationIssue issue, String message) =>
      DictationStatus._(DictationPhase.error, issue: issue, message: message);

  final DictationPhase phase;

  /// Record-then-send: the audio is transcribed by the PC's local STT.
  final bool toPc;

  /// Words heard so far (listening / processing).
  final String partial;

  /// Input level 0..1 while listening.
  final double level;

  final DictationIssue? issue;

  /// Indonesian message for [DictationPhase.error].
  final String? message;

  bool get active => phase == DictationPhase.starting || phase == DictationPhase.listening || phase == DictationPhase.processing;
  bool get isError => phase == DictationPhase.error;
  DictationAction get action => issue == null ? DictationAction.none : dictationActionFor(issue!);

  DictationStatus copyWith({String? partial, double? level}) =>
      DictationStatus._(phase,
          partial: partial ?? this.partial, level: (level ?? this.level).clamp(0.0, 1.0).toDouble(), issue: issue, message: message, toPc: toPc);

  @override
  bool operator ==(Object other) =>
      other is DictationStatus && other.phase == phase && other.partial == partial && other.level == level && other.issue == issue && other.message == message && other.toPc == toPc;

  @override
  int get hashCode => Object.hash(phase, partial, level, issue, message, toPc);

  @override
  String toString() => 'DictationStatus($phase${issue != null ? ', $issue' : ''}${partial.isNotEmpty ? ', "$partial"' : ''})';
}

// ---- messages ----------------------------------------------------------------

const micDeniedText = 'Izin mikrofon ditolak. Ketuk mik lagi lalu pilih "Izinkan".';
const micDeniedPermanentText = 'Izin mikrofon ditolak permanen. Buka pengaturan → Izin → Mikrofon → Izinkan, lalu ketuk mik lagi.';
const noRecognizerText = 'Speech Services Google tidak ada di HP ini, jadi dikte tidak bisa jalan. '
    'Pasang "Speech Services by Google" (Play Store / GetApps), lalu ketuk mik lagi.';
const recognizerMicText = 'Izin mikrofon Neovarch sudah aktif, tapi layanan pengenal suara HP (aplikasi Google) '
    'tidak punya izin mikrofon. Buka Speech Services → Izin → Mikrofon → Izinkan.';
const noSpeechText = 'Suara tidak tertangkap: tidak ada suara terdeteksi. Coba lagi lebih dekat ke mikrofon.';
const networkText = 'Jaringan bermasalah: pengenal suara Google butuh internet (atau unduh paket bahasa offline di pengaturan Google).';
const busyText = 'Pengenal suara sedang dipakai aplikasi lain. Tunggu sebentar lalu coba lagi.';
const audioText = 'Mikrofon sedang dipakai (mis. aplikasi lain atau "Hey Neo"). Coba lagi sebentar lagi.';
const languageText = 'Bahasa ini belum tersedia di pengenal suara HP. Tekan lama tombol mik untuk ganti ID/EN.';
const timeoutText = 'Pengenal suara tidak menjawab. Coba lagi.';

/// Indonesian text the strip shows for [issue].
String dictationMessage(DictationIssue issue, {String? detail}) => switch (issue) {
      DictationIssue.permissionDenied => micDeniedText,
      DictationIssue.permissionPermanent => micDeniedPermanentText,
      DictationIssue.noRecognizer => noRecognizerText,
      DictationIssue.recognizerMicDenied => recognizerMicText,
      DictationIssue.noSpeech => noSpeechText,
      DictationIssue.network => networkText,
      DictationIssue.busy => busyText,
      DictationIssue.audio => audioText,
      DictationIssue.language => languageText,
      DictationIssue.timeout => timeoutText,
      DictationIssue.failed => detail == null || detail.isEmpty ? 'Dikte gagal.' : 'Dikte gagal ($detail).',
    };

DictationAction dictationActionFor(DictationIssue issue) => switch (issue) {
      DictationIssue.permissionPermanent => DictationAction.openAppSettings,
      DictationIssue.noRecognizer => DictationAction.installSpeechServices,
      DictationIssue.recognizerMicDenied => DictationAction.openSpeechServices,
      DictationIssue.language => DictationAction.none,
      _ => DictationAction.retry,
    };

/// Button label (Indonesian; the strip runs it through `tr`).
String? dictationActionLabel(DictationAction a) => switch (a) {
      DictationAction.none => null,
      DictationAction.openAppSettings => 'Buka pengaturan',
      DictationAction.installSpeechServices => 'Pasang Speech Services',
      DictationAction.openSpeechServices => 'Buka Speech Services',
      DictationAction.retry => 'Coba lagi',
    };

/// SpeechRecognizer / speech_to_text error code → issue. speech_to_text 7.x
/// sends `error_audio_error` for ERROR_AUDIO and `error_unknown (n)` for
/// codes it doesn't know; `recognizerNotAvailable` comes from initialize().
DictationIssue issueForSttCode(String code) {
  final c = code.trim();
  if (c.startsWith('error_unknown')) return DictationIssue.failed;
  return switch (c) {
    'error_permission' || 'error_insufficient_permissions' => DictationIssue.permissionDenied,
    'error_no_match' || 'error_speech_timeout' => DictationIssue.noSpeech,
    'error_network' || 'error_network_timeout' || 'error_server' => DictationIssue.network,
    'error_language_not_supported' || 'error_language_unavailable' => DictationIssue.language,
    'error_busy' || 'error_recognizer_busy' || 'error_too_many_requests' => DictationIssue.busy,
    'error_audio' || 'error_audio_error' => DictationIssue.audio,
    'error_timeout' => DictationIssue.timeout,
    'recognizerNotAvailable' || 'error_recognizer_not_available' => DictationIssue.noRecognizer,
    _ => DictationIssue.failed,
  };
}

/// Normalised level (0..1) from the recogniser's RMS dB (speech_to_text on
/// Android reports roughly -2..10).
double levelFromRms(double rms) {
  if (rms.isNaN) return 0;
  return ((rms + 2) / 12).clamp(0.0, 1.0).toDouble();
}

/// Where a finished transcript goes in the composer: appended to what was
/// typed before dictation started (one space between), never sent.
String insertTranscript(String before, String transcript) {
  final t = transcript.trim();
  if (t.isEmpty) return before;
  final b = before.trimRight();
  return b.isEmpty ? t : '$b $t';
}
