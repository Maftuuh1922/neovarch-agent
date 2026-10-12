// Stop benar-benar berhenti (v1.4.7), phone side: Stop sends session.interrupt to
// the PC (which cancels the model request, the running tool and the commands it
// started), shows "Menghentikan…" until the PC confirms, ends the turn with a plain
// Indonesian "Dihentikan" note + "Lanjutkan" (never the raw word "interrupted"),
// and ends it on screen by itself when the PC does not confirm in time.
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:neovarch_agent/data/gateway_client.dart' show GatewayEventFrame;
import 'package:neovarch_agent/models/models.dart';
import 'package:neovarch_agent/remote/remote_controller.dart';
import 'package:neovarch_agent/remote/remote_gateway.dart';
import 'package:neovarch_agent/remote/remote_transcript.dart';
import 'package:neovarch_agent/remote/saved_desktops.dart';

class _Gw extends RemoteGateway {
  _Gw({this.fail = false}) : super(baseUrl: 'http://192.168.1.20:9319', token: 'tok-123', autoReconnect: false);
  final bool fail;
  final interrupts = <String>[];
  @override
  Future<void> interrupt(String runtimeId) async {
    if (fail) throw StateError('Belum terhubung ke PC.');
    interrupts.add(runtimeId);
  }
}

RemoteTranscript _running() {
  final t = RemoteTranscript(history: [ChatMsg(id: 'u1', role: 'user', content: 'jalankan tes', ts: 1)]);
  t.apply(const GatewayEventFrame('message.start', 'rt-1', {}));
  t.apply(const GatewayEventFrame('message.delta', 'rt-1', {'text': 'Menjalankan pytest'}));
  return t;
}

void main() {
  late SharedPreferences prefs;
  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    prefs = await SharedPreferences.getInstance();
  });

  RemoteController controller(_Gw g) => RemoteController(SavedDesktops(prefs)..load())
    ..gateway = g
    ..status = RemoteStatus.connected
    ..runtimeId = 'rt-1'
    ..transcript = _running();

  test('an interrupted turn ends with a plain "Dihentikan" note and Lanjutkan', () {
    final t = _running();
    expect(t.running, isTrue);
    t.apply(const GatewayEventFrame('message.complete', 'rt-1', {'text': '', 'error': 'interrupted', 'status': 'interrupted'}));
    expect(t.running, isFalse);
    final last = t.messages.lastWhere((m) => m.role == 'assistant');
    expect(last.content, 'Menjalankan pytest');
    expect(last.error, startsWith('Dihentikan'));
    expect(last.error, isNot(contains('interrupted')));
    expect(last.errorInfo?['code'], 'stopped');
    expect(last.errorInfo?['action'], 'continue');
    expect(last.errorInfo?['action_label'], 'Lanjutkan');
  });

  test('Stop sends session.interrupt and waits for the PC to confirm', () async {
    final g = _Gw();
    final r = controller(g);
    expect(await r.stop(), isNull);
    expect(g.interrupts, ['rt-1']);
    expect(r.stopping, isTrue);
    r.debugEvent(const GatewayEventFrame('message.complete', 'rt-1', {'text': '', 'error': 'interrupted', 'status': 'interrupted'}));
    expect(r.stopping, isFalse);
    expect(r.running, isFalse);
  });

  test('no confirmation from the PC: the turn ends on screen by itself', () async {
    final saved = RemoteController.stopConfirmTimeout;
    RemoteController.stopConfirmTimeout = const Duration(milliseconds: 30);
    addTearDown(() => RemoteController.stopConfirmTimeout = saved);
    final r = controller(_Gw());
    await r.stop();
    expect(r.running, isTrue);
    await Future<void>.delayed(const Duration(milliseconds: 80));
    expect(r.running, isFalse);
    expect(r.stopping, isFalse);
    expect(r.transcript.messages.lastWhere((m) => m.role == 'assistant').errorInfo?['code'], 'stopped');
  });

  test('Stop that cannot reach the PC says so (no silent failure)', () async {
    final r = controller(_Gw(fail: true));
    final err = await r.stop();
    expect(err, isNotNull);
    expect(r.stopping, isFalse);
  });
}
