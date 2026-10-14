// Kantor → Perusahaan on the phone: org chart, tickets, approvals, costs, all
// through a fake `company.*` API (the PC core answers the same in production).
import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:neovarch_agent/data/gateway_client.dart' show RpcError;
import 'package:neovarch_agent/remote/appearance.dart';
import 'package:neovarch_agent/remote/company_models.dart';
import 'package:neovarch_agent/remote/remote_controller.dart';
import 'package:neovarch_agent/remote/remote_gateway.dart' show RemoteStatus;
import 'package:neovarch_agent/remote/saved_desktops.dart';
import 'package:neovarch_agent/remote/ui/remote_app.dart' show PaletteScope, themeFor;
import 'package:neovarch_agent/remote/ui/remote_company_screen.dart';
import 'package:neovarch_agent/remote/ui/remote_kantor_tab.dart';
import 'package:neovarch_agent/state/app_controller.dart' show settingsProvider;
import 'package:neovarch_agent/state/settings_controller.dart';
import 'package:neovarch_agent/theme/neovarch_mobile_theme.dart';

class FakeCompany implements CompanyApi {
  FakeCompany({this.exists = true});
  bool exists;
  final calls = <(String, Map<String, dynamic>)>[];
  bool extraApprovals = false;

  /// method → error thrown (once per entry in the list, then answers).
  final failures = <String, List<Object>>{};

  Map<String, dynamic> agent(int id, String name, String title, int? reportsTo, {String status = 'idle', Map<String, dynamic>? ticket, String? pause}) => {
        'id': id,
        'name': name,
        'title': title,
        'role': 'pegawai',
        'reports_to': reportsTo,
        'status': status,
        'pause_reason': pause,
        'current_ticket': ticket,
        'budget': {'cents': 0, 'tokens': 1200, 'pct': id == 3 ? 85.0 : null, 'level': id == 3 ? 'warning' : 'ok'},
        'job_description': 'Tugas $name',
        'budget_monthly_cents': id == 3 ? 500 : 0,
        'budget_monthly_tokens': 0,
      };

  @override
  Future<dynamic> companyCall(String method, [Map<String, dynamic> params = const {}]) async {
    calls.add((method, params));
    final f = failures[method];
    if (f != null && f.isNotEmpty) throw f.removeAt(0);
    switch (method) {
      case 'snapshot':
        if (!exists) return {'exists': false};
        return {
          'exists': true,
          'company': {
            'name': 'Neovarch Studio',
            'mission': 'Bikin aplikasi yang membantu orang',
            'autorun': false,
            'require_hire_approval': true,
            'budget_monthly_cents': 2500,
            'budget_monthly_tokens': 0,
          },
          'goals': [
            {'id': 1, 'parent_id': null, 'title': 'Rilis 1.5 stabil', 'description': 'Tanpa crash', 'status': 'active'},
            {'id': 2, 'parent_id': 1, 'title': 'Nol crash di Android', 'description': '', 'status': 'active'},
          ],
          'projects': [
            {'id': 1, 'goal_id': 1, 'name': 'Aplikasi HP', 'description': '', 'status': 'active', 'budget_monthly_cents': 1000},
          ],
          'routines': [
            {'id': 4, 'name': 'Laporan pagi', 'schedule': 'daily 08:00', 'agent_id': 1, 'project_id': null, 'title': 'Laporan pagi', 'description': '', 'enabled': 1, 'next_run_at': 1791000000.0},
          ],
          'pending_approvals': 1,
          'active_agents': [3],
          'agents': [
            agent(3, 'Raka', 'Engineer', 2, ticket: {'key': 'NV-2', 'title': 'Perbaiki crash', 'status': 'in_progress'}),
            agent(1, 'Dimas', 'CEO', null),
            agent(2, 'Hana', 'CTO', 1, status: 'paused', pause: 'budget'),
          ],
          'ticket_counts': {'in_progress': 1, 'todo': 1},
          'budget': {'cents': 12.5, 'tokens': 4000, 'pct': null, 'level': 'ok'},
        };
      case 'ticket.list':
        return {
          'tickets': [
            {'id': 2, 'key': 'NV-2', 'title': 'Perbaiki crash', 'status': 'in_progress', 'assignee_id': 3, 'assignee_name': 'Raka', 'locked': true, 'blocked_by': 0},
            {'id': 3, 'key': 'NV-3', 'title': 'Tulis catatan rilis', 'status': 'todo', 'assignee_id': null, 'assignee_name': null, 'locked': false, 'blocked_by': 1},
          ],
        };
      case 'ticket.get':
        return {
          'id': 3, 'key': 'NV-3', 'title': 'Tulis catatan rilis', 'status': 'todo', 'description': 'Untuk rilis berikutnya',
          'ancestry': [
            {'type': 'goal', 'title': 'Rilis 1.5 stabil'},
            {'type': 'mission', 'title': 'Bikin aplikasi yang membantu orang'},
          ],
          'comments': [
            {'author_type': 'agent', 'author_name': 'Dimas', 'body': 'Sari, tolong kerjakan ini.'},
          ],
          'timeline': [
            {'type': 'event', 'actor_type': 'agent', 'actor_name': 'Dimas', 'summary': 'memindahkan NV-3: Backlog → Akan dikerjakan', 'id': 'a1'},
            {'type': 'comment', 'actor_type': 'agent', 'actor_name': 'Dimas', 'body': 'Sari, tolong kerjakan ini.', 'id': 'c1'},
          ],
        };
      case 'activity':
        final all = [
          {'id': 1, 'actor_name': 'Kamu', 'actor_type': 'user', 'action': 'ticket.created', 'summary': 'membuat NV-3', 'entity': 'ticket', 'entity_id': 3, 'ts': 0},
        ];
        return {'items': params['agent_id'] == null ? all : const []};
      case 'approval.list':
        return {
          'approvals': [
            {'id': 9, 'kind': 'review', 'title': 'Tinjau hasil NV-2', 'status': 'pending', 'agent_name': 'Raka', 'payload': {'summary': 'Crash sudah hilang'}},
            if (extraApprovals) ...[
              {
                'id': 10, 'kind': 'strategy', 'title': 'Strategi CEO: Rilis bertahap', 'status': 'pending', 'agent_name': 'Dimas',
                'payload': {
                  'plan': 'Teknik dulu, lalu materi rilis.',
                  'tickets': [
                    {'title': 'Rancang arsitektur', 'assignee': 'Hana'},
                    {'title': 'Cari desainer', 'assignee': null},
                  ],
                },
              },
              {'id': 11, 'kind': 'budget', 'title': 'Naikkan anggaran Raka dan lanjutkan', 'status': 'pending', 'agent_name': 'Raka', 'payload': {'extra_tokens': 50000, 'extra_cents': 0}},
            ],
          ],
        };
      case 'costs':
        return {
          'month': '2026-10',
          'total': {'cents': 12.5, 'tokens': 4000, 'pct': 50.0, 'level': 'ok'},
          'by_agent': [
            {'id': 3, 'name': 'Raka', 'cents': 10.0, 'tokens': 3000, 'pct': 85.0},
            {'id': 1, 'name': 'Dimas', 'cents': 2.5, 'tokens': 1000, 'pct': null},
          ],
        };
      case 'seed_demo':
        exists = true;
        return {'exists': true};
      case 'agent.save':
        final id = params['id'] as int?;
        return agent(id ?? 7, '${params['name'] ?? 'X'}', '${params['title'] ?? ''}', params['reports_to'] as int?,
            status: id == null ? 'pending_approval' : 'idle');
      default:
        return {'ok': true};
    }
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
  });

  RemoteController controller(FakeCompany fake) {
    final desktops = SavedDesktops(prefs)..load();
    return RemoteController(desktops)
      ..desktop = desktops.items.first
      ..status = RemoteStatus.connected
      ..debugApprovals = []
      ..debugCompanyApi = fake;
  }

  Future<void> pump(WidgetTester tester, RemoteController r, {int segment = companySegOrg}) async {
    tester.view.physicalSize = const Size(1170, 2532);
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
        builder: (context, child) => PaletteScope(revision: look.revision, child: child!),
        home: RemoteCompanyScreen(initialSegment: segment),
      ),
    ));
    await tester.pumpAndSettle();
  }

  bool called(FakeCompany f, String method, [Map<String, dynamic>? params]) =>
      f.calls.any((c) => c.$1 == method && (params == null || params.entries.every((e) => c.$2[e.key] == e.value)));

  testWidgets('no company yet: the Kantor is empty, with no sample staff to create', (tester) async {
    final fake = FakeCompany(exists: false);
    await pump(tester, controller(fake));
    expect(find.text('Kantor masih kosong'), findsOneWidget);
    expect(find.byKey(const ValueKey('company-seed')), findsNothing);
    expect(called(fake, 'seed_demo'), isFalse);
  });

  testWidgets('org chart: managers first, indented reports, live status and controls', (tester) async {
    final fake = FakeCompany();
    await pump(tester, controller(fake));
    expect(find.text('Neovarch Studio'), findsOneWidget);
    final dimas = tester.getTopLeft(find.descendant(of: find.byKey(const ValueKey('company-agent-1')), matching: find.byType(Material)).first);
    final hana = tester.getTopLeft(find.descendant(of: find.byKey(const ValueKey('company-agent-2')), matching: find.byType(Material)).first);
    final raka = tester.getTopLeft(find.descendant(of: find.byKey(const ValueKey('company-agent-3')), matching: find.byType(Material)).first);
    expect(dimas.dy < hana.dy && hana.dy < raka.dy, isTrue);
    expect(dimas.dx < hana.dx && hana.dx < raka.dx, isTrue);
    expect(find.text('bekerja'), findsOneWidget); // Raka is running on the PC
    expect(find.text('dijeda · anggaran'), findsOneWidget);
    expect(find.textContaining('NV-2 · Perbaiki crash'), findsOneWidget);
    expect(find.text('85%'), findsOneWidget);
    // Dimas: wake; Hana: resume; Raka: stop
    await tester.tap(find.descendant(of: find.byKey(const ValueKey('company-agent-1')), matching: find.text('Bangunkan')));
    await tester.pumpAndSettle();
    expect(called(fake, 'agent.wake', {'id': 1}), isTrue);
    await tester.tap(find.descendant(of: find.byKey(const ValueKey('company-agent-2')), matching: find.text('Lanjutkan')));
    await tester.pumpAndSettle();
    expect(called(fake, 'agent.resume', {'id': 2}), isTrue);
    await tester.ensureVisible(find.byKey(const ValueKey('company-agent-3')));
    await tester.pumpAndSettle();
    await tester.tap(find.descendant(of: find.byKey(const ValueKey('company-agent-3')), matching: find.text('Hentikan')));
    await tester.pumpAndSettle();
    expect(called(fake, 'agent.stop', {'id': 3}), isTrue);
  });

  testWidgets('heartbeat switch goes to company.heartbeat (pause / resume)', (tester) async {
    final fake = FakeCompany();
    await pump(tester, controller(fake));
    expect(find.text('Heartbeat dijeda'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('company-autorun')));
    await tester.pumpAndSettle();
    expect(called(fake, 'heartbeat', {'on': true}), isTrue);
  });

  testWidgets('feed: reads the activity log, live rows land on top, filter by employee', (tester) async {
    final fake = FakeCompany();
    final r = controller(fake);
    await pump(tester, r, segment: companySegFeed);
    expect(find.textContaining('membuat NV-3', findRichText: true), findsOneWidget);
    r.companyFeed = mergeFeed(r.companyFeed, [
      const CompanyActivity(id: 50, actor: 'Raka', actorType: 'agent', actorId: 3, action: 'run.started', summary: 'mulai bekerja di NV-2', ts: 0),
    ]);
    r.notifyListeners(); // ignore: invalid_use_of_protected_member, invalid_use_of_visible_for_testing_member
    await tester.pumpAndSettle();
    final live = tester.getTopLeft(find.byKey(const ValueKey('company-feed-50')));
    final old = tester.getTopLeft(find.byKey(const ValueKey('company-feed-1')));
    expect(live.dy < old.dy, isTrue);
    await tester.tap(find.byKey(const ValueKey('company-feed-agent')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Dimas').last);
    await tester.pumpAndSettle();
    expect(called(fake, 'activity', {'agent_id': 1}), isTrue);
    expect(find.textContaining('mulai bekerja di NV-2', findRichText: true), findsNothing); // Raka's row is not Dimas's
  });

  testWidgets('approvals: CEO strategy lists its tickets, budget shows the raise, revise from the phone', (tester) async {
    final fake = FakeCompany()..extraApprovals = true;
    await pump(tester, controller(fake), segment: companySegApprovals);
    expect(find.text('Strategi CEO: Rilis bertahap'), findsOneWidget);
    expect(find.text('• Rancang arsitektur → Hana'), findsOneWidget);
    expect(find.text('• Cari desainer → belum ada penanggung jawab'), findsOneWidget);
    await tester.ensureVisible(find.byKey(const ValueKey('company-revise-10')));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.textContaining('50.0 rb token'), 200, scrollable: find.byType(Scrollable).first);
    expect(find.textContaining('50.0 rb token'), findsOneWidget);
    expect(find.byKey(const ValueKey('company-revise-11')), findsNothing); // budget: no revise
    await tester.ensureVisible(find.byKey(const ValueKey('company-revise-10')));
    await tester.tap(find.byKey(const ValueKey('company-revise-10')));
    await tester.pumpAndSettle();
    expect(called(fake, 'approval.decide', {'id': 10, 'decision': 'revise'}), isTrue);
  });

  testWidgets('tickets grouped by status; sheet shows the why and moves / comments', (tester) async {
    final fake = FakeCompany();
    await pump(tester, controller(fake), segment: companySegTickets);
    expect(find.text('DIKERJAKAN'), findsOneWidget);
    expect(find.text('AKAN DIKERJAKAN'), findsOneWidget);
    expect(find.textContaining('Raka · dikerjakan'), findsOneWidget);
    expect(find.textContaining('1 hambatan'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('company-ticket-NV-3')));
    await tester.pumpAndSettle();
    expect(find.textContaining('Kenapa: Rilis 1.5 stabil → Bikin aplikasi'), findsOneWidget);
    expect(find.textContaining('Sari, tolong kerjakan ini.'), findsOneWidget);
    expect(find.text('· Dimas memindahkan NV-3: Backlog → Akan dikerjakan'), findsOneWidget); // audit line in the thread
    await tester.tap(find.byKey(const ValueKey('company-move-blocked')));
    await tester.pumpAndSettle();
    expect(called(fake, 'ticket.move', {'id': 3, 'status': 'blocked'}), isTrue);
    await tester.enterText(find.byKey(const ValueKey('company-comment')), 'Pakai nada santai');
    await tester.tap(find.byTooltip('Kirim'));
    await tester.pumpAndSettle();
    expect(called(fake, 'ticket.comment', {'id': 3, 'body': 'Pakai nada santai'}), isTrue);
  });

  testWidgets('new ticket from the phone', (tester) async {
    final fake = FakeCompany();
    await pump(tester, controller(fake), segment: companySegTickets);
    await tester.tap(find.byKey(const ValueKey('company-new-ticket')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('company-ticket-title')), 'Riset kompetitor');
    await tester.tap(find.byKey(const ValueKey('company-ticket-create')));
    await tester.pumpAndSettle();
    expect(called(fake, 'ticket.save', {'title': 'Riset kompetitor'}), isTrue);
  });

  testWidgets('approvals: approve and reject remotely', (tester) async {
    final fake = FakeCompany();
    await pump(tester, controller(fake), segment: companySegApprovals);
    expect(find.text('Tinjau hasil NV-2'), findsOneWidget);
    expect(find.text('Crash sudah hilang'), findsOneWidget);
    await tester.tap(find.text('Setujui'));
    await tester.pumpAndSettle();
    expect(called(fake, 'approval.decide', {'id': 9, 'decision': 'approve'}), isTrue);
    await tester.tap(find.text('Tolak'));
    await tester.pumpAndSettle();
    expect(called(fake, 'approval.decide', {'id': 9, 'decision': 'reject'}), isTrue);
  });

  testWidgets('costs per agent with budget meters', (tester) async {
    final fake = FakeCompany();
    await pump(tester, controller(fake), segment: companySegCosts);
    expect(find.textContaining(r'$0.13 · 4.0 rb token'), findsOneWidget);
    expect(find.textContaining('3.0 rb token'), findsOneWidget);
    expect(find.text('85%'), findsOneWidget);
    expect(find.text('50%'), findsOneWidget);
  });

  testWidgets('company.changed push re-reads the snapshot', (tester) async {
    final fake = FakeCompany();
    final r = controller(fake);
    await pump(tester, r);
    final before = fake.calls.where((c) => c.$1 == 'snapshot').length;
    r.companyRevision++;
    r.notifyListeners(); // ignore: invalid_use_of_protected_member, invalid_use_of_visible_for_testing_member
    await tester.pumpAndSettle();
    expect(fake.calls.where((c) => c.$1 == 'snapshot').length, before + 1);
  });

  test('models parse the core JSON and build the org tree', () async {
    final s = CompanySnapshot.fromJson(Map<String, dynamic>.from(await FakeCompany().companyCall('snapshot') as Map));
    expect(s.orgTree.map((e) => '${e.$1.name}:${e.$2}').toList(), ['Dimas:0', 'Hana:1', 'Raka:2']);
    expect(s.isRunning(s.agents.firstWhere((a) => a.name == 'Raka')), isTrue);
    expect(const CompanySnapshot(exists: false).orgTree, isEmpty);
    expect(formatCents(0.25), r'$0.0025');
    expect(formatTokens(1500000), '1.5 jt token');
  });

  // ------------------------------------------------------------ 1.4.5 gaps --
  Finder scrollable() => find.descendant(of: find.byKey(const ValueKey('company-list')), matching: find.byType(Scrollable)).first;

  Future<void> tapKey(WidgetTester tester, Key key) async {
    await tester.ensureVisible(find.byKey(key));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(key));
    await tester.pumpAndSettle();
  }

  Future<void> showInList(WidgetTester tester, Key key) async {
    await tester.scrollUntilVisible(find.byKey(key), 200, scrollable: scrollable());
    await tester.pumpAndSettle();
  }

  testWidgets('hire from the phone: agent.save without id, hire approval toast', (tester) async {
    final fake = FakeCompany();
    await pump(tester, controller(fake));
    await tapKey(tester, const ValueKey('company-hire'));
    expect(find.text('Rekrut pegawai'), findsOneWidget);
    expect(find.textContaining('Rekrutmen perlu persetujuan'), findsOneWidget);
    await tester.enterText(find.byKey(const ValueKey('company-agent-name')), 'Sari');
    await tester.enterText(find.byKey(const ValueKey('company-agent-title')), 'Penulis');
    await tester.tap(find.byKey(const ValueKey('company-agent-manager')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Dimas · CEO').last);
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('company-budget-cents')), '5');
    await tester.enterText(find.byKey(const ValueKey('company-budget-tokens')), '200000');
    await tapKey(tester, const ValueKey('company-agent-save'));
    expect(called(fake, 'agent.save', {'name': 'Sari', 'title': 'Penulis', 'reports_to': 1, 'budget_monthly_cents': 500, 'budget_monthly_tokens': 200000}), isTrue);
    expect(fake.calls.firstWhere((c) => c.$1 == 'agent.save').$2.containsKey('id'), isFalse);
    expect(find.textContaining('menunggu persetujuan di Setujui'), findsOneWidget);
  });

  testWidgets('hire needs a name', (tester) async {
    final fake = FakeCompany();
    await pump(tester, controller(fake));
    await tapKey(tester, const ValueKey('company-hire'));
    await tapKey(tester, const ValueKey('company-agent-save'));
    expect(find.text('Nama pegawai wajib diisi'), findsOneWidget);
    expect(called(fake, 'agent.save'), isFalse);
  });

  testWidgets('edit an agent: manager list excludes itself and its reports; terminate asks first', (tester) async {
    final fake = FakeCompany();
    await pump(tester, controller(fake));
    await tapKey(tester, const ValueKey('company-edit-agent-2')); // Hana (CTO), Raka reports to her
    expect(find.text('Ubah Hana'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('company-agent-manager')));
    await tester.pumpAndSettle();
    expect(find.text('Raka · Engineer'), findsNothing);
    expect(find.text('Hana · CTO'), findsNothing);
    await tester.tap(find.text('Dimas · CEO').last);
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('company-agent-job')), 'Pimpin tim teknik');
    await tapKey(tester, const ValueKey('company-agent-save'));
    expect(called(fake, 'agent.save', {'id': 2, 'job_description': 'Pimpin tim teknik', 'reports_to': 1}), isTrue);

    await tapKey(tester, const ValueKey('company-edit-agent-2'));
    await tapKey(tester, const ValueKey('company-agent-terminate'));
    expect(find.text('Berhentikan Hana?'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('company-confirm')));
    await tester.pumpAndSettle();
    expect(called(fake, 'agent.terminate', {'id': 2}), isTrue);
  });

  testWidgets('budgets: per agent from Biaya (dollars → cents) and for the company', (tester) async {
    final fake = FakeCompany();
    await pump(tester, controller(fake), segment: companySegCosts);
    expect(find.textContaining(r'batas $25.00'), findsOneWidget);
    expect(find.textContaining(r'batas $5.00'), findsOneWidget); // Raka
    await tapKey(tester, const ValueKey('company-cost-Raka'));
    expect(find.text('Anggaran Raka'), findsOneWidget);
    await tester.enterText(find.byKey(const ValueKey('company-budget-cents')), '2,5');
    await tapKey(tester, const ValueKey('company-budget-save'));
    expect(called(fake, 'agent.save', {'id': 3, 'budget_monthly_cents': 250, 'budget_monthly_tokens': 0}), isTrue);

    await tapKey(tester, const ValueKey('company-budget-company'));
    await tester.enterText(find.byKey(const ValueKey('company-budget-cents')), '');
    await tester.enterText(find.byKey(const ValueKey('company-budget-tokens')), '1.000.000');
    await tapKey(tester, const ValueKey('company-budget-save'));
    expect(called(fake, 'update', {'budget_monthly_cents': 0, 'budget_monthly_tokens': 1000000}), isTrue);
  });

  testWidgets('Rencana: mission, goal tree, new / edit / delete goal', (tester) async {
    final fake = FakeCompany();
    await pump(tester, controller(fake), segment: companySegPlan);
    final g1 = tester.getTopLeft(find.descendant(of: find.byKey(const ValueKey('company-goal-1')), matching: find.byType(Material)).first);
    final g2 = tester.getTopLeft(find.descendant(of: find.byKey(const ValueKey('company-goal-2')), matching: find.byType(Material)).first);
    expect(g1.dy < g2.dy && g1.dx < g2.dx, isTrue);
    expect(find.text('▸ Aplikasi HP'), findsOneWidget);

    await tapKey(tester, const ValueKey('company-edit-mission'));
    await tester.enterText(find.byKey(const ValueKey('company-mission')), 'Misi baru');
    await tapKey(tester, const ValueKey('company-mission-save'));
    expect(called(fake, 'update', {'name': 'Neovarch Studio', 'mission': 'Misi baru'}), isTrue);

    await tapKey(tester, const ValueKey('company-new-goal'));
    await tester.enterText(find.byKey(const ValueKey('company-goal-title')), 'Pengguna senang');
    await tapKey(tester, const ValueKey('company-goal-save'));
    expect(called(fake, 'goal.save', {'title': 'Pengguna senang'}), isTrue);
    expect(fake.calls.lastWhere((c) => c.$1 == 'goal.save').$2.containsKey('id'), isFalse);

    await tapKey(tester, const ValueKey('company-goal-2'));
    await tester.tap(find.byKey(const ValueKey('company-goal-parent')));
    await tester.pumpAndSettle();
    expect(find.widgetWithText(DropdownMenuItem<int?>, 'Nol crash di Android'), findsNothing); // not its own parent
    expect(find.widgetWithText(DropdownMenuItem<int?>, 'Rilis 1.5 stabil'), findsWidgets);
    await tester.tap(find.text('Langsung di bawah misi').last);
    await tester.pumpAndSettle();
    await tapKey(tester, const ValueKey('company-goal-save'));
    expect(called(fake, 'goal.save', {'id': 2, 'parent_id': null, 'status': 'active'}), isTrue, reason: '${fake.calls.where((c) => c.$1.startsWith('goal'))}');

    await tapKey(tester, const ValueKey('company-goal-1'));
    await tapKey(tester, const ValueKey('company-goal-delete'));
    await tester.tap(find.byKey(const ValueKey('company-confirm')));
    await tester.pumpAndSettle();
    expect(called(fake, 'goal.delete', {'id': 1}), isTrue);
  });

  testWidgets('Rencana: projects with goal and budget', (tester) async {
    final fake = FakeCompany();
    await pump(tester, controller(fake), segment: companySegPlan);
    await showInList(tester, const ValueKey('company-new-project'));
    await tapKey(tester, const ValueKey('company-new-project'));
    await tester.enterText(find.byKey(const ValueKey('company-project-name')), 'Situs web');
    await tester.enterText(find.byKey(const ValueKey('company-project-budget')), '12');
    await tapKey(tester, const ValueKey('company-project-save'));
    expect(called(fake, 'project.save', {'name': 'Situs web', 'budget_monthly_cents': 1200}), isTrue);

    await showInList(tester, const ValueKey('company-project-1'));
    expect(find.textContaining(r'tujuan: Rilis 1.5 stabil · anggaran $10.00/bln'), findsOneWidget);
    await tapKey(tester, const ValueKey('company-project-1'));
    await tester.enterText(find.byKey(const ValueKey('company-project-name')), 'Aplikasi Android');
    await tapKey(tester, const ValueKey('company-project-save'));
    expect(called(fake, 'project.save', {'id': 1, 'name': 'Aplikasi Android', 'goal_id': 1, 'budget_monthly_cents': 1000}), isTrue);
  });

  testWidgets('Rencana: routines — create, toggle, run now, delete', (tester) async {
    final fake = FakeCompany();
    await pump(tester, controller(fake), segment: companySegPlan);
    await showInList(tester, const ValueKey('company-routine-4'));
    expect(find.textContaining('daily 08:00 · berikutnya'), findsOneWidget);
    expect(find.textContaining('· Dimas'), findsOneWidget);

    await tapKey(tester, const ValueKey('company-routine-enabled-4'));
    expect(called(fake, 'routine.save', {'id': 4, 'enabled': false}), isTrue);
    await showInList(tester, const ValueKey('company-routine-run-4'));
    await tapKey(tester, const ValueKey('company-routine-run-4'));
    expect(called(fake, 'routine.trigger', {'id': 4}), isTrue);

    await showInList(tester, const ValueKey('company-new-routine'));
    await tapKey(tester, const ValueKey('company-new-routine'));
    await tester.enterText(find.byKey(const ValueKey('company-routine-name')), 'Cek ulasan');
    await tapKey(tester, const ValueKey('company-routine-save'));
    expect(find.text('Jadwal wajib diisi'), findsOneWidget);
    await tester.enterText(find.byKey(const ValueKey('company-routine-schedule')), 'every 2h');
    await tapKey(tester, const ValueKey('company-routine-save'));
    expect(called(fake, 'routine.save', {'name': 'Cek ulasan', 'schedule': 'every 2h', 'title': 'Cek ulasan', 'enabled': true}), isTrue);

    await showInList(tester, const ValueKey('company-routine-4'));
    await tapKey(tester, const ValueKey('company-routine-4'));
    await tapKey(tester, const ValueKey('company-routine-delete'));
    await tester.tap(find.byKey(const ValueKey('company-confirm')));
    await tester.pumpAndSettle();
    expect(called(fake, 'routine.delete', {'id': 4}), isTrue);
  });

  testWidgets('PC offline: Indonesian notice with Coba lagi; loads once it connects', (tester) async {
    final fake = FakeCompany();
    final r = controller(fake)..status = RemoteStatus.disconnected;
    await pump(tester, r);
    expect(find.text('PC tidak terhubung'), findsOneWidget);
    expect(find.byKey(const ValueKey('company-retry')), findsOneWidget);
    expect(called(fake, 'snapshot'), isFalse);
    r.status = RemoteStatus.connected;
    r.notifyListeners(); // ignore: invalid_use_of_protected_member, invalid_use_of_visible_for_testing_member
    await tester.pumpAndSettle();
    expect(find.text('Neovarch Studio'), findsOneWidget);
    // dropping again keeps the last data with a stale notice
    r.status = RemoteStatus.reconnecting;
    r.notifyListeners(); // ignore: invalid_use_of_protected_member, invalid_use_of_visible_for_testing_member
    await tester.pumpAndSettle();
    expect(find.textContaining('Terputus dari PC'), findsOneWidget);
    expect(find.text('Neovarch Studio'), findsOneWidget);
  });

  testWidgets('older core without company.*: "Belum didukung PC" and the Kantor segment hides', (tester) async {
    final fake = FakeCompany()
      ..failures['snapshot'] = [
        const RpcError(-32601, 'method not implemented in the Neovarch core: company.snapshot'),
        const RpcError(-32601, 'method not implemented in the Neovarch core: company.snapshot'),
      ];
    final r = controller(fake);
    await pump(tester, r);
    expect(find.text('Belum didukung PC'), findsOneWidget);
    expect(find.textContaining('Perbarui Neovarch di PC'), findsOneWidget);
    await r.probeCompany();
    expect(r.companySupported, isFalse);
    // Coba lagi: the PC was updated meanwhile
    await tester.tap(find.byKey(const ValueKey('company-retry')));
    await tester.pumpAndSettle();
    expect(find.text('Neovarch Studio'), findsOneWidget);
  });

  testWidgets('network error then Coba lagi recovers', (tester) async {
    final fake = FakeCompany()..failures['snapshot'] = [TimeoutException('timed out')];
    await pump(tester, controller(fake));
    expect(find.text('Gagal memuat perusahaan'), findsOneWidget);
    expect(find.textContaining('PC tidak menjawab'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('company-retry')));
    await tester.pumpAndSettle();
    expect(find.text('Neovarch Studio'), findsOneWidget);
  });

  testWidgets('an action error is toasted in Indonesian and the screen stays', (tester) async {
    final fake = FakeCompany()..failures['agent.wake'] = [const RpcError(-32009, 'Dimas sedang bekerja')];
    await pump(tester, controller(fake));
    await tester.tap(find.descendant(of: find.byKey(const ValueKey('company-agent-1')), matching: find.text('Bangunkan')));
    await tester.pumpAndSettle();
    expect(find.text('Dimas sedang bekerja'), findsOneWidget);
    expect(find.text('Neovarch Studio'), findsOneWidget);
  });

  group('Kantor tab', () {
    Future<void> pumpTab(WidgetTester tester, RemoteController r) async {
      tester.view.physicalSize = const Size(1170, 2532);
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
          builder: (context, child) => PaletteScope(revision: look.revision, child: child!),
          home: Scaffold(body: RemoteKantorTab(segment: kantorSegCompany, onSegment: (_) {}, onOpenChat: () {}, onOpenApprovals: () {})),
        ),
      ));
      await tester.pump(const Duration(milliseconds: 500));
    }

    testWidgets('shows Perusahaan on a core that has it', (tester) async {
      final r = controller(FakeCompany())..companySupported = true;
      await pumpTab(tester, r);
      expect(find.text('PERUSAHAAN'), findsOneWidget);
    });

    testWidgets('hides Perusahaan on an older core and falls back to Kantor', (tester) async {
      final r = controller(FakeCompany())..companySupported = false;
      await pumpTab(tester, r);
      expect(find.text('PERUSAHAAN'), findsNothing);
      expect(find.text('KANTOR'), findsOneWidget);
      expect(find.text('TUGAS'), findsOneWidget);
      expect(find.byType(RemoteCompanyScreen), findsNothing);
    });
  });

  test('Paperclip pass models: feed merge/filter, timeline, strategy + budget approvals', () {
    const a1 = CompanyActivity(id: 1, actor: 'Kamu', summary: 'x');
    const a2 = CompanyActivity(id: 2, actor: 'Raka', actorType: 'agent', actorId: 3, summary: 'y');
    expect(mergeFeed([a1], [a2, a1]).map((a) => a.id).toList(), [2, 1]);
    expect(mergeFeed([a1], [a2], cap: 1).map((a) => a.id).toList(), [2]);
    expect(a2.involves(3), isTrue);
    expect(a2.involves(1), isFalse);
    expect(a1.involves(null), isTrue);
    expect(const CompanyActivity(id: 3, actor: 'S', summary: 'z', entity: 'agent', entityId: 1).involves(1), isTrue);
    final row = CompanyActivity.fromJson({'id': 7, 'actor_name': 'Hana', 'actor_type': 'agent', 'actor_id': 2, 'summary': 's', 'ts': 5});
    expect((row.id, row.actorId, row.ts), (7, 2, 5.0));
    final d = TicketDetail.fromJson({
      'id': 1, 'key': 'NV-1', 'title': 't', 'status': 'todo',
      'timeline': [
        {'type': 'run', 'actor_name': 'Dimas', 'summary': 'heartbeat #1', 'actor_type': 'agent'},
        {'type': 'comment', 'actor_name': 'Kamu', 'body': 'ok', 'actor_type': 'user'},
      ],
    });
    expect(d.timeline.map((e) => '${e.type}:${e.text}:${e.fromUser}').toList(), ['run:heartbeat #1:false', 'comment:ok:true']);
    final st = CompanyApproval.fromJson({
      'id': 1, 'kind': 'strategy', 'title': 'S',
      'payload': {'tickets': [{'title': 'A', 'assignee': 'Hana'}, {'title': ''}, 'junk']},
    });
    expect(st.tickets, ['A → Hana']);
    expect((st.canRevise, st.kindLabel), (true, 'strategi CEO'));
    final b = CompanyApproval.fromJson({'id': 2, 'kind': 'budget', 'title': 'B', 'payload': {'extra_tokens': 100, 'extra_cents': 250}});
    expect((b.extraTokens, b.extraCents, b.canRevise), (100, 250.0, false));
  });

  test('1.4.5 models: goal tree, routines, money input', () async {
    final s = CompanySnapshot.fromJson(Map<String, dynamic>.from(await FakeCompany().companyCall('snapshot') as Map));
    expect(s.goalTree.map((e) => '${e.$1.title}:${e.$2}').toList(), ['Rilis 1.5 stabil:0', 'Nol crash di Android:1']);
    expect(s.requireHireApproval, isTrue);
    expect(s.budgetMonthlyCents, 2500);
    expect(s.routines.single.enabled, isTrue);
    expect(s.routines.single.agentId, 1);
    expect(s.agentName(1), 'Dimas');
    expect(s.agents.firstWhere((a) => a.id == 3).budgetMonthlyCents, 500);
    expect(dollarsToCents('2,5'), 250);
    expect(dollarsToCents(r'$12'), 1200);
    expect(dollarsToCents(''), 0);
    expect(dollarsToCents('-3'), 0);
    expect(centsToDollars(250), '2.50');
    expect(centsToDollars(1200), '12');
    expect(centsToDollars(0), '');
    expect(isCompanyUnsupported(const RpcError(-32601, 'x')), isTrue);
    expect(isCompanyUnsupported(const RpcError(-32004, 'Pegawai tidak ditemukan')), isFalse);
    expect(companyErrorText(const RpcError(-32004, 'Pegawai tidak ditemukan')), 'Pegawai tidak ditemukan');
    expect(companyErrorText(const RpcError(-32601, 'x')), contains('Perbarui Neovarch di PC'));
  });
}

