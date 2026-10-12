// v1.4.7 Antrean pesan: sending while the agent works queues on the PC (never
// the raw "a turn is already running"), the strip mirrors `queue.update`, and
// `queue.sent` turns the message into a chat bubble.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:neovarch_agent/data/gateway_client.dart';
import 'package:neovarch_agent/remote/l10n/strings.dart';
import 'package:neovarch_agent/remote/message_queue.dart';
import 'package:neovarch_agent/remote/remote_controller.dart';
import 'package:neovarch_agent/remote/remote_gateway.dart';
import 'package:neovarch_agent/remote/saved_desktops.dart';
import 'package:neovarch_agent/remote/ui/queue_strip.dart';

class _Gw extends RemoteGateway {
  _Gw() : super(baseUrl: 'http://192.168.1.20:9319', token: 'tok', autoReconnect: false);
  final submits = <String>[];
  final calls = <String>[];
  Object Function(String text)? answer;
  @override
  Future<dynamic> submit(String runtimeId, String text, {List<String> attachments = const [], Map<String, dynamic> extra = const {}}) async {
    submits.add(text);
    final a = answer?.call(text);
    if (a is Exception) throw a;
    return a ?? {'ok': true, 'status': 'running'};
  }

  @override
  Future<dynamic> queueCall(String runtimeId, String action, {String? id, String? text}) async {
    calls.add('$action:${id ?? ''}:${text ?? ''}');
    return {'items': const [], 'count': 0, 'paused': false};
  }
}

Map<String, dynamic> _q(List<String> texts, {bool paused = false, String? reason}) => {
      'items': [for (var i = 0; i < texts.length; i++) {'id': 'q-$i', 'text': texts[i], 'ts': 1.0, 'attachments': const []}],
      'count': texts.length,
      'paused': paused,
      'paused_reason': ?reason,
    };

void main() {
  tearDown(() => L10n.code = 'id');

  test('parse queue payloads', () {
    final q = MessageQueueState.fromJson(_q(['a', 'b'], paused: true, reason: 'stopped'));
    expect(q.count, 2);
    expect(q.label, 'Antre (2)');
    expect(q.pausedLabel, contains('dihentikan'));
    expect(MessageQueueState.fromJson(null).isEmpty, isTrue);
    expect(MessageQueueState.fromJson(_q(const [], paused: true)).paused, isFalse);
    L10n.code = 'en';
    expect(q.label, 'Queued (2)');
  });

  test('raw core errors are never shown in English to an Indonesian user', () {
    expect(friendlyCoreError('RPC -32010: a turn is already running in this session'), startsWith('Agen masih bekerja'));
    L10n.code = 'en';
    expect(friendlyCoreError('a turn is already running in this session'), startsWith('The agent is still working'));
    expect(friendlyCoreError('something else'), isNull);
  });

  group('controller', () {
    late SharedPreferences prefs;
    setUp(() async {
      SharedPreferences.setMockInitialValues({});
      prefs = await SharedPreferences.getInstance();
    });

    RemoteController make(_Gw g) => RemoteController(SavedDesktops(prefs)..load())
      ..gateway = g
      ..status = RemoteStatus.connected
      ..runtimeId = 'rt-1';

    test('send while running → queued strip, bubble only when the PC sends it', () async {
      final g = _Gw()..answer = (t) => {'ok': true, 'status': 'queued', 'queued': true, 'queue': _q([t])};
      final r = make(g);
      r.transcript.addUser('pertama'); // a turn is running
      final before = r.transcript.messages.length;
      expect(await r.send('kedua'), isNull);
      expect(g.submits, ['kedua']);
      expect(r.transcript.messages.length, before); // no bubble yet
      expect(r.queue.items.single.text, 'kedua');
      expect(r.transcript.error, isNull);
      r.debugEvent(const GatewayEventFrame('queue.sent', 'rt-1', {'id': 'q-0', 'text': 'kedua'}));
      expect(r.transcript.messages.last.content, 'kedua');
      expect(r.queue.isEmpty, isTrue);
    });

    test('idle send that the PC queued anyway (desktop started a turn) drops the optimistic bubble', () async {
      final g = _Gw()..answer = (t) => {'ok': true, 'status': 'queued', 'queue': _q([t])};
      final r = make(g);
      expect(await r.send('halo'), isNull);
      expect(r.transcript.messages.where((m) => m.role == 'user'), isEmpty);
      expect(r.queue.count, 1);
      expect(r.transcript.running, isTrue);
    });

    test('older PC refusing while running: friendly text, the running turn is kept', () async {
      final g = _Gw()..answer = (t) => Exception('RPC -32010: a turn is already running in this session');
      final r = make(g);
      r.transcript.addUser('pertama');
      final err = await r.send('kedua');
      expect(err, startsWith('Agen masih bekerja'));
      expect(r.transcript.running, isTrue);
      expect(r.transcript.error, isNull);
    });

    test('queue.update from the desktop is mirrored; actions call the PC', () async {
      final g = _Gw();
      final r = make(g);
      r.debugEvent(GatewayEventFrame('queue.update', 'rt-1', _q(['a', 'b'])));
      expect(r.queue.count, 2);
      r.debugEvent(GatewayEventFrame('queue.update', 'rt-2', _q(['x'])));
      expect(r.queue.count, 2); // another chat's queue is not this one
      await r.queueAction('send_now', id: 'q-1');
      await r.queueAction('edit', id: 'q-0', text: 'a!');
      await r.queueAction('remove', id: 'q-0');
      expect(g.calls, ['send_now:q-1:', 'edit:q-0:a!', 'remove:q-0:']);
    });
  });

  testWidgets('QueueStrip shows "Antre (n)" with send-now / edit / remove', (tester) async {
    final actions = <String>[];
    Future<String?> act(String a, {String? id, String? text}) async {
      actions.add('$a:${id ?? ''}');
      return null;
    }

    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: QueueStrip(queue: MessageQueueState.fromJson(_q(['cek log', 'lanjut deploy'], paused: true, reason: 'error')), onAction: act)),
    ));
    expect(find.text('Antre (2)'), findsOneWidget);
    expect(find.text('cek log'), findsOneWidget);
    expect(find.byKey(const ValueKey('queue-paused')), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('queue-send-q-1')));
    await tester.tap(find.byKey(const ValueKey('queue-remove-q-0')));
    await tester.tap(find.byKey(const ValueKey('queue-resume')));
    await tester.pump();
    expect(actions, ['send_now:q-1', 'remove:q-0', 'resume:']);
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: QueueStrip(queue: MessageQueueState.empty, onAction: act))));
    expect(find.byKey(const ValueKey('queue-strip')), findsNothing);
  });
}
