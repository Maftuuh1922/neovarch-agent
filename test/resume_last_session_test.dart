// v1.4.7: closing and reopening the app reopens the last chat on that PC (not
// an empty new chat); a new chat only comes from "+"; a turn still running on
// the PC comes back as running.
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:neovarch_agent/data/gateway_client.dart';
import 'package:neovarch_agent/models/models.dart' show ChatMsg;
import 'package:neovarch_agent/remote/remote_controller.dart';
import 'package:neovarch_agent/remote/remote_gateway.dart';
import 'package:neovarch_agent/remote/saved_desktops.dart';

class _Gw extends RemoteGateway {
  _Gw({this.running = false, this.missing = false})
      : super(
            baseUrl: 'http://192.168.1.20:9319',
            token: 'tok',
            autoReconnect: false,
            httpClient: MockClient((_) async => http.Response('{}', 404)));
  final bool running;
  final bool missing;
  final resumed = <String>[];
  int created = 0;
  @override
  Future<OpenedSession> resume(String storedId) async {
    resumed.add(storedId);
    if (missing) throw const RpcError(-32004, 'session not found');
    return OpenedSession(
        storedId: storedId,
        runtimeId: 'rt-$storedId',
        title: 'halo',
        running: running,
        messages: [ChatMsg(id: 'u1', role: 'user', content: 'cek build', ts: 1)]);
  }

  @override
  Future<OpenedSession> create() async {
    created++;
    return OpenedSession(storedId: 's-new$created', runtimeId: 'rt-new$created', title: '', messages: const []);
  }
}

SavedDesktop _pc() => SavedDesktop(id: 'pc_1', name: 'PC Kantor', url: 'http://192.168.1.20:9319', addedAt: DateTime(2026, 10, 12));

void main() {
  late SharedPreferences prefs;
  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    prefs = await SharedPreferences.getInstance();
  });

  RemoteController controller(_Gw g, SavedDesktops d) => RemoteController(d)
    ..gateway = g
    ..desktop = _pc();

  test('opening or creating a chat remembers it per PC', () async {
    final d = SavedDesktops(prefs)..load();
    final g = _Gw();
    final r = controller(g, d)..status = RemoteStatus.connected;
    await r.openSession('s-7');
    expect(d.lastSession('pc_1'), 's-7');
    await r.newChat();
    expect(d.lastSession('pc_1'), 's-new1');
  });

  test('cold start: connecting reopens the last chat, no new chat is made', () async {
    final d = SavedDesktops(prefs)..load();
    d.setLastSession('pc_1', 's-7');
    final g = _Gw();
    final r = controller(g, d);
    r.debugStatus(RemoteStatus.connected);
    await pumpEventQueue();
    expect(g.resumed, ['s-7']);
    expect(g.created, 0);
    expect(r.storedId, 's-7');
    expect(r.runtimeId, 'rt-s-7');
    expect(r.transcript.messages.single.content, 'cek build');
    expect(r.opening, isFalse);
  });

  test('a turn still running on the PC comes back as running', () async {
    final d = SavedDesktops(prefs)..load();
    d.setLastSession('pc_1', 's-7');
    final g = _Gw(running: true);
    final r = controller(g, d);
    r.debugStatus(RemoteStatus.connected);
    await pumpEventQueue();
    expect(r.running, isTrue);
  });

  test('a chat deleted on the PC is forgotten quietly (empty chat, no error)', () async {
    final d = SavedDesktops(prefs)..load();
    d.setLastSession('pc_1', 's-gone');
    final g = _Gw(missing: true);
    final r = controller(g, d);
    r.debugStatus(RemoteStatus.connected);
    await pumpEventQueue();
    expect(r.storedId, isNull);
    expect(r.error, isNull);
    expect(d.lastSession('pc_1'), isNull);
    expect(g.created, 0);
  });

  test('nothing saved: stays empty until "+" or the first message', () async {
    final d = SavedDesktops(prefs)..load();
    final g = _Gw();
    final r = controller(g, d);
    r.debugStatus(RemoteStatus.connected);
    await pumpEventQueue();
    expect(g.resumed, isEmpty);
    expect(g.created, 0);
    expect(r.storedId, isNull);
  });

  test('an open chat is never replaced by the restore (reconnect keeps it)', () async {
    final d = SavedDesktops(prefs)..load();
    d.setLastSession('pc_1', 's-old');
    final g = _Gw();
    final r = controller(g, d)
      ..storedId = 's-open'
      ..runtimeId = 'rt-open';
    await r.restoreLastSession();
    expect(g.resumed, isEmpty);
    expect(r.storedId, 's-open');
  });

  test('saved per PC and cleared when the PC is removed', () async {
    final d = SavedDesktops(prefs)..load();
    d.setLastSession('pc_1', 's-7');
    d.setLastSession('pc_2', 's-9');
    expect(d.lastSession('pc_2'), 's-9');
    await d.remove('pc_1');
    expect(d.lastSession('pc_1'), isNull);
    expect(d.lastSession('pc_2'), 's-9');
  });
}
