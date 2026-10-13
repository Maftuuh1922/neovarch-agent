// Chat header (1.4.8): the status line runs the full width under the title
// (never squeezed beside the buttons, never cut mid-segment), the step
// counter never reads "9/3", and "mode fokus": scrolling down shrinks the
// header into a compact bar and folds the composer chips; scrolling up or
// back to the top restores them, and typing always keeps the composer whole.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:neovarch_agent/data/gateway_client.dart' show GatewayEventFrame;
import 'package:neovarch_agent/models/models.dart';
import 'package:neovarch_agent/remote/appearance.dart';
import 'package:neovarch_agent/remote/remote_controller.dart';
import 'package:neovarch_agent/remote/remote_gateway.dart' show RemoteStatus;
import 'package:neovarch_agent/remote/remote_transcript.dart';
import 'package:neovarch_agent/remote/saved_desktops.dart';
import 'package:neovarch_agent/remote/ui/chat_focus.dart';
import 'package:neovarch_agent/remote/ui/glass/glass_chat.dart';
import 'package:neovarch_agent/remote/ui/remote_chat_screen.dart';
import 'package:neovarch_agent/remote/ui/remote_composer.dart' show ComposerChipsRow;
import 'package:neovarch_agent/state/app_controller.dart' show settingsProvider;
import 'package:neovarch_agent/state/settings_controller.dart';
import 'package:neovarch_agent/theme/neovarch_mobile_theme.dart';

const _para = 'Saya cek log build-nya dulu, lalu jalankan tes yang terkait. Kalau ada yang merah, '
    'saya perbaiki satu per satu dan laporkan hasilnya di sini supaya kamu bisa meninjau perubahan sebelum digabung.';

List<ChatMsg> _history(int pairs) => [
      for (var i = 0; i < pairs; i++) ...[
        ChatMsg(id: 'u$i', role: 'user', content: 'Pertanyaan nomor $i', ts: 1000 + i * 2),
        ChatMsg(id: 'a$i', role: 'assistant', content: 'Jawaban $i. $_para', ts: 1001 + i * 2),
      ],
    ];

void main() {
  group('step counter', () {
    test('never reads current over a smaller total', () {
      expect(formatStepLabel(9, 3), 'langkah 9');
      expect(formatStepLabel(9, 12), 'langkah 9/12');
      expect(formatStepLabel(30, 30), 'langkah 30/30');
      expect(formatStepLabel(9, null), 'langkah 9');
      expect(formatStepLabel(1, 30), isNull);
      expect(formatStepLabel(null, 30), isNull);
      expect(formatStepShort(9, 3), '9');
      expect(formatStepShort(9, 60), '9/60');
    });

    test('follows the core: an extended limit shows, a stale one never does', () {
      final t = RemoteTranscript(history: const []);
      t.apply(const GatewayEventFrame('message.start', 's', {}));
      t.apply(const GatewayEventFrame('turn.progress', 's', {'step': 5, 'limit': 30, 'max': 150, 'extended': 0}));
      expect(t.stepLabel, 'langkah 5/30');
      // Tempest v2: limit grows before the step passes it (with a status message)
      t.apply(const GatewayEventFrame('turn.progress', 's', {'step': 31, 'limit': 60, 'max': 150, 'extended': 1}));
      expect(t.stepLabel, 'langkah 31/60');
      expect(t.stepShort, '31/60');
      // an older core that still reports a step past its limit
      t.apply(const GatewayEventFrame('turn.progress', 's', {'step': 9, 'limit': 3}));
      expect(t.stepLabel, 'langkah 9');
    });

    test('status segments wrap only between segments', () {
      final s = joinStatus(chatStatusSegments(status: 'terhubung', running: true, step: 'langkah 9/30', context: 'konteks 42% · 54k/128k'));
      expect(s.replaceAll('\u00A0', ' '), 'terhubung · agen bekerja · langkah 9/30 · konteks 42% · 54k/128k');
      // breakable spaces only right after a separator dot
      expect(RegExp(r' ').allMatches(s).length, 3);
      expect(s.contains('agen bekerja'), isFalse);
      expect(chatStatusSegments(status: 'terhubung', tokensPerSecond: 41.6), ['terhubung', '42 tok/s']);
    });
  });

  group('focus tracker', () {
    test('down collapses, up restores, top and programmatic scrolls behave', () {
      final f = ChatFocusTracker();
      f.update(pixels: 400, maxExtent: 2000, user: false);
      expect(f.update(pixels: 410, maxExtent: 2000, user: true), isFalse); // below the threshold
      expect(f.update(pixels: 450, maxExtent: 2000, user: true), isTrue);
      expect(f.focused, isTrue);
      // auto-follow of a streaming reply never toggles it
      expect(f.update(pixels: 300, maxExtent: 2000, user: false), isFalse);
      expect(f.focused, isTrue);
      expect(f.update(pixels: 260, maxExtent: 2000, user: true), isTrue);
      expect(f.focused, isFalse);
      f.update(pixels: 400, maxExtent: 2000, user: true);
      expect(f.focused, isTrue);
      // content resize (composer folded) is not the user's scroll
      expect(f.update(pixels: 310, maxExtent: 1910, user: true), isFalse);
      expect(f.focused, isTrue);
      // reaching the top restores the header
      expect(f.update(pixels: 0, maxExtent: 1910, user: true), isTrue);
      expect(f.focused, isFalse);
    });
  });

  group('chat screen', () {
    late SharedPreferences prefs;
    late SettingsController settings;

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

    setUp(() async {
      SharedPreferences.setMockInitialValues({
        'remote.desktops': jsonEncode([
          {'id': 'pc1', 'name': 'MUHAMMADMAFTUH', 'url': 'http://192.168.1.20:9319', 'addedAt': DateTime.now().toIso8601String()},
        ]),
        'remote.active': 'pc1',
      });
      prefs = await SharedPreferences.getInstance();
      settings = SettingsController(prefs);
      await settings.load();
    });
    tearDown(() => NV.palette = NvPalette.red);

    RemoteController controller({bool running = false}) {
      final desktops = SavedDesktops(prefs)..load();
      final t = RemoteTranscript(history: _history(12));
      if (running) {
        t
          ..running = true
          ..step = 9
          ..stepLimit = 30
          ..contextTokens = 54000
          ..contextWindow = 128000;
      }
      return RemoteController(desktops)
        ..desktop = desktops.items.first
        ..status = RemoteStatus.connected
        ..runtimeId = 'rt-1'
        ..storedId = 's-1'
        ..title = 'halo'
        ..transcript = t;
    }

    Widget host(RemoteController r) {
      final look = AppearanceController(prefs);
      NV.palette = NvPalette.red;
      return ProviderScope(
        overrides: [
          settingsProvider.overrideWith((ref) => settings),
          remoteProvider.overrideWith((ref) => r),
          appearanceProvider.overrideWith((ref) => look),
        ],
        child: MaterialApp(
          debugShowCheckedModeBanner: false,
          theme: buildNeovarchMobileTheme(),
          home: RemoteChatScreen(onOpenApprovals: () {}),
        ),
      );
    }

    Future<void> phone(WidgetTester tester) async {
      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 3;
      tester.view.padding = const FakeViewPadding(top: 120, bottom: 330);
      tester.view.viewPadding = const FakeViewPadding(top: 120, bottom: 330);
      addTearDown(tester.view.reset);
    }

    Future<void> settle(WidgetTester tester) async {
      for (var i = 0; i < 12; i++) {
        await tester.pump(const Duration(milliseconds: 60));
      }
    }

    ScrollPosition pos(WidgetTester tester) =>
        tester.state<ScrollableState>(find.descendant(of: find.byType(ListView), matching: find.byType(Scrollable)).first).position;

    double opacityOf(WidgetTester tester, Finder f) =>
        tester.widget<Opacity>(find.ancestor(of: f, matching: find.byType(Opacity)).first).opacity;

    testWidgets('status line: own full-width row under the title, not truncated, sane counter', (tester) async {
      await phone(tester);
      await tester.pumpWidget(host(controller(running: true)));
      await settle(tester);
      final status = find.byKey(const ValueKey('glass-header-status'));
      expect(status, findsOneWidget);
      final text = tester.widget<Text>(status).data!.replaceAll('\u00A0', ' ');
      expect(text, 'terhubung · agen bekerja · langkah 9/30 · konteks 42% · 54k/128k');
      expect(text.contains('9/3 '), isFalse);
      // nothing cut off
      final para = tester.renderObject<RenderParagraph>(find.descendant(of: status, matching: find.byType(RichText)));
      expect(para.didExceedMaxLines, isFalse);
      // below the round buttons, and as wide as the header (minus its padding)
      final header = tester.getRect(find.byKey(const ValueKey('glass-chat-header')));
      final row = tester.getRect(find.byKey(const ValueKey('glass-header-status-row')));
      final clock = tester.getRect(find.byTooltip('Riwayat sesi di PC'));
      expect(row.top, greaterThanOrEqualTo(clock.bottom - 0.5));
      expect(row.right, closeTo(header.right - 12, 1));
      expect(row.width, greaterThan(header.width - 40));
    });

    testWidgets('scrolling down collapses header + composer chips; scrolling up restores', (tester) async {
      await phone(tester);
      await tester.pumpWidget(host(controller()));
      await settle(tester);
      final header = find.byKey(const ValueKey('glass-chat-header'));
      final fullH = tester.getSize(header).height;
      expect(find.byType(ComposerChipsRow), findsOneWidget);
      expect(opacityOf(tester, find.byKey(const ValueKey('glass-header-compact-title'))), 0);

      // read from the top, then scroll down through the conversation
      pos(tester).jumpTo(0);
      await tester.pump();
      await tester.drag(find.byType(ListView), const Offset(0, -320));
      await settle(tester);
      final compactH = tester.getSize(header).height;
      expect(compactH, lessThan(fullH - 30), reason: 'header shrinks into a compact bar');
      expect(opacityOf(tester, find.byKey(const ValueKey('glass-header-compact-title'))), 1);
      expect(find.byType(ComposerChipsRow), findsNothing, reason: 'composer chips fold away');
      expect(find.byKey(const ValueKey('chat-composer')), findsOneWidget, reason: 'the composer itself never hides');
      final container = ProviderScope.containerOf(tester.element(find.byType(RemoteChatScreen)));
      expect(container.read(chatFocusProvider), isTrue, reason: 'the shell hides the nav pill from this');

      // scrolling back up restores everything
      await tester.drag(find.byType(ListView), const Offset(0, 160));
      await settle(tester);
      expect(tester.getSize(header).height, closeTo(fullH, 0.5));
      expect(find.byType(ComposerChipsRow), findsOneWidget);
      expect(container.read(chatFocusProvider), isFalse);
    });

    testWidgets('tap on the compact bar and typing keep the chrome whole', (tester) async {
      await phone(tester);
      await tester.pumpWidget(host(controller()));
      await settle(tester);
      final header = find.byKey(const ValueKey('glass-chat-header'));
      final fullH = tester.getSize(header).height;
      pos(tester).jumpTo(0);
      await tester.pump();
      await tester.drag(find.byType(ListView), const Offset(0, -320));
      await settle(tester);
      expect(tester.getSize(header).height, lessThan(fullH - 30));

      // typing: the composer chips come back even in focus mode
      await tester.tap(find.byType(TextField));
      await settle(tester);
      expect(find.byType(ComposerChipsRow), findsOneWidget);
      final container = ProviderScope.containerOf(tester.element(find.byType(RemoteChatScreen)));
      expect(container.read(chatFocusProvider), isFalse);
      FocusManager.instance.primaryFocus?.unfocus();
      await settle(tester);

      // tap the compact bar: full header again
      await tester.tap(find.byKey(const ValueKey('glass-header-compact')));
      await settle(tester);
      expect(tester.getSize(header).height, closeTo(fullH, 0.5));
    });
  });
}
