// v1.4.2: theme picker in the first-launch onboarding and before pairing,
// accent-following intro/connect (incl. recoloured art), custom app
// background + glass strength, drag-to-switch on the glass nav bar,
// Cupertino icons and Inter type.
import 'dart:convert';

import 'package:flutter/cupertino.dart' show CupertinoIcons;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:neovarch_agent/main.dart' as app;
import 'package:neovarch_agent/models/models.dart' show ChatMsg;
import 'package:neovarch_agent/remote/appearance.dart';
import 'package:neovarch_agent/remote/l10n/strings.dart' show L10n;
import 'package:neovarch_agent/remote/remote_controller.dart';
import 'package:neovarch_agent/remote/remote_gateway.dart';
import 'package:neovarch_agent/remote/remote_transcript.dart';
import 'package:neovarch_agent/remote/saved_desktops.dart';
import 'package:neovarch_agent/remote/ui/connect_screen.dart';
import 'package:neovarch_agent/remote/ui/remote_app.dart' show PaletteScope, themeFor;
import 'package:neovarch_agent/remote/ui/remote_background.dart';
import 'package:neovarch_agent/remote/ui/remote_intro_screen.dart';
import 'package:neovarch_agent/remote/ui/remote_pc_screen.dart' show AppearancePanel;
import 'package:neovarch_agent/remote/ui/nv_widgets.dart' show NvGlassButton;
import 'package:neovarch_agent/remote/ui/remote_shell.dart';
import 'package:neovarch_agent/state/app_controller.dart' show settingsProvider;
import 'package:neovarch_agent/state/settings_controller.dart';
import 'package:neovarch_agent/remote/ui/appearance/appearance_section.dart' show NvAppearanceSection;
import 'package:neovarch_agent/theme/neovarch_mobile_theme.dart';

const _biru = Color(0xFF2563EB);
// The curated "Biru" swatch of the redesigned accent picker.
const _biruSwatch = Color(0xFF487CDE);

void main() {
  late SharedPreferences prefs;
  late SettingsController settings;

  Future<void> reset({bool paired = true}) async {
    SharedPreferences.setMockInitialValues({
      if (paired)
        'remote.desktops': jsonEncode([
          {'id': 'pc1', 'name': 'PC Kantor', 'url': 'http://192.168.1.20:9319', 'addedAt': DateTime.now().toIso8601String()},
        ]),
      if (paired) 'remote.active': 'pc1',
    });
    prefs = await SharedPreferences.getInstance();
    settings = SettingsController(prefs);
    await settings.load();
    NV.palette = NvPalette.red;
    NV.glassSigma.value = NV.glassBlur;
  }

  setUp(() => reset());
  tearDown(() {
    NV.palette = NvPalette.red;
    NV.glassSigma.value = NV.glassBlur;
    app.previewTab = 0;
  });

  RemoteController controller({bool paired = true}) {
    final desktops = SavedDesktops(prefs)..load();
    final r = RemoteController(desktops)
      ..transcript = RemoteTranscript()
      ..debugApprovals = [];
    if (paired) {
      r
        ..desktop = desktops.items.first
        ..status = RemoteStatus.connected;
    }
    return r;
  }

  Future<AppearanceController> pump(WidgetTester tester, Widget home, {AppearanceController? look, RemoteController? r}) async {
    tester.view.physicalSize = const Size(1170, 2532);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    final l = look ?? AppearanceController(prefs, systemBrightness: Brightness.dark);
    await tester.pumpWidget(ProviderScope(
      overrides: [
        settingsProvider.overrideWith((ref) => settings),
        remoteProvider.overrideWith((ref) => r ?? controller()),
        appearanceProvider.overrideWith((ref) => l),
      ],
      child: Consumer(builder: (context, ref, _) {
        final look = ref.watch(appearanceProvider);
        return MaterialApp(
          theme: themeFor(look),
          builder: (context, child) => PaletteScope(revision: look.revision, look: look, child: child!),
          home: home,
        );
      }),
    ));
    await tester.pump(const Duration(milliseconds: 50));
    return l;
  }

  Future<void> settle(WidgetTester tester) async {
    for (var i = 0; i < 10; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
  }

  test('version is 1.4.5', () => expect(SettingsController.appVersion, '1.4.5'));

  group('Onboarding theme step', () {
    testWidgets('last page "Pilih tema": picker without "Ikuti tema PC", pick = local override, applied live', (tester) async {
      final look = await pump(tester, const RemoteIntroScreen(initialPage: introThemePage), r: controller(paired: false));
      expect(find.byKey(const ValueKey('intro-theme-step')), findsOneWidget);
      expect(find.text('Pilih temamu.'), findsOneWidget);
      expect(find.byType(AppearancePanel), findsOneWidget);
      expect(find.text('Ikuti tema PC'), findsNothing);
      expect(find.byKey(const ValueKey('background-section')), findsNothing);
      expect(find.text('5 / 5'), findsOneWidget);
      expect(find.text('Hubungkan PC'), findsOneWidget); // last page
      expect(look.followPc, isTrue);

      await tester.ensureVisible(find.byKey(const ValueKey('accent-Biru')));
      await settle(tester);
      await tester.tap(find.byKey(const ValueKey('accent-Biru')));
      await settle(tester);
      expect(look.followPc, isFalse);
      expect(NV.red, _biruSwatch);
      expect(prefs.getBool('nv.theme.follow'), isFalse);
      expect(prefs.getString('nv.theme.accent'), '#487CDE');
      // the button and progress dots follow the accent
      final btn = tester.widget<NvGlassButton>(find.byKey(const ValueKey('intro-next')));
      expect(Theme.of(tester.element(find.byKey(const ValueKey('intro-next')))).colorScheme.primary, _biruSwatch);
      expect(btn.onPressed, isNotNull);
      final dot = tester.widget<Container>(find.byKey(const ValueKey('intro-dot-4')));
      expect((dot.decoration as BoxDecoration).color, _biruSwatch);
      expect(find.byKey(const ValueKey('intro-theme-note')), findsOneWidget);

      await tester.tap(find.text('Terang'));
      await settle(tester);
      expect(NV.palette.dark, isFalse);
      expect(tester.widget<Scaffold>(find.byType(Scaffold).first).backgroundColor, NV.bg);

      // finishing the intro keeps the local theme (survives a restart)
      await tester.tap(find.byKey(const ValueKey('intro-next')));
      await settle(tester);
      expect(settings.introSeen, isTrue);
      final again = AppearanceController(prefs, systemBrightness: Brightness.dark);
      expect(again.followPc, isFalse);
      expect(again.accent, _biruSwatch);
      expect(again.dark, isFalse);
    });

    testWidgets('first page "Pilih bahasa": English switches the intro at once', (tester) async {
      addTearDown(() => L10n.code = 'id');
      await pump(tester, const RemoteIntroScreen(), r: controller(paired: false));
      expect(find.byKey(const ValueKey('intro-language-step')), findsOneWidget);
      expect(find.text('Pilih bahasa.'), findsOneWidget);
      expect(find.byKey(const ValueKey('language-system')), findsNothing); // only the two languages here
      await tester.tap(find.byKey(const ValueKey('language-en')));
      await settle(tester);
      expect(find.text('Choose your language.'), findsOneWidget);
      expect(find.text('Continue'), findsOneWidget);
      expect(find.text('Skip'), findsOneWidget);
    });

    testWidgets('language step, slides 1–3 then the theme step; untouched = still follows the PC', (tester) async {
      final look = await pump(tester, const RemoteIntroScreen(), r: controller(paired: false));
      expect(find.text('1 / 5'), findsOneWidget);
      expect(find.byKey(const ValueKey('intro-language-step')), findsOneWidget);
      for (var i = 0; i < 4; i++) {
        await tester.tap(find.byKey(const ValueKey('intro-next')));
        await settle(tester);
      }
      expect(find.byKey(const ValueKey('intro-theme-step')), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('intro-next')));
      await settle(tester);
      expect(settings.introSeen, isTrue);
      expect(look.followPc, isTrue);
      // PC appearance still applies after pairing
      look.applyPc({'accent': '#16A34A', 'base': 'dark'});
      expect(NV.red, const Color(0xFF16A34A));
    });

    test('red art is recoloured to the accent, unchanged in Merah', () {
      expect(artTintFor(NvPalette.defaultAccent), isNull);
      expect(artTintFor(_biru), isNotNull);
      // a red ink pixel maps close to the accent; neutral highlights stay neutral
      List<double> apply(List<double> m, List<double> px) =>
          [for (var r = 0; r < 3; r++) m[r * 5] * px[0] + m[r * 5 + 1] * px[1] + m[r * 5 + 2] * px[2]];
      final m = artTintMatrix(_biru)!;
      final red = apply(m, [238 / 255, 28 / 255, 28 / 255]);
      expect(red[2], greaterThan(red[0])); // blue now dominates
      final white = apply(m, [1, 1, 1]);
      for (final c in white) {
        expect(c, closeTo(1, 1e-6));
      }
    });

    testWidgets('slide art is tinted when the accent is not Merah', (tester) async {
      final look = AppearanceController(prefs, systemBrightness: Brightness.dark);
      await pump(tester, const RemoteIntroScreen(), look: look, r: controller(paired: false));
      expect(find.byKey(const ValueKey('nv-art-tint')), findsNothing);
      look.setLocal(accent: _biru);
      await settle(tester);
      expect(find.byKey(const ValueKey('nv-art-tint')), findsWidgets);
    });
  });

  group('Tampilan before pairing', () {
    testWidgets('connect screen has a Tampilan button that opens the full picker', (tester) async {
      final look = await pump(tester, const ConnectScreen(onboarding: true), r: controller(paired: false));
      final btn = find.byKey(const ValueKey('connect-appearance'));
      expect(btn, findsOneWidget);
      await tester.tap(btn);
      await settle(tester);
      expect(find.byKey(const ValueKey('appearance-sheet')), findsOneWidget);
      expect(find.byType(AppearancePanel), findsOneWidget);
      expect(find.text('Ikuti tema PC'), findsOneWidget);
      await tester.ensureVisible(find.byKey(const ValueKey('accent-Hijau')));
      await settle(tester);
      await tester.tap(find.byKey(const ValueKey('accent-Hijau')));
      await settle(tester);
      expect(look.followPc, isFalse);
      expect(NV.red, const Color(0xFF4FA866));
    });

    testWidgets('"Tambah PC" header also has it', (tester) async {
      await pump(tester, const ConnectScreen());
      expect(find.byKey(const ValueKey('connect-appearance')), findsOneWidget);
    });
  });

  group('Background', () {
    test('persisted, clamped, reset; glass strength drives NvGlass', () {
      final look = AppearanceController(prefs, systemBrightness: Brightness.dark);
      expect(look.background.active, isFalse);
      expect(look.background.dim, 0.4);
      look.setBackground(look.background.copyWith(source: 'asset:${backgroundPresets.first.$2}', blur: 99, dim: 0.55, tint: 0.3, saturation: 1.4, glass: 12));
      expect(look.background.blur, 30); // clamped
      expect(NV.glassSigma.value, 12);
      final again = AppearanceController(prefs, systemBrightness: Brightness.dark);
      expect(again.background, look.background);
      expect(again.background.isAsset, isTrue);
      again.resetBackground();
      expect(again.background, const NvBackground());
      expect(NV.glassSigma.value, NV.glassBlur);
      expect(AppearanceController(prefs).background.active, isFalse);
    });

    testWidgets('drawn behind the shell tabs, tab scaffolds transparent, glass above it', (tester) async {
      final look = AppearanceController(prefs, systemBrightness: Brightness.dark);
      await pump(tester, const RemoteShell(), look: look);
      expect(find.byKey(const ValueKey('nv-app-background')), findsNothing);
      look.setBackground(look.background.copyWith(source: 'asset:${backgroundPresets.last.$2}'));
      await settle(tester);
      expect(find.byKey(const ValueKey('nv-app-background')), findsOneWidget);
      final tabScaffolds = find.descendant(of: find.byType(IndexedStack), matching: find.byType(Scaffold));
      expect(tabScaffolds, findsWidgets);
      expect(Theme.of(tester.element(tabScaffolds.first)).scaffoldBackgroundColor, Colors.transparent);
      // background sits below the nav bar in paint order
      final bg = tester.getRect(find.byKey(const ValueKey('nv-app-background')));
      expect(bg.height, greaterThan(tester.getRect(find.byKey(const ValueKey('nv-nav-bar'))).bottom - 1));
      // glass strength slider value reaches the BackdropFilter
      look.setBackground(look.background.copyWith(glass: 5));
      await tester.pump();
      expect(NV.glassSigma.value, 5);
      look.resetBackground();
      await settle(tester);
      expect(find.byKey(const ValueKey('nv-app-background')), findsNothing);
    });

    testWidgets('Latar belakang controls: presets, gallery, sliders, reset', (tester) async {
      final look = await pump(
          tester,
          Scaffold(
              body: SingleChildScrollView(
                  child: Consumer(builder: (context, ref, _) => const Column(children: [AppearancePanel()])))));
      expect(find.byKey(const ValueKey('background-section')), findsOneWidget);
      expect(find.text('Kekuatan kaca'), findsOneWidget);
      final preset = find.byKey(ValueKey('bg-choice-preset-${backgroundPresets[1].$1}'));
      await tester.ensureVisible(preset);
      await tester.tap(preset);
      await tester.pump();
      expect(look.background.source, 'asset:${backgroundPresets[1].$2}');
      final dim = find.byKey(const ValueKey('bg-dim'));
      await tester.ensureVisible(dim);
      await tester.tapAt(tester.getCenter(dim) + Offset(tester.getSize(dim).width * 0.3, 0));
      await tester.pump();
      expect(look.background.dim, greaterThan(0.4));
      expect(prefs.getDouble('nv.bg.dim'), look.background.dim);
      final resetBtn = find.byKey(const ValueKey('bg-reset'));
      await tester.ensureVisible(resetBtn);
      await tester.tap(resetBtn);
      await tester.pump();
      expect(look.background, const NvBackground());
    });

    testWidgets('gallery pick stores the copied file path', (tester) async {
      final look = await pump(tester, Scaffold(body: SingleChildScrollView(child: BackgroundSection(picker: () async => '/data/user/0/x/nv_background_1.jpg'))));
      await tester.tap(find.byKey(const ValueKey('bg-choice-gallery')));
      await tester.pump();
      await tester.pump();
      expect(look.background.source, 'file:/data/user/0/x/nv_background_1.jpg');
      expect(prefs.getString('nv.bg.source'), 'file:/data/user/0/x/nv_background_1.jpg');
    });
  });

  group('Nav bar drag', () {
    testWidgets('drag the lens along the pill: follows the finger, ticks per tab, snaps and switches on release; taps still work',
        (tester) async {
      final haptics = <String>[];
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, (call) async {
        if (call.method == 'HapticFeedback.vibrate') haptics.add('${call.arguments}');
        return null;
      });
      addTearDown(() => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, null));
      app.previewTab = 0;
      await pump(tester, const RemoteShell());
      await settle(tester);
      IndexedStack stack() => tester.widget<IndexedStack>(find.byType(IndexedStack).first);
      expect(stack().index, 0);

      final bar = tester.getRect(find.byKey(const ValueKey('nv-nav-bar')));
      final tabW = (bar.width - 8) / 4;
      double lensX() => tester.getRect(find.byKey(const ValueKey('nv-nav-lens'))).center.dx;
      final start = Offset(bar.left + 4 + tabW * 0.5, bar.center.dy);
      final g = await tester.startGesture(start);
      await g.moveBy(const Offset(20, 0));
      await tester.pump();
      // move in small steps across two tabs; the lens tracks the finger
      for (var i = 0; i < 10; i++) {
        await g.moveBy(Offset((tabW * 2 - 20) / 10, 0));
        await tester.pump();
      }
      expect(lensX(), closeTo(start.dx + tabW * 2, tabW * 0.15));
      expect(stack().index, 0); // not switched until release
      // the highlight follows the lens: Chat is no longer filled (tab 2 = PC)
      expect(find.byIcon(CupertinoIcons.chat_bubble_fill), findsNothing);
      expect(find.byIcon(CupertinoIcons.person_crop_circle_fill), findsNothing);
      expect(haptics.where((h) => h.contains('selectionClick')).length, 2); // crossed into tab 1, then 2
      await g.up();
      await settle(tester);
      await tester.pump(const Duration(milliseconds: 600));
      expect(stack().index, 2);
      expect(lensX(), closeTo(bar.left + 4 + tabW * 2.5, 1.5));

      // a quick flick from tab 2 to the right lands on the next tab
      await tester.timedDragFrom(Offset(bar.left + 4 + tabW * 2.5, bar.center.dy), Offset(tabW * 0.45, 0), const Duration(milliseconds: 50));
      await settle(tester);
      await tester.pump(const Duration(milliseconds: 600));
      expect(stack().index, 3);

      // plain taps still switch
      await tester.tap(find.descendant(of: find.byKey(const ValueKey('nv-nav-bar')), matching: find.text('CREW')));
      await settle(tester);
      expect(stack().index, 1);
      await tester.tap(find.descendant(of: find.byKey(const ValueKey('nv-nav-bar')), matching: find.text('CHAT')));
      await settle(tester);
      expect(stack().index, 0);
    });
  });

  group('Chat keyboard', () {
    testWidgets('keyboard open: pill hidden, composer sits ~8px above the keyboard; closed: above the pill', (tester) async {
      app.previewTab = 0;
      final r = controller()
        ..transcript = RemoteTranscript(history: [
          for (var i = 0; i < 30; i++) ChatMsg(id: 'm$i', role: i.isEven ? 'user' : 'assistant', content: 'pesan nomor $i', ts: 1000 + i),
        ]);
      tester.view.padding = const FakeViewPadding(bottom: 66);
      tester.view.viewPadding = const FakeViewPadding(bottom: 66);
      await pump(tester, const RemoteShell(), r: r);
      await settle(tester);
      final screenH = tester.view.physicalSize.height / tester.view.devicePixelRatio;
      Rect composer() => tester.getRect(find.byKey(const ValueKey('chat-composer')));
      final bar = tester.getRect(find.byKey(const ValueKey('nv-nav-bar')));
      expect(composer().bottom, lessThanOrEqualTo(bar.top));
      expect(bar.top - composer().bottom, lessThan(24));

      // keyboard up: 300 logical px (system nav padding is consumed by it)
      tester.view.viewInsets = const FakeViewPadding(bottom: 900);
      tester.view.padding = FakeViewPadding.zero;
      await settle(tester);
      final kbTop = screenH - 300;
      expect(find.byKey(const ValueKey('nv-nav-bar')), findsNothing);
      final gap = kbTop - composer().bottom;
      expect(gap, greaterThanOrEqualTo(0));
      expect(gap, lessThanOrEqualTo(16));
      // newest message stays in view just above the composer
      final last = tester.getRect(find.text('pesan nomor 29'));
      expect(last.bottom, lessThan(composer().top));
      expect(last.bottom, greaterThan(composer().top - 140));

      // keyboard down: back above the pill
      tester.view.viewInsets = FakeViewPadding.zero;
      tester.view.padding = const FakeViewPadding(bottom: 66);
      await settle(tester);
      expect(find.byKey(const ValueKey('nv-nav-bar')), findsOneWidget);
      expect(composer().bottom, lessThanOrEqualTo(tester.getRect(find.byKey(const ValueKey('nv-nav-bar'))).top));
    });
  });

  group('Accent consistency', () {
    for (final tab in [0, 1, 2, 3]) {
      testWidgets('a non-red accent leaves no default red anywhere (tab $tab)', (tester) async {
        final look = AppearanceController(prefs, systemBrightness: Brightness.dark)..setLocal(accent: const Color(0xFFEA580C));
        app.previewTab = tab;
        final r = controller()
          ..transcript = RemoteTranscript(history: [
            ChatMsg(id: 'u', role: 'user', content: 'halo', ts: 1),
            ChatMsg(id: 'a', role: 'assistant', content: 'Hai!', ts: 2),
          ]);
        await pump(tester, const RemoteShell(), look: look, r: r);
        await settle(tester);
        const red = Color(0xFFEE1C1C);
        final bad = <String>[];
        // (the Merah swatch in the theme picker is red on purpose)
        final swatches = find.descendant(of: find.byType(NvAppearanceSection), matching: find.byWidgetPredicate((_) => true)).evaluate().toSet();
        for (final e in find.byWidgetPredicate((_) => true).evaluate()) {
          if (swatches.contains(e)) continue;
          final w = e.widget;
          Color? c;
          if (w is Icon) c = w.color;
          if (w is Text) c = w.style?.color;
          if (w is ColoredBox) c = w.color;
          if (w is DecoratedBox && w.decoration is BoxDecoration) c = (w.decoration as BoxDecoration).color;
          if (w is Container && w.decoration is BoxDecoration) c = (w.decoration as BoxDecoration).color;
          if (c != null && c.withAlpha(255).toARGB32() == red.toARGB32()) bad.add('${w.runtimeType}');
        }
        expect(bad, isEmpty);
        expect(Theme.of(tester.element(find.byType(IndexedStack).first)).colorScheme.primary, const Color(0xFFEA580C));
      });
    }
  });

  group('iOS look', () {
    test('Inter / Inter Display type, iOS scale, mono only for code', () {
      final t = buildNeovarchMobileTheme();
      expect(NV.sans, 'Inter');
      expect(NV.display().fontFamily, 'InterDisplay');
      expect(NV.display().fontSize, 34);
      expect(NV.display().fontWeight, FontWeight.w700);
      expect(NV.display().letterSpacing!, lessThan(0)); // tight tracking on large sizes
      expect(t.textTheme.bodyLarge!.fontSize, 17);
      expect(t.textTheme.bodyLarge!.fontFamily, 'Inter');
      expect(NV.monoLabel().fontFamily, 'Inter');
      expect(NV.code().fontFamily, NV.mono);
    });

    testWidgets('nav bar uses Cupertino icons, filled when active', (tester) async {
      app.previewTab = 0;
      await pump(tester, const RemoteShell());
      await settle(tester);
      expect(find.byIcon(CupertinoIcons.chat_bubble_fill), findsWidgets);
      expect(find.byIcon(CupertinoIcons.person_crop_circle), findsWidgets);
      expect(find.byIcon(CupertinoIcons.desktopcomputer), findsWidgets);
      expect(find.byIcon(Icons.chat_bubble_rounded), findsNothing);
    });
  });
}

