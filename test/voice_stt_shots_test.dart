// Screenshots of voice dictation via the PC (1.4.9) on a 392 px phone, dark
// and light: Profil → Dikte suara, and the composer strip while recording for
// the PC, transcribing there, and the "no STT on the PC" error.
// Run with --update-goldens and NV_SHOTS_DIR=… to write PNGs; a plain run only
// checks each view renders without errors.
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:neovarch_agent/remote/appearance.dart';
import 'package:neovarch_agent/remote/remote_controller.dart';
import 'package:neovarch_agent/remote/saved_desktops.dart';
import 'package:neovarch_agent/remote/ui/dictation_settings_panel.dart';
import 'package:neovarch_agent/remote/ui/dictation_strip.dart';
import 'package:neovarch_agent/remote/ui/remote_app.dart' show PaletteScope;
import 'package:neovarch_agent/state/app_controller.dart' show settingsProvider;
import 'package:neovarch_agent/state/settings_controller.dart';
import 'package:neovarch_agent/state/voice_service.dart';
import 'package:neovarch_agent/theme/neovarch_mobile_theme.dart';

final _shotsDir = Platform.environment['NV_SHOTS_DIR'] ?? 'build/screenshots/voice';

class _Engine implements SpeechEngine {
  @override
  Future<bool> initialize({required void Function(String error) onError, required void Function(String status) onStatus}) async => false;
  @override
  Future<List<String>> localeIds() async => const [];
  @override
  Future<void> listen({required String localeId, required void Function(String words, bool isFinal) onResult}) async {}
  @override
  Future<void> stop() async {}
}

class _Rec implements AudioRecorder {
  @override
  String get mimeType => 'audio/mp4';
  @override
  Future<bool> start() async => true;
  @override
  Future<Uint8List?> stop() async => Uint8List(4000);
  @override
  Future<void> cancel() async {}
}

class _Mic implements MicPermissions {
  @override
  Future<({bool granted, bool askable})> status() async => (granted: true, askable: true);
  @override
  Future<MicPermission> request() async => MicPermission.granted;
}

void main() {
  late SharedPreferences prefs;
  late SettingsController settings;
  final v = VoiceService.instance;

  setUpAll(() async {
    TestWidgetsFlutterBinding.ensureInitialized();
    final manifest = jsonDecode(await rootBundle.loadString('FontManifest.json')) as List;
    for (final f in manifest.cast<Map<String, dynamic>>()) {
      final loader = FontLoader(f['family'] as String);
      for (final a in (f['fonts'] as List).cast<Map<String, dynamic>>()) {
        loader.addFont(rootBundle.load(a['asset'] as String));
      }
      await loader.load();
    }
  });

  tearDown(() {
    VoiceService.debugEngine = null;
    VoiceService.debugMicPermissions = null;
    VoiceService.debugRecorder = null;
    VoiceService.pcTranscriber = null;
    v.debugReset();
  });

  Future<void> setUpPrefs({required bool light}) async {
    SharedPreferences.setMockInitialValues({'nv.theme.pc.base': light ? 'light' : 'dark', 'dictationEngine': 'pc'});
    prefs = await SharedPreferences.getInstance();
    settings = SettingsController(prefs);
    await settings.load();
    VoiceService.debugEngine = _Engine();
    VoiceService.debugMicPermissions = _Mic();
    VoiceService.debugRecorder = _Rec();
    v.debugReset();
  }

  Future<void> shot(WidgetTester tester, String name, {required String state}) async {
    tester.view.physicalSize = const Size(392 * 3, 760 * 3);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    final r = RemoteController(SavedDesktops(prefs)..load());
    final look = AppearanceController(prefs);
    NV.palette = look.palette;
    await tester.pumpWidget(ProviderScope(
      overrides: [
        settingsProvider.overrideWith((ref) => settings),
        remoteProvider.overrideWith((ref) => r),
        appearanceProvider.overrideWith((ref) => look),
      ],
      child: RepaintBoundary(
        key: const ValueKey('shot'),
        child: MaterialApp(
          debugShowCheckedModeBanner: false,
          theme: buildNeovarchMobileTheme(),
          builder: (context, child) => PaletteScope(revision: look.revision, child: child!),
          home: Scaffold(
            backgroundColor: NV.bg,
            body: SafeArea(
              child: ListView(padding: const EdgeInsets.only(top: 16), children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(20, 0, 20, 10),
                  child: Text('Profil → Dikte suara', style: TextStyle(fontSize: 13, color: NV.muted)),
                ),
                const DictationSettingsPanel(),
                const SizedBox(height: 28),
                Padding(
                  padding: const EdgeInsets.fromLTRB(20, 0, 20, 6),
                  child: Text('Chat → mik ($state)', style: TextStyle(fontSize: 13, color: NV.muted)),
                ),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 12),
                  child: DictationStrip(voice: v, onStop: () {}, onAction: (_) {}),
                ),
              ]),
            ),
          ),
        ),
      ),
    ));
    await tester.pump();
    if (state != 'idle') {
      final never = Completer<String>(); // keeps "transcribing" on screen
      VoiceService.pcTranscriber = (a, m, l) async {
        if (state == 'error') throw const PcTranscriptionError('no engine', code: 'stt_unavailable');
        return never.future;
      };
      await v.startDictation(locale: 'id_ID', route: 'pc', onText: (_, _) {});
      if (state == 'error') await v.stopDictation();
      if (state == 'processing') unawaited(v.stopDictation());
      await tester.pump();
    }
    await tester.pump(const Duration(milliseconds: 300));
    expect(tester.takeException(), isNull);
    if (autoUpdateGoldenFiles) {
      final dir = Directory(_shotsDir).absolute.path;
      Directory(dir).createSync(recursive: true);
      await expectLater(find.byKey(const ValueKey('shot')), matchesGoldenFile('$dir/$name.png'));
    }
    await v.cancelDictation();
  }

  for (final light in [false, true]) {
    final mode = light ? 'light' : 'dark';
    group(mode, () {
      setUp(() => setUpPrefs(light: light));
      testWidgets('merekam', (t) => shot(t, 'phone-392-$mode-1-merekam-untuk-pc', state: 'recording'));
      testWidgets('transkripsi', (t) => shot(t, 'phone-392-$mode-2-transkripsi-di-pc', state: 'processing'));
      testWidgets('error', (t) => shot(t, 'phone-392-$mode-3-pc-belum-ada-stt', state: 'error'));
    });
  }
}
