// Record-then-send dictation (1.4.9): the phone records, the PC's local STT
// (faster-whisper / whisper.cpp) transcribes; the text goes into the field.
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:neovarch_agent/remote/pc_dictation.dart';
import 'package:neovarch_agent/remote/ui/dictation_strip.dart';
import 'package:neovarch_agent/state/voice_service.dart';

class _Engine implements SpeechEngine {
  _Engine({this.ready = false});
  bool ready;
  int listens = 0;
  @override
  Future<bool> initialize({required void Function(String error) onError, required void Function(String status) onStatus}) async => ready;
  @override
  Future<List<String>> localeIds() async => ['id_ID'];
  @override
  Future<void> listen({required String localeId, required void Function(String words, bool isFinal) onResult}) async => listens++;
  @override
  Future<void> stop() async {}
}

class _Rec implements AudioRecorder {
  bool ok = true;
  int starts = 0, stops = 0, cancels = 0;
  Uint8List? audio = Uint8List(4000);
  @override
  String get mimeType => 'audio/mp4';
  @override
  Future<bool> start() async {
    starts++;
    return ok;
  }

  @override
  Future<Uint8List?> stop() async {
    stops++;
    return audio;
  }

  @override
  Future<void> cancel() async => cancels++;
}

class _Mic implements MicPermissions {
  @override
  Future<({bool granted, bool askable})> status() async => (granted: true, askable: true);
  @override
  Future<MicPermission> request() async => MicPermission.granted;
}

Future<void> _settle([int n = 8]) async {
  for (var i = 0; i < n; i++) {
    await Future<void>.delayed(Duration.zero);
  }
}

void main() {
  final v = VoiceService.instance;
  late _Engine engine;
  late _Rec rec;
  final sent = <(int, String, String)>[];
  var answer = 'buka repo neovarch';
  Object? fail;

  setUp(() {
    engine = _Engine();
    rec = _Rec();
    sent.clear();
    answer = 'buka repo neovarch';
    fail = null;
    VoiceService.debugEngine = engine;
    VoiceService.debugMicPermissions = _Mic();
    VoiceService.debugRecorder = rec;
    VoiceService.pcTranscriber = (a, mime, locale) async {
      sent.add((a.length, mime, locale));
      if (fail != null) throw fail!;
      return answer;
    };
    v.debugReset();
  });
  tearDown(() {
    VoiceService.debugEngine = null;
    VoiceService.debugMicPermissions = null;
    VoiceService.debugRecorder = null;
    VoiceService.pcTranscriber = null;
    v.debugReset();
  });

  test('no recogniser on the phone → record, tap again → PC transcript into the field (not sent)', () async {
    final got = <(String, bool)>[];
    await v.startDictation(locale: 'id_ID', onText: (t, f) => got.add((t, f)));
    expect(v.engine, 'pc');
    expect(v.status.phase, DictationPhase.listening);
    expect(v.status.toPc, isTrue);
    expect(rec.starts, 1);
    await v.stopDictation();
    await _settle();
    expect(sent, [(4000, 'audio/mp4', 'id_ID')]);
    expect(got, [('buka repo neovarch', true)]);
    expect(v.status.phase, DictationPhase.idle);
  });

  test('route "pc" skips a working recogniser', () async {
    engine.ready = true;
    await v.startDictation(locale: 'en_US', route: 'pc', onText: (_, _) {});
    expect(engine.listens, 0);
    expect(v.engine, 'pc');
    await v.stopDictation();
    await _settle();
    expect(sent.single.$3, 'en_US');
  });

  test('route "auto" keeps the phone recogniser when it works', () async {
    engine.ready = true;
    await v.startDictation(locale: 'id_ID', onText: (_, _) {});
    expect(v.engine, 'recognizer');
    expect(rec.starts, 0);
    await v.cancelDictation();
  });

  test('PC without an STT engine → clear Indonesian error with the install command', () async {
    fail = const PcTranscriptionError('no engine', code: 'stt_unavailable');
    await v.startDictation(locale: 'id_ID', onText: (_, _) {});
    await v.stopDictation();
    await _settle();
    expect(v.status.isError, isTrue);
    expect(v.status.message, contains('pip install faster-whisper'));
    expect(v.status.action, DictationAction.retry);
  });

  test('mic cannot open / empty recording / cancel', () async {
    rec.ok = false;
    await v.startDictation(locale: 'id_ID', onText: (_, _) {});
    expect(v.status.issue, DictationIssue.audio);
    rec.ok = true;
    rec.audio = Uint8List(10);
    await v.startDictation(locale: 'id_ID', onText: (_, _) {});
    await v.stopDictation();
    await _settle();
    expect(v.status.issue, DictationIssue.noSpeech);
    expect(sent, isEmpty);
    await v.startDictation(locale: 'id_ID', onText: (_, _) {});
    await v.cancelDictation();
    expect(rec.cancels, 1);
    expect(v.status.phase, DictationPhase.idle);
  });

  test('no PC link and no recogniser → the old "no recogniser" error, never a hang', () async {
    VoiceService.pcTranscriber = null;
    await v.startDictation(locale: 'id_ID', onText: (_, _) {});
    expect(v.status.isError, isTrue);
    expect(v.status.issue, DictationIssue.noRecognizer);
  });

  test('PC answers are parsed: transcript, typed refusal, failure text', () {
    expect(transcriptOf({'ok': true, 'transcript': 'halo'}), 'halo');
    expect(() => transcriptOf({'ok': false, 'code': 'stt_unavailable', 'error': 'x', 'transcript': ''}),
        throwsA(isA<PcTranscriptionError>().having((e) => e.code, 'code', 'stt_unavailable')));
    expect(pcSttErrorText(const PcTranscriptionError('Transkripsi gagal (faster-whisper): oom / Failed', code: 'stt_failed')),
        'Transkripsi di PC gagal: Transkripsi gagal (faster-whisper): oom');
    expect(sttLanguageOf('id_ID'), 'id');
    expect(sttLanguageOf('en-US'), 'en');
  });

  testWidgets('strip says it is recording for / transcribing on the PC', (t) async {
    await v.startDictation(locale: 'id_ID', onText: (_, _) {});
    await t.pumpWidget(MaterialApp(home: Scaffold(body: DictationStrip(voice: v, onStop: () {}, onAction: (_) {}))));
    expect(find.textContaining('kirim ke PC'), findsOneWidget);
    await v.cancelDictation();
    await t.pump();
  });
}
