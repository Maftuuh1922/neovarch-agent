// Phone remote ↔ desktop gateway, end to end against an in-process mock of
// the Neovarch core gateway WebSocket (`/api/ws`) and its REST routes:
// pair from a QR string, open a session, send a message, receive the
// streamed events, approve the dangerous tool remotely (server→client
// `approval` request), read and move a Kanban task.
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:neovarch_agent/remote/remote_controller.dart';
import 'package:neovarch_agent/remote/saved_desktops.dart';
import 'package:neovarch_agent/remote/update_check.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:neovarch_agent/remote/pairing.dart';
import 'package:neovarch_agent/remote/remote_gateway.dart';
import 'package:neovarch_agent/remote/remote_transcript.dart';

const _token = 'sesi-rahasia-123';

class MockGateway {
  late HttpServer server;
  bool serverRequests = false;
  final approvalAnswers = <Map<String, dynamic>>[];
  final rpcResponds = <Map<String, dynamic>>[];
  final submitted = <String>[];
  final patched = <String, dynamic>{};
  String? lastRestToken;
  int connections = 0;
  final sockets = <WebSocket>[];
  // realtime: every event gets a seq; events.replay serves the log
  int seq = 0;
  String bootId = 'boot-1';
  final log = <Map<String, dynamic>>[];
  final replayCalls = <Map<String, dynamic>>[];

  /// Publish a global event (session_id null) to every socket and the log.
  void publish(String type, Map<String, dynamic> payload) {
    final ev = {'type': type, 'session_id': null, 'payload': payload, 'seq': ++seq};
    log.add(ev);
    for (final ws in sockets) {
      try {
        ws.add(jsonEncode({'jsonrpc': '2.0', 'method': 'event', 'params': ev}));
      } catch (_) {}
    }
  }

  late int port;

  Future<void> start() async {
    server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    port = server.port;
    server.listen(_onRequest);
  }

  Future<void> _onRequest(HttpRequest req) async {
    final path = req.uri.path;
    if (path == '/api/ws') {
      if (req.uri.queryParameters['token'] != _token) {
        req.response.statusCode = 403;
        await req.response.close();
        return;
      }
      final ws = await WebSocketTransformer.upgrade(req);
      connections++;
      sockets.add(ws);
      _serve(ws);
      return;
    }
    final res = req.response..headers.contentType = ContentType.json;
    if (path == '/api/status') {
      res.write(jsonEncode({'version': '0.99.0', 'gateway_running': true}));
      await res.close();
      return;
    }
    lastRestToken = req.headers.value('X-Neovarch-Session-Token');
    if (lastRestToken != _token) {
      res.statusCode = 401;
      res.write('{"detail":"unauthorized"}');
      await res.close();
      return;
    }
    if (path == '/api/office') {
      res.write(jsonEncode({
        'agents': [
          {'id': 'session:st_1', 'session_id': 'st_1', 'name': 'Raka', 'role': 'Agen utama · desktop', 'status': 'working', 'current_task': 'Riset GPU'}
        ],
        'counts': {'working': 1},
        'feed': [
          {'id': 1, 'ts': 1760000000, 'kind': 'tool', 'agent': 'Raka', 'text': 'menjalankan web_search'}
        ],
      }));
    } else if (path == '/api/appearance') {
      res.write(jsonEncode({'accent': '#2563EB', 'base': 'light', 'on_accent': '#FFFFFF'}));
    } else if (path == '/api/obsidian/note') {
      res.write(jsonEncode({
        'path': req.uri.queryParameters['path'],
        'title': 'Skripsi',
        'content': '[[Metode]]',
        'outgoing': [
          {'target': 'Metode', 'path': 'Metode.md'}
        ],
        'backlinks': [],
        'open_uri': 'obsidian://open?vault=Kuliah&file=Skripsi'
      }));
    } else if (path == '/api/plugins/kanban/board' && req.method == 'GET') {
      res.write(jsonEncode({
        'columns': [
          {
            'name': 'ready',
            'tasks': [
              {'id': 't_1', 'title': 'Tulis laporan', 'status': 'ready', 'assignee': 'riset', 'priority': 1}
            ]
          },
          {'name': 'done', 'tasks': []}
        ],
        'tenants': [],
        'assignees': ['riset'],
        'latest_event_id': 3,
        'now': 0
      }));
    } else if (path.startsWith('/api/plugins/kanban/tasks/') && req.method == 'PATCH') {
      final body = jsonDecode(await utf8.decoder.bind(req).join()) as Map;
      patched[path.split('/').last] = body['status'];
      res.write(jsonEncode({'task': {'id': path.split('/').last, 'status': body['status']}}));
    } else {
      res.statusCode = 404;
    }
    await res.close();
  }

  void _serve(WebSocket ws) {
    void event(String type, String? sid, Map<String, dynamic> payload) {
      final ev = {'type': type, 'session_id': sid, 'payload': payload, 'seq': ++seq};
      log.add(ev);
      if (ws.closeCode != null) return;
      try {
        ws.add(jsonEncode({'jsonrpc': '2.0', 'method': 'event', 'params': ev}));
      } catch (_) {}
    }
    void reply(Object? id, Object? result) {
      if (ws.closeCode != null) return; // client went away mid-request
      try {
        ws.add(jsonEncode({'jsonrpc': '2.0', 'id': id, 'result': result}));
      } catch (_) {}
    }
    final pendingSrq = <String, Completer<Map<String, dynamic>>>{};

    // like the core: the hello frame is sent directly, not through the event log
    ws.add(jsonEncode({
      'jsonrpc': '2.0',
      'method': 'event',
      'params': {
        'type': 'gateway.ready',
        'session_id': null,
        'payload': {'product': 'neovarch', 'boot_id': bootId, 'seq': seq}
      }
    }));
    ws.listen((raw) async {
      final f = Map<String, dynamic>.from(jsonDecode(raw as String) as Map);
      final id = f['id'];
      final method = f['method'] as String?;
      final p = Map<String, dynamic>.from(f['params'] as Map? ?? const {});
      if (method == null) {
        // our server request answered
        pendingSrq.remove('$id')?.complete(Map<String, dynamic>.from(f['result'] as Map? ?? const {}));
        return;
      }
      switch (method) {
        case 'client.capabilities':
          serverRequests = p['server_requests'] == true;
          reply(id, {'server_requests': ['approval', 'clarify'], 'declines_not_shown': true});
        case 'ping':
          reply(id, {'pong': true, 'seq': seq, 'boot_id': bootId});
        case 'events.replay':
          replayCalls.add(p);
          final since = (p['since'] as num?)?.toInt() ?? 0;
          if (p['boot_id'] != bootId) {
            reply(id, {'resync': true, 'reason': 'restart', 'boot_id': bootId, 'seq': seq, 'events': []});
          } else {
            reply(id, {'resync': false, 'boot_id': bootId, 'seq': seq, 'events': [for (final e in log) if ((e['seq'] as int) > since) e]});
          }
        case 'network.addresses':
          reply(id, {
            'urls': ['http://127.0.0.1:$port', 'http://pc.tail1234.ts.net:$port', 'http://100.101.2.3:$port']
          });
        case 'session.list':
          reply(id, {
            'sessions': [
              {'id': 'st_1', 'title': 'Riset GPU', 'preview': 'bandingkan harga', 'message_count': 3, 'last_active': 1760000000}
            ]
          });
        case 'session.active_list':
          reply(id, {
            'sessions': [
              {'id': 'rt_1', 'title': 'Riset GPU', 'status': 'idle', 'model': 'qwen3-coder', 'preview': '', 'current': false, 'last_active': 0, 'message_count': 3, 'session_key': 'k', 'started_at': 0}
            ]
          });
        case 'approval.pending':
          reply(id, {
            'approvals': p['session_id'] == 'rt_2'
                ? [
                    {'request_id': 'ap_9', 'command': 'git push --force', 'description': 'push paksa', 'choices': ['once', 'deny'], 'tool_name': 'terminal'}
                  ]
                : []
          });
        case 'approval.respond':
          rpcResponds.add(p);
          reply(id, {'resolved': true});
        case 'session.resume':
          reply(id, {
            'session_id': 'rt_1',
            'stored_session_id': p['session_id'],
            'message_count': 3,
            'messages': [
              {'role': 'user', 'text': 'bandingkan harga GPU'},
              {'role': 'assistant', 'text': 'Saya cek dulu.'},
              {'role': 'tool', 'name': 'web_search', 'text': '3 hasil', 'tool_call_id': 'c0'},
            ],
            'info': {'title': 'Riset GPU', 'running': false},
            'open_requests': [],
          });
        case 'prompt.submit':
          submitted.add('${p['text']}');
          reply(id, {'status': 'started'});
          final sid = '${p['session_id']}';
          event('message.start', sid, {});
          event('reasoning.delta', sid, {'text': 'Perlu membersihkan folder build. '});
          event('tool.start', sid, {'tool_id': 'tl_1', 'name': 'terminal', 'args_text': 'rm -rf build'});
          var choice = 'deny';
          if (serverRequests) {
            final c = pendingSrq['srq-001'] = Completer<Map<String, dynamic>>();
            ws.add(jsonEncode({
              'jsonrpc': '2.0',
              'id': 'srq-001',
              'method': 'approval',
              'params': {
                'session_id': sid,
                'request_id': 'ap_1',
                'command': 'rm -rf build',
                'description': 'perintah berbahaya: hapus rekursif',
                'choices': ['once', 'session', 'always', 'deny'],
                'tool_name': 'terminal',
              }
            }));
            final r = await c.future;
            approvalAnswers.add(r);
            choice = '${r['choice']}';
          }
          event('tool.complete', sid, {
            'tool_id': 'tl_1',
            'name': 'terminal',
            'summary': choice == 'deny' ? 'ditolak' : 'folder build dihapus',
            'result_text': choice == 'deny' ? 'denied' : 'removed 12 files',
            'duration_s': 0.4
          });
          for (final w in ['Beres, ', 'folder ', 'build bersih.']) {
            event('message.delta', sid, {'text': w});
          }
          event('session.title', sid, {'session_id': sid, 'title': 'Bersihkan build'});
          event('message.complete', sid, {
            'text': 'Beres, folder build bersih.',
            'usage': {'avg_tps': 42.0, 'context_percent': 7}
          });
        default:
          if (ws.closeCode == null) {
            ws.add(jsonEncode({
              'jsonrpc': '2.0',
              'id': id,
              'error': {'code': -32601, 'message': 'unknown method $method'}
            }));
          }
      }
    });
  }
}

void main() {
  group('pairing payload', () {
    test('QR URI, JSON, dashboard URL and bare host:port', () {
      final qr = const GatewayPairing(url: 'http://192.168.1.5:9319', token: 'abc', name: 'PC Kantor').toUri();
      final a = GatewayPairing.parse(qr)!;
      expect(a.url, 'http://192.168.1.5:9319');
      expect(a.token, 'abc');
      expect(a.name, 'PC Kantor');

      final b = GatewayPairing.parse('{"url":"192.168.1.9","token":"t"}')!;
      expect(b.url, 'http://192.168.1.9:9319');
      expect(b.token, 't');

      final c = GatewayPairing.parse('ws://10.0.0.2:47800/api/ws?token=zz')!;
      expect(c.url, 'http://10.0.0.2:47800');
      expect(c.token, 'zz');

      expect(GatewayPairing.parse('https://gateway.example.com/?token=q')!.url, 'https://gateway.example.com');
      expect(GatewayPairing.parse('pc.local:9000')!.url, 'http://pc.local:9000');
      expect(GatewayPairing.parse(''), isNull);
      expect(GatewayPairing.parse('ftp://x'), isNull);
    });
  });

  group('remote gateway', () {
    late MockGateway mock;
    setUp(() async {
      mock = MockGateway();
      await mock.start();
    });
    tearDown(() async => mock.server.close(force: true));

    test('wrong token is refused', () async {
      final g = RemoteGateway(baseUrl: 'http://127.0.0.1:${mock.port}', token: 'salah', autoReconnect: false);
      await expectLater(g.connect(), throwsA(anything));
      expect(g.status, RemoteStatus.failed);
      await g.close();
    });

    test('pair, chat with streamed events, approve remotely, Kanban', () async {
      final pairing = GatewayPairing.parse(
          GatewayPairing(url: 'http://127.0.0.1:${mock.port}', token: _token, name: 'PC-Tes').toUri())!;
      final g = RemoteGateway(baseUrl: pairing.url, token: pairing.token, heartbeat: const Duration(milliseconds: 200));
      await g.connect();
      expect(g.status, RemoteStatus.connected);
      expect(mock.serverRequests, isTrue, reason: 'must advertise server_requests or approvals never arrive');

      final sessions = await g.listSessions();
      expect(sessions.single.title, 'Riset GPU');

      final opened = await g.resume('st_1');
      expect(opened.runtimeId, 'rt_1');
      expect(opened.messages.map((m) => m.role), ['user', 'assistant']);
      expect(opened.messages.last.tools.single.name, 'web_search');

      final t = RemoteTranscript(history: opened.messages);
      final done = Completer<void>();
      final sub = g.events.listen((f) {
        if (f.sessionId == 'rt_1') t.apply(f);
        if (f.type == 'message.complete' && !done.isCompleted) done.complete();
      });
      final appr = g.approvalsChanged.firstWhere((a) => a != null);

      t.addUser('bersihkan folder build');
      await g.submit('rt_1', 'bersihkan folder build');
      final a = (await appr.timeout(const Duration(seconds: 5)))!;
      expect(a.rid, 'srq-001');
      expect(a.requestId, 'ap_1');
      expect(a.toolName, 'terminal');
      expect(a.choices, contains('once'));
      expect(t.running, isTrue);
      expect(t.messages.last.tools.single.running, isTrue); // waiting on us

      await g.respondApproval(a, 'once');
      expect(g.approvals, isEmpty);
      await done.future.timeout(const Duration(seconds: 5));
      await sub.cancel();

      expect(mock.submitted, ['bersihkan folder build']);
      expect(mock.approvalAnswers.single['choice'], 'once');
      expect(t.running, isFalse);
      expect(t.title, 'Bersihkan build');
      expect(t.tokensPerSecond, 42.0);
      final turn = t.messages.sublist(2);
      expect(turn.first.role, 'user');
      final tool = turn.expand((m) => m.tools).single;
      expect(tool.summary, 'folder build dihapus');
      expect(tool.running, isFalse);
      expect(turn.last.content, 'Beres, folder build bersih.');
      expect(turn.any((m) => m.reasoning.contains('membersihkan')), isTrue);
      expect(turn.every((m) => !m.streaming), isTrue);

      // heartbeat keeps the socket up
      await Future<void>.delayed(const Duration(milliseconds: 500));
      expect(g.status, RemoteStatus.connected);

      // status + Kanban REST with the same token
      expect((await g.serverStatus())['version'], '0.99.0');
      expect((await g.activeSessions()).single.model, 'qwen3-coder');
      final board = await g.board();
      expect(board.lanes.first.name, 'ready');
      expect(board.lanes.first.cards.single.title, 'Tulis laporan');
      await g.moveTask('t_1', 'done');
      expect(mock.patched['t_1'], 'done');
      expect(mock.lastRestToken, _token);

      // Approval of a session the phone never opened: approval.pending →
      // answered through the approval.respond RPC.
      final other = await g.pendingApprovals('rt_2');
      expect(other.single.rid, isNull);
      expect(g.approvals.single.command, 'git push --force');
      await g.respondApproval(other.single, 'deny');
      expect(mock.rpcResponds.single, containsPair('request_id', 'ap_9'));
      expect(mock.rpcResponds.single, containsPair('session_id', 'rt_2'));
      expect(mock.rpcResponds.single, containsPair('choice', 'deny'));
      expect(g.approvals, isEmpty);

      await g.close();
      expect(g.status, RemoteStatus.disconnected);
    });

    test('reconnects after the gateway drops the socket', () async {
      final g = RemoteGateway(baseUrl: 'http://127.0.0.1:${mock.port}', token: _token, heartbeat: const Duration(seconds: 30));
      await g.connect();
      final back = g.statusStream.firstWhere((s) => s == RemoteStatus.connected);
      final dropped = g.statusStream.firstWhere((s) => s == RemoteStatus.reconnecting);
      // server goes away and comes back on the same port
      final port = mock.port;
      await mock.server.close(force: true);
      for (final s in mock.sockets) {
        await s.close();
      }
      await dropped.timeout(const Duration(seconds: 5));
      mock.server = await HttpServer.bind(InternetAddress.loopbackIPv4, port);
      mock.server.listen(mock._onRequest);
      await back.timeout(const Duration(seconds: 10));
      expect(mock.connections, greaterThanOrEqualTo(2));
      await g.close();
    });

    test('Office, appearance and vault over REST with the session token', () async {
      final g = RemoteGateway(baseUrl: 'http://127.0.0.1:${mock.port}', token: _token, autoReconnect: false);
      await g.connect();
      final o = await g.office();
      expect(o.agents.single.name, 'Raka');
      expect(o.agents.single.statusLabel, 'bekerja');
      expect(o.feed.single.text, 'menjalankan web_search');
      expect((await g.appearance())!['accent'], '#2563EB');
      final n = await g.vaultNote('Skripsi.md');
      expect(n.resolve('Metode'), 'Metode.md');
      expect(n.openUri, startsWith('obsidian://open'));
      expect(mock.lastRestToken, _token);
      await g.close();
    });

    test('office.update push arrives with seq; ping measures RTT and learns boot_id', () async {
      final g = RemoteGateway(baseUrl: 'http://127.0.0.1:${mock.port}', token: _token, autoReconnect: false);
      await g.connect();
      final got = g.events.firstWhere((f) => f.type == 'office.update');
      final sw = Stopwatch()..start();
      mock.publish('office.update', {'agents': [], 'feed': []});
      final f = await got.timeout(const Duration(seconds: 5));
      expect(sw.elapsedMilliseconds, lessThan(300), reason: 'push latency on loopback');
      expect(f.seq, mock.seq);
      expect(g.lastSeq, mock.seq);
      await g.ping();
      expect(g.lastRtt, isNotNull);
      expect(g.bootId, 'boot-1');
      await g.close();
    });

    test('after a drop, missed events are replayed (no full resync)', () async {
      final g = RemoteGateway(baseUrl: 'http://127.0.0.1:${mock.port}', token: _token, heartbeat: const Duration(seconds: 30));
      await g.connect();
      await g.ping(); // learn boot_id + seq
      mock.publish('office.update', {'n': 1});
      await g.events.firstWhere((f) => f.type == 'office.update').timeout(const Duration(seconds: 5));
      final dropped = g.statusStream.firstWhere((s) => s == RemoteStatus.reconnecting);
      for (final s in [...mock.sockets]) {
        await s.close();
      }
      mock.sockets.clear();
      await dropped.timeout(const Duration(seconds: 5));
      // happens while the phone is offline
      mock.publish('kanban.changed', {'task': 't_1'});
      final replayed = g.events.firstWhere((f) => f.type == 'kanban.changed');
      final ev = await replayed.timeout(const Duration(seconds: 10));
      expect(ev.replayed, isTrue);
      expect(mock.replayCalls, isNotEmpty);
      expect(g.resyncNeeded, isFalse);
      expect(g.status, RemoteStatus.connected);
      await g.close();
    });

    test('PC restarted (new boot_id) → resync.required', () async {
      final g = RemoteGateway(baseUrl: 'http://127.0.0.1:${mock.port}', token: _token, autoReconnect: false);
      await g.connect();
      await g.ping();
      final resync = g.events.firstWhere((f) => f.type == 'resync.required');
      mock.bootId = 'boot-2';
      await g.ping();
      await resync.timeout(const Duration(seconds: 5));
      expect(g.resyncNeeded, isTrue);
      await g.close();
    });

    test('LAN address down → next address; PC-reported routes are learned', () async {
      final g = RemoteGateway(
        baseUrl: 'http://127.0.0.1:1', // nothing listens there
        alternates: ['http://127.0.0.1:${mock.port}'],
        token: _token,
        autoReconnect: false,
        lanTimeout: const Duration(milliseconds: 800),
      );
      final routes = g.routesChanged.first;
      await g.connect();
      expect(g.activeUrl, 'http://127.0.0.1:${mock.port}');
      final learned = await routes.timeout(const Duration(seconds: 5));
      expect(learned, contains('http://pc.tail1234.ts.net:${mock.port}'));
      // v1.4.7 Tailscale first: the tailnet IP, then MagicDNS, then the LAN
      expect(g.candidates.indexOf('http://100.101.2.3:${mock.port}'), lessThan(g.candidates.indexOf('http://pc.tail1234.ts.net:${mock.port}')));
      await g.close();
    });

    test('controller: Office + appearance load once, then follow WebSocket pushes (no polling)', () async {
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      final desktops = SavedDesktops(prefs)..load();
      final r = RemoteController(desktops)
        ..updateChecker = UpdateChecker(client: MockClient((_) async => http.Response('{"tag_name":"v1.4.0"}', 200)));
      final looks = <Map<String, dynamic>>[];
      r.onAppearance = looks.add;
      final d = await desktops.upsert(GatewayPairing(url: 'http://127.0.0.1:${mock.port}', token: _token, name: 'PC'));
      await r.connectTo(d);
      for (var i = 0; i < 50 && (r.office == null || looks.isEmpty); i++) {
        await Future<void>.delayed(const Duration(milliseconds: 50));
      }
      expect(r.connected, isTrue);
      expect(r.office!.agents.single.name, 'Raka');
      expect(looks.single['accent'], '#2563EB');
      // pushes
      mock.publish('office.update', {
        'agents': [
          {'id': 'session:x', 'session_id': 'x', 'name': 'Sari', 'role': 'Agen', 'status': 'idle'}
        ],
        'feed': [],
      });
      mock.publish('appearance.changed', {'accent': '#16A34A', 'base': 'dark'});
      mock.publish('vault.changed', {'tool': 'obsidian_write'});
      for (var i = 0; i < 50 && (r.office!.agents.single.name != 'Sari' || looks.length < 2); i++) {
        await Future<void>.delayed(const Duration(milliseconds: 20));
      }
      expect(r.office!.agents.single.name, 'Sari');
      expect(looks.last['accent'], '#16A34A');
      expect(r.vaultRevision, 1);
      expect(desktops.items.single.alternates, contains('http://pc.tail1234.ts.net:${mock.port}'));
      await r.disconnect();
    });
  });
}
