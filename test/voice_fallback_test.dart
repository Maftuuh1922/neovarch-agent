// Chat dictation without Google's speech service (Xiaomi): system speech
// dialog, offline Vosk (English), and visible errors instead of silence.
import 'package:flutter_test/flutter_test.dart';
import 'package:neovarch_agent/state/voice_service.dart';

class _Engine implements SpeechEngine {
  bool ready = true;
  void Function(String)? onError;
  void Function(String)? onStatus;
  void Function(String, bool)? onResult;
  int listens = 0;
  @override
  Future<bool> initialize({required void Function(String error) onError, required void Function(String status) onStatus}) async {
    this.onError = onError;
    this.onStatus = onStatus;
    return ready;
  }

  @override
  Future<List<String>> localeIds() async => ['id_ID', 'en_US'];
  @override
  Future<void> listen({required String localeId, required void Function(String words, bool isFinal) onResult}) async {
    listens++;
    this.onResult = onResult;
  }

  @override
  Future<void> stop() async {}
}

class _Fallback implements SpeechFallback {
  _Fallback(this.c, {this.intentText});
  Map<String, bool> c;
  String? intentText;
  final calls = <String>[];
  void Function(String, bool)? voskText;
  @override
  Future<Map<String, bool>> caps() async => c;
  @override
  Future<String?> recognizeIntent(String locale) async {
    calls.add('intent:$locale');
    return intentText;
  }

  @override
  Future<void> voskStart({required void Function(String text, bool isFinal) onText, required void Function(String error) onError}) async {
    calls.add('vosk');
    voskText = onText;
  }

  @override
  Future<void> voskStop() async => calls.add('voskStop');
}

void main() {
  final v = VoiceService.instance;
  late _Engine engine;
  setUp(() {
    engine = _Engine();
    VoiceService.debugEngine = engine;
    VoiceService.debugMicPermission = () async => true;
    v.debugReset();
  });
  tearDown(() {
    VoiceService.debugEngine = null;
    VoiceService.debugFallback = null;
    VoiceService.debugMicPermission = null;
    v.debugReset();
  });

  test('phone with a recognizer: partial words stream, final text arrives', () async {
    VoiceService.debugFallback = _Fallback({'recognizer': true, 'intent': true, 'vosk': false});
    final got = <(String, bool)>[];
    await v.startDictation(locale: 'id_ID', onText: (t, f) => got.add((t, f)));
    expect(v.engine, 'recognizer');
    engine.onResult!('halo', false);
    engine.onResult!('halo neo apa kabar', true);
    expect(got, [('halo', false), ('halo neo apa kabar', true)]);
    expect(v.listening, isFalse);
  });

  test('no recognizer service (Xiaomi) → system speech dialog', () async {
    final fb = _Fallback({'recognizer': false, 'intent': true, 'vosk': true}, intentText: 'buatin ppt');
    VoiceService.debugFallback = fb;
    final got = <(String, bool)>[];
    await v.startDictation(locale: 'id_ID', onText: (t, f) => got.add((t, f)));
    expect(engine.listens, 0);
    expect(fb.calls, ['intent:id_ID']);
    expect(v.engine, 'intent');
    expect(got, [('buatin ppt', true)]);
    expect(v.error, isNull);
  });

  test('no recognizer, no dialog, English → offline Vosk streams into the field', () async {
    final fb = _Fallback({'recognizer': false, 'intent': false, 'vosk': true});
    VoiceService.debugFallback = fb;
    final got = <(String, bool)>[];
    await v.startDictation(locale: 'en_US', onText: (t, f) => got.add((t, f)));
    expect(fb.calls, ['vosk']);
    expect(v.engine, 'vosk');
    fb.voskText!('make a', false);
    fb.voskText!('make a deck', true);
    expect(got.last, ('make a deck', true));
    await v.stopDictation();
    expect(fb.calls.last, 'voskStop');
  });

  test('nothing available in Indonesian → clear message, not silence', () async {
    VoiceService.debugFallback = _Fallback({'recognizer': false, 'intent': false, 'vosk': true});
    final errors = <String>[];
    await v.startDictation(locale: 'id_ID', onText: (_, _) {}, onError: errors.add);
    expect(errors.single, noSpeechServiceText);
    expect(v.error, noSpeechServiceText);
    expect(v.listening, isFalse);
    VoiceService.debugFallback = _Fallback({'recognizer': false, 'intent': false, 'vosk': false});
    v.debugReset();
    await v.startDictation(locale: 'en_US', onText: (_, _) {}, onError: errors.add);
    expect(errors.last, voskModelMissingText);
  });

  test('recognizer that cannot run here (error_client) falls back once', () async {
    final fb = _Fallback({'recognizer': true, 'intent': true, 'vosk': false}, intentText: 'tes');
    VoiceService.debugFallback = fb;
    final got = <(String, bool)>[];
    await v.startDictation(locale: 'id_ID', onText: (t, f) => got.add((t, f)));
    engine.onError!('error_client');
    await Future<void>.delayed(Duration.zero);
    await Future<void>.delayed(Duration.zero);
    expect(fb.calls, ['intent:id_ID']);
    expect(got, [('tes', true)]);
  });

  test('recognizer stops without hearing anything → "Suara tidak tertangkap"', () async {
    VoiceService.debugFallback = _Fallback({'recognizer': true, 'intent': false, 'vosk': false});
    final errors = <String>[];
    await v.startDictation(locale: 'id_ID', onText: (_, _) {}, onError: errors.add);
    engine.onStatus!('done');
    expect(errors.single, contains('Suara tidak tertangkap'));
  });

  test('microphone permission denied → message', () async {
    VoiceService.debugMicPermission = () async => false;
    await v.startDictation(locale: 'id_ID', onText: (_, _) {});
    expect(v.error, contains('Izin mikrofon ditolak'));
  });

  test('recognizer says error_permission while the app HAS the mic → fallback, not "izin ditolak" (v1.4.7)', () async {
    final fb = _Fallback({'recognizer': true, 'intent': true, 'vosk': false}, intentText: 'halo');
    VoiceService.debugFallback = fb;
    final got = <(String, bool)>[];
    final errors = <String>[];
    await v.startDictation(locale: 'id_ID', onText: (t, f) => got.add((t, f)), onError: errors.add);
    engine.onError!('error_permission');
    for (var i = 0; i < 5; i++) {
      await Future<void>.delayed(Duration.zero);
    }
    expect(fb.calls, ['intent:id_ID']);
    expect(got, [('halo', true)]);
    expect(errors, isEmpty);
  });

  test('recognizer mic denied and no fallback → names the speech service, not Neovarch', () async {
    VoiceService.debugFallback = _Fallback({'recognizer': true, 'intent': false, 'vosk': false});
    final errors = <String>[];
    await v.startDictation(locale: 'id_ID', onText: (_, _) {}, onError: errors.add);
    engine.onError!('error_permission');
    for (var i = 0; i < 5; i++) {
      await Future<void>.delayed(Duration.zero);
    }
    expect(errors.single, recognizerMicDeniedText);
    expect(errors.single, isNot(contains('Izin mikrofon ditolak')));
  });

  test('app really lacks the mic → the Neovarch permission message', () async {
    VoiceService.debugFallback = _Fallback({'recognizer': true, 'intent': true, 'vosk': false});
    final errors = <String>[];
    await v.startDictation(locale: 'id_ID', onText: (_, _) {}, onError: errors.add);
    VoiceService.debugMicPermission = () async => false;
    engine.onError!('error_permission');
    for (var i = 0; i < 5; i++) {
      await Future<void>.delayed(Duration.zero);
    }
    expect(errors.single, contains('Izin mikrofon ditolak'));
  });
}
