// Kartu Neovarch (1.4.5): share-target selection against a fake package list,
// privacy scrubbing of the card data, the card in 3 styles × 2 formats with the
// stats / Kantor toggles, PNG export at 1080×1920 and 1080×1080, the share
// sheet (swipe "1 dari 3", installed targets only, Bagikan / Salin tautan /
// Unduh) and screenshots (run with --update-goldens, NV_SHOTS_DIR=…,
// NV_SCENE_DIR=… for a real Kantor 3D render).
import 'dart:convert';
import 'dart:io';

import 'package:flutter/cupertino.dart' show CupertinoSwitch;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:neovarch_agent/models/models.dart' show ChatSessionInfo;
import 'package:neovarch_agent/remote/appearance.dart';
import 'package:neovarch_agent/remote/office_models.dart';
import 'package:neovarch_agent/remote/remote_gateway.dart' show KanbanSnapshot;
import 'package:neovarch_agent/remote/share/brag_card_data.dart';
import 'package:neovarch_agent/remote/share/share_targets.dart';
import 'package:neovarch_agent/remote/social_models.dart';
import 'package:neovarch_agent/remote/ui/brag_card.dart';
import 'package:neovarch_agent/remote/ui/brag_share_sheet.dart';
import 'package:neovarch_agent/remote/ui/profile_share_card.dart' show renderShareCardPng, pngSize, shareChannel, writeShareFile;
import 'package:neovarch_agent/remote/ui/remote_app.dart' show neovarchMobileTheme;
import 'package:neovarch_agent/remote/ui/remote_office_3d.dart' show decodeDataUrl;
import 'package:neovarch_agent/remote/ui/remote_social_screen.dart' show socialAvatarProvider;
import 'package:neovarch_agent/theme/neovarch_mobile_theme.dart';

final _shotsDir = Platform.environment['NV_SHOTS_DIR'] ?? 'build/screenshots/brag';
final _sceneDir = Platform.environment['NV_SCENE_DIR'];

SocialProfile _profile() {
  final counts = List<int>.generate(365, (i) => (i * 7 + 3) % 11 < 4 ? 0 : (i * 13) % 9 + (i > 330 ? 2 : 0));
  return SocialProfile.fromJson({
    'login': 'Maftuuh1922',
    'name': 'Maftuh',
    'heatmap': {'start': '2025-10-10', 'end': '2026-10-09', 'counts': counts, 'total': counts.fold<int>(0, (a, b) => a + b), 'active_days': 230, 'streak': 6},
  });
}

OfficeSnapshot _office() => OfficeSnapshot.fromJson({
      'host': 'my-pc.local',
      'agents': [
        {'id': 'a', 'name': 'Raka', 'status': 'working'},
        {'id': 'b', 'name': 'Ayu', 'status': 'working'},
        {'id': 'c', 'name': 'Citra', 'status': 'idle'},
        {'id': 'd', 'name': 'Dimas', 'status': 'waiting-approval'},
      ],
      'kanban': {'done': 9},
      'default_model': {'model': 'anthropic/claude-sonnet-4.5', 'provider': 'openrouter'},
    });

KanbanSnapshot _board() => KanbanSnapshot.fromJson({
      'columns': [
        {'name': 'todo', 'tasks': [{'id': 1, 'title': 'x'}]},
        {'name': 'done', 'tasks': [for (var i = 0; i < 12; i++) {'id': 10 + i, 'title': 't$i'}]},
      ],
    });

List<ChatSessionInfo> _sessions() => [
      for (var i = 0; i < 37; i++) ChatSessionInfo(id: 's$i', title: 'Sesi $i', profile: 'default', messageCount: 40 + i),
    ];

BragCardData _data({Uint8List? shot}) =>
    BragCardData.gather(profile: _profile(), office: _office(), board: _board(), sessions: _sessions(), officeShot: shot);

void main() {
  group('share targets', () {
    test('only installed apps, in a fixed order, first matching package wins', () {
      final t = availableShareTargets(['org.telegram.messenger', 'com.whatsapp.w4b', 'com.instagram.android', 'com.example.other']);
      expect(t.map((e) => e.id), ['ig-story', 'ig-feed', 'whatsapp', 'telegram']);
      expect(t[2].package, 'com.whatsapp.w4b');
      expect(t.first.mode, ShareMode.igStory);
      expect(availableShareTargets(['com.whatsapp', 'com.whatsapp.w4b']).single.package, 'com.whatsapp');
      expect(availableShareTargets(const []), isEmpty);
      expect(availableShareTargets(['com.ss.android.ugc.trill', 'com.twitter.android', 'com.facebook.lite']).map((e) => e.id), ['tiktok', 'x', 'facebook']);
    });

    test('channel args: direct target vs system chooser', () {
      final ig = availableShareTargets(['com.instagram.android']).first;
      final a = shareImageArgs(path: '/c/share/k.png', text: 'hai', target: ig);
      expect(a['package'], 'com.instagram.android');
      expect(a['mode'], 'ig-story');
      expect(a['mime'], 'image/png');
      final b = shareImageArgs(path: '/c/share/k.png', text: 'hai');
      expect(b.containsKey('package'), isFalse);
      expect(shareFellBack('chooser'), isTrue);
      expect(shareFellBack('shared'), isFalse);
    });

    test('every target package is declared in the manifest <queries>', () {
      final manifest = File('android/app/src/main/AndroidManifest.xml').readAsStringSync();
      for (final p in kShareTargetPackages) {
        expect(manifest.contains('<package android:name="$p" />'), isTrue, reason: p);
      }
      expect(manifest.contains('com.instagram.share.ADD_TO_STORY'), isTrue);
      // no new permission for sharing (MediaStore on API 29+ needs none);
      // 21 = 1.4.4's set + REQUEST_INSTALL_PACKAGES (in-app update)
      // + SYSTEM_ALERT_WINDOW / REQUEST_IGNORE_BATTERY_OPTIMIZATIONS (Hey Neo rows)
      expect('uses-permission'.allMatches(manifest).length, 24);
      expect(manifest.contains('android.permission.REQUEST_INSTALL_PACKAGES'), isTrue);
    });
  });

  group('card data', () {
    test('gathers stats from Office, Kanban, sessions and the default model', () {
      final d = _data();
      expect(d.name, 'Maftuh');
      expect(d.login, 'Maftuuh1922');
      expect(d.stats.agentsActive, 2);
      expect(d.stats.agentsTotal, 4);
      expect(d.stats.tasksDone, 12); // the Kanban "done" lane wins over office.kanban
      expect(d.stats.sessions, 37);
      expect(d.stats.messages, List.generate(37, (i) => 40 + i).reduce((a, b) => a + b));
      expect(d.stats.model, 'claude-sonnet-4.5');
      expect(d.link, kNeovarchLandingUrl);
      expect(d.avatarUrl, 'https://github.com/Maftuuh1922.png?size=160');
    });

    test('works offline / signed out', () {
      final d = BragCardData.gather();
      expect(d.name, 'Pengguna Neovarch');
      expect(d.login, isNull);
      expect(d.stats.isEmpty, isTrue);
    });

    test('scrubs secrets, paths, hosts and private avatar URLs', () {
      expect(safeLabel('sk-or-v1-abcdef0123456789abcdef0123456789'), isNull);
      expect(safeLabel('ghp_abcdefghijklmnop'), isNull);
      expect(safeLabel('/home/aku/.neovarch/config'), isNull);
      expect(safeLabel(r'C:\Users\aku'), isNull);
      expect(safeLabel('http://192.168.1.4:9319'), isNull);
      expect(safeLabel('Maftuh   Dev'), 'Maftuh Dev');
      expect(safeHandle('@Maftuuh1922'), 'Maftuuh1922');
      expect(safeHandle('../etc'), isNull);
      expect(safeModelName('/models/llama.gguf'), isNull);
      expect(safeModelName('http://localhost:11434/qwen'), isNull);
      expect(safeModelName('openrouter/deepseek/deepseek-r1-distill-llama-70b:free'), 'deepseek-r1-distill-llama…');
      final d = BragCardData.gather(
        profile: SocialProfile.fromJson({'login': 'aku', 'name': 'sk-ant-api03-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', 'avatar_url': 'http://10.0.0.2:9319/avatar'}),
        office: OfficeSnapshot.fromJson({'default_model': {'model': r'C:\models\x.gguf', 'provider': 'local'}}),
      );
      expect(d.name, 'aku');
      expect(d.avatarUrl, 'https://github.com/aku.png?size=160');
      expect(d.stats.model, isNull);
    });

    test('Kantor 3D snapshot data URL decodes (plain and JSON-quoted)', () {
      final bytes = Uint8List.fromList(List.generate(200, (i) => i % 256));
      final url = 'data:image/jpeg;base64,${base64Encode(bytes)}';
      expect(decodeDataUrl(url), bytes);
      expect(decodeDataUrl(jsonEncode(url)), bytes);
      expect(decodeDataUrl('""'), isNull);
      expect(decodeDataUrl('data:image/png;base64,AAAA'), isNull); // too small = blank canvas
      expect(decodeDataUrl(null), isNull);
    });

    test('office3d page exposes snapshot()', () {
      final html = File('assets/office3d/index.html').readAsStringSync();
      expect(html.contains("snapshot: function"), isTrue);
      expect(html.contains("toDataURL('image/jpeg'"), isTrue);
    });
  });

  group('card widget', () {
    late SharedPreferences prefs;
    late Uint8List shot;

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
      final scene = _sceneDir == null ? null : File('$_sceneDir/scene_dark.png');
      shot = scene != null && scene.existsSync()
          ? scene.readAsBytesSync()
          : (await rootBundle.load('assets/intro/eva_office.webp')).buffer.asUint8List();
    });

    setUp(() async {
      SharedPreferences.setMockInitialValues({});
      prefs = await SharedPreferences.getInstance();
      socialAvatarProvider = (url) => null;
    });

    tearDown(() => NV.palette = NvPalette.red);

    Widget backdrop() => Stack(fit: StackFit.expand, children: [
          Image.asset('assets/art/feat-remote.webp', fit: BoxFit.cover),
          ColoredBox(color: NV.bg.withValues(alpha: 0.30)),
        ]);

    Widget host(Widget child, {bool center = true}) => ProviderScope(
          overrides: [appearanceProvider.overrideWith((ref) => AppearanceController(prefs))],
          child: MaterialApp(
            debugShowCheckedModeBanner: false,
            theme: neovarchMobileTheme,
            darkTheme: neovarchMobileTheme,
            themeMode: NV.palette.dark ? ThemeMode.dark : ThemeMode.light,
            home: Scaffold(body: center ? Center(child: child) : child),
          ),
        );

    Future<void> precache(WidgetTester tester) async {
      final ctx = tester.element(find.byType(MaterialApp));
      await tester.runAsync(() async {
        await precacheImage(const AssetImage('assets/art/feat-remote.webp'), ctx);
        await precacheImage(const AssetImage('assets/brand/monogram.png'), ctx);
        await precacheImage(MemoryImage(shot), ctx);
      });
    }

    for (final format in BragFormat.values) {
      for (final style in BragStyle.values) {
        testWidgets('renders ${style.name} ${format.name} without overflow, with QR + footer', (tester) async {
          tester.view.physicalSize = const Size(1200, 2100);
          tester.view.devicePixelRatio = 1;
          addTearDown(tester.view.reset);
          await tester.pumpWidget(host(NeovarchBragCard(data: _data(shot: shot), style: style, format: format, background: backdrop())));
          await tester.pump();
          expect(tester.takeException(), isNull);
          expect(find.byKey(const ValueKey('brag-qr')), findsOneWidget);
          expect(find.text('Dibuat dengan Neovarch'), findsOneWidget);
          expect(find.text('Maftuh'), findsOneWidget);
          expect(find.text('@Maftuuh1922'), findsOneWidget);
          expect(find.byKey(const ValueKey('brag-stats')), findsOneWidget);
          expect(find.byKey(const ValueKey('brag-office')), findsOneWidget);
          expect(find.textContaining('Hermes'), findsNothing);
          final size = tester.getSize(find.byKey(ValueKey('brag-card-${style.name}-${format.name}')));
          expect(size, Size(format.logical.w, format.logical.h));
        });
      }
    }

    testWidgets('toggles hide the stats and the Kantor snapshot', (tester) async {
      tester.view.physicalSize = const Size(1200, 2100);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(host(NeovarchBragCard(data: _data(shot: shot), showStats: false, showOffice: false, background: backdrop())));
      await tester.pump();
      expect(find.byKey(const ValueKey('brag-stats')), findsNothing);
      expect(find.byKey(const ValueKey('brag-model')), findsNothing);
      expect(find.byKey(const ValueKey('brag-office')), findsNothing);
      expect(find.textContaining('agen aktif'), findsNothing);
      expect(find.byKey(const ValueKey('brag-heat')), findsOneWidget);
      // no snapshot at all -> no office tile even when allowed
      await tester.pumpWidget(host(NeovarchBragCard(data: _data(), format: BragFormat.feed, background: backdrop())));
      await tester.pump();
      expect(find.byKey(const ValueKey('brag-office')), findsNothing);
      expect(tester.takeException(), isNull);
    });

    test('Warna-warni text stays readable on light and dark accents', () {
      for (final hex in [0xFFEE1C1C, 0xFFFACC15, 0xFF84CC16, 0xFF1E3A8A, 0xFFFFFFFF]) {
        NV.palette = NvPalette.from(Color(hex), Brightness.dark);
        final c = BragColors.of(BragStyle.warna);
        final l1 = c.ground.computeLuminance() + 0.05, l2 = c.text.computeLuminance() + 0.05;
        expect((l1 > l2 ? l1 / l2 : l2 / l1), greaterThan(4.5), reason: hex.toRadixString(16));
      }
      NV.palette = NvPalette.from(const Color(0xFF3A0505), Brightness.dark);
      final g = BragColors.of(BragStyle.gelap);
      final a = g.accent.computeLuminance() + 0.05, p = g.panel.computeLuminance() + 0.05;
      expect(a / p, greaterThan(3.0));
    });

    for (final format in BragFormat.values) {
      testWidgets('exports ${format.pixels.w}×${format.pixels.h} PNG (${format.name})', (tester) async {
        tester.view.physicalSize = const Size(1200, 2100);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.reset);
        final key = GlobalKey();
        await tester.pumpWidget(host(RepaintBoundary(key: key, child: NeovarchBragCard(data: _data(), format: format, style: BragStyle.gelap))));
        await tester.pump();
        final png = await tester.runAsync(() => renderShareCardPng(key));
        expect(pngSize(png!), (format.pixels.w, format.pixels.h));
      });
    }

    testWidgets('sheet: swipe styles, installed targets only, share / copy / save', (tester) async {
      tester.view.physicalSize = const Size(1080, 2340);
      tester.view.devicePixelRatio = 2.75;
      addTearDown(tester.view.reset);
      final calls = <(String, Map<String, dynamic>)>[];
      final oldChannel = shareChannel, oldWrite = writeShareFile, oldApps = installedShareApps;
      shareChannel = (m, a) async {
        calls.add((m, a));
        return m == 'saveImageToGallery' ? 'content://media/1' : 'shared';
      };
      writeShareFile = (png, name) async => '/cache/share/$name';
      installedShareApps = () async => ['com.instagram.android', 'com.whatsapp', 'com.twitter.android'];
      addTearDown(() {
        shareChannel = oldChannel;
        writeShareFile = oldWrite;
        installedShareApps = oldApps;
      });
      String? copied;
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, (call) async {
        if (call.method == 'Clipboard.setData') copied = (call.arguments as Map)['text'] as String?;
        return null;
      });
      addTearDown(() => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, null));

      await tester.pumpWidget(host(BragSharePreview(data: _data(shot: shot), debugBackground: backdrop()), center: false));
      await tester.pump();
      await tester.pump();
      expect(find.text('1 dari 3'), findsOneWidget);
      expect(find.byKey(const ValueKey('brag-target-ig-story')), findsOneWidget);
      expect(find.byKey(const ValueKey('brag-target-whatsapp')), findsOneWidget);
      expect(find.byKey(const ValueKey('brag-target-x')), findsOneWidget);
      expect(find.byKey(const ValueKey('brag-target-tiktok')), findsNothing);
      expect(find.byKey(const ValueKey('brag-target-telegram')), findsNothing);
      expect(find.byKey(const ValueKey('brag-target-more')), findsOneWidget);

      await tester.fling(find.byKey(const ValueKey('brag-pages')), const Offset(-300, 0), 1200);
      await tester.pumpAndSettle();
      expect(find.text('2 dari 3'), findsOneWidget);

      // Feed format + stats off still exports
      await tester.tap(find.byKey(const ValueKey('segment-Feed 1:1')));
      await tester.pumpAndSettle();
      final sw = find.descendant(of: find.byKey(const ValueKey('brag-toggle-stats')), matching: find.byType(CupertinoSwitch));
      await tester.ensureVisible(sw);
      await tester.pumpAndSettle();
      await tester.tap(sw);
      await tester.pumpAndSettle();
      expect(tester.widget<CupertinoSwitch>(sw).value, isFalse);
      await tester.ensureVisible(find.byKey(const ValueKey('brag-save')));
      await tester.pumpAndSettle();

      await tester.runAsync(() async {
        await tester.tap(find.byKey(const ValueKey('brag-target-ig-story')));
        await Future<void>.delayed(const Duration(milliseconds: 300));
      });
      await tester.pump();
      final ig = calls.lastWhere((c) => c.$1 == 'shareImage').$2;
      expect(ig['package'], 'com.instagram.android');
      expect(ig['mode'], 'ig-story');
      expect('${ig['path']}', startsWith('/cache/share/kartu-neovarch-'));
      expect('${ig['text']}', contains(kNeovarchLandingUrl));

      await tester.runAsync(() async {
        await tester.tap(find.byKey(const ValueKey('brag-share')));
        await Future<void>.delayed(const Duration(milliseconds: 300));
      });
      await tester.pump();
      expect(calls.lastWhere((c) => c.$1 == 'shareImage').$2.containsKey('package'), isFalse);

      await tester.runAsync(() async {
        await tester.tap(find.byKey(const ValueKey('brag-save')));
        await Future<void>.delayed(const Duration(milliseconds: 300));
      });
      await tester.pump();
      expect(calls.any((c) => c.$1 == 'saveImageToGallery'), isTrue);

      await tester.tap(find.byKey(const ValueKey('brag-copy')));
      await tester.pump();
      expect(copied, kNeovarchLandingUrl);
      await tester.pump(const Duration(seconds: 4));
    });

    // Screenshots: 3 styles × story/feed (dark red), Kaca in light + another
    // accent, and the share sheet.
    if (autoUpdateGoldenFiles) {
      for (final (name, hex, bright, style, format) in const [
        ('kartu_kaca_story', 0xFFEE1C1C, Brightness.dark, BragStyle.kaca, BragFormat.story),
        ('kartu_gelap_story', 0xFFEE1C1C, Brightness.dark, BragStyle.gelap, BragFormat.story),
        ('kartu_warna_story', 0xFFEE1C1C, Brightness.dark, BragStyle.warna, BragFormat.story),
        ('kartu_kaca_feed', 0xFFEE1C1C, Brightness.dark, BragStyle.kaca, BragFormat.feed),
        ('kartu_gelap_feed', 0xFFEE1C1C, Brightness.dark, BragStyle.gelap, BragFormat.feed),
        ('kartu_warna_feed', 0xFFEE1C1C, Brightness.dark, BragStyle.warna, BragFormat.feed),
        ('kartu_kaca_terang_story', 0xFF0D9488, Brightness.light, BragStyle.kaca, BragFormat.story),
        ('kartu_warna_kuning_feed', 0xFFFACC15, Brightness.dark, BragStyle.warna, BragFormat.feed),
      ]) {
        testWidgets('shot $name', (tester) async {
          NV.palette = NvPalette.from(Color(hex), bright);
          final l = format.logical;
          tester.view.physicalSize = Size(format.pixels.w.toDouble(), format.pixels.h.toDouble());
          tester.view.devicePixelRatio = kBragPixelRatio;
          addTearDown(tester.view.reset);
          await tester.pumpWidget(ProviderScope(
            overrides: [appearanceProvider.overrideWith((ref) => AppearanceController(prefs))],
            child: RepaintBoundary(
              key: const ValueKey('shot'),
              child: MaterialApp(
                debugShowCheckedModeBanner: false,
                theme: neovarchMobileTheme,
                home: SizedBox(width: l.w, height: l.h, child: NeovarchBragCard(data: _data(shot: shot), style: style, format: format, background: backdrop())),
              ),
            ),
          ));
          await precache(tester);
          await tester.pump();
          final dir = Directory(_shotsDir).absolute.path;
          Directory(dir).createSync(recursive: true);
          await expectLater(find.byKey(const ValueKey('shot')), matchesGoldenFile('$dir/$name.png'));
        });
      }

      for (final (name, bright) in const [('kartu_sheet_dark', Brightness.dark), ('kartu_sheet_light', Brightness.light)]) {
        testWidgets('shot $name', (tester) async {
          NV.palette = NvPalette.from(const Color(0xFFEE1C1C), bright);
          tester.view.physicalSize = const Size(1080, 2340);
          tester.view.devicePixelRatio = 2.75;
          addTearDown(tester.view.reset);
          final oldApps = installedShareApps;
          installedShareApps = () async => ['com.instagram.android', 'com.whatsapp', 'com.zhiliaoapp.musically', 'com.twitter.android', 'org.telegram.messenger'];
          addTearDown(() => installedShareApps = oldApps);
          await tester.pumpWidget(RepaintBoundary(
            key: const ValueKey('shot'),
            child: host(BragSharePreview(data: _data(shot: shot), debugBackground: backdrop()), center: false),
          ));
          await precache(tester);
          await tester.pump();
          await tester.pump();
          final dir = Directory(_shotsDir).absolute.path;
          Directory(dir).createSync(recursive: true);
          await expectLater(find.byKey(const ValueKey('shot')), matchesGoldenFile('$dir/$name.png'));
        });
      }
    }
  });
}
