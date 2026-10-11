// Voice: dictation (speech_to_text) and read-back (flutter_tts), like
// Desktop's mic + "Read replies aloud" toggle.
import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:speech_to_text/speech_recognition_result.dart';
import 'package:speech_to_text/speech_to_text.dart';

import '../data/device_tools.dart' show deviceCall, ensurePermissions;
import '../data/platform_caps.dart';

/// The speech recogniser behind dictation (Android SpeechRecognizer through
/// speech_to_text in the app; a fake in tests).
abstract class SpeechEngine {
  Future<bool> initialize({required void Function(String error) onError, required void Function(String status) onStatus});
  Future<List<String>> localeIds();
  Future<void> listen({required String localeId, required void Function(String words, bool isFinal) onResult});
  Future<void> stop();
}

class _SttEngine implements SpeechEngine {
  final SpeechToText _stt = SpeechToText();
  @override
  Future<bool> initialize({required void Function(String error) onError, required void Function(String status) onStatus}) =>
      _stt.initialize(onError: (e) => onError(e.errorMsg), onStatus: onStatus);
  @override
  Future<List<String>> localeIds() async => [for (final l in await _stt.locales()) l.localeId];
  @override
  Future<void> listen({required String localeId, required void Function(String words, bool isFinal) onResult}) => _stt.listen(
        onResult: (SpeechRecognitionResult r) => onResult(r.recognizedWords, r.finalResult),
        listenOptions: SpeechListenOptions(
          partialResults: true,
          cancelOnError: true,
          listenMode: ListenMode.dictation,
          localeId: localeId,
          pauseFor: const Duration(seconds: 4),
          listenFor: const Duration(minutes: 2),
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

/// No speech service at all on this phone (Indonesian text).
const noSpeechServiceText = 'HP ini tidak punya layanan pengenal suara. Pasang "Speech Services by Google" (Play Store / GetApps), '
    'atau ganti dikte ke English (tekan lama tombol mik) untuk memakai model offline Hey Neo.';
const voskModelMissingText = 'HP ini tidak punya layanan pengenal suara. Untuk dikte offline (English), nyalakan Hey Neo sekali di Profil '
    'supaya model suara terunduh, atau pasang "Speech Services by Google".';

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
String sttErrorText(String code) => switch (code) {
      'error_permission' || 'error_insufficient_permissions' => 'Izin mikrofon ditolak. Buka Pengaturan → Aplikasi → Neovarch → Izin → Mikrofon.',
      'error_no_match' || 'error_speech_timeout' => 'Suara tidak tertangkap. Coba lagi lebih dekat ke mikrofon.',
      'error_network' || 'error_network_timeout' || 'error_server' => 'Pengenalan suara butuh internet (atau unduh paket bahasa offline di pengaturan Google).',
      'error_language_not_supported' || 'error_language_unavailable' => 'Bahasa ini belum tersedia di pengenal suara HP. Ganti ID/EN (tekan lama tombol mik).',
      'error_busy' || 'error_recognizer_busy' => 'Pengenal suara sedang dipakai aplikasi lain.',
      'error_audio' => 'Mikrofon sedang dipakai (mis. aplikasi lain atau "Hey Neo"). Coba lagi sebentar lagi.',
      'error_client' => 'Pengenal suara HP menolak permintaan. Coba lagi, atau mulai ulang aplikasi Google.',
      'error_timeout' => 'Pengenal suara tidak menjawab. Coba lagi.',
      _ => 'Dikte gagal ($code).',
    };

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
  /// Tests: the Android fallbacks (RecognizerIntent / Vosk).
  @visibleForTesting
  static SpeechFallback? debugFallback;
  /// Tests: how long the recogniser may take to start before dictation gives up.
  @visibleForTesting
  static Duration initTimeout = const Duration(seconds: 12);

  SpeechEngine? _engine;
  SpeechEngine get _e => _engine ??= debugEngine ?? _SttEngine();
  SpeechFallback? _fallbackImpl;
  SpeechFallback? get _fb {
    if (debugFallback != null) return debugFallback;
    if (kIsWeb || defaultTargetPlatform != TargetPlatform.android || debugEngine != null) return null;
    return _fallbackImpl ??= _ChannelFallback();
  }

  FlutterTts? _tts;
  bool _sttReady = false;
  bool listening = false;
  bool speaking = false;
  String? error;
  List<String>? _locales;

  /// Which recogniser the current / last dictation used:
  /// `recognizer`, `intent`, `vosk` (diagnostics, tests).
  String? engine;

  // current dictation
  void Function(String text, bool isFinal)? _onText;
  void Function(String error)? _onError;
  bool _gotText = false;
  bool _fellBack = false;
  String _locale = 'id_ID';

  @visibleForTesting
  void debugReset() {
    _engine = null;
    _sttReady = false;
    _locales = null;
    listening = false;
    error = null;
    engine = null;
  }

  Future<bool> _micPermission() async {
    final f = debugMicPermission;
    if (f != null) return f();
    if (kIsWeb || defaultTargetPlatform != TargetPlatform.android) return true;
    try {
      return await ensurePermissions(const ['android.permission.RECORD_AUDIO']);
    } catch (_) {
      return true; // no bridge: let the recogniser ask
    }
  }

  /// Error after dictation started (the chat shows it; never silent).
  void _fail(String text) {
    error = text;
    listening = false;
    _holdWakeMic(false);
    notifyListeners();
    _onError?.call(text);
  }

  Future<bool> _initStt() async {
    if (_sttReady) return true;
    try {
      _sttReady = await _e.initialize(
        onError: (code) {
          debugPrint('dictation: recognizer error $code');
          // A recogniser that can't run here: try the other ways once.
          if (!_gotText && !_fellBack && sttUnavailableError(code) && _fb != null) {
            _fellBack = true;
            _sttReady = false;
            unawaited(_startFallback());
            return;
          }
          _fail(sttErrorText(code));
        },
        onStatus: (st) {
          if ((st == 'done' || st == 'notListening') && listening && engine == 'recognizer') {
            listening = false;
            _holdWakeMic(false);
            notifyListeners();
            if (!_gotText && error == null) _fail(sttErrorText('error_no_match'));
          }
        },
      ).timeout(initTimeout, onTimeout: () {
        error = sttErrorText('error_timeout');
        return false;
      });
      if (!_sttReady) error ??= 'Pengenal suara tidak tersedia. Pasang/aktifkan aplikasi Google (Speech Services).';
    } catch (e) {
      error = e is PlatformException ? sttErrorText(e.code) : 'Pengenal suara HP gagal dimulai: $e';
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

  /// Mic → text. Order: Android SpeechRecognizer (speech_to_text), then the
  /// system speech dialog, then offline Vosk (English). [onText] gets partial
  /// words and the final text; [onError] gets any later failure in Indonesian.
  /// Never throws: every failure (no recogniser, mic denied or busy, plugin
  /// error, a recogniser that never answers) ends in [error] holding a message
  /// for the user and [listening] false, so the mic button can never take the
  /// app down. "Hey Neo" is paused while dictation holds the microphone.
  Future<void> startDictation({
    required String locale,
    required void Function(String text, bool isFinal) onText,
    void Function(String error)? onError,
  }) async {
    error = null;
    engine = null;
    _gotText = false;
    _fellBack = false;
    _locale = locale;
    _onText = (t, fin) {
      if (t.trim().isNotEmpty) _gotText = true;
      try {
        onText(t, fin);
      } catch (e) {
        error = 'dikte gagal: $e';
      }
      if (fin) {
        listening = false;
        _holdWakeMic(false);
        notifyListeners();
      }
    };
    _onError = onError;
    try {
      await _startDictation();
    } catch (e) {
      listening = false;
      _holdWakeMic(false);
      error = _readable(e);
      notifyListeners();
    }
  }

  Future<void> _startDictation() async {
    if (!canDictate && debugEngine == null && debugFallback == null) {
      error = 'dikte suara belum tersedia di platform ini';
      notifyListeners();
      return;
    }
    bool allowed;
    try {
      allowed = await _micPermission().timeout(const Duration(minutes: 2), onTimeout: () => false);
    } catch (_) {
      allowed = false;
    }
    if (!allowed) {
      error = sttErrorText('error_permission');
      notifyListeners();
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
    if (useRecognizer && await _initStt()) {
      try {
        _locales ??= await _e.localeIds().timeout(const Duration(seconds: 5));
      } catch (_) {
        _locales = const [];
      }
      final id = resolveSttLocale(_locales!, _locale) ?? _locale;
      engine = 'recognizer';
      _holdWakeMic(true);
      listening = true;
      notifyListeners();
      try {
        await _e.listen(localeId: id, onResult: (t, fin) => _onText?.call(t, fin));
        return;
      } catch (e) {
        debugPrint('dictation: listen failed: $e');
        listening = false;
        _holdWakeMic(false);
        error = _readable(e);
      }
    }
    if (fb == null) {
      error ??= useRecognizer ? 'Pengenal suara tidak tersedia. Pasang/aktifkan aplikasi Google (Speech Services).' : noSpeechServiceText;
      notifyListeners();
      return;
    }
    // The fallbacks report their own outcome.
    error = null;
    _fellBack = true;
    await _startFallback();
  }

  Future<void> _startFallback() async {
    final fb = _fb!;
    Map<String, bool> caps = const {};
    try {
      caps = await fb.caps();
    } catch (_) {}
    if (caps['intent'] == true) {
      engine = 'intent';
      _holdWakeMic(true);
      listening = true;
      notifyListeners();
      try {
        final t = await fb.recognizeIntent(_locale);
        listening = false;
        _holdWakeMic(false);
        notifyListeners();
        if (t != null && t.trim().isNotEmpty) {
          _onText?.call(t, true);
        } else {
          _fail(sttErrorText('error_no_match'));
        }
        return;
      } catch (e) {
        debugPrint('dictation: speech dialog failed: $e');
        listening = false;
      }
    }
    final english = _locale.toLowerCase().startsWith('en');
    if (english && caps['vosk'] == true) {
      engine = 'vosk';
      _holdWakeMic(true);
      listening = true;
      notifyListeners();
      try {
        await fb.voskStart(onText: (t, fin) => _onText?.call(t, fin), onError: (e) => _fail('Dikte offline berhenti: $e'));
        return;
      } catch (e) {
        _fail('Dikte offline gagal: $e');
        return;
      }
    }
    _fail(english ? voskModelMissingText : noSpeechServiceText);
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

  Future<void> stopDictation() async {
    try {
      if (engine == 'vosk') {
        await _fb?.voskStop();
      } else {
        await _e.stop();
      }
    } catch (_) {}
    listening = false;
    _holdWakeMic(false);
    notifyListeners();
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
