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
  /// Tests: how long the recogniser may take to start before dictation gives up.
  @visibleForTesting
  static Duration initTimeout = const Duration(seconds: 12);

  SpeechEngine? _engine;
  SpeechEngine get _e => _engine ??= debugEngine ?? _SttEngine();
  FlutterTts? _tts;
  bool _sttReady = false;
  bool listening = false;
  bool speaking = false;
  String? error;
  List<String>? _locales;

  @visibleForTesting
  void debugReset() {
    _engine = null;
    _sttReady = false;
    _locales = null;
    listening = false;
    error = null;
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

  Future<bool> _initStt() async {
    if (_sttReady) return true;
    if (!canDictate && debugEngine == null) {
      error = 'dikte suara belum tersedia di platform ini';
      return false;
    }
    bool allowed;
    try {
      allowed = await _micPermission().timeout(const Duration(minutes: 2), onTimeout: () => false);
    } catch (_) {
      allowed = false;
    }
    if (!allowed) {
      error = sttErrorText('error_permission');
      return false;
    }
    try {
      _sttReady = await _e.initialize(
        onError: (e) {
          error = sttErrorText(e);
          listening = false;
          notifyListeners();
        },
        onStatus: (s) {
          if (s == 'done' || s == 'notListening') {
            listening = false;
            _holdWakeMic(false);
            notifyListeners();
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

  /// Starts dictation. Never throws: every failure (no recogniser, mic denied
  /// or busy, plugin error) ends in [error] holding a message for the user and
  /// [listening] false, so the mic button can never take the app down.
  Future<void> startDictation({required String locale, required void Function(String text, bool isFinal) onText}) async {
    error = null;
    try {
      if (!await _initStt()) {
        error ??= 'pengenalan suara tidak tersedia di perangkat ini';
        listening = false;
        notifyListeners();
        return;
      }
      try {
        _locales ??= await _e.localeIds().timeout(const Duration(seconds: 5));
      } catch (_) {
        _locales = const [];
      }
      final id = resolveSttLocale(_locales!, locale) ?? locale;
      _holdWakeMic(true);
      listening = true;
      notifyListeners();
      void safeText(String words, bool isFinal) {
        try {
          onText(words, isFinal);
        } catch (e) {
          error = 'dikte gagal: $e';
        }
        if (isFinal) _holdWakeMic(false);
      }

      await _e.listen(localeId: id, onResult: safeText);
    } catch (e) {
      listening = false;
      _holdWakeMic(false);
      error = _readable(e);
      notifyListeners();
    }
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
      await _e.stop();
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
