// Voice: dictation (speech_to_text) and read-back (flutter_tts), like
// Desktop's mic + "Read replies aloud" toggle.
//
// Dictation state (1.4.8) lives in [VoiceService.status] (see
// dictation_status.dart): the chat composer shows it in a strip above the
// input, so a refused permission, a missing Speech Services or a silent
// recogniser is never a 2-second toast hidden behind the nav bar again.
// A watchdog guarantees the mic never stays stuck in "listening".
import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:speech_to_text/speech_recognition_result.dart';
import 'package:speech_to_text/speech_to_text.dart';

import '../data/device_tools.dart' show checkPermissions, deviceCall, ensurePermissions;
import '../data/platform_caps.dart';
import 'dictation_status.dart';

export 'dictation_status.dart';

/// The speech recogniser behind dictation (Android SpeechRecognizer through
/// speech_to_text in the app; a fake in tests).
abstract class SpeechEngine {
  Future<bool> initialize({required void Function(String error) onError, required void Function(String status) onStatus});
  Future<List<String>> localeIds();
  Future<void> listen({required String localeId, required void Function(String words, bool isFinal) onResult});
  Future<void> stop();
}

/// Optional: an engine that reports the microphone level (RMS dB) while it
/// listens. The status strip shows it as a level bar.
abstract class SpeechLevels {
  set onLevel(void Function(double rms)? f);
}

class _SttEngine implements SpeechEngine, SpeechLevels {
  final SpeechToText _stt = SpeechToText();
  void Function(double rms)? _level;
  @override
  set onLevel(void Function(double rms)? f) => _level = f;
  @override
  Future<bool> initialize({required void Function(String error) onError, required void Function(String status) onStatus}) =>
      _stt.initialize(onError: (e) => onError(e.errorMsg), onStatus: onStatus);
  @override
  Future<List<String>> localeIds() async => [for (final l in await _stt.locales()) l.localeId];
  @override
  Future<void> listen({required String localeId, required void Function(String words, bool isFinal) onResult}) => _stt.listen(
        onResult: (SpeechRecognitionResult r) => onResult(r.recognizedWords, r.finalResult),
        onSoundLevelChange: (double l) => _level?.call(l),
        listenOptions: SpeechListenOptions(
          partialResults: true,
          cancelOnError: true,
          listenMode: ListenMode.dictation,
          localeId: localeId,
          pauseFor: VoiceService.pauseFor,
          listenFor: VoiceService.listenFor,
        ),
      );
  @override
  Future<void> stop() => _stt.stop();
}

/// Android fallbacks when the phone has no SpeechRecognizer service (common
/// on Xiaomi without Google): the system speech dialog (RecognizerIntent) and
/// the offline Vosk model Hey Neo downloads (English only). MainActivity.kt.
abstract class SpeechFallback {
  /// `{recognizer, intent, vosk, mic}` booleans.
  Future<Map<String, bool>> caps();
  /// The system "Bicara sekarang" dialog; final text or null (cancelled).
  Future<String?> recognizeIntent(String locale);
  /// Offline dictation; partial / final text and errors arrive on the callbacks.
  Future<void> voskStart({required void Function(String text, bool isFinal) onText, required void Function(String error) onError});
  Future<void> voskStop();
}

class _ChannelFallback implements SpeechFallback {
  static const _speech = MethodChannel('neovarch/speech');
  void Function(String, bool)? _onText;
  void Function(String)? _onError;
  String _done = '';

  _ChannelFallback() {
    _speech.setMethodCallHandler((call) async {
      final a = (call.arguments as Map?) ?? const {};
      if (call.method == 'text') {
        final t = '${a['text'] ?? ''}'.trim();
        final fin = a['final'] == true;
        if (a['segment'] == true) {
          // a finished sentence: keep it and keep listening
          if (t.isNotEmpty) _done = _done.isEmpty ? t : '$_done $t';
          _onText?.call(_done, fin);
        } else if (t.isNotEmpty) {
          _onText?.call(_done.isEmpty ? t : '$_done $t', fin);
        }
      } else if (call.method == 'error') {
        _onError?.call('${a['message'] ?? 'mikrofon'}');
      }
      return null;
    });
  }

  @override
  Future<Map<String, bool>> caps() async {
    final r = await deviceCall<Map>('speechCaps');
    return {for (final e in (r ?? const {}).entries) '${e.key}': e.value == true};
  }

  @override
  Future<String?> recognizeIntent(String locale) => deviceCall<String>('recognizeSpeechIntent', {'locale': locale});

  @override
  Future<void> voskStart({required void Function(String text, bool isFinal) onText, required void Function(String error) onError}) async {
    _onText = onText;
    _onError = onError;
    _done = '';
    await deviceCall<bool>('voskDictate');
  }

  @override
  Future<void> voskStop() async {
    await deviceCall<bool>('voskStop');
  }
}

/// RECORD_AUDIO for dictation (MainActivity.kt `micPermission` / `requestMic`;
/// a fake in tests).
abstract class MicPermissions {
  /// Current state without prompting. `askable` false means Android will not
  /// show the dialog again (denied with "jangan tanya lagi", or MIUI).
  Future<({bool granted, bool askable})> status();

  /// Shows the system dialog (or returns at once when Android won't).
  Future<MicPermission> request();
}

class _AndroidMic implements MicPermissions {
  @override
  Future<({bool granted, bool askable})> status() async {
    try {
      final m = await deviceCall<Map>('micPermission') ?? const {};
      final granted = m['granted'] == true;
      final asked = m['asked'] == true;
      final rationale = m['rationale'] == true;
      return (granted: granted, askable: granted || !asked || rationale);
    } catch (_) {
      // older native side: only the plain check
      final r = await checkPermissions(const ['android.permission.RECORD_AUDIO']);
      return (granted: r['android.permission.RECORD_AUDIO'] ?? false, askable: true);
    }
  }

  @override
  Future<MicPermission> request() async {
    try {
      final m = await deviceCall<Map>('requestMic') ?? const {};
      if (m['granted'] == true) return MicPermission.granted;
      return m['permanent'] == true ? MicPermission.permanent : MicPermission.denied;
    } catch (_) {
      return await ensurePermissions(const ['android.permission.RECORD_AUDIO']) ? MicPermission.granted : MicPermission.denied;
    }
  }
}

/// Wraps the older bool test hook (no explanation dialog).
class _BoolMic implements MicPermissions {
  _BoolMic(this.f);
  final Future<bool> Function() f;
  @override
  Future<({bool granted, bool askable})> status() async => (granted: await f(), askable: false);
  @override
  Future<MicPermission> request() async => await f() ? MicPermission.granted : MicPermission.denied;
}

/// No speech service at all on this phone (Indonesian text).
const noSpeechServiceText = 'Speech Services Google tidak ada di HP ini, jadi dikte tidak bisa jalan. Pasang "Speech Services by Google" '
    '(Play Store / GetApps), atau ganti dikte ke English (tekan lama tombol mik) untuk memakai model offline Hey Neo.';
const voskModelMissingText = 'Speech Services Google tidak ada di HP ini. Untuk dikte offline (English), nyalakan Hey Neo sekali di Profil '
    'supaya model suara terunduh, atau pasang "Speech Services by Google".';

/// The speech service (Google app / the phone's recogniser) refused the mic
/// although Neovarch itself has the microphone permission (v1.4.7 bug: the
/// chat said "Izin mikrofon ditolak" while the permission was granted).
const recognizerMicDeniedText = 'Izin mikrofon Neovarch sudah aktif, tapi layanan pengenal suara HP (aplikasi Google) '
    'tidak punya izin mikrofon. Buka Speech Services → Izin → Mikrofon → Izinkan, '
    'atau tekan lama tombol mik untuk dikte English offline.';

/// SpeechRecognizer `ERROR_INSUFFICIENT_PERMISSIONS` (speech_to_text: `error_permission`).
bool sttPermissionError(String code) => code == 'error_permission' || code == 'error_insufficient_permissions';

/// SpeechRecognizer errors that mean "this recogniser can't work here" →
/// try the fallbacks instead of failing.
bool sttUnavailableError(String code) => const {
      'error_client', 'error_server_disconnected', 'error_language_unavailable', 'error_language_not_supported', 'error_cannot_check_support',
    }.contains(code);

/// Picks the recogniser locale for [wanted] ("id_ID", "en-US"): exact, then
/// the same language, else null (the recogniser's default).
String? resolveSttLocale(List<String> available, String wanted) {
  String norm(String x) => x.replaceAll('-', '_').toLowerCase();
  final w = norm(wanted);
  for (final a in available) {
    if (norm(a) == w) return a;
  }
  final lang = w.split('_').first;
  for (final a in available) {
    if (norm(a).split('_').first == lang) return a;
  }
  return null;
}

/// Friendly Indonesian text for SpeechRecognizer error codes.
String sttErrorText(String code) => code == 'error_client'
    ? 'Pengenal suara HP menolak permintaan. Coba lagi, atau mulai ulang aplikasi Google.'
    : dictationMessage(issueForSttCode(code), detail: code);

class VoiceService extends ChangeNotifier {
  VoiceService._();
  static final VoiceService instance = VoiceService._();

  /// Tests: a fake recogniser and permission answer.
  @visibleForTesting
  static SpeechEngine? debugEngine;
  /// True when a test engine stands in (shows the mic on any platform).
  static bool get hasTestEngine => debugEngine != null;
  @visibleForTesting
  static Future<bool> Function()? debugMicPermission;
  /// Tests: the full permission fake (status + request, permanent denial).
  @visibleForTesting
  static MicPermissions? debugMicPermissions;
  /// Tests: the Android fallbacks (RecognizerIntent / Vosk).
  @visibleForTesting
  static SpeechFallback? debugFallback;
  /// How long the recogniser may take to start before dictation gives up.
  static Duration initTimeout = const Duration(seconds: 12);
  /// No callback at all (result, status, level) for this long while
  /// listening → stop and reset (keep any words heard).
  static Duration watchdogTimeout = const Duration(seconds: 10);
  /// After "stop": how long to wait for the recogniser's final text.
  static Duration finalTimeout = const Duration(seconds: 3);
  /// Longest single dictation, and the silence that ends it.
  static Duration listenFor = const Duration(seconds: 60);
  static Duration pauseFor = const Duration(seconds: 4);

  SpeechEngine? _engine;
  SpeechEngine get _e => _engine ??= debugEngine ?? _SttEngine();
  SpeechFallback? _fallbackImpl;
  SpeechFallback? get _fb {
    if (debugFallback != null) return debugFallback;
    if (kIsWeb || defaultTargetPlatform != TargetPlatform.android || debugEngine != null) return null;
    return _fallbackImpl ??= _ChannelFallback();
  }

  MicPermissions? _micImpl;
  MicPermissions? get _mic {
    if (debugMicPermissions != null) return debugMicPermissions;
    final f = debugMicPermission;
    if (f != null) return _BoolMic(f);
    if (kIsWeb || defaultTargetPlatform != TargetPlatform.android) return null; // no runtime permission here
    return _micImpl ??= _AndroidMic();
  }

  FlutterTts? _tts;
  bool _sttReady = false;
  bool speaking = false;
  String? error;
  List<String>? _locales;

  /// What dictation is doing (the composer's status strip).
  DictationStatus status = DictationStatus.idle;

  /// Dictation holds (or is acquiring) the microphone.
  bool get listening => status.active;

  /// Which recogniser the current / last dictation used:
  /// `recognizer`, `intent`, `vosk` (diagnostics, tests).
  String? engine;

  // current dictation
  int _gen = 0;
  void Function(String text, bool isFinal)? _userText;
  void Function(String error)? _onError;
  bool _gotText = false;
  bool _anyEvent = false;
  bool _fellBack = false;
  bool _recognizerDenied = false;
  bool _stopRequested = false;
  String _partial = '';
  String _locale = 'id_ID';
  DictationStatus? _initFailure;
  Timer? _watchdog;
  Timer? _hardCap;
  Timer? _finalTimer;

  @visibleForTesting
  void debugReset() {
    _gen++;
    _cancelTimers();
    _engine = null;
    _sttReady = false;
    _locales = null;
    status = DictationStatus.idle;
    error = null;
    engine = null;
    _partial = '';
  }

  void _set(DictationStatus s) {
    status = s;
    notifyListeners();
  }

  void _cancelTimers() {
    _watchdog?.cancel();
    _hardCap?.cancel();
    _finalTimer?.cancel();
    _watchdog = _hardCap = _finalTimer = null;
  }

  /// Any sign of life from the recogniser: push the watchdog back.
  void _kick() {
    _anyEvent = true;
    if (status.phase != DictationPhase.listening) return;
    _watchdog?.cancel();
    final g = _gen;
    _watchdog = Timer(watchdogTimeout, () => _onWatchdog(g));
  }

  void _armTimers() {
    _cancelTimers();
    final g = _gen;
    _watchdog = Timer(watchdogTimeout, () => _onWatchdog(g));
    _hardCap = Timer(listenFor + const Duration(seconds: 8), () => _onWatchdog(g, cap: true));
  }

  void _onWatchdog(int g, {bool cap = false}) {
    if (g != _gen || !status.active) return;
    debugPrint('dictation: watchdog fired (cap=$cap, text=${_partial.isNotEmpty}, events=$_anyEvent)');
    unawaited(_stopEngine());
    if (_partial.trim().isNotEmpty) {
      _deliver(_partial);
    } else if (engine == 'recognizer' && !_anyEvent) {
      _fail(DictationStatus.error(DictationIssue.timeout));
    } else {
      _fail(DictationStatus.error(DictationIssue.noSpeech));
    }
  }

  Future<void> _stopEngine() async {
    try {
      if (engine == 'vosk') {
        await _fb?.voskStop();
      } else if (engine == 'recognizer') {
        await _e.stop();
      }
    } catch (_) {}
  }

  /// Does Neovarch itself hold RECORD_AUDIO right now (no prompt)?
  Future<bool> _micGranted() async {
    final m = _mic;
    if (m == null) return true;
    try {
      return (await m.status()).granted;
    } catch (_) {
      return true;
    }
  }

  /// The recogniser said "insufficient permissions". When our own permission is
  /// granted, the speech SERVICE lacks the mic: use the fallbacks (the system
  /// speech dialog runs in Google's own activity), and name the real fix.
  Future<void> _onRecognizerPermission(String code) async {
    if (!await _micGranted()) {
      _fail(DictationStatus.error(DictationIssue.permissionDenied));
      return;
    }
    _recognizerDenied = true;
    if (!_fellBack && _fb != null) {
      _fellBack = true;
      _sttReady = false;
      await _startFallback();
      return;
    }
    _fail(DictationStatus.errorText(DictationIssue.recognizerMicDenied, recognizerMicDeniedText));
  }

  /// Asks for RECORD_AUDIO. null = the user backed out of the explanation.
  Future<MicPermission?> _askMic(Future<bool> Function()? rationale) async {
    final m = _mic;
    if (m == null) return MicPermission.granted;
    final st = await m.status();
    if (st.granted) return MicPermission.granted;
    // Explain first, unless Android won't show its dialog anyway (then the
    // request returns "permanent" at once and the strip offers Settings).
    if (st.askable && rationale != null) {
      if (!await rationale()) return null;
    }
    return m.request();
  }

  /// Error after dictation started (the strip shows it; never silent).
  void _fail(DictationStatus s) {
    _cancelTimers();
    error = s.message;
    _partial = '';
    _holdWakeMic(false);
    _set(s);
    _onError?.call(s.message ?? 'Dikte gagal.');
  }

  /// Final text → the composer; the strip goes back to idle.
  void _deliver(String text) {
    _cancelTimers();
    _holdWakeMic(false);
    final t = text.trim();
    _partial = '';
    if (t.isEmpty) {
      if (_stopRequested) {
        _set(DictationStatus.idle);
      } else {
        _fail(DictationStatus.error(DictationIssue.noSpeech));
      }
      return;
    }
    _set(DictationStatus.idle);
    try {
      _userText?.call(t, true);
    } catch (e) {
      error = 'dikte gagal: $e';
    }
  }

  /// Words from any engine (partial or final) for dictation [g].
  void _onWords(int g, String t, bool fin) {
    if (g != _gen) return;
    if (!status.active) return;
    _kick();
    if (fin) {
      _deliver(t.trim().isEmpty ? _partial : t);
      return;
    }
    if (t.trim().isEmpty) return;
    _gotText = true;
    _partial = t;
    if (status.phase == DictationPhase.processing) {
      _set(DictationStatus.processing(partial: t));
    } else {
      _set(DictationStatus.listening(partial: t, level: status.level));
    }
    try {
      _userText?.call(t, false);
    } catch (e) {
      error = 'dikte gagal: $e';
    }
  }

  void _onLevel(int g, double rms) {
    if (g != _gen || status.phase != DictationPhase.listening) return;
    _kick();
    final l = levelFromRms(rms);
    if ((l - status.level).abs() < 0.05) return;
    _set(status.copyWith(level: l));
  }

  Future<bool> _initStt() async {
    if (_sttReady) return true;
    _initFailure = null;
    try {
      _sttReady = await _e.initialize(
        onError: (code) {
          debugPrint('dictation: recognizer error $code');
          if (engine != 'recognizer') return;
          if (status.phase == DictationPhase.processing) {
            _deliver(_partial);
            return;
          }
          if (!status.active) return;
          if (!_gotText && sttPermissionError(code)) {
            unawaited(_onRecognizerPermission(code));
            return;
          }
          // A recogniser that can't run here: try the other ways once.
          if (!_gotText && !_fellBack && sttUnavailableError(code) && _fb != null) {
            _fellBack = true;
            _sttReady = false;
            _cancelTimers();
            unawaited(_startFallback());
            return;
          }
          if (_gotText && (code == 'error_no_match' || code == 'error_speech_timeout')) {
            _deliver(_partial);
            return;
          }
          _fail(DictationStatus.errorText(issueForSttCode(code), sttErrorText(code)));
        },
        onStatus: (st) {
          if (engine != 'recognizer') return;
          if (status.active) _kick();
          if (st != 'done' && st != 'notListening') return;
          if (status.phase == DictationPhase.processing) {
            // stop() was asked: the final result normally came first; give it
            // a moment, then use what was heard.
            if (st == 'done') _deliver(_partial);
            return;
          }
          if (status.phase == DictationPhase.listening && st == 'done') {
            // the recogniser ended on its own (silence / time limit)
            _deliver(_partial);
          }
        },
      ).timeout(initTimeout, onTimeout: () {
        _initFailure = DictationStatus.error(DictationIssue.timeout);
        return false;
      });
      if (!_sttReady) _initFailure ??= DictationStatus.error(DictationIssue.noRecognizer);
    } catch (e) {
      _initFailure = e is PlatformException
          ? DictationStatus.errorText(issueForSttCode(e.code), sttErrorText(e.code))
          : DictationStatus.errorText(DictationIssue.failed, 'Pengenal suara HP gagal dimulai: $e');
      _sttReady = false;
    }
    return _sttReady;
  }

  /// "Hey Neo" listens on the same microphone: pause it while dictating.
  /// Best effort (older builds and other platforms have no such call).
  static void _holdWakeMic(bool on) {
    if (debugEngine != null || kIsWeb || defaultTargetPlatform != TargetPlatform.android) return;
    unawaited(deviceCall<bool>('wakeHoldMic', {'hold': on}).then<void>((_) {}, onError: (_) {}));
  }

  /// Like [_holdWakeMic] but waits (briefly) until Hey Neo let go of the mic,
  /// so the recogniser doesn't start on a busy microphone (error_audio).
  static Future<void> _holdWakeMicNow() async {
    if (debugEngine != null || kIsWeb || defaultTargetPlatform != TargetPlatform.android) return;
    try {
      await deviceCall<bool>('wakeHoldMic', {'hold': true}).timeout(const Duration(milliseconds: 1500));
    } catch (_) {}
  }

  /// Mic → text. Order: Android SpeechRecognizer (speech_to_text), then the
  /// system speech dialog, then offline Vosk (English). [onText] gets partial
  /// words and the final text; [onError] gets any failure in Indonesian;
  /// [rationale] explains the microphone before Android's permission dialog
  /// (return false to cancel).
  /// Never throws: every failure (no recogniser, mic denied or busy, plugin
  /// error, a recogniser that never answers) ends in [status] holding an
  /// error for the user, so the mic button can never take the app down or
  /// stay stuck. "Hey Neo" is paused while dictation holds the microphone.
  Future<void> startDictation({
    required String locale,
    required void Function(String text, bool isFinal) onText,
    void Function(String error)? onError,
    Future<bool> Function()? rationale,
  }) async {
    final g = ++_gen;
    _cancelTimers();
    error = null;
    engine = null;
    _gotText = false;
    _anyEvent = false;
    _fellBack = false;
    _recognizerDenied = false;
    _stopRequested = false;
    _partial = '';
    _locale = locale;
    _userText = onText;
    _onError = onError;
    _set(DictationStatus.starting);
    try {
      await _startDictation(g, rationale);
    } catch (e) {
      if (g != _gen) return;
      _fail(DictationStatus.errorText(DictationIssue.failed, _readable(e)));
    }
  }

  Future<void> _startDictation(int g, Future<bool> Function()? rationale) async {
    if (!canDictate && debugEngine == null && debugFallback == null) {
      _fail(DictationStatus.errorText(DictationIssue.failed, 'Dikte suara belum tersedia di platform ini.'));
      return;
    }
    MicPermission? perm;
    try {
      perm = await _askMic(rationale).timeout(const Duration(minutes: 2), onTimeout: () => MicPermission.denied);
    } catch (_) {
      perm = MicPermission.denied;
    }
    if (g != _gen) return;
    if (perm == null) {
      _set(DictationStatus.idle); // backed out of the explanation
      return;
    }
    if (perm != MicPermission.granted) {
      _fail(DictationStatus.error(perm == MicPermission.permanent ? DictationIssue.permissionPermanent : DictationIssue.permissionDenied));
      return;
    }
    var useRecognizer = true;
    final fb = _fb;
    if (fb != null) {
      try {
        final caps = await fb.caps();
        useRecognizer = caps['recognizer'] ?? true;
        debugPrint('dictation caps: $caps');
      } catch (_) {}
    }
    if (g != _gen) return;
    DictationStatus? failure;
    if (useRecognizer && await _initStt()) {
      if (g != _gen) return;
      try {
        _locales ??= await _e.localeIds().timeout(const Duration(seconds: 5));
      } catch (_) {
        _locales = const [];
      }
      final id = resolveSttLocale(_locales!, _locale) ?? _locale;
      engine = 'recognizer';
      await _holdWakeMicNow();
      if (g != _gen) return;
      final e = _e;
      if (e case final SpeechLevels lv) lv.onLevel = (rms) => _onLevel(g, rms);
      _set(DictationStatus.listening());
      _armTimers();
      try {
        await e.listen(localeId: id, onResult: (t, fin) => _onWords(g, t, fin));
        return;
      } catch (err) {
        debugPrint('dictation: listen failed: $err');
        if (g != _gen) return;
        _cancelTimers();
        _holdWakeMic(false);
        failure = DictationStatus.errorText(_issueOf(err), _readable(err));
      }
    } else {
      failure = _initFailure;
    }
    if (g != _gen) return;
    if (fb == null) {
      _fail(failure ?? (useRecognizer ? DictationStatus.error(DictationIssue.noRecognizer) : DictationStatus.errorText(DictationIssue.noRecognizer, noSpeechServiceText)));
      return;
    }
    // The fallbacks report their own outcome.
    _fellBack = true;
    await _startFallback();
  }

  Future<void> _startFallback() async {
    final g = _gen;
    final fb = _fb!;
    Map<String, bool> caps = const {};
    try {
      caps = await fb.caps();
    } catch (_) {}
    if (g != _gen) return;
    if (caps['intent'] == true) {
      engine = 'intent';
      _holdWakeMic(true);
      _set(DictationStatus.listening());
      try {
        final t = await fb.recognizeIntent(_locale);
        if (g != _gen) return;
        if (t != null && t.trim().isNotEmpty) {
          _deliver(t);
        } else {
          _fail(DictationStatus.error(DictationIssue.noSpeech));
        }
        return;
      } catch (e) {
        debugPrint('dictation: speech dialog failed: $e');
        if (g != _gen) return;
      }
    }
    final english = _locale.toLowerCase().startsWith('en');
    if (english && caps['vosk'] == true) {
      engine = 'vosk';
      _holdWakeMic(true);
      _set(DictationStatus.listening());
      _armTimers();
      try {
        await fb.voskStart(
          onText: (t, fin) => _onWords(g, t, fin),
          onError: (e) {
            if (g == _gen && status.active) _fail(DictationStatus.errorText(DictationIssue.failed, 'Dikte offline berhenti: $e'));
          },
        );
        return;
      } catch (e) {
        if (g == _gen) _fail(DictationStatus.errorText(DictationIssue.failed, 'Dikte offline gagal: $e'));
        return;
      }
    }
    _fail(_recognizerDenied
        ? DictationStatus.errorText(DictationIssue.recognizerMicDenied, recognizerMicDeniedText)
        : DictationStatus.errorText(DictationIssue.noRecognizer, english ? voskModelMissingText : noSpeechServiceText));
  }

  static DictationIssue _issueOf(Object e) {
    if (e is PlatformException) return issueForSttCode(e.code);
    final code = RegExp(r'error_[a-z_]+').firstMatch('$e')?.group(0);
    return code != null ? issueForSttCode(code) : DictationIssue.failed;
  }

  static String _readable(Object e) {
    if (e is PlatformException) return sttErrorText(e.code);
    final t = '$e';
    if (t.contains('error_')) {
      final code = RegExp(r'error_[a-z_]+').firstMatch(t)?.group(0);
      if (code != null) return sttErrorText(code);
    }
    return 'Dikte gagal: $t';
  }

  /// Tap again while listening: stop recording and keep what was heard
  /// (the recogniser's final text, or the last partial words). With nothing
  /// heard yet, just back to idle.
  Future<void> stopDictation() async {
    if (!status.active) {
      await _stopEngine(); // best effort: an engine that kept running
      if (status.isError) _set(DictationStatus.idle);
      return;
    }
    _stopRequested = true;
    final g = _gen;
    final heard = _partial.trim().isNotEmpty;
    if (status.phase == DictationPhase.starting || engine == 'intent' || !heard) {
      // nothing to wait for
      _gen++;
      await _stopEngine();
      _cancelTimers();
      _holdWakeMic(false);
      _partial = '';
      _set(DictationStatus.idle);
      return;
    }
    _cancelTimers();
    _set(DictationStatus.processing(partial: _partial));
    _finalTimer = Timer(finalTimeout, () {
      if (g == _gen && status.phase == DictationPhase.processing) _deliver(_partial);
    });
    await _stopEngine();
    if (engine == 'vosk' && g == _gen && status.phase == DictationPhase.processing) _deliver(_partial);
  }

  /// Abandon the current dictation without inserting anything.
  Future<void> cancelDictation() async {
    _gen++;
    await _stopEngine();
    _cancelTimers();
    _holdWakeMic(false);
    _partial = '';
    _set(DictationStatus.idle);
  }

  /// Hide an error in the strip.
  void dismissDictationError() {
    if (status.isError) _set(DictationStatus.idle);
  }

  Future<void> speak(String text, {String language = 'id-ID', double rate = 0.5}) async {
    if (!canSpeak) return;
    try {
      _tts ??= FlutterTts();
      final t = _tts!;
      t.setCompletionHandler(() {
        speaking = false;
        notifyListeners();
      });
      await t.setLanguage(language);
      await t.setSpeechRate(rate);
      speaking = true;
      notifyListeners();
      await t.speak(_plain(text));
    } catch (e) {
      speaking = false;
      error = 'pembacaan suara gagal: $e';
      notifyListeners();
    }
  }

  Future<void> stopSpeaking() async {
    try {
      await _tts?.stop();
    } on MissingPluginException {
      // no TTS engine on this platform
    }
    speaking = false;
    notifyListeners();
  }

  /// Strip markdown and code so TTS reads prose, not syntax.
  static String _plain(String md) => md
      .replaceAll(RegExp(r'```[\s\S]*?```'), ' (blok kode) ')
      .replaceAll(RegExp(r'`([^`]*)`'), r'$1')
      .replaceAll(RegExp(r'\[([^\]]+)\]\([^)]+\)'), r'$1')
      .replaceAll(RegExp(r'[#*_>~|]'), '')
      .replaceAll(RegExp(r'\s+'), ' ')
      .trim();
}
