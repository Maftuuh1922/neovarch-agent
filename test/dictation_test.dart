// Composer dictation (1.4.8): the state machine behind the status strip,
// its Indonesian messages and fix buttons, the watchdog that never leaves
// the mic stuck in "listening", and the strip itself.
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:neovarch_agent/remote/ui/dictation_strip.dart';
import 'package:neovarch_agent/state/voice_service.dart';

class _Engine implements SpeechEngine, SpeechLevels {
  bool ready = true;
  void Function(String)? onError;
  void Function(String)? onStatus;
  void Function(String, bool)? onResult;
  void Function(double)? level;
  int listens = 0;
  int stops = 0;
  Object? listenError;
  @override
  set onLevel(void Function(double rms)? f) => level = f;
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
    if (listenError != null) throw listenError!;
    listens++;
    this.onResult = onResult;
  }

  @override
  Future<void> stop() async => stops++;
}

class _Fallback implements SpeechFallback {
  _Fallback(this.c);
  Map<String, bool> c;
  @override
  Future<Map<String, bool>> caps() async => c;
  @override
  Future<String?> recognizeIntent(String locale) async => null;
  @override
  Future<void> voskStart({required void Function(String text, bool isFinal) onText, required void Function(String error) onError}) async {}
  @override
  Future<void> voskStop() async {}
}

class _Mic implements MicPermissions {
  _Mic({this.granted = false, this.askable = true, this.answer = MicPermission.granted});
  bool granted;
  bool askable;
  MicPermission answer;
  int requests = 0;
  Completer<MicPermission>? pending;
  @override
  Future<({bool granted, bool askable})> status() async => (granted: granted, askable: askable);
  @override
  Future<MicPermission> request() {
    requests++;
    if (pending != null) return pending!.future;
    return Future.value(answer);
  }
}

Future<void> _settle([int n = 6]) async {
  for (var i = 0; i < n; i++) {
    await Future<void>.delayed(Duration.zero);
  }
}

void main() {
  group('messages and actions', () {
    test('recogniser codes map to clear issues (incl. speech_to_text 7.x spellings)', () {
      expect(issueForSttCode('error_permission'), DictationIssue.permissionDenied);
      expect(issueForSttCode('error_no_match'), DictationIssue.noSpeech);
      expect(issueForSttCode('error_speech_timeout'), DictationIssue.noSpeech);
      expect(issueForSttCode('error_network'), DictationIssue.network);
      expect(issueForSttCode('error_network_timeout'), DictationIssue.network);
      expect(issueForSttCode('error_audio_error'), DictationIssue.audio);
      expect(issueForSttCode('error_audio'), DictationIssue.audio);
      expect(issueForSttCode('error_busy'), DictationIssue.busy);
      expect(issueForSttCode('error_too_many_requests'), DictationIssue.busy);
      expect(issueForSttCode('error_language_not_supported'), DictationIssue.language);
      expect(issueForSttCode('recognizerNotAvailable'), DictationIssue.noRecognizer);
      expect(issueForSttCode('error_unknown (11)'), DictationIssue.failed);
      expect(sttErrorText('error_audio_error'), contains('Mikrofon sedang dipakai'));
      expect(sttErrorText('error_unknown (11)'), contains('error_unknown (11)'));
    });

    test('every error is Indonesian and the right ones offer a fix', () {
      expect(dictationMessage(DictationIssue.permissionDenied), contains('Izin mikrofon ditolak'));
      expect(dictationMessage(DictationIssue.permissionPermanent), contains('ditolak permanen'));
      expect(dictationMessage(DictationIssue.noRecognizer), contains('Speech Services Google tidak ada'));
      expect(dictationMessage(DictationIssue.noSpeech), contains('tidak ada suara terdeteksi'));
      expect(dictationMessage(DictationIssue.network), contains('Jaringan'));
      expect(dictationActionFor(DictationIssue.permissionPermanent), DictationAction.openAppSettings);
      expect(dictationActionFor(DictationIssue.noRecognizer), DictationAction.installSpeechServices);
      expect(dictationActionFor(DictationIssue.recognizerMicDenied), DictationAction.openSpeechServices);
      expect(dictationActionFor(DictationIssue.noSpeech), DictationAction.retry);
      expect(dictationActionLabel(DictationAction.openAppSettings), 'Buka pengaturan');
      expect(dictationActionLabel(DictationAction.installSpeechServices), 'Pasang Speech Services');
      expect(dictationActionLabel(DictationAction.openSpeechServices), 'Buka Speech Services');
      expect(dictationActionLabel(DictationAction.none), isNull);
      for (final i in DictationIssue.values) {
        expect(dictationMessage(i), isNotEmpty);
      }
    });

    test('transcript is appended to what was typed, empty results change nothing', () {
      expect(insertTranscript('', ' halo neo '), 'halo neo');
      expect(insertTranscript('tolong ', 'rapikan folder'), 'tolong rapikan folder');
      expect(insertTranscript('tolong', ''), 'tolong');
      expect(insertTranscript('tolong', '   '), 'tolong');
    });

    test('level from RMS dB is 0..1', () {
      expect(levelFromRms(-10), 0);
      expect(levelFromRms(20), 1);
      expect(levelFromRms(4), closeTo(0.5, 0.01));
      expect(levelFromRms(double.nan), 0);
    });
  });

  group('state machine', () {
    final v = VoiceService.instance;
    late _Engine engine;
    late _Mic mic;
    setUp(() {
      engine = _Engine();
      mic = _Mic(granted: true);
      VoiceService.debugEngine = engine;
      VoiceService.debugMicPermissions = mic;
      VoiceService.watchdogTimeout = const Duration(milliseconds: 80);
      VoiceService.finalTimeout = const Duration(milliseconds: 60);
      v.debugReset();
    });
    tearDown(() {
      VoiceService.debugEngine = null;
      VoiceService.debugMicPermissions = null;
      VoiceService.debugFallback = null;
      VoiceService.watchdogTimeout = const Duration(seconds: 10);
      VoiceService.finalTimeout = const Duration(seconds: 3);
      v.debugReset();
    });

    test('idle → listening (partial + level) → final text → idle', () async {
      final phases = <DictationPhase>[];
      void track() => phases.add(v.status.phase);
      v.addListener(track);
      final got = <(String, bool)>[];
      await v.startDictation(locale: 'id_ID', onText: (t, f) => got.add((t, f)));
      expect(v.status.phase, DictationPhase.listening);
      expect(v.listening, isTrue);
      engine.level!(8);
      expect(v.status.level, greaterThan(0.5));
      engine.onResult!('halo', false);
      expect(v.status.partial, 'halo');
      engine.onResult!('halo neo', true);
      v.removeListener(track);
      expect(got, [('halo', false), ('halo neo', true)]);
      expect(v.status, DictationStatus.idle);
      expect(v.listening, isFalse);
      expect(phases.first, DictationPhase.starting);
      expect(phases, contains(DictationPhase.listening));
    });

    test('permission denied permanently → error with "Buka pengaturan", recogniser never started', () async {
      mic
        ..granted = false
        ..askable = false
        ..answer = MicPermission.permanent;
      var asked = 0;
      await v.startDictation(locale: 'id_ID', onText: (_, _) {}, rationale: () async {
        asked++;
        return true;
      });
      expect(asked, 0, reason: 'Android will not show its dialog: no explanation first');
      expect(v.status.phase, DictationPhase.error);
      expect(v.status.issue, DictationIssue.permissionPermanent);
      expect(v.status.action, DictationAction.openAppSettings);
      expect(v.status.message, contains('permanen'));
      expect(engine.listens, 0);
    });

    test('first time: explanation, then the system dialog; backing out stays silent', () async {
      mic
        ..granted = false
        ..askable = true;
      await v.startDictation(locale: 'id_ID', onText: (_, _) {}, rationale: () async => false);
      expect(mic.requests, 0);
      expect(v.status, DictationStatus.idle);
      expect(v.error, isNull);

      mic.answer = MicPermission.denied;
      var asked = 0;
      await v.startDictation(locale: 'id_ID', onText: (_, _) {}, rationale: () async {
        asked++;
        return true;
      });
      expect(asked, 1);
      expect(mic.requests, 1);
      expect(v.status.issue, DictationIssue.permissionDenied);
      expect(v.status.action, DictationAction.retry);

      mic.answer = MicPermission.granted;
      await v.startDictation(locale: 'id_ID', onText: (_, _) {}, rationale: () async => true);
      expect(v.status.phase, DictationPhase.listening);
      await v.cancelDictation();
    });

    test('no Speech Services and no fallback → "Pasang Speech Services"', () async {
      engine.ready = false;
      VoiceService.debugFallback = _Fallback({'recognizer': true, 'intent': false, 'vosk': false});
      await v.startDictation(locale: 'id_ID', onText: (_, _) {});
      expect(v.status.issue, DictationIssue.noRecognizer);
      expect(v.status.action, DictationAction.installSpeechServices);
      expect(v.listening, isFalse);
    });

    test('speech service lacks the mic → "Buka Speech Services"', () async {
      VoiceService.debugFallback = _Fallback({'recognizer': true, 'intent': false, 'vosk': false});
      await v.startDictation(locale: 'id_ID', onText: (_, _) {});
      engine.onError!('error_permission');
      await _settle();
      expect(v.status.issue, DictationIssue.recognizerMicDenied);
      expect(v.status.action, DictationAction.openSpeechServices);
    });

    test('mic busy on start (error_audio_error) → clear message, not stuck', () async {
      engine.listenError = Exception('error_audio_error');
      await v.startDictation(locale: 'id_ID', onText: (_, _) {});
      expect(v.status.issue, DictationIssue.audio);
      expect(v.status.message, contains('Mikrofon sedang dipakai'));
      expect(v.listening, isFalse);
    });

    test('network error while listening → "Jaringan" + Coba lagi', () async {
      await v.startDictation(locale: 'id_ID', onText: (_, _) {});
      engine.onError!('error_network');
      expect(v.status.issue, DictationIssue.network);
      expect(v.status.action, DictationAction.retry);
      expect(v.listening, isFalse);
    });

    test('recogniser ends without hearing anything → "tidak ada suara terdeteksi"', () async {
      await v.startDictation(locale: 'id_ID', onText: (_, _) {});
      engine.onStatus!('listening');
      engine.onStatus!('done');
      expect(v.status.issue, DictationIssue.noSpeech);
    });

    test('watchdog: a recogniser that never calls back resets to an error', () async {
      await v.startDictation(locale: 'id_ID', onText: (_, _) {});
      expect(v.listening, isTrue);
      await Future<void>.delayed(const Duration(milliseconds: 200));
      expect(v.listening, isFalse);
      expect(v.status.issue, DictationIssue.timeout);
      expect(engine.stops, greaterThan(0));
    });

    test('watchdog keeps the words heard so far', () async {
      final got = <(String, bool)>[];
      await v.startDictation(locale: 'id_ID', onText: (t, f) => got.add((t, f)));
      engine.onResult!('buka kalender', false);
      await Future<void>.delayed(const Duration(milliseconds: 200));
      expect(v.status, DictationStatus.idle);
      expect(got.last, ('buka kalender', true));
    });

    test('tap again: processing, then the final text', () async {
      final got = <(String, bool)>[];
      await v.startDictation(locale: 'id_ID', onText: (t, f) => got.add((t, f)));
      engine.onResult!('kirim laporan', false);
      await v.stopDictation();
      expect(v.status.phase, DictationPhase.processing);
      expect(v.listening, isTrue);
      engine.onResult!('kirim laporan harian', true);
      expect(v.status, DictationStatus.idle);
      expect(got.last, ('kirim laporan harian', true));
    });

    test('tap again with no final from the recogniser → last words after a short wait', () async {
      final got = <(String, bool)>[];
      await v.startDictation(locale: 'id_ID', onText: (t, f) => got.add((t, f)));
      engine.onResult!('cek email', false);
      await v.stopDictation();
      await Future<void>.delayed(const Duration(milliseconds: 150));
      expect(v.status, DictationStatus.idle);
      expect(got.last, ('cek email', true));
    });

    test('tap again before anything was heard → idle, no text, no error', () async {
      final got = <(String, bool)>[];
      await v.startDictation(locale: 'id_ID', onText: (t, f) => got.add((t, f)));
      await v.stopDictation();
      expect(v.status, DictationStatus.idle);
      expect(got, isEmpty);
      expect(v.error, isNull);
      // a late error from the stopped recogniser is ignored
      engine.onError!('error_no_match');
      expect(v.status, DictationStatus.idle);
    });

    test('tap again while the permission dialog is open → idle; the late answer is ignored', () async {
      mic
        ..granted = false
        ..pending = Completer<MicPermission>();
      final started = v.startDictation(locale: 'id_ID', onText: (_, _) {});
      await _settle();
      expect(v.status.phase, DictationPhase.starting);
      await v.stopDictation();
      expect(v.status, DictationStatus.idle);
      mic.pending!.complete(MicPermission.granted);
      await started;
      expect(v.status, DictationStatus.idle);
      expect(engine.listens, 0);
    });

    test('an error can be dismissed and the next tap starts fresh', () async {
      engine.listenError = Exception('error_busy');
      await v.startDictation(locale: 'id_ID', onText: (_, _) {});
      expect(v.status.isError, isTrue);
      v.dismissDictationError();
      expect(v.status, DictationStatus.idle);
      engine.listenError = null;
      await v.startDictation(locale: 'id_ID', onText: (_, _) {});
      expect(v.status.phase, DictationPhase.listening);
      await v.cancelDictation();
      expect(v.status, DictationStatus.idle);
    });
  });

  group('status strip', () {
    final v = VoiceService.instance;
    late _Engine engine;
    setUp(() {
      engine = _Engine();
      VoiceService.debugEngine = engine;
      VoiceService.debugMicPermissions = _Mic(granted: true);
      v.debugReset();
    });
    tearDown(() {
      VoiceService.debugEngine = null;
      VoiceService.debugMicPermissions = null;
      v.debugReset();
    });

    Future<List<DictationAction>> pumpStrip(WidgetTester tester, {VoidCallback? onStop}) async {
      final actions = <DictationAction>[];
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(body: DictationStrip(voice: v, onStop: onStop ?? () {}, onAction: actions.add)),
      ));
      return actions;
    }

    testWidgets('hidden when idle; "Mendengarkan…" with live words while listening', (tester) async {
      var stopped = 0;
      await pumpStrip(tester, onStop: () => stopped++);
      expect(find.byKey(const ValueKey('dictation-strip')), findsNothing);
      await v.startDictation(locale: 'id_ID', onText: (_, _) {});
      engine.onResult!('halo dunia', false);
      await tester.pump();
      expect(find.text('Mendengarkan…'), findsOneWidget);
      expect(find.text('halo dunia'), findsOneWidget);
      expect(find.byKey(const ValueKey('dictation-strip-level')), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('dictation-strip-stop')));
      expect(stopped, 1);
      await v.cancelDictation();
      await tester.pump();
      expect(find.byKey(const ValueKey('dictation-strip')), findsNothing);
    });

    testWidgets('permanent denial: message + "Buka pengaturan" button; close hides it', (tester) async {
      VoiceService.debugMicPermissions = _Mic(granted: false, askable: false, answer: MicPermission.permanent);
      final actions = await pumpStrip(tester);
      await v.startDictation(locale: 'id_ID', onText: (_, _) {});
      await tester.pump();
      expect(find.textContaining('ditolak permanen'), findsOneWidget);
      expect(find.text('Buka pengaturan'), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('dictation-strip-action')));
      expect(actions, [DictationAction.openAppSettings]);
      await tester.tap(find.byKey(const ValueKey('dictation-strip-close')));
      await tester.pump();
      expect(find.byKey(const ValueKey('dictation-strip')), findsNothing);
    });

    testWidgets('no recogniser: "Pasang Speech Services"', (tester) async {
      engine.ready = false;
      final actions = await pumpStrip(tester);
      await v.startDictation(locale: 'id_ID', onText: (_, _) {});
      await tester.pump();
      expect(find.text('Pasang Speech Services'), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('dictation-strip-action')));
      expect(actions, [DictationAction.installSpeechServices]);
    });
  });
}
