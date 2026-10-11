// v1.4.2 (second batch): 4-tab nav (Chat · Kantor · PC · Profil) with a lens
// wide enough for its labels, approvals merged into Chat (chip + sheet),
// Kantor | Tugas segments, Profil (Tampilan + launcher icon + social slot),
// nav avatar, liquid-glass greeting and the glass/animated intro.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:neovarch_agent/remote/social_models.dart';
import 'package:neovarch_agent/remote/ui/remote_profile_screen.dart' show ProfileGroup;
import 'package:shared_preferences/shared_preferences.dart';

import 'package:neovarch_agent/main.dart' as app;
import 'package:neovarch_agent/remote/app_icon.dart';
import 'package:neovarch_agent/remote/appearance.dart';
import 'package:neovarch_agent/remote/profile_avatar.dart';
import 'package:neovarch_agent/remote/remote_controller.dart';
import 'package:neovarch_agent/remote/remote_gateway.dart';
import 'package:neovarch_agent/remote/remote_transcript.dart';
import 'package:neovarch_agent/remote/saved_desktops.dart';
import 'package:neovarch_agent/remote/ui/app_icon_panel.dart';
import 'package:neovarch_agent/remote/ui/appearance/appearance_section.dart' show NvAppearanceSection;
import 'package:neovarch_agent/remote/ui/glass_style_picker.dart';
import 'package:neovarch_agent/remote/wallpaper_palette.dart';
import 'package:neovarch_agent/remote/ui/nv_glass_text.dart';
import 'package:neovarch_agent/remote/ui/nv_widgets.dart';
import 'package:neovarch_agent/remote/ui/profile_header_slot.dart';
import 'package:neovarch_agent/remote/ui/remote_app.dart' show PaletteScope, themeFor;
import 'package:neovarch_agent/remote/ui/remote_intro_screen.dart';
import 'package:neovarch_agent/remote/ui/remote_kantor_tab.dart';
import 'package:neovarch_agent/remote/ui/remote_shell.dart';
import 'package:neovarch_agent/state/app_controller.dart' show settingsProvider;
import 'package:neovarch_agent/state/settings_controller.dart';
import 'package:neovarch_agent/theme/neovarch_mobile_theme.dart';

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

// 1x1 PNG for the avatar
final _png = Uint8List.fromList(base64Decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='));

void main() {
  late SharedPreferences prefs;
  late SettingsController settings;

  setUpAll(() async {
    TestWidgetsFlutterBinding.ensureInitialized();
    await _loadFonts();
  });

  setUp(() async {
    SharedPreferences.setMockInitialValues({
      'remote.desktops': jsonEncode([
        {'id': 'pc1', 'name': 'PC Kantor', 'url': 'http://192.168.1.20:9319', 'addedAt': DateTime.now().toIso8601String()},
      ]),
      'remote.active': 'pc1',
    });
    prefs = await SharedPreferences.getInstance();
    settings = SettingsController(prefs);
    await settings.load();
    NV.palette = NvPalette.red;
  });
  tearDown(() {
    NV.palette = NvPalette.red;
    NV.glassStyle = NvGlassStyle.reguler;
    app.previewTab = 0;
    previewKantorSegment = kantorSegOffice;
  });

  RemoteController controller({bool approvals = false}) {
    final desktops = SavedDesktops(prefs)..load();
    final r = RemoteController(desktops)
      ..transcript = RemoteTranscript()
      ..debugApprovals = [
        if (approvals)
          RemoteApproval(
            sessionId: 'other',
            requestId: 'req1',
            command: 'rm a.pdf',
            description: 'Hapus berkas duplikat',
            toolName: 'terminal',
            choices: const ['once', 'deny'],
            receivedAt: DateTime.now(),
          ),
      ];
    r
      ..desktop = desktops.items.first
      ..status = RemoteStatus.connected;
    return r;
  }

  Future<AppearanceController> pump(WidgetTester tester, Widget home,
      {RemoteController? r, double width = 390, bool reduce = false, List<Override> extra = const []}) async {
    tester.view.physicalSize = Size(width * 3, 844 * 3);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    final l = AppearanceController(prefs, systemBrightness: Brightness.dark);
    await tester.pumpWidget(ProviderScope(
      overrides: [
        settingsProvider.overrideWith((ref) => settings),
        remoteProvider.overrideWith((ref) => r ?? controller()),
        appearanceProvider.overrideWith((ref) => l),
        ...extra,
      ],
      child: Consumer(builder: (context, ref, _) {
        final look = ref.watch(appearanceProvider);
        return MaterialApp(
          theme: themeFor(look),
          builder: (context, child) => PaletteScope(
              revision: look.revision,
              look: look,
              child: MediaQuery(data: MediaQuery.of(context).copyWith(disableAnimations: reduce), child: child!)),
          home: home,
        );
      }),
    ));
    await tester.pump(const Duration(milliseconds: 50));
    return l;
  }

  Future<void> settle(WidgetTester tester, [int n = 10]) async {
    for (var i = 0; i < n; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
  }

  final navBar = find.byKey(const ValueKey('nv-nav-bar'));
  Finder inNav(String t) => find.descendant(of: navBar, matching: find.text(t));

  group('4-tab nav', () {
    testWidgets('Chat · Kantor · PC · Profil; no Tugas / Setujui tabs', (tester) async {
      await pump(tester, const RemoteShell());
      await settle(tester, 4);
      for (final t in ['CHAT', 'KANTOR', 'PROFIL', 'PC']) {
        expect(inNav(t), findsOneWidget);
      }
      expect(inNav('TUGAS'), findsNothing);
      expect(inNav('SETUJUI'), findsNothing);
    });

    for (final width in [390.0, 360.0]) {
      for (final (tab, label) in [(1, 'KANTOR'), (3, 'PROFIL'), (0, 'CHAT')]) {
        testWidgets('lens fits the magnified $label with padding · ${width.toInt()} dp', (tester) async {
          app.previewTab = tab;
          await pump(tester, const RemoteShell(), width: width);
          await settle(tester, 6);
          final lensF = find.byKey(const ValueKey('nv-nav-lens'));
          final lens = tester.getRect(lensF);
          final mag = tester.widget<NvLens>(lensF).magnification;
          final text = tester.getRect(inNav(label));
          // centred on the tab label
          expect((lens.center.dx - text.center.dx).abs(), lessThan(1.0));
          // magnified label width + >= 10 px each side
          final magW = text.width * mag;
          expect(lens.width - magW, greaterThanOrEqualTo(20.0 - 0.01), reason: 'lens ${lens.width} vs ${magW.toStringAsFixed(1)}');
          expect(mag, greaterThanOrEqualTo(1.0));
          // never wider than the allowed overreach, never over a neighbouring label
          final bar = tester.getRect(navBar);
          final tabW = (bar.width - 8) / 4;
          expect(lens.width, lessThanOrEqualTo(tabW * (1 + NvLensFit.maxOverreach) + 0.01));
          for (final other in ['CHAT', 'KANTOR', 'PROFIL', 'PC']..remove(label)) {
            expect(tester.getRect(inNav(other)).overlaps(lens.deflate(0.5)), isFalse, reason: '$other under the lens');
          }
        });
      }
    }

    testWidgets('lens still follows a drag and springs to the tab', (tester) async {
      await pump(tester, const RemoteShell());
      await settle(tester, 4);
      final bar = tester.getRect(navBar);
      final tabW = (bar.width - 8) / 4;
      double lensX() => tester.getRect(find.byKey(const ValueKey('nv-nav-lens'))).center.dx;
      final g = await tester.startGesture(Offset(bar.left + 4 + tabW * 0.5, bar.center.dy));
      for (var i = 0; i < 10; i++) {
        await g.moveBy(Offset(tabW * 3 / 10, 0));
        await tester.pump(const Duration(milliseconds: 16));
      }
      expect(lensX(), closeTo(bar.left + 4 + tabW * 3.5, tabW * 0.2));
      await g.up();
      await settle(tester);
      expect(lensX(), closeTo(bar.left + 4 + tabW * 3.5, 1.5));
      expect(find.byKey(const ValueKey('profile-header-slot')), findsOneWidget);
    });

    testWidgets('Profil item: person icon by default, avatar (ring when active, dimmed when not) when set', (tester) async {
      await pump(tester, const RemoteShell());
      await settle(tester, 4);
      expect(find.byKey(const ValueKey('nv-nav-avatar-3')), findsNothing);
      final ctx = tester.element(find.byType(RemoteShell));
      final container = ProviderScope.containerOf(ctx);
      container.read(profileAvatarProvider.notifier).state = MemoryImage(_png);
      await settle(tester, 3);
      final av = find.byKey(const ValueKey('nv-nav-avatar-3'));
      expect(av, findsOneWidget);
      expect(tester.getSize(av), const Size(NvNavBar.avatarSize, NvNavBar.avatarSize));
      double opacity() => tester.widget<Opacity>(find.descendant(of: av, matching: find.byType(Opacity)).first).opacity;
      Color ring() => ((tester.widget<Container>(find.descendant(of: av, matching: find.byType(Container)).first).decoration as BoxDecoration).border as Border).top.color;
      expect(opacity(), lessThan(0.7)); // inactive: dimmed
      await tester.tap(inNav('PROFIL'));
      await settle(tester);
      expect(opacity(), closeTo(1, 0.01));
      expect(ring().toARGB32(), NV.red.toARGB32());
    });
  });

  group('Approvals live in Chat', () {
    testWidgets('pinned chip with the count, badge on Chat, sheet lists every approval', (tester) async {
      final r = controller(approvals: true);
      await pump(tester, const RemoteShell(), r: r);
      await settle(tester, 4);
      final chip = find.byKey(const ValueKey('chat-approvals-chip'));
      expect(chip, findsOneWidget);
      expect(find.textContaining('1 menunggu persetujuan'), findsOneWidget);
      // badge "1" sits in the nav bar (on Chat)
      expect(find.descendant(of: navBar, matching: find.text('1')), findsOneWidget);
      await tester.tap(chip);
      await settle(tester);
      expect(find.byKey(const ValueKey('approvals-sheet')), findsOneWidget);
      expect(find.text('Persetujuan'), findsOneWidget);
      expect(find.text('rm a.pdf'), findsWidgets);
    });

    testWidgets('a tapped approval notification (route "approvals") opens Chat + the sheet', (tester) async {
      app.previewTab = 2; // on PC
      await pump(tester, const RemoteShell(), r: controller(approvals: true));
      await settle(tester, 4);
      final state = tester.state(find.byType(RemoteShell)) as dynamic;
      state.route('approvals');
      await settle(tester);
      expect(find.byKey(const ValueKey('approvals-sheet')), findsOneWidget);
      expect(find.byKey(const ValueKey('chat-approvals-chip')), findsOneWidget);
    });
  });

  group('Kantor | Tugas', () {
    testWidgets('one tab with a glass segmented control; route "tasks" opens the Tugas segment', (tester) async {
      app.previewTab = 1;
      await pump(tester, const RemoteShell());
      await settle(tester, 4);
      expect(find.byKey(const ValueKey('kantor-segments')), findsOneWidget);
      expect(find.byType(NvGlassSegmented), findsOneWidget);
      IndexedStack seg() => tester.widget<IndexedStack>(
          find.descendant(of: find.byType(RemoteKantorTab), matching: find.byType(IndexedStack)).first);
      expect(seg().index, kantorSegOffice);
      await tester.tap(find.byKey(const ValueKey('segment-Tugas')));
      await settle(tester, 4);
      expect(seg().index, kantorSegTasks);
      await tester.tap(find.byKey(const ValueKey('segment-Kantor')));
      await settle(tester, 4);
      expect(seg().index, kantorSegOffice);
      // deep link to Tugas from another tab
      await tester.tap(inNav('PC'));
      await settle(tester, 4);
      (tester.state(find.byType(RemoteShell)) as dynamic).route('tasks');
      await settle(tester, 4);
      expect(seg().index, kantorSegTasks);
    });
  });

  group('Profil', () {
    testWidgets('holds the social slot, the whole Tampilan section and the icon picker; PC tab has no theme settings', (tester) async {
      app.previewTab = 3;
      ProfileGroup.debugOpen = {'appearance', 'glass', 'icon', 'friends'};
      addTearDown(() => ProfileGroup.debugOpen = {});
      await pump(tester, const RemoteShell());
      await settle(tester, 4);
      expect(find.byType(ProfileHeaderSlot), findsOneWidget);
      expect(find.byType(NvAppearanceSection), findsOneWidget);
      expect(find.text('Ikuti tema PC'), findsOneWidget);
      expect(find.byKey(const ValueKey('corner-card')), findsOneWidget);
      await tester.scrollUntilVisible(find.byKey(const ValueKey('app-icon-panel')), 300,
          scrollable: find.descendant(of: find.byKey(const ValueKey('profile-list')), matching: find.byType(Scrollable)).first);
      expect(find.byType(AppIconPanel), findsOneWidget);
      expect(find.byKey(const ValueKey('app-icon-note')), findsOneWidget);
      await tester.scrollUntilVisible(find.byKey(const ValueKey('social-section')), 300,
          scrollable: find.descendant(of: find.byKey(const ValueKey('profile-list')), matching: find.byType(Scrollable)).first);
      expect(find.byKey(const ValueKey('social-section')), findsOneWidget);
      await tester.tap(inNav('PC'));
      await settle(tester, 4);
      // the Tampilan section is gone from PC (only the Profil one, offstage, remains)
      expect(find.byType(NvAppearanceSection, skipOffstage: true), findsNothing);
      expect(find.byKey(const ValueKey('pc-licenses'), skipOffstage: false), findsOneWidget);
    });
  });

  group('Profil 1.4.4', () {
    SocialProfile sample() => SocialProfile.fromJson({
          'login': 'maftuuh', 'name': 'Maftuh', 'bio': 'Bikin agen di Bandung',
          'heatmap': {'start': '2025-10-05', 'end': '2026-10-08', 'counts': [for (var i = 0; i < 370; i++) i % 5]},
          'stack': {'languages': [{'name': 'Dart', 'share': 0.5}, {'name': 'Python', 'share': 0.3}, {'name': 'TypeScript', 'share': 0.2}]},
        });

    testWidgets('header, graph and stack on top; settings start collapsed and unfold', (tester) async {
      app.previewTab = 3;
      final r = controller()
        ..socialSignedIn = true
        ..socialProfile = sample();
      await pump(tester, const RemoteShell(), r: r);
      await settle(tester, 4);
      expect(find.byKey(const ValueKey('github-header')), findsOneWidget);
      expect(find.text('Maftuh'), findsOneWidget);
      expect(find.text('@maftuuh · lewat PC'), findsOneWidget);
      expect(find.text('Bikin agen di Bandung'), findsOneWidget);
      expect(find.byKey(const ValueKey('contribution-graph')), findsOneWidget);
      expect(find.byKey(const ValueKey('chip-Dart')), findsOneWidget);
      // order: header above graph above stack above the settings
      double y(String k) => tester.getTopLeft(find.byKey(ValueKey(k))).dy;
      expect(y('github-header'), lessThan(y('contribution-card')));
      expect(y('contribution-card'), lessThan(y('profile-stack')));
      expect(y('profile-stack'), lessThan(y('profile-group-appearance')));
      // collapsed: the big appearance section is not built until opened
      expect(find.byType(NvAppearanceSection), findsNothing);
      expect(find.byKey(const ValueKey('social-section')), findsNothing);
      // 1.4.5: "Pamerkan" sits under the header, so the group may start below the fold
      expect(y('profile-stack'), lessThan(y('profile-pamerkan')));
      await tester.ensureVisible(find.byKey(const ValueKey('profile-group-appearance')));
      await settle(tester, 2);
      await tester.tap(find.byKey(const ValueKey('profile-group-appearance')));
      await settle(tester, 4);
      expect(find.byType(NvAppearanceSection), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('profile-group-appearance')));
      await settle(tester, 4);
      expect(find.byType(NvAppearanceSection), findsNothing);
    });

    for (final open in [false, true]) {
      testWidgets('last Profil item scrolls fully above the floating nav · 390 dp${open ? ' · groups open' : ''}', (tester) async {
        app.previewTab = 3;
        if (open) {
          ProfileGroup.debugOpen = {'appearance', 'glass', 'icon', 'friends'};
          addTearDown(() => ProfileGroup.debugOpen = {});
        }
        final r = controller()
          ..socialSignedIn = true
          ..socialProfile = sample();
        await pump(tester, const RemoteShell(), r: r, width: 390);
        await settle(tester, 4);
        final list = find.byKey(const ValueKey('profile-list'));
        for (var i = 0; i < 30; i++) {
          await tester.drag(list, const Offset(0, -600));
          await tester.pump(const Duration(milliseconds: 50));
        }
        await settle(tester, 6);
        final last = find.byKey(open ? const ValueKey('profile-group-body-friends') : const ValueKey('profile-group-friends'));
        final nav = tester.getRect(navBar);
        expect(tester.getRect(last).bottom, lessThanOrEqualTo(nav.top), reason: 'last item ${tester.getRect(last)} vs nav $nav');
      });
    }
  });

  group('Launcher icon', () {
    test('nearest variant to an accent', () {
      expect(nearestAppIcon(const Color(0xFFEE1C1C)), 'merah');
      expect(nearestAppIcon(const Color(0xFF2563EB)), 'biru');
      expect(nearestAppIcon(const Color(0xFF0284C7)), 'biru'); // Langit
      expect(nearestAppIcon(const Color(0xFF7C3AED)), 'ungu');
      expect(nearestAppIcon(const Color(0xFF0D9488)), 'toska');
      expect(nearestAppIcon(const Color(0xFF16A34A)), 'hijau');
      expect(nearestAppIcon(const Color(0xFFEA580C)), 'oranye');
      expect(nearestAppIcon(const Color(0xFFA3A3A3)), 'monokrom');
    });

    test('select calls the channel and persists; follow-accent picks the nearest; errors surface', () async {
      final calls = <String>[];
      final c = AppIconController(prefs, channel: (m, a) async {
        calls.add('$m:${a?['id']}');
        return a?['id'] as String?;
      });
      expect(c.current, 'merah');
      expect(await c.select('toska'), isNull);
      expect(c.current, 'toska');
      expect(prefs.getString('nv.icon.id'), 'toska');
      await c.setFollowAccent(true, const Color(0xFF7C3AED));
      expect(c.current, 'ungu');
      await c.onAccent(const Color(0xFF16A34A));
      expect(c.current, 'hijau');
      // a manual pick turns following off
      await c.select('biru');
      expect(c.followAccent, isFalse);
      await c.onAccent(const Color(0xFFEA580C));
      expect(c.current, 'biru');
      expect(calls, ['setLauncherIcon:toska', 'setLauncherIcon:ungu', 'setLauncherIcon:hijau', 'setLauncherIcon:biru']);
      final bad = AppIconController(prefs, channel: (m, a) async => throw Exception('no bridge'));
      expect(await bad.select('ungu'), isNotNull);
      expect(bad.current, 'biru'); // unchanged (persisted value)
    });

    testWidgets('picker shows a preview tile per variant', (tester) async {
      final calls = <String>[];
      await pump(tester, const Scaffold(body: SingleChildScrollView(child: AppIconPanel())), extra: [
        appIconProvider.overrideWith((ref) => AppIconController(prefs, channel: (m, a) async {
              calls.add('${a?['id']}');
              return null;
            })),
      ]);
      await settle(tester, 2);
      for (final (id, _, _) in appIconVariants) {
        expect(find.byKey(ValueKey('app-icon-$id')), findsOneWidget);
      }
      await tester.tap(find.byKey(const ValueKey('app-icon-ungu')));
      await settle(tester, 3);
      expect(calls, ['ungu']);
      expect(find.text('Ungu'), findsWidgets);
    });
  });

  group('Glass greeting', () {
    testWidgets('renders as glass, entrance settles, sheen keeps looping', (tester) async {
      await pump(tester, const RemoteShell());
      final g = find.byKey(const ValueKey('chat-greeting'));
      expect(g, findsOneWidget);
      final st = tester.state<NvGlassTextState>(g);
      expect(st.entrance, lessThan(0.5)); // just started
      await settle(tester, 12);
      expect(st.entrance, closeTo(1, 0.02));
      expect(st.animating, isTrue);
      expect(find.descendant(of: g, matching: find.byType(ShaderMask)), findsWidgets);
      expect(find.descendant(of: g, matching: find.byType(ImageFiltered)), findsNothing); // sharp after entrance
    });

    testWidgets('reduce motion: static glass, no animation, no sheen', (tester) async {
      await pump(tester, const RemoteShell(), reduce: true);
      final g = find.byKey(const ValueKey('chat-greeting'));
      final st = tester.state<NvGlassTextState>(g);
      expect(st.entrance, 1);
      expect(st.animating, isFalse);
      expect(find.byKey(const ValueKey('nv-glass-text-static')), findsOneWidget);
    });
  });

  group('Glass intro', () {
    testWidgets('glass button, chips and dot lens; drag-following lens; stagger settles', (tester) async {
      await pump(tester, const RemoteIntroScreen(initialPage: 1));
      expect(find.byKey(const ValueKey('nv-glass-button')), findsOneWidget);
      expect(find.byKey(const ValueKey('intro-chip-Tanpa kunci API di HP')), findsOneWidget);
      expect(find.byKey(const ValueKey('intro-numeral-1')), findsOneWidget);
      expect(find.byType(NvGlassText), findsWidgets);
      double lensX() => tester.getRect(find.byKey(const ValueKey('intro-dot-lens'))).center.dx;
      double dotX(int i) => tester.getRect(find.byKey(ValueKey('intro-dot-$i'))).center.dx;
      await settle(tester, 10);
      expect(lensX(), closeTo(dotX(1), 0.5));
      // drag half a page: the lens is between dot 1 and 2 and stretched
      final w = tester.getSize(find.byType(PageView)).width;
      final g = await tester.startGesture(Offset(w * 0.8, 400));
      for (var i = 0; i < 10; i++) {
        await g.moveBy(Offset(-w * 0.45 / 10, 0));
        await tester.pump(const Duration(milliseconds: 16));
      }
      expect(lensX(), greaterThan(dotX(1) + 3));
      expect(lensX(), lessThan(dotX(2) - 3));
      expect(tester.getSize(find.byKey(const ValueKey('intro-dot-lens'))).width, greaterThan(IntroDots.lensW + 4));
      for (var i = 0; i < 5; i++) {
        await g.moveBy(Offset(-w * 0.2 / 5, 0));
        await tester.pump(const Duration(milliseconds: 16));
      }
      await g.up();
      await settle(tester, 10);
      expect(find.text('3 / 5'), findsOneWidget);
      expect(lensX(), closeTo(dotX(2), 0.5));
    });

    testWidgets('reduce motion: everything visible at once, no backdrop drift', (tester) async {
      await pump(tester, const RemoteIntroScreen(initialPage: 1), reduce: true);
      await tester.pump();
      final op = tester.widgetList<Opacity>(find.ancestor(of: find.text('PC = OTAK · HP = REMOTE'), matching: find.byType(Opacity)));
      for (final o in op) {
        expect(o.opacity, 1);
      }
      expect(find.byType(ImageFiltered), findsNothing);
    });
  });

  group('Gaya kaca', () {
    test('per-style fill opacity and blur', () {
      NV.palette = NvPalette.red;
      expect(NV.glassFill(NvGlassStyle.reguler).a, closeTo(0.55, 0.01));
      expect(NV.glassFill(NvGlassStyle.bening).a, lessThan(0.2));
      expect(NV.glassFill(NvGlassStyle.gelap).a, closeTo(0.68, 0.01));
      expect(NV.glassFill(NvGlassStyle.warna).a, closeTo(0.58, 0.01));
      expect(NV.glassFill(NvGlassStyle.tanpa).a, greaterThan(0.9));
      expect(NV.glassSigmaScale(NvGlassStyle.reguler), 1);
      expect(NV.glassSigmaScale(NvGlassStyle.bening), lessThan(0.5));
      expect(NV.glassSigmaScale(NvGlassStyle.gelap), greaterThan(1));
      expect(NV.glassSigmaScale(NvGlassStyle.tanpa), 0);
      // Warna is tinted by the accent; Gelap is darker than Reguler
      NV.palette = NvPalette.from(const Color(0xFF2563EB), Brightness.dark);
      final w = NV.glassFill(NvGlassStyle.warna);
      expect(w.b, greaterThan(w.r));
      expect(HSLColor.fromColor(NV.glassFill(NvGlassStyle.gelap)).lightness, lessThan(HSLColor.fromColor(NV.glassFill(NvGlassStyle.reguler)).lightness));
      // Bening adds a text shadow for legibility, the others don't
      NV.glassStyle = NvGlassStyle.bening;
      expect(NV.glassTextShadows, isNotEmpty);
      NV.glassStyle = NvGlassStyle.reguler;
      expect(NV.glassTextShadows, isEmpty);
    });

    for (final st in NvGlassStyle.values) {
      testWidgets('chat in ${st.name}: nav ${st == NvGlassStyle.tanpa ? 'has no' : 'has a'} BackdropFilter, style persisted', (tester) async {
        final look = await pump(tester, const RemoteShell());
        look.setGlassStyle(st);
        await settle(tester, 4);
        expect(prefs.getString('nv.glass.style') ?? 'reguler', st.name);
        expect(NV.glassStyle, st);
        final blur = find.descendant(of: navBar, matching: find.byType(BackdropFilter));
        expect(blur, st == NvGlassStyle.tanpa ? findsNothing : findsOneWidget);
        final fill = tester.widget<DecoratedBox>(find.descendant(of: navBar, matching: find.byKey(const ValueKey('nv-glass'))).first);
        expect((fill.decoration as BoxDecoration).color!.a, closeTo(NV.glassFill(st, nav: true).a, st == NvGlassStyle.reguler ? 0.001 : 0.25));
        if (st == NvGlassStyle.tanpa) {
          expect(find.byKey(const ValueKey('nv-glass-text-solid')), findsOneWidget);
          expect(find.byType(BackdropFilter), findsNothing);
        }
        // survives a restart
        expect(AppearanceController(prefs).glassStyle, st);
      });
    }

    testWidgets('picker: 4 effects + Tanpa efek under Aksesibilitas; tap switches app-wide', (tester) async {
      final look = await pump(tester, const Scaffold(body: SingleChildScrollView(child: GlassStylePicker())));
      for (final st in NvGlassStyle.values) {
        expect(find.byKey(ValueKey('glass-preview-${st.name}')), findsOneWidget);
      }
      expect(find.text('AKSESIBILITAS'), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('glass-style-gelap')));
      await settle(tester, 2);
      expect(look.glassStyle, NvGlassStyle.gelap);
      // previews render their own style regardless of the app-wide one
      expect(find.descendant(of: find.byKey(const ValueKey('glass-preview-tanpa')), matching: find.byType(BackdropFilter)), findsNothing);
      expect(find.descendant(of: find.byKey(const ValueKey('glass-preview-bening')), matching: find.byType(BackdropFilter)), findsOneWidget);
    });

    testWidgets('accessibility on: Tanpa efek is recommended', (tester) async {
      await pump(tester, const Scaffold(body: SingleChildScrollView(child: GlassStylePicker())), reduce: true);
      expect(find.textContaining('Disarankan: Tanpa efek'), findsOneWidget);
    });

    test('PC theme sync carries the glass style', () {
      final look = AppearanceController(prefs, systemBrightness: Brightness.dark);
      look.applyPc({'accent': '#2563EB', 'base': 'dark', 'glass_style': 'bening'});
      expect(look.glassStyle, NvGlassStyle.bening);
    });
  });

  group('Warna dari wallpaper', () {
    List<int> solid(int argb, [int n = 128 * 72]) => List<int>.filled(n, argb);

    test('solid blue image -> blue accent; greyscale -> Monokrom', () async {
      final blue = await paletteFromPixels(solid(0xFF1D4ED8));
      final h = HSLColor.fromColor(blue.seed);
      expect(h.hue, inInclusiveRange(200, 250));
      expect(h.saturation, greaterThan(0.4));
      expect(blue.monochrome, isFalse);
      expect(blue.swatches.length, inInclusiveRange(1, 5));
      final grey = await paletteFromPixels([for (var i = 0; i < 128 * 72; i++) 0xFF000000 | ((i % 256) * 0x010101)]);
      expect(grey.monochrome, isTrue);
      expect(grey.seed, monochromeAccent);
    });

    test('several colours -> 3–5 swatches; seed toned for dark vs light', () async {
      final px = [...solid(0xFF1D4ED8, 4000), ...solid(0xFFDC2626, 3000), ...solid(0xFF16A34A, 2000), ...solid(0xFF7C3AED, 1500)];
      final d = await paletteFromPixels(px, dark: true);
      final l = await paletteFromPixels(px, dark: false);
      expect(d.swatches.length, inInclusiveRange(3, 5));
      expect(HSLColor.fromColor(d.seed).lightness, greaterThan(HSLColor.fromColor(l.seed).lightness));
    });

    test('chosen wallpaper sets the accent; manual accent turns it off; launcher icon follows', () async {
      AppearanceController.paletteLoader = (b, dark) => paletteFromPixels(solid(0xFF1D4ED8), dark: dark);
      addTearDown(() => AppearanceController.paletteLoader = (b, dark) async => null);
      final look = AppearanceController(prefs, systemBrightness: Brightness.dark);
      final icon = AppIconController(prefs, channel: (m, a) async => null);
      await icon.setFollowAccent(true, look.accent);
      look.addListener(() => icon.onAccent(look.accent));
      expect(look.wallpaperColors, isTrue);
      look.setBackground(look.background.copyWith(source: 'asset:assets/art/feat-remote.webp'));
      await Future<void>.delayed(const Duration(milliseconds: 50));
      for (var i = 0; i < 20 && look.wallpaperSwatches.isEmpty; i++) {
        await Future<void>.delayed(const Duration(milliseconds: 50));
      }
      expect(HSLColor.fromColor(look.accent).hue, inInclusiveRange(200, 250));
      expect(look.followPc, isFalse);
      expect(prefs.getStringList('nv.bg.swatches'), isNotEmpty);
      await Future<void>.delayed(const Duration(milliseconds: 10));
      expect(icon.current, 'biru');
      // manual accent: toggle off
      look.setLocal(accent: const Color(0xFF16A34A));
      expect(look.wallpaperColors, isFalse);
      expect(prefs.getBool('nv.bg.autoColor'), isFalse);
      // persisted
      final again = AppearanceController(prefs, systemBrightness: Brightness.dark);
      expect(again.wallpaperColors, isFalse);
      expect(again.wallpaperSwatches, isNotEmpty);
    });

    testWidgets('toggle panel + "Dari wallpaper" row (from the extracted swatches); a suggestion keeps the toggle on', (tester) async {
      prefs.setString('nv.bg.source', 'asset:assets/art/feat-remote.webp');
      prefs.setStringList('nv.bg.swatches', ['#3B82F6', '#A855F7', '#22C55E']);
      final look = await pump(tester, const Scaffold(body: SingleChildScrollView(child: Column(children: [WallpaperColorsPanel(), NvAppearanceSection()]))));
      await settle(tester, 2);
      expect(find.byKey(const ValueKey('wallpaper-colors')), findsOneWidget);
      final wall = find.byKey(const ValueKey('accent-wall-1'));
      expect(wall, findsOneWidget);
      await tester.ensureVisible(wall);
      await tester.tap(wall);
      await settle(tester, 2);
      expect(look.accent.toARGB32(), const Color(0xFFA855F7).toARGB32());
      expect(look.wallpaperColors, isTrue);
    });
  });
}
