// "Mode ringan" can always be turned off again: on → off persists across a
// restart, the low-RAM suggestion never re-enables it, reduce-transparency
// follows every glass-style × lite combination, the switch sits first in
// Profil › Tampilan, and the "Mode ringan aktif · Matikan" chip turns it off
// in one tap with the glass (BackdropFilter) back at once, no restart.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:neovarch_agent/main.dart' as app;
import 'package:neovarch_agent/remote/appearance.dart';
import 'package:neovarch_agent/remote/lite_mode.dart';
import 'package:neovarch_agent/remote/remote_controller.dart';
import 'package:neovarch_agent/remote/remote_gateway.dart';
import 'package:neovarch_agent/remote/remote_transcript.dart';
import 'package:neovarch_agent/remote/saved_desktops.dart';
import 'package:neovarch_agent/remote/ui/appearance/panel_tone.dart' show NvGlassFx;
import 'package:neovarch_agent/remote/ui/lite_mode_panel.dart';
import 'package:neovarch_agent/remote/ui/remote_app.dart' show PaletteScope, themeFor;
import 'package:neovarch_agent/remote/ui/remote_profile_screen.dart' show ProfileGroup;
import 'package:neovarch_agent/remote/ui/remote_shell.dart';
import 'package:neovarch_agent/state/app_controller.dart' show settingsProvider;
import 'package:neovarch_agent/state/settings_controller.dart';
import 'package:neovarch_agent/theme/neovarch_mobile_theme.dart';
import 'package:shared_preferences/shared_preferences.dart';

Future<void> _loadFonts() async {
  final manifest = jsonDecode(await rootBundle.loadString('FontManifest.json')) as List;
  for (final f in manifest.cast<Map<String, dynamic>>()) {
    final loader = FontLoader(f['family'] as String);
    for (final a in (f['fonts'] as List).cast<Map<String, dynamic>>()) {
      loader.addFont(rootBundle.load(a['asset'] as String));
    }
    await loader.load();
  }
}

Map<String, Object> _paired() => {
      'remote.desktops': jsonEncode([
        {'id': 'pc1', 'name': 'PC', 'url': 'http://192.168.1.20:9319', 'addedAt': '2026-10-01T00:00:00', 'lastConnected': '2026-10-01T00:00:00'},
      ]),
      'remote.active': 'pc1',
      'nv.perf.liteSuggested': true,
    };

void main() {
  setUpAll(() async {
    TestWidgetsFlutterBinding.ensureInitialized();
    await _loadFonts();
  });

  tearDown(() {
    NV.liteMode = false;
    NV.glassStyle = NvGlassStyle.reguler;
    NvGlassFx.reduceTransparency.value = false;
    liteMemoryReader = readMemoryInfo;
    app.previewTab = 0;
    ProfileGroup.debugOpen = {};
  });

  group('controller', () {
    test('on → off → a new AppearanceController(prefs) starts off', () async {
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      final look = AppearanceController(prefs);
      await look.setLiteMode(true);
      expect(AppearanceController(prefs).liteMode, isTrue);
      await look.setLiteMode(false);
      expect(look.liteMode, isFalse);
      expect(NV.liteMode, isFalse);
      expect(prefs.getBool(AppearanceController.kLite), isFalse);
      final again = AppearanceController(prefs);
      expect(again.liteMode, isFalse);
      expect(NV.liteMode, isFalse);
      expect(NvGlassFx.reduceTransparency.value, isFalse);
    });

    test('setting the same value re-asserts the app-wide flags', () async {
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      final look = AppearanceController(prefs);
      NV.liteMode = true; // stale flag from elsewhere
      NvGlassFx.reduceTransparency.value = true;
      await look.setLiteMode(false);
      expect(NV.liteMode, isFalse);
      expect(NvGlassFx.reduceTransparency.value, isFalse);
      expect(prefs.getBool(AppearanceController.kLite), isFalse);
    });

    test('the low-RAM suggestion never turns it back on', () async {
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      Future<Map?> small() async => {'total': 3 << 30, 'low_ram': true};
      final look = AppearanceController(prefs);
      // suggested once → user turned it on → then off
      expect(await liteSuggestion(prefs, liteOn: look.liteMode, read: small), isNotNull);
      await look.setLiteMode(true);
      await look.setLiteMode(false);
      expect(await liteSuggestion(prefs, liteOn: look.liteMode, read: small), isNull, reason: 'once per install');
      expect(look.liteMode, isFalse);
      expect(prefs.getBool(AppearanceController.kLite), isFalse);
      // even a suggestion that does show only offers; it never writes the setting
      await prefs.remove(kLiteSuggested);
      expect(await liteSuggestion(prefs, liteOn: false, read: small), isNotNull);
      expect(prefs.getBool(AppearanceController.kLite), isFalse);
      expect(AppearanceController(prefs).liteMode, isFalse);
    });

    test('reduceTransparency for every glass style × Mode ringan', () async {
      for (final st in NvGlassStyle.values) {
        for (final lite in [false, true]) {
          SharedPreferences.setMockInitialValues({'nv.glass.style': st.name, AppearanceController.kLite: lite});
          final prefs = await SharedPreferences.getInstance();
          final look = AppearanceController(prefs);
          final want = st == NvGlassStyle.tanpa || lite;
          expect(look.reduceTransparency, want, reason: '${st.name} lite=$lite');
          expect(NvGlassFx.reduceTransparency.value, want, reason: '${st.name} lite=$lite');
          // toggling Mode ringan only ever adds/removes its own part
          await look.setLiteMode(!lite);
          expect(NvGlassFx.reduceTransparency.value, st == NvGlassStyle.tanpa || !lite, reason: '${st.name} toggled to ${!lite}');
          await look.setLiteMode(false);
          expect(NvGlassFx.reduceTransparency.value, st == NvGlassStyle.tanpa, reason: '${st.name} off');
          expect(NV.liteMode, isFalse);
        }
      }
    });
  });

  group('UI', () {
    late SharedPreferences prefs;
    late SettingsController settings;

    // settings.load() does real async work: only outside the fake-async zone
    setUp(() async {
      SharedPreferences.setMockInitialValues(_paired());
      prefs = await SharedPreferences.getInstance();
      settings = SettingsController(prefs);
      await settings.load();
    });

    // the in-memory cache updates synchronously (no await in the fake zone)
    void startLite() => prefs.setBool(AppearanceController.kLite, true);

    Future<AppearanceController> pumpShell(WidgetTester tester) async {
      final desktops = SavedDesktops(prefs)..load();
      final r = RemoteController(desktops)
        ..transcript = RemoteTranscript()
        ..debugApprovals = []
        ..desktop = desktops.items.first
        ..status = RemoteStatus.connected;
      final look = AppearanceController(prefs, systemBrightness: Brightness.dark);
      tester.view.physicalSize = const Size(1170, 2532);
      tester.view.devicePixelRatio = 3;
      addTearDown(tester.view.reset);
      app.previewTab = 3; // Profil
      await tester.pumpWidget(ProviderScope(
        overrides: [
          settingsProvider.overrideWith((ref) => settings),
          remoteProvider.overrideWith((ref) => r),
          appearanceProvider.overrideWith((ref) => look),
        ],
        child: Consumer(builder: (context, ref, _) {
          final look = ref.watch(appearanceProvider);
          return MaterialApp(
            theme: themeFor(look),
            builder: (context, child) => PaletteScope(revision: look.revision, look: look, child: child!),
            home: const RemoteShell(),
          );
        }),
      ));
      await settle(tester);
      return look;
    }

    int blurs() => find.byType(BackdropFilter, skipOffstage: false).evaluate().length;

    testWidgets('chip "Mode ringan aktif · Matikan" turns it off in one tap; glass is back at once', (tester) async {
      startLite();
      final look = await pumpShell(tester);
      expect(look.liteMode, isTrue);
      expect(blurs(), 0, reason: 'no backdrop blur while Mode ringan is on');
      final chip = find.byKey(const ValueKey('lite-mode-chip'));
      expect(chip, findsOneWidget);
      expect(find.text('Mode ringan aktif'), findsOneWidget);
      expect(find.text('Matikan'), findsOneWidget);
      await tester.tap(chip);
      await settle(tester);
      expect(look.liteMode, isFalse);
      expect(NV.liteMode, isFalse);
      expect(NvGlassFx.reduceTransparency.value, isFalse);
      expect(prefs.getBool(AppearanceController.kLite), isFalse);
      expect(chip, findsNothing);
      expect(blurs(), greaterThan(0), reason: 'the glass surfaces have their blur back without a restart');
      expect(find.byKey(const ValueKey('nv-theme-crossfade')), findsNothing, reason: 'the cross-fade never sticks');
      expect(AppearanceController(prefs).liteMode, isFalse);
      await tester.pumpWidget(const SizedBox());
    });

    testWidgets('switch is first in Tampilan and turns it off; state and scroll kept', (tester) async {
      startLite();
      ProfileGroup.debugOpen = {'appearance'};
      final look = await pumpShell(tester);
      final sw = find.byKey(const ValueKey('lite-mode'));
      expect(sw, findsOneWidget);
      // above every other Tampilan card
      final swY = tester.getTopLeft(find.byKey(const ValueKey('lite-mode-panel'))).dy;
      expect(swY, lessThan(tester.getTopLeft(find.byKey(const ValueKey('appearance-panel'))).dy));
      expect(swY, greaterThan(tester.getTopLeft(find.byKey(const ValueKey('profile-group-appearance'))).dy));
      await tester.ensureVisible(sw);
      await settle(tester);
      final scr = find.descendant(of: find.byKey(const ValueKey('profile-list')), matching: find.byType(Scrollable)).first;
      final before = tester.state<ScrollableState>(scr);
      final px = before.position.pixels;
      await tester.tap(sw);
      await settle(tester);
      expect(look.liteMode, isFalse);
      expect(tester.widget<SwitchListTile>(sw).value, isFalse);
      expect(identical(tester.state<ScrollableState>(scr), before), isTrue);
      expect(before.position.pixels, px);
      expect(blurs(), greaterThan(0));
      // and back on, then off again: never stuck
      await tester.tap(sw);
      await settle(tester);
      expect(look.liteMode, isTrue);
      await tester.tap(sw);
      await settle(tester);
      expect(look.liteMode, isFalse);
      expect(AppearanceController(prefs).liteMode, isFalse);
      await tester.pumpWidget(const SizedBox());
    });

    testWidgets('suggestion snackbar without "Aktifkan" leaves it off', (tester) async {
      prefs.remove(kLiteSuggested); // cache updates synchronously
      final look = AppearanceController(prefs);
      liteMemoryReader = () async => {'total': 3 << 30};
      await tester.pumpWidget(ProviderScope(
        overrides: [appearanceProvider.overrideWith((ref) => look)],
        child: MaterialApp(
          home: Scaffold(
            body: Consumer(builder: (context, ref, _) => TextButton(onPressed: () => maybeSuggestLiteMode(context, ref), child: const Text('cek'))),
          ),
        ),
      ));
      await tester.tap(find.text('cek'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));
      expect(find.textContaining('Profil (paling atas)'), findsOneWidget);
      await tester.pumpAndSettle(const Duration(seconds: 13));
      expect(look.liteMode, isFalse);
      expect(prefs.getBool(AppearanceController.kLite), isNull);
    });
  });
}

Future<void> settle(WidgetTester tester) async {
  for (var i = 0; i < 10; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}
