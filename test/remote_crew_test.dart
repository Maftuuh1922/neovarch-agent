// Crew on the phone: goal → the PC's main agent proposes a team → approve
// (with consent for side effects) → the pixel room follows `crew.update`,
// approvals are answered from the phone, Lanjutan edits by hand.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:neovarch_agent/remote/appearance.dart';
import 'package:neovarch_agent/remote/crew_models.dart';
import 'package:neovarch_agent/remote/l10n/strings.dart';
import 'package:neovarch_agent/remote/remote_controller.dart';
import 'package:neovarch_agent/remote/remote_gateway.dart' show RemoteStatus;
import 'package:neovarch_agent/remote/saved_desktops.dart';
import 'package:neovarch_agent/remote/ui/crew_pixel.dart';
import 'package:neovarch_agent/remote/ui/remote_app.dart' show PaletteScope, themeFor;
import 'package:neovarch_agent/remote/ui/remote_crew_screen.dart';
import 'package:neovarch_agent/remote/ui/remote_kantor_tab.dart';
import 'package:neovarch_agent/state/app_controller.dart' show settingsProvider;
import 'package:neovarch_agent/state/settings_controller.dart';
import 'package:neovarch_agent/theme/neovarch_mobile_theme.dart';

Map<String, dynamic> member(String id, String name, String role, List<String> tools, {String status = 'idle', Map<String, dynamic>? approval}) => {
  'id': id,
  'name': name,
  'role': role,
  'goal': '$role goal',
  'tools': tools,
  'model': '',
  'avatar': int.parse(id.substring(1)),
  'status': status,
  'approval': ?approval,
};

Map<String, dynamic> crewJson({String status = 'proposed', List<Map<String, dynamic>>? members, List<Map<String, dynamic>>? tasks, String finalOutput = ''}) =>
    {
      'id': 'c1',
      'title': 'Bug login',
      'goal': 'Perbaiki bug login',
      'status': status,
      'process': 'hierarchical',
      'manager': 'm1',
      'designed_by': 'agent',
      'template': 'coding',
      'side_effects': ['shell', 'write'],
      'allow_side_effects': status != 'proposed',
      'final_output': finalOutput,
      'error': '',
      'created_at': 10,
      'members':
          members ??
          [
            member('m1', 'Arga', 'Manajer teknis', ['files']),
            member('m2', 'Fajar', 'Programmer', ['files', 'write', 'shell']),
          ],
      'tasks':
          tasks ??
          [
            {'id': 't1', 'title': 'Implementasi', 'description': 'ubah kode', 'member_id': 'm2', 'status': 'todo', 'output': ''},
          ],
    };

class FakeCrew implements CrewApi {
  final calls = <(String, Map<String, dynamic>)>[];
  final approvals = <(String, String, String)>[];
  List<Map<String, dynamic>> list = [];

  @override
  Future<dynamic> crewCall(String method, [Map<String, dynamic> params = const {}]) async {
    calls.add((method, params));
    switch (method) {
      case 'list':
        return {'crews': list};
      case 'propose':
        return crewJson();
      case 'approve':
        return crewJson(status: 'running');
      case 'get':
        return crewJson(status: 'done', finalOutput: 'Semua tes lulus');
      case 'update':
        final patch = Map<String, dynamic>.from(params['patch'] as Map);
        return {...crewJson(), ...patch};
      default:
        return {'ok': true};
    }
  }

  @override
  Future<void> crewApproval(String sessionId, String requestId, String choice) async => approvals.add((sessionId, requestId, choice));
}

void main() {
  late SharedPreferences prefs;
  late SettingsController settings;

  setUp(() async {
    SharedPreferences.setMockInitialValues({
      crewIntroKey: true,
      'remote.desktops': jsonEncode([
        {'id': 'pc1', 'name': 'PC Rumah', 'url': 'http://192.168.1.20:9319', 'addedAt': DateTime.now().toIso8601String()},
      ]),
      'remote.active': 'pc1',
    });
    prefs = await SharedPreferences.getInstance();
    settings = SettingsController(prefs);
    await settings.load();
    NV.palette = NvPalette.red;
    crewPixelAnimate = false;
  });

  // The Crew tab's IndexedStack keeps all three segments' lists; scroll the one on screen.
  Finder visibleList() => find.byWidgetPredicate((w) => w is Scrollable && w.axisDirection == AxisDirection.down).hitTestable().first;

  RemoteController controller(FakeCrew fake) {
    final desktops = SavedDesktops(prefs)..load();
    return RemoteController(desktops)
      ..desktop = desktops.items.isEmpty ? null : desktops.items.first
      ..status = RemoteStatus.connected
      ..debugApprovals = []
      ..debugCrewApi = fake;
  }

  Future<void> pump(WidgetTester tester, RemoteController r, {int segment = kantorSegCrew}) async {
    tester.view.physicalSize = const Size(392 * 3, 850 * 3);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    final look = AppearanceController(prefs);
    var seg = segment;
    await tester.pumpWidget(
      ProviderScope(
        overrides: [settingsProvider.overrideWith((ref) => settings), remoteProvider.overrideWith((ref) => r), appearanceProvider.overrideWith((ref) => look)],
        child: MaterialApp(
          theme: themeFor(look),
          builder: (context, child) => PaletteScope(revision: look.revision, child: child!),
          home: Scaffold(
            body: StatefulBuilder(
              builder: (context, set) => RemoteKantorTab(segment: seg, onSegment: (i) => set(() => seg = i), onOpenChat: () {}, onOpenApprovals: () {}),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  Future<void> push(WidgetTester tester, RemoteController r, Map<String, dynamic> payload) async {
    r.crewPush = payload;
    r.crewRevision++;
    r.notifyListeners(); // ignore: invalid_use_of_protected_member, invalid_use_of_visible_for_testing_member
    await tester.pumpAndSettle();
  }

  testWidgets('three segments: Crew · Tugas · Lanjutan', (tester) async {
    await pump(tester, controller(FakeCrew()));
    for (final t in ['CREW', 'TUGAS', 'LANJUTAN']) {
      expect(find.text(t), findsOneWidget);
    }
    expect(find.byKey(const ValueKey('crew-goal')), findsOneWidget);
  });

  testWidgets('short onboarding shows once', (tester) async {
    SharedPreferences.setMockInitialValues({});
    prefs = await SharedPreferences.getInstance();
    await pump(tester, controller(FakeCrew()));
    expect(find.byKey(const ValueKey('crew-intro')), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('crew-intro-ok')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('crew-intro')), findsNothing);
    expect((await SharedPreferences.getInstance()).getBool(crewIntroKey), isTrue);
  });

  testWidgets('goal → proposal; approve needs consent for side effects', (tester) async {
    final fake = FakeCrew();
    await pump(tester, controller(fake));
    await tester.enterText(find.byKey(const ValueKey('crew-goal')), 'Perbaiki bug login');
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('crew-propose')));
    await tester.pumpAndSettle();
    expect(fake.calls.where((c) => c.$1 == 'propose').single.$2, {'goal': 'Perbaiki bug login'});
    expect(find.byKey(const ValueKey('crew-title')), findsOneWidget);
    expect(find.text('Disusun agen utama'), findsOneWidget);
    expect(find.byKey(const ValueKey('crew-room')), findsOneWidget);
    expect(find.byKey(const ValueKey('crew-seat-m2')), findsOneWidget);
    await tester.scrollUntilVisible(find.byKey(const ValueKey('crew-approve')), 300, scrollable: visibleList());
    final approve = tester.widget<FilledButton>(find.byKey(const ValueKey('crew-approve')));
    expect(approve.onPressed, isNull);
    await tester.tap(find.byKey(const ValueKey('crew-consent')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('crew-approve')));
    await tester.pumpAndSettle();
    expect(fake.calls.where((c) => c.$1 == 'approve').single.$2, {'id': 'c1', 'allow_side_effects': true});
  });

  testWidgets('template chip sends the template id', (tester) async {
    final fake = FakeCrew();
    await pump(tester, controller(fake));
    await tester.enterText(find.byKey(const ValueKey('crew-goal')), 'Riset EV');
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('crew-template-riset_laporan')));
    await tester.pumpAndSettle();
    expect(fake.calls.where((c) => c.$1 == 'propose').single.$2, {'goal': 'Riset EV', 'template': 'riset_laporan'});
  });

  testWidgets('crew.update push moves the pixel room and the phone answers approvals', (tester) async {
    final fake = FakeCrew();
    final r = controller(fake);
    await pump(tester, r);
    await tester.enterText(find.byKey(const ValueKey('crew-goal')), 'x');
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('crew-propose')));
    await tester.pumpAndSettle();
    await push(
      tester,
      r,
      crewJson(
        status: 'running',
        members: [
          member('m1', 'Arga', 'Manajer teknis', ['files'], status: 'reviewing'),
          member('m2', 'Fajar', 'Programmer', ['shell'], status: 'waiting', approval: {'session_id': 's9', 'request_id': 'apr-1', 'command': 'npm test'}),
        ],
      ),
    );
    expect(find.byKey(const ValueKey('crew-station-waiting')), findsOneWidget);
    expect(find.byKey(const ValueKey('crew-station-reviewing')), findsOneWidget);
    expect(find.text('npm test'), findsNWidgets(2)); // approval card + speech bubble
    final allowOnce = find.descendant(of: find.byKey(const ValueKey('crew-approval-m2')), matching: find.text('Izinkan sekali'));
    await tester.ensureVisible(allowOnce);
    await tester.pumpAndSettle();
    await tester.tap(allowOnce);
    await tester.pumpAndSettle();
    expect(fake.approvals.single, ('s9', 'apr-1', 'once'));
    await tester.scrollUntilVisible(find.byKey(const ValueKey('crew-stop')), 300, scrollable: visibleList());
    expect(find.byKey(const ValueKey('crew-stop')), findsOneWidget);
  });

  testWidgets('Lanjutan edits role, tools and flow through crew.update', (tester) async {
    final fake = FakeCrew();
    final r = controller(fake);
    await pump(tester, r);
    await tester.enterText(find.byKey(const ValueKey('crew-goal')), 'x');
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('crew-propose')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('segment-Lanjutan')));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.byKey(const ValueKey('crew-m1-role')), 200, scrollable: visibleList());
    await tester.enterText(find.byKey(const ValueKey('crew-m1-role')), 'Penguji');
    await tester.scrollUntilVisible(find.byKey(const ValueKey('crew-m1-tool-web')), 200, scrollable: visibleList());
    await tester.tap(find.byKey(const ValueKey('crew-m1-tool-web')));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.byKey(const ValueKey('crew-save')), 300, scrollable: visibleList());
    await tester.tap(find.byKey(const ValueKey('crew-save')));
    await tester.pumpAndSettle();
    final patch = fake.calls.where((c) => c.$1 == 'update').single.$2['patch'] as Map;
    final members = patch['members'] as List;
    expect((members[0] as Map)['role'], 'Penguji');
    expect((members[0] as Map)['tools'], contains('web'));
    expect(patch['process'], 'hierarchical');
    expect(patch['manager'], 'm1');
    await tester.scrollUntilVisible(find.byKey(const ValueKey('crew-legacy-office')), 300, scrollable: visibleList());
    expect(find.byKey(const ValueKey('crew-legacy-office')), findsOneWidget);
  });

  testWidgets('history opens a finished crew with its result', (tester) async {
    final fake = FakeCrew()
      ..list = [
        {'id': 'c1', 'title': 'Bug login', 'status': 'done', 'template': 'coding', 'done': 1, 'tasks': 1},
      ];
    await pump(tester, controller(fake));
    await tester.tap(find.byKey(const ValueKey('crew-history-c1')));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.byKey(const ValueKey('crew-result')), 300, scrollable: visibleList());
    expect(find.text('Semua tes lulus'), findsOneWidget);
  });

  test('pixel frames match the desktop generator and poses/layout mirror it', () {
    for (final set in crewFrames.values) {
      expect(set.every((f) => f.length == 21 && f.every((r) => r.length == 12)), isTrue);
    }
    expect(crewPalettes, hasLength(10));
    expect(crewFrameRows('type', 0), isNot(crewFrameRows('type', 2)));
    expect(crewFrameRows('walk', 0), isNot(crewFrameRows('walk', 2)));
    expect(crewFrameRows('idle', 23)[4], isNot(contains('e')));
    expect(crewFrameRows('idle', 0)[4], contains('e'));
    expect(
      [
        crewPose('working', 'running'),
        crewPose('reviewing'),
        crewPose('waiting'),
        crewPose('done'),
        crewPose('error'),
        crewPose('idle', 'running'),
        crewPose('idle'),
        crewPose('working', 'proposed'),
      ],
      ['type', 'walk', 'wait', 'cheer', 'slump', 'walk', 'idle', 'think'],
    );
    final phone = crewLayout(360, 3);
    expect((phone.scale, phone.width, phone.cols, phone.floors), (3, 120, 2, 2));
    final desk = crewLayout(644, 5);
    expect((desk.scale, desk.cols, desk.floors), (3, 4, 2));
    expect(crewLayout(1200, 4).scale, 4);
    expect(enStrings.containsKey('Gedung crew: tiap anggota di mejanya'), isTrue);
  });

  test('models parse the core payload; English strings exist', () {
    final c = Crew.fromJson(crewJson(status: 'running'));
    expect((c.running, c.members.length), (true, 2));
    expect(c.member('m2')!.tools, ['files', 'write', 'shell']);
    expect(c.sideEffects, ['shell', 'write']);
    expect(c.tasks.single.memberId, 'm2');
    for (final s in [
      'Crew',
      'Lanjutan',
      'Susun crew',
      'Setujui & mulai',
      'Kenalan dengan Crew',
      'Hanya model gratis',
      ...crewTemplateLabel.values,
      ...crewToolLabel.values,
      ...crewMemberStatusLabel.values,
      ...crewStatusLabel.values,
    ]) {
      expect(enStrings.containsKey(s), isTrue, reason: s);
    }
  });
}
