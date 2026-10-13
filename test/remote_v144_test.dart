// v1.4.4: Kantor 3D (three.js WebView fed over the JS bridge), the agent
// sheet with "Kasih tugas", the list/3D toggle and live updates from the
// gateway event stream.
import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:neovarch_agent/remote/github_public.dart';
import 'package:neovarch_agent/remote/ui/profile_header_slot.dart';
import 'package:neovarch_agent/data/gateway_client.dart';
import 'package:neovarch_agent/remote/appearance.dart';
import 'package:neovarch_agent/remote/office_models.dart';
import 'package:neovarch_agent/remote/models_api.dart';
import 'package:neovarch_agent/remote/office_scene_state.dart';
import 'package:neovarch_agent/remote/remote_controller.dart';
import 'package:flutter/services.dart';
import 'package:neovarch_agent/remote/home_widget.dart';
import 'package:neovarch_agent/remote/remote_gateway.dart' show RemoteStatus, KanbanSnapshot, KanbanLane, KanbanCard;
import 'package:neovarch_agent/remote/ui/remote_tasks_screen.dart';
import 'package:neovarch_agent/remote/saved_desktops.dart';
import 'package:neovarch_agent/remote/ui/remote_chat_screen.dart';
import 'package:neovarch_agent/remote/ui/model_picker.dart' show providerLabel, modelPillText;
import 'package:neovarch_agent/remote/ui/remote_office_3d.dart';
import 'package:neovarch_agent/state/voice_service.dart';
import 'package:neovarch_agent/remote/ui/remote_app.dart' show themeFor;
import 'package:neovarch_agent/remote/ui/remote_office_screen.dart';
import 'package:neovarch_agent/state/app_controller.dart' show settingsProvider;
import 'package:neovarch_agent/state/settings_controller.dart';
import 'package:neovarch_agent/theme/neovarch_mobile_theme.dart';
import 'package:shared_preferences/shared_preferences.dart';

Map<String, dynamic> officeJson({String rakaStatus = 'working', String rakaTask = 'Rapikan folder Unduhan'}) => {
      'agents': [
        {'id': 'session:s1', 'kind': 'session', 'session_id': 's1', 'name': 'Raka', 'role': 'Agen remote · HP', 'status': rakaStatus, 'current_task': rakaTask},
        {'id': 'session:s2', 'kind': 'session', 'session_id': 's2', 'name': 'Ayu', 'role': 'Agen utama · desktop', 'status': 'waiting-approval',
          'current_task': 'Hapus cache lama', 'pending_approval': {'command': 'rm -rf ~/.cache/old'}},
        {'id': 'kanban:writer', 'kind': 'kanban', 'name': 'writer', 'role': 'Pelaksana tugas Kanban', 'status': 'idle', 'current_task': 'Draf laporan'},
      ],
      'kanban': {'todo': 2, 'running': 1},
      'feed': [],
    };

class SpyController extends RemoteController {
  SpyController(super.desktops);
  void poke() => notifyListeners();
  final created = <Map<String, String?>>[];
  final sent = <String>[];
  @override
  Future<String?> send(String text) async {
    sent.add(text);
    return null;
  }
  @override
  Future<String?> createTask({required String title, String? body, String? assignee}) async {
    created.add({'title': title, 'body': body, 'assignee': assignee});
    return null;
  }
}

void main() {
  late SharedPreferences prefs;
  late SettingsController settings;

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
    previewOfficeList = false;
  });

  tearDown(() {
    debugOfficeSceneBuilder = null;
    debugOfficeActiveChanged = null;
  });

  SpyController controller() {
    final desktops = SavedDesktops(prefs)..load();
    return SpyController(desktops)
      ..desktop = desktops.items.first
      ..status = RemoteStatus.connected
      ..debugApprovals = []
      ..office = OfficeSnapshot.fromJson(officeJson());
  }

  Future<void> pump(WidgetTester tester, RemoteController r, {double width = 390, Widget? home}) async {
    tester.view.physicalSize = Size(width * 3, 844 * 3);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    final look = AppearanceController(prefs);
    await tester.pumpWidget(ProviderScope(
      overrides: [
        settingsProvider.overrideWith((ref) => settings),
        remoteProvider.overrideWith((ref) => r),
        appearanceProvider.overrideWith((ref) => look),
      ],
      child: MaterialApp(
        theme: themeFor(look),
        home: home ?? RemoteOfficeScreen(onOpenChat: () {}, onOpenApprovals: () {}),
      ),
    ));
    await tester.pump(const Duration(milliseconds: 50));
  }

  /// Stand-in for the WebView: records every state the page would get and
  /// renders one tappable figure per agent.
  List<Map<String, Object?>> fakeScene() {
    final pushed = <Map<String, Object?>>[];
    debugOfficeSceneBuilder = (state, onTap) {
      pushed.add(state);
      final agents = (state['agents'] as List).cast<Map<String, Object?>>();
      return Column(key: const ValueKey('fake-scene'), children: [
        for (final a in agents)
          GestureDetector(
            key: ValueKey('figure-${a['id']}'),
            onTap: () => onTap('${a['id']}'),
            child: Text('${a['name']}:${a['status']}:${a['desk']}'),
          ),
      ]);
    };
    return pushed;
  }

  group('scene state', () {
    test('agents keep their desk across status changes; idle agents get none until busy', () {
      final desks = OfficeDeskAssigner();
      var s = officeSceneState(OfficeSnapshot.fromJson(officeJson()), desks: desks, accentArgb: 0xFFEE1C1C, dark: true);
      List<Map<String, Object?>> agents() => (s['agents'] as List).cast<Map<String, Object?>>();
      expect(s['accent'], '#ee1c1c');
      expect(s['kanban'], {'todo': 2, 'running': 1});
      expect(agents().map((a) => a['desk']).toList(), [0, 1, null]);
      expect(agents()[1]['status'], 'waiting-approval');
      expect(agents()[0]['task'], 'Rapikan folder Unduhan');
      // Raka goes idle (keeps desk 0), writer starts working (gets desk 2)
      final j = officeJson(rakaStatus: 'idle');
      (j['agents'] as List)[2]['status'] = 'working';
      s = officeSceneState(OfficeSnapshot.fromJson(j), desks: desks, accentArgb: 0xFFEE1C1C, dark: false);
      expect(agents().map((a) => a['desk']).toList(), [0, 1, 2]);
      expect(s['dark'], false);
      // Ayu leaves the office: her desk is freed
      (j['agents'] as List).removeAt(1);
      officeSceneState(OfficeSnapshot.fromJson(j), desks: desks, accentArgb: 0, dark: false);
      expect(desks.desks.containsKey('session:s2'), isFalse);
      expect(officeSceneScript({'a': 1}), 'window.nvOffice && window.nvOffice.setState({"a":1});');
    });
  });

  group('Kantor 3D', () {
    testWidgets('default is the 3D view, rendered from the remote office data', (tester) async {
      final pushed = fakeScene();
      await pump(tester, controller());
      expect(find.byKey(const ValueKey('office-scene-panel')), findsOneWidget);
      expect(find.text('Raka:working:0'), findsOneWidget);
      expect(find.text('Ayu:waiting-approval:1'), findsOneWidget);
      expect(find.text('writer:idle:null'), findsOneWidget);
      expect(pushed.last['kanban'], {'todo': 2, 'running': 1});
      // compact roster under the room carries the current tasks
      expect(find.byKey(const ValueKey('roster-session:s1')), findsOneWidget);
      expect(find.text('Rapikan folder Unduhan'), findsOneWidget);
      expect(find.byType(AgentDesk), findsNothing);
    });

    testWidgets('toggle switches between 3D and the list (with Kasih tugas on every card)', (tester) async {
      fakeScene();
      await pump(tester, controller());
      await tester.tap(find.byKey(const ValueKey('office-view-list')));
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.byKey(const ValueKey('office-scene-panel')), findsNothing);
      expect(find.byType(AgentDesk), findsNWidgets(3));
      expect(find.byKey(const ValueKey('assign-session:s1')), findsOneWidget);
      expect(find.byKey(const ValueKey('assign-kanban:writer')), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('office-view-visual')));
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.byKey(const ValueKey('office-scene-panel')), findsOneWidget);
      expect(find.byType(AgentDesk), findsNothing);
    });

    testWidgets('no WebView on the platform: falls back to the list with a note', (tester) async {
      await pump(tester, controller()); // flutter test has no WebViewPlatform
      await tester.pump();
      expect(find.byKey(const ValueKey('office-3d-fallback')), findsOneWidget);
      expect(find.byType(AgentDesk), findsWidgets);
      expect(find.byKey(const ValueKey('office-scene-panel')), findsNothing);
    });

    testWidgets('render loop pauses when the Kantor tab is hidden or the app is paused', (tester) async {
      fakeScene();
      final sent = <bool>[];
      debugOfficeActiveChanged = sent.add;
      final tab = ValueNotifier<int>(0);
      addTearDown(tab.dispose);
      await pump(tester, controller(),
          home: Scaffold(
            body: ValueListenableBuilder<int>(
              valueListenable: tab,
              builder: (_, i, _) => IndexedStack(index: i, children: [
                RemoteOfficeScreen(onOpenChat: () {}, onOpenApprovals: () {}),
                const Text('chat'),
              ]),
            ),
          ));
      expect(sent, [true]);
      tab.value = 1; // another tab: offstage, tickers muted
      await tester.pump();
      expect(sent, [true, false]);
      tab.value = 0;
      await tester.pump();
      expect(sent, [true, false, true]);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      await tester.pump();
      expect(sent.last, false);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pump();
      expect(sent.last, true);
      expect(sent.where((v) => v).length, 3);
    });

    testWidgets('a gateway office.update event updates the scene without a refresh', (tester) async {
      final pushed = fakeScene();
      final r = controller();
      await pump(tester, r);
      expect(find.text('Raka:working:0'), findsOneWidget);
      final before = pushed.length;
      // exactly what the WebSocket subscription delivers
      r.debugEvent(GatewayEventFrame('office.update', null, officeJson(rakaStatus: 'idle', rakaTask: 'Selesai, 3 berkas')));
      await tester.pump();
      expect(pushed.length, greaterThan(before));
      expect(find.text('Raka:idle:0'), findsOneWidget); // same desk kept
      expect(find.text('Selesai, 3 berkas'), findsOneWidget);
    });

    testWidgets('tapping an agent opens the sheet; Kasih tugas creates a Kanban task assigned to it', (tester) async {
      fakeScene();
      final r = controller();
      await pump(tester, r);
      await tester.tap(find.byKey(const ValueKey('figure-session:s1')));
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('agent-sheet')), findsOneWidget);
      expect(find.byKey(const ValueKey('agent-sheet-task')), findsOneWidget);
      await tester.enterText(find.byKey(const ValueKey('assign-task-field')), 'Cek email kampus\nBalas yang penting saja');
      await tester.tap(find.byKey(const ValueKey('assign-task-send')));
      await tester.pumpAndSettle();
      expect(r.created, [
        {'title': 'Cek email kampus', 'body': 'Balas yang penting saja', 'assignee': 'Raka'}
      ]);
      expect(find.byKey(const ValueKey('agent-sheet')), findsNothing);
      expect(find.text('Tugas dikirim ke Raka'), findsOneWidget);
    });

    testWidgets('Kasih tugas from a list card uses that agent as assignee', (tester) async {
      previewOfficeList = true;
      final r = controller();
      await pump(tester, r);
      await tester.dragUntilVisible(find.byKey(const ValueKey('assign-kanban:writer')), find.byKey(const ValueKey('office-list')), const Offset(0, -200));
      await tester.ensureVisible(find.byKey(const ValueKey('assign-kanban:writer')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('assign-kanban:writer')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const ValueKey('assign-task-field')), 'Bab 3');
      await tester.tap(find.byKey(const ValueKey('assign-task-send')));
      await tester.pumpAndSettle();
      expect(r.created.single['assignee'], 'writer');
      expect(r.created.single['title'], 'Bab 3');
    });

    testWidgets('the open sheet follows live pushes', (tester) async {
      fakeScene();
      final r = controller();
      await pump(tester, r);
      await tester.tap(find.byKey(const ValueKey('roster-session:s1')));
      await tester.pumpAndSettle();
      r.debugEvent(GatewayEventFrame('office.update', null, officeJson(rakaTask: 'Tugas baru dari PC')));
      await tester.pump();
      expect(find.descendant(of: find.byKey(const ValueKey('agent-sheet')), matching: find.text('Tugas baru dari PC')), findsOneWidget);
    });
  });

  group('Profil GitHub (public, no token)', () {
    String html() {
      final b = StringBuffer('<table>');
      final start = DateTime.utc(2025, 10, 5);
      for (var i = 0; i < 371; i++) {
        final d = start.add(Duration(days: i));
        final date = d.toIso8601String().substring(0, 10);
        final n = i % 7 == 0 ? 0 : (i % 4) * 3;
        final lvl = n == 0 ? 0 : (n > 6 ? 3 : 1);
        b.write('<td tabindex="0" data-date="$date" id="contribution-day-component-${i % 7}-${i ~/ 7}" data-level="$lvl" class="ContributionCalendar-day"></td>');
        b.write('<tool-tip id="t$i" for="contribution-day-component-${i % 7}-${i ~/ 7}" class="sr-only">${n == 0 ? 'No contributions' : '$n contributions'} on day.</tool-tip>');
      }
      return '$b</table>';
    }

    test('contributions HTML parses into a heatmap with exact counts', () {
      final h = parseContributionsHtml(html())!;
      expect(h.start, '2025-10-05');
      expect(h.counts.length, 371);
      expect(h.counts.take(5).toList(), [0, 3, 6, 9, 0]);
      expect(h.max, 9);
      expect(h.total, h.counts.fold<int>(0, (a, b) => a + b));
      expect(h.weeks().length, 53);
      expect(parseContributionsHtml('<html>nothing</html>'), isNull);
    });

    test('languages from public repos (forks ignored)', () {
      final l = languagesFromRepos([
        {'language': 'Dart'}, {'language': 'Dart'}, {'language': 'Python'}, {'language': 'Go', 'fork': true}, {'language': null},
      ]);
      expect(l.map((e) => e.name).toList(), ['Dart', 'Python']);
      expect(l.first.share, closeTo(2 / 3, 1e-9));
    });

    test('fetch, cache, and offline keeps the last copy', () async {
      SharedPreferences.setMockInitialValues({});
      final p = await SharedPreferences.getInstance();
      var online = true;
      final client = MockClient((req) async {
        if (!online) throw const SocketExceptionLike();
        final u = req.url.toString();
        if (u.endsWith('/users/octo')) return http.Response(jsonEncode({'login': 'octo', 'name': 'Octo Cat', 'bio': 'hi', 'avatar_url': 'https://a/x.png'}), 200);
        if (u.contains('/contributions')) return http.Response(html(), 200);
        if (u.contains('/repos')) return http.Response(jsonEncode([{'language': 'Dart'}]), 200);
        return http.Response('', 404);
      });
      final gh = GithubPublicController(prefs: p, client: client);
      await gh.setLogin('@octo');
      expect(gh.login, 'octo');
      expect(gh.profile!.name, 'Octo Cat');
      expect(gh.profile!.heatmap!.max, 9);
      expect(gh.profile!.languages.single.name, 'Dart');
      // a new controller reads the cache (app restart, offline)
      online = false;
      final again = GithubPublicController(prefs: p, client: client);
      expect(again.profile!.name, 'Octo Cat');
      await again.refresh();
      expect(again.profile!.name, 'Octo Cat');
      expect(again.error, contains('Offline'));
    });

    testWidgets('graph paints accent levels from sample data and scrolls sideways at 390 dp', (tester) async {
      tester.view.physicalSize = const Size(390 * 3, 844 * 3);
      tester.view.devicePixelRatio = 3;
      addTearDown(tester.view.reset);
      NV.palette = NvPalette.from(const Color(0xFFEE1C1C), Brightness.light);
      final h = parseContributionsHtml(html())!;
      await tester.pumpWidget(MaterialApp(home: Scaffold(body: Padding(padding: const EdgeInsets.all(16), child: ContributionGraphCard(heatmap: h)))));
      final painter = tester.widget<CustomPaint>(find.byKey(const ValueKey('contribution-graph'))).painter! as ContributionPainter;
      expect(painter.weeks.length, 53);
      expect(painter.levelOf(0), 0);
      expect(painter.levelOf(9), 4);
      expect(contributionColor(4), NV.palette.accent);
      expect(contributionColor(0), isNot(NV.palette.accent));
      // wider than the card: it scrolls, opened on the latest weeks
      expect(tester.getSize(find.byKey(const ValueKey('contribution-graph'))).width, greaterThan(358));
      expect(find.byKey(const ValueKey('contribution-scroll')), findsOneWidget);
      expect(find.text('${h.total} kontribusi'), findsOneWidget);
      NV.palette = NvPalette.red;
    });
  });

  group('Home-screen widget', () {
    tearDown(() => remoteLaunchAction.value = null);

    test('summary: PC, connection, working / waiting / open tasks, current task', () {
      final r = controller();
      expect(homeWidgetPayload(r), containsPair('pc', 'PC Kantor'));
      expect(homeWidgetPayload(r), allOf([
        containsPair('connected', true),
        containsPair('status', 'terhubung'),
        containsPair('working', 1),
        containsPair('waiting', 0),
        containsPair('tasks', 3), // office kanban: todo 2 + running 1
        containsPair('task', 'Raka: Rapikan folder Unduhan'),
      ]));
      r.board = const KanbanSnapshot([
        KanbanLane('ready', [KanbanCard(id: 't1', title: 'A', status: 'ready')]),
        KanbanLane('done', [KanbanCard(id: 't2', title: 'B', status: 'done')]),
      ], ['coder']);
      r.status = RemoteStatus.reconnecting;
      final p = homeWidgetPayload(r);
      expect(p['tasks'], 1); // done lane not counted
      expect(p['status'], 'menyambung…');
      expect(p['connected'], false);
    });

    test('sync sends only when the summary changed', () {
      final sent = <Map<String, Object?>>[];
      final sync = HomeWidgetSync(send: (p) async => sent.add(p), minInterval: Duration.zero);
      final r = controller();
      sync.update(r);
      sync.update(r);
      expect(sent.length, 1);
      r.office = OfficeSnapshot.fromJson(officeJson(rakaStatus: 'idle'));
      sync.update(r);
      expect(sent.length, 2);
      expect(sent.last['working'], 0);
      expect(sent.last['task'], isNull);
    });

    testWidgets('platform send: updateWidget on the neovarch/device channel', (tester) async {
      final calls = <MethodCall>[];
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(const MethodChannel('neovarch/device'), (c) async {
        calls.add(c);
        return true;
      });
      addTearDown(() => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(const MethodChannel('neovarch/device'), null));
      HomeWidgetSync().update(controller());
      await tester.pump();
      expect(calls.single.method, 'updateWidget');
      expect((calls.single.arguments as Map)['pc'], 'PC Kantor');
    });

    testWidgets('"+ Tugas" button: the Tugas screen opens the Tugas baru sheet', (tester) async {
      final r = controller()
        ..board = const KanbanSnapshot([
          KanbanLane('ready', [KanbanCard(id: 't1', title: 'A', status: 'ready')]),
        ], ['coder']);
      await pump(tester, r, home: const Scaffold(body: RemoteTasksScreen()));
      expect(find.text('Tugas baru di PC'), findsNothing);
      remoteLaunchAction.value = 'newtask';
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
      expect(find.text('Tugas baru di PC'), findsOneWidget);
      expect(remoteLaunchAction.value, isNull);
    });

    testWidgets('"+ Tugas" before the board arrives waits for it', (tester) async {
      final r = controller();
      remoteLaunchAction.value = 'newtask';
      await pump(tester, r, home: const Scaffold(body: RemoteTasksScreen()));
      await tester.pump(const Duration(milliseconds: 400));
      expect(find.text('Tugas baru di PC'), findsNothing);
      r.board = const KanbanSnapshot([KanbanLane('ready', [])], ['coder']);
      r.poke();
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
      expect(find.text('Tugas baru di PC'), findsOneWidget);
    });

    testWidgets('"Suara" button: Chat starts dictation', (tester) async {
      final engine = FakeEngine();
      VoiceService.debugEngine = engine;
      VoiceService.debugMicPermission = () async => true;
      VoiceService.instance.debugReset();
      addTearDown(() {
        VoiceService.debugEngine = null;
        VoiceService.debugMicPermission = null;
        VoiceService.instance.debugReset();
      });
      final r = controller();
      await pump(tester, r, home: RemoteChatScreen(onOpenApprovals: () {}));
      await tester.pump(const Duration(milliseconds: 300));
      expect(engine.listening, isFalse);
      remoteLaunchAction.value = 'voice';
      for (var i = 0; i < 5; i++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      expect(engine.listening, isTrue);
      expect(remoteLaunchAction.value, isNull);
      await VoiceService.instance.stopDictation();
    });
  });

  group('Voice (composer mic)', () {
    late FakeEngine engine;
    setUp(() {
      engine = FakeEngine();
      VoiceService.debugEngine = engine;
      VoiceService.debugMicPermission = () async => true;
      VoiceService.instance.debugReset();
    });
    tearDown(() {
      VoiceService.debugEngine = null;
      VoiceService.debugMicPermission = null;
      VoiceService.instance.debugReset();
    });

    test('locale resolution', () {
      expect(resolveSttLocale(['en-US', 'id-ID'], 'id_ID'), 'id-ID');
      expect(resolveSttLocale(['en_GB', 'in_ID'], 'en_US'), 'en_GB');
      expect(resolveSttLocale(['fr_FR'], 'id_ID'), isNull);
      expect(sttErrorText('error_permission'), contains('Izin mikrofon'));
    });

    testWidgets('mic: partial words fill the field, the final result stays in the field (not sent)', (tester) async {
      final r = controller();
      await pump(tester, r, home: RemoteChatScreen(onOpenApprovals: () {}));
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.byKey(const ValueKey('composer-mic-lang')), findsOneWidget);
      await tester.tap(find.byTooltip('Dikte perintah (tekan lama: ganti bahasa)'));
      await tester.pump();
      expect(engine.listening, isTrue);
      expect(engine.localeId, 'id-ID'); // settings id_ID -> recogniser's id-ID
      engine.emit('rapikan folder', false);
      await tester.pump();
      // in the field and in the dictation strip
      expect(find.text('rapikan folder'), findsNWidgets(2));
      expect(find.byKey(const ValueKey('dictation-strip')), findsOneWidget);
      expect(r.sent, isEmpty);
      engine.emit('rapikan folder unduhan', true);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));
      // 1.4.8: dictation never sends by itself
      expect(r.sent, isEmpty);
      expect(find.text('rapikan folder unduhan'), findsOneWidget);
      expect(find.byKey(const ValueKey('dictation-strip')), findsNothing);
    });

    testWidgets('long-press switches to English; a denied mic permission explains how to allow it', (tester) async {
      final r = controller();
      await pump(tester, r, home: RemoteChatScreen(onOpenApprovals: () {}));
      await tester.pump(const Duration(milliseconds: 300));
      await tester.longPress(find.byKey(const ValueKey('composer-mic')));
      await tester.pump();
      expect(settings.sttLocale, 'en_US');
      expect(find.text('EN'), findsOneWidget);
      settings.update((x) => x.sttLocale = 'id_ID');
      VoiceService.debugMicPermission = () async => false;
      ScaffoldMessenger.of(tester.element(find.byType(RemoteChatScreen))).removeCurrentSnackBar();
      await tester.pump(const Duration(seconds: 1));
      await tester.tap(find.byTooltip('Dikte perintah (tekan lama: ganti bahasa)'));
      for (var i = 0; i < 10; i++) {
        await tester.pump(const Duration(milliseconds: 200));
      }
      expect(engine.listening, isFalse);
      expect(VoiceService.instance.error, contains('Izin mikrofon'));
      expect(find.textContaining('Izin mikrofon ditolak'), findsOneWidget);
    });
  });

  group('Voice failures are never fatal', () {
    tearDown(() {
      VoiceService.debugEngine = null;
      VoiceService.debugMicPermission = null;
      VoiceService.initTimeout = const Duration(seconds: 12);
      VoiceService.instance.debugReset();
    });

    Future<void> tapMic(WidgetTester tester) async {
      await tester.tap(find.byTooltip('Dikte perintah (tekan lama: ganti bahasa)'));
      for (var i = 0; i < 10; i++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
    }

    for (final c in <(String, FakeEngine, String)>[
      ('recogniser throws on start', ThrowingEngine(onInit: true), 'gagal dimulai'),
      ('mic busy (error_audio)', ThrowingEngine(listenError: PlatformException(code: 'error_audio')), 'Mikrofon sedang dipakai'),
      ('recogniser never answers', ThrowingEngine(hang: true), 'tidak menjawab'),
    ]) {
      testWidgets('mic: ${c.$1} -> message, app keeps running', (tester) async {
        VoiceService.debugEngine = c.$2;
        VoiceService.debugMicPermission = () async => true;
        VoiceService.initTimeout = const Duration(milliseconds: 300);
        VoiceService.instance.debugReset();
        final r = controller();
        await pump(tester, r, home: RemoteChatScreen(onOpenApprovals: () {}));
        await tester.pump(const Duration(milliseconds: 300));
        await tapMic(tester);
        expect(tester.takeException(), isNull);
        expect(VoiceService.instance.listening, isFalse);
        expect(VoiceService.instance.error, contains(c.$3));
        expect(find.textContaining(c.$3), findsOneWidget);
        // the mic still works after the failure
        expect(find.byKey(const ValueKey('composer-mic')), findsOneWidget);
        await tester.pump(const Duration(seconds: 5));
      });
    }
  });

  group('Models (9Router contract v1, fake adapter)', () {
    late FakeModels api;
    setUp(() => api = FakeModels());

    test('snapshot parsing and grouping', () {
      final m = ModelsSnapshot.fromJson(FakeModels.json);
      expect(m.defaultModel, const ModelRef('oc/big-pickle', '9router'));
      expect(m.groups().first.$1, 'OpenCode Free');
      expect(m.groups(query: 'sonnet').single.$2.single.id, 'kr/claude-sonnet-4.5');
      expect(modelShort('oc/big-pickle'), 'big-pickle');
      final a = OfficeAgent.fromJson({'id': 'session:s1', 'model': 'kr/claude-sonnet-4.5', 'model_override': {'model': 'kr/claude-sonnet-4.5', 'provider': '9router'}, 'model_source': 'agent'});
      expect(a.modelOverride!.model, 'kr/claude-sonnet-4.5');
      expect(a.modelSource, 'agent');
    });

    testWidgets('composer chip shows the PC default; picking a model sets it; model.default.changed updates live', (tester) async {
      final r = controller()..debugModelsApi = api;
      await r.refreshModels();
      await pump(tester, r, home: RemoteChatScreen(onOpenApprovals: () {}));
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.descendant(of: find.byKey(const ValueKey('model-chip')), matching: find.text('big-pickle')), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('model-chip')));
      for (var i = 0; i < 12; i++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      expect(find.byKey(const ValueKey('model-picker')), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('model-kr/claude-sonnet-4.5')));
      for (var i = 0; i < 12; i++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      expect(api.defaults.single, 'kr/claude-sonnet-4.5');
      expect(find.descendant(of: find.byKey(const ValueKey('model-chip')), matching: find.text('claude-sonnet-4.5')), findsOneWidget);
      // changed on the PC
      r.debugEvent(const GatewayEventFrame('model.default.changed', null, {'model': 'oc/big-pickle', 'provider': '9router'}));
      await tester.pump();
      expect(find.descendant(of: find.byKey(const ValueKey('model-chip')), matching: find.text('big-pickle')), findsOneWidget);
    });

    testWidgets('agent sheet: own model, and back to the PC default', (tester) async {
      fakeScene();
      final r = controller()..debugModelsApi = api;
      await r.refreshModels();
      await pump(tester, r);
      await tester.tap(find.byKey(const ValueKey('figure-session:s1')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('agent-model')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('model-kr/claude-sonnet-4.5')));
      await tester.pumpAndSettle();
      expect(api.agentSets.last, ('session:s1', 'kr/claude-sonnet-4.5'));
      await tester.tap(find.byKey(const ValueKey('agent-model')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('model-follow-default')));
      await tester.pumpAndSettle();
      expect(api.agentSets.last, ('session:s1', null));
    });

    test('pill text: label · provider, "—" without a PC', () {
      expect(providerLabel('9router'), '9Router');
      expect(providerLabel('custom:foo'), 'Kustom');
      expect(providerLabel('openrouter'), 'Openrouter');
      expect(providerLabel(''), '');
      final off = controller()..status = RemoteStatus.disconnected;
      expect(modelPillText(off), '—');
    });

    testWidgets('top-bar model pill: shows the PC model, tap opens the picker, picking switches it', (tester) async {
      final r = controller()..debugModelsApi = api;
      await r.refreshModels();
      await pump(tester, r, home: RemoteChatScreen(onOpenApprovals: () {}));
      await tester.pump(const Duration(milliseconds: 300));
      final pillText = find.byKey(const ValueKey('model-switcher-text'));
      expect(tester.widget<Text>(pillText).data, 'Big Pickle · 9Router');
      await tester.tap(find.byKey(const ValueKey('model-switcher-pill')));
      for (var i = 0; i < 12; i++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      expect(find.byKey(const ValueKey('model-picker')), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('model-kr/claude-sonnet-4.5')));
      for (var i = 0; i < 12; i++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      expect(api.defaults.single, 'kr/claude-sonnet-4.5');
      expect(tester.widget<Text>(pillText).data, 'Claude Sonnet 4.5 · 9Router');
    });

    testWidgets('top-bar model pill: greyed "—" and not tappable with no PC', (tester) async {
      final r = controller()..status = RemoteStatus.disconnected;
      await pump(tester, r, home: RemoteChatScreen(onOpenApprovals: () {}));
      await tester.pump(const Duration(milliseconds: 300));
      expect(tester.widget<Text>(find.byKey(const ValueKey('model-switcher-text'))).data, '—');
      await tester.tap(find.byKey(const ValueKey('model-switcher-pill')), warnIfMissed: false);
      for (var i = 0; i < 6; i++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      expect(find.byKey(const ValueKey('model-picker')), findsNothing);
    });

    testWidgets('older PC without /api/models: no chip', (tester) async {
      final r = controller()..modelsUnsupported = true;
      await pump(tester, r, home: RemoteChatScreen(onOpenApprovals: () {}));
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.byKey(const ValueKey('model-chip')), findsNothing);
    });
  });
}

class SocketExceptionLike implements Exception {
  const SocketExceptionLike();
  @override
  String toString() => 'SocketException: offline';
}

class FakeEngine implements SpeechEngine {
  bool listening = false;
  String? localeId;
  void Function(String, bool)? _on;
  @override
  Future<bool> initialize({required void Function(String error) onError, required void Function(String status) onStatus}) async => true;
  @override
  Future<List<String>> localeIds() async => ['en-US', 'id-ID'];
  @override
  Future<void> listen({required String localeId, required void Function(String words, bool isFinal) onResult}) async {
    listening = true;
    this.localeId = localeId;
    _on = onResult;
  }
  void emit(String w, bool fin) {
    _on?.call(w, fin);
    if (fin) listening = false;
  }
  @override
  Future<void> stop() async => listening = false;
}

class FakeModels implements ModelsApi {
  static final json = <String, dynamic>{
    'models': [
      {'id': 'oc/big-pickle', 'label': 'Big Pickle', 'provider': '9router', 'group': 'OpenCode Free', 'free': true, 'recommended': true},
      {'id': 'oc/nemotron-3-ultra-free', 'label': 'Nemotron 3 Ultra', 'provider': '9router', 'group': 'OpenCode Free', 'free': true},
      {'id': 'kr/claude-sonnet-4.5', 'label': 'Claude Sonnet 4.5', 'provider': '9router', 'group': 'Kiro'},
    ],
    'default': {'model': 'oc/big-pickle', 'provider': '9router'},
    'router': {'setup': {'ready': true}},
  };
  final defaults = <String>[];
  final agentSets = <(String, String?)>[];
  @override
  Future<ModelsSnapshot> listModels({bool refresh = false}) async => ModelsSnapshot.fromJson(json);
  @override
  Future<ModelRef> setDefaultModel(String model, {String? provider}) async {
    defaults.add(model);
    return ModelRef(model, provider ?? '9router');
  }
  @override
  Future<AgentModel> setAgentModel(String agentId, String? model, {String? provider}) async {
    agentSets.add((agentId, model));
    return AgentModel(agentId: agentId, model: model ?? 'oc/big-pickle', provider: '9router');
  }
}

class ThrowingEngine extends FakeEngine {
  ThrowingEngine({this.onInit = false, this.listenError, this.hang = false});
  final bool onInit;
  final Object? listenError;
  final bool hang;
  @override
  Future<bool> initialize({required void Function(String error) onError, required void Function(String status) onStatus}) {
    if (hang) return Completer<bool>().future;
    if (onInit) throw StateError('SpeechRecognizer crashed');
    return Future.value(true);
  }
  @override
  Future<void> listen({required String localeId, required void Function(String words, bool isFinal) onResult}) async {
    if (listenError != null) throw listenError!;
    return super.listen(localeId: localeId, onResult: onResult);
  }
}
