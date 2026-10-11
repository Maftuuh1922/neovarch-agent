// PC screen ▸ "Layanan latar": the phone reads the PC's background service
// status, toggles "Jalan di latar" / "Mulai saat login", and stops or restarts
// the agent and the gateway (GET/POST /api/remote/background). No real PC.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:neovarch_agent/remote/pc_background.dart';
import 'package:neovarch_agent/remote/remote_gateway.dart';
import 'package:neovarch_agent/remote/ui/pc_background_panel.dart';
import 'package:neovarch_agent/theme/neovarch_mobile_theme.dart';

Map<String, dynamic> _json({bool run = false, bool login = false, bool attached = true, int running = 1}) => {
      'run_in_background': run,
      'start_at_login': login,
      'updated_at': 1760000000.0,
      'service': {'state': 'running', 'mode': attached ? 'app' : 'background', 'desktop_attached': attached, 'pid': 4242, 'port': 9319, 'uptime_s': 5400},
      'agent': {'sessions': 2, 'running': running},
      'relay': {'enabled': true, 'state': 'online', 'phones': 1, 'error': null},
    };

class _FakeApi implements PcBackgroundApi {
  _FakeApi(this.state);
  Map<String, dynamic> state;
  final sets = <Map<String, bool?>>[];
  final actions = <PcBackgroundAction>[];
  bool missing = false;

  @override
  Future<PcBackgroundStatus> backgroundStatus() async {
    if (missing) throw const RemoteRestError(404, 'fitur ini belum ada');
    return PcBackgroundStatus.fromJson(state);
  }

  @override
  Future<PcBackgroundStatus> setBackground({bool? runInBackground, bool? startAtLogin}) async {
    sets.add({'run': runInBackground, 'login': startAtLogin});
    state = {
      ...state,
      'run_in_background': ?runInBackground,
      'start_at_login': ?startAtLogin,
    };
    return PcBackgroundStatus.fromJson(state);
  }

  @override
  Future<String> backgroundAction(PcBackgroundAction action) async {
    actions.add(action);
    if (action == PcBackgroundAction.stopAgent) state = {...state, 'agent': {'sessions': 2, 'running': 0}};
    return 'OK: ${action.wire}';
  }
}

Future<void> _pump(WidgetTester tester, PcBackgroundApi api) async {
  await tester.pumpWidget(MaterialApp(
    theme: buildNeovarchMobileTheme(),
    home: Scaffold(body: ListView(children: [PcBackgroundPanel(api: api)])),
  ));
  await tester.pumpAndSettle();
}

void main() {
  test('status JSON parses into Indonesian labels', () {
    final st = PcBackgroundStatus.fromJson(_json(run: true));
    expect(st.runInBackground, isTrue);
    expect(st.pid, 4242);
    expect(st.uptimeLabel, '1 jam 30 menit');
    expect(st.serviceLabel, 'Berjalan · tetap jalan saat jendela ditutup');
    expect(PcBackgroundStatus.fromJson(_json(attached: false)).serviceLabel, contains('aplikasi PC tertutup'));
    expect(PcBackgroundStatus.fromJson({..._json(), 'will_stop': true}).serviceLabel, 'Sedang dihentikan');
    expect(PcBackgroundStatus.fromJson(const {}).runInBackground, isFalse);
    expect(PcBackgroundAction.values.map((a) => a.wire), ['stop-agent', 'restart-agent', 'restart-gateway', 'stop-gateway']);
  });

  testWidgets('shows the service status and toggles "Jalan di latar" and "Mulai saat login"', (tester) async {
    final api = _FakeApi(_json());
    await _pump(tester, api);

    expect(find.text('Berjalan · ikut jendela aplikasi'), findsOneWidget);
    expect(find.textContaining('1/2 agen berjalan'), findsOneWidget);
    expect(find.textContaining('relay online'), findsOneWidget);

    Switch sw(String key) => tester.widget<Switch>(find.descendant(of: find.byKey(ValueKey(key)), matching: find.byType(Switch)));
    expect(sw('pc-bg-run').value, isFalse);

    await tester.tap(find.descendant(of: find.byKey(const ValueKey('pc-bg-run')), matching: find.byType(Switch)));
    await tester.pumpAndSettle();
    expect(api.sets.single, {'run': true, 'login': null});
    expect(sw('pc-bg-run').value, isTrue);
    expect(find.text('Berjalan · tetap jalan saat jendela ditutup'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('pc-bg-login')));
    await tester.pumpAndSettle();
    expect(api.sets.last, {'run': null, 'login': true});
    expect(sw('pc-bg-login').value, isTrue);
  });

  testWidgets('agent stop runs at once; gateway stop asks first', (tester) async {
    final api = _FakeApi(_json(run: true));
    await _pump(tester, api);

    await tester.tap(find.byKey(const ValueKey('pc-bg-stop-agent')));
    await tester.pumpAndSettle();
    expect(api.actions, [PcBackgroundAction.stopAgent]);
    expect(find.text('OK: stop-agent'), findsOneWidget);
    expect(find.textContaining('0/2 agen berjalan'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('pc-bg-stop-gateway')));
    await tester.pumpAndSettle();
    expect(find.text('Hentikan gateway di PC?'), findsOneWidget);
    expect(api.actions.length, 1); // nothing sent before confirming
    await tester.tap(find.text('Hentikan'));
    await tester.pumpAndSettle();
    expect(api.actions.last, PcBackgroundAction.stopGateway);
  });

  testWidgets('an older PC without the endpoint shows an update hint', (tester) async {
    final api = _FakeApi(_json())..missing = true;
    await _pump(tester, api);
    expect(find.textContaining('Perbarui aplikasi Neovarch di PC'), findsOneWidget);
    expect(find.byKey(const ValueKey('pc-bg-run')), findsNothing);
  });
}
