// v1.4.7: a PC restart asked from the phone (or announced by the core with
// `core.restarting`) shows "PC sedang restart… menyambung ulang", keeps
// retrying, never shows a connection error, and reopens the chat when back.
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:neovarch_agent/data/gateway_client.dart';
import 'package:neovarch_agent/remote/remote_controller.dart';
import 'package:neovarch_agent/remote/remote_gateway.dart';
import 'package:neovarch_agent/remote/saved_desktops.dart';

class _Gw extends RemoteGateway {
  _Gw()
      : super(
            baseUrl: 'http://192.168.1.20:9319',
            token: 'tok',
            autoReconnect: false,
            httpClient: MockClient((_) async => http.Response('{}', 404)));
  int reconnects = 0;
  final resumed = <String>[];
  @override
  Future<void> reconnect() async => reconnects++;
  @override
  Future<OpenedSession> resume(String storedId) async {
    resumed.add(storedId);
    return OpenedSession(storedId: storedId, runtimeId: 'rt-2', title: 'halo', messages: const []);
  }
}

void main() {
  late SharedPreferences prefs;
  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    prefs = await SharedPreferences.getInstance();
  });

  testWidgets('core.restarting → friendly status, steady retries, no error, chat reopened when back', (tester) async {
      final g = _Gw();
      final r = RemoteController(SavedDesktops(prefs)..load())
        ..gateway = g
        ..status = RemoteStatus.connected
        ..storedId = 's-1'
        ..runtimeId = 'rt-1';
      r.debugEvent(const GatewayEventFrame('core.restarting', null, {'port': 9319}));
      expect(r.pcRestarting, isTrue);
      r.debugStatus(RemoteStatus.reconnecting);
      expect(r.statusLabel, 'PC sedang restart… menyambung ulang');
      r.debugStatus(RemoteStatus.failed);
      expect(r.error, isNull); // no "gagal terhubung" while it restarts
      await tester.pump(const Duration(seconds: 7));
      expect(g.reconnects, greaterThanOrEqualTo(3));
      r.debugStatus(RemoteStatus.connected);
      await tester.pump();
      expect(r.pcRestarting, isFalse);
      expect(r.statusLabel, 'terhubung');
      expect(g.resumed, ['s-1']);
      final n = g.reconnects;
      await tester.pump(const Duration(seconds: 10));
      expect(g.reconnects, n); // retries stop once back
      r.dispose();
  });

  testWidgets('a PC that never comes back ends with a clear message after the window', (tester) async {
      final g = _Gw();
      final r = RemoteController(SavedDesktops(prefs)..load())
        ..gateway = g
        ..status = RemoteStatus.connected;
      r.notePcRestarting();
      r.debugStatus(RemoteStatus.reconnecting);
      await tester.pump(RemoteController.kRestartWindow + const Duration(seconds: 5));
      expect(r.pcRestarting, isFalse);
      expect(r.error, contains('PC belum kembali'));
      r.dispose();
  });
}
