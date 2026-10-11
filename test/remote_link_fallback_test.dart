// Remote dari mana saja: connection fallback on the phone.
//   * a DNS failure on one paired address (a *.ts.net name while that VPN is
//     off) never surfaces: the next address answers;
//   * when no direct address answers, the gateway goes through the encrypted
//     relay tunnel (fake PC over an in-memory frame link) and REST calls such
//     as the model switch follow the live transport;
//   * with no route at all the error is one Indonesian sentence, never the
//     raw ClientException/SocketException text;
//   * new QR fields parse, old QRs still work.
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:neovarch_agent/remote/link/frame_link.dart';
import 'package:neovarch_agent/remote/link/link_crypto.dart';
import 'package:neovarch_agent/remote/link/link_info.dart';
import 'package:neovarch_agent/remote/link/tunnel.dart';
import 'package:neovarch_agent/remote/pairing.dart';
import 'package:neovarch_agent/remote/remote_errors.dart';
import 'package:neovarch_agent/remote/remote_gateway.dart';

/// Minimal PC gateway: /api/ws JSON-RPC + /api/models/default + /api/remote/devices.
class MockPc {
  late HttpServer server;
  String model = 'oc/old';
  final enrolled = <String>[];
  String get url => 'http://127.0.0.1:${server.port}';

  Future<void> start() async {
    server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    server.listen((req) async {
      final path = req.uri.path;
      if (path == '/api/ws' && WebSocketTransformer.isUpgradeRequest(req)) {
        final ws = await WebSocketTransformer.upgrade(req);
        ws.add(jsonEncode({'method': 'event', 'params': {'type': 'gateway.ready', 'payload': {'boot_id': 'b1'}}}));
        ws.listen((raw) {
          final f = jsonDecode('$raw') as Map;
          final m = f['method'];
          Object? result = {};
          if (m == 'ping') result = {'pong': true, 'boot_id': 'b1'};
          if (m == 'network.addresses') result = {'urls': []};
          ws.add(jsonEncode({'id': f['id'], 'result': result}));
        });
        return;
      }
      final body = await utf8.decodeStream(req);
      req.response.headers.contentType = ContentType.json;
      if (path == '/api/models/default' && req.method == 'PUT') {
        model = '${(jsonDecode(body) as Map)['model']}';
        req.response.write(jsonEncode({'model': model, 'provider': '9router'}));
      } else if (path == '/api/remote/devices' && req.method == 'POST') {
        enrolled.add('${(jsonDecode(body) as Map)['pk']}');
        req.response.statusCode = 404; // an older PC: enrollment is optional
      } else if (path == '/api/status') {
        req.response.write('{"ok":true}');
      } else {
        req.response.statusCode = 404;
        req.response.write('{}');
      }
      await req.response.close();
    });
  }

  Future<void> stop() => server.close(force: true);
}

/// The PC side of the encrypted link, in Dart for tests (the real one is
/// core/neovarch/remote_link/peer.py): handshake, auth, ws + http proxy.
class FakeLinkPc {
  FakeLinkPc(this.pcKeys, this.gatewayUrl, {this.knownDevices = const {}, this.deny});
  final LinkKeyPair pcKeys;
  final String gatewayUrl;
  final Set<String> knownDevices;
  final String? deny;
  int connections = 0;

  MemoryFrameLink connect() {
    connections++;
    final link = MemoryFrameLink();
    LinkSession? s;
    WebSocket? ws;
    var chain = Future<void>.value();
    Future<void> out(Map<String, dynamic> m) async {
      for (final f in await s!.encrypt(m)) {
        link.deliver(f);
      }
    }

    link.onSend = (frame) {
      chain = chain.then((_) async {
        if (s == null) {
          final hello = Map<String, dynamic>.from(jsonDecode(frame) as Map);
          final (welcome, sess) = await LinkSession.pcAccept(pcKeys, await LinkKeyPair.generate(), hello);
          s = sess;
          link.deliver(jsonEncode(welcome));
          return;
        }
        final m = await s!.decrypt(frame);
        if (m == null) return;
        switch (m['t']) {
          case 'auth' || 'pair':
            if (deny != null) {
              await out({'t': 'denied', 'reason': deny});
            } else {
              await out({'t': 'ready', 'device': 'dev1', 'name': 'PC Uji'});
            }
          case 'ws.open':
            ws = await WebSocket.connect('${gatewayUrl.replaceFirst('http', 'ws')}/api/ws');
            await out({'t': 'ws.opened'});
            ws!.listen((d) => chain = chain.then((_) => out({'t': 'ws', 'd': '$d'})));
          case 'ws':
            ws?.add('${m['d']}');
          case 'http':
            final c = HttpClient();
            final req = await c.openUrl('${m['m']}', Uri.parse('$gatewayUrl${m['p']}'));
            if (m['b'] != null) req.add(base64.decode('${m['b']}'));
            final res = await req.close();
            final bytes = await res.fold<List<int>>([], (a, b) => a..addAll(b));
            await out({'t': 'http.res', 'id': m['id'], 's': res.statusCode, 'h': {}, 'b': base64.encode(bytes)});
            c.close();
        }
      });
    };
    return link;
  }
}

void main() {
  group('pairing payload', () {
    test('new QR carries the relay identity; old QR still parses', () {
      final pk = 'A' * 43;
      final p = GatewayPairing.parse('neovarch://pair?v=1&url=http%3A%2F%2F192.168.1.5%3A9319&token=t&name=PC'
          '&alt=http%3A%2F%2Fpc.tail1.ts.net%3A9319&pc=hkPbq-MaVpvc2ZsNQZYXL6&pk=$pk'
          '&relay=wss%3A%2F%2Frelay.example.test&pair=code123&bt=aa:bb:cc:dd:ee:ff&btch=3')!;
      expect(p.link!.pcId, 'hkPbq-MaVpvc2ZsNQZYXL6');
      expect(p.link!.relayUrl, 'wss://relay.example.test');
      expect(p.link!.pairCode, 'code123');
      expect(p.link!.bluetooth!.address, 'AA:BB:CC:DD:EE:FF');
      expect(p.link!.bluetooth!.channel, 3);
      // LAN first, MagicDNS after it
      expect(p.allUrls, ['http://192.168.1.5:9319', 'http://pc.tail1.ts.net:9319']);
      final round = GatewayPairing.parse(p.toUri())!;
      expect(round.link!.pcPk, pk);

      final old = GatewayPairing.parse('neovarch://pair?v=1&url=http%3A%2F%2F192.168.1.5%3A9319&token=t')!;
      expect(old.link, isNull);
      expect(old.token, 't');
    });

    test('friendly errors never leak raw socket text', () {
      const raw = "ClientException with SocketException: Failed host lookup: 'pc.tailfd5434.ts.net' (OS Error: No address associated with hostname, errno = 7), uri=http://pc.tailfd5434.ts.net:9319/api/models/default";
      expect(isNetworkError(raw), isTrue);
      final msg = friendlyRemoteError(raw, relayAvailable: true);
      expect(msg, 'PC tidak terjangkau. Mencoba lewat relay…');
      expect(msg, isNot(contains('Exception')));
      expect(friendlyRemoteError(raw), contains('PC tidak terjangkau'));
    });
  });

  group('connection fallback', () {
    late MockPc pc;
    setUp(() async {
      pc = MockPc();
      await pc.start();
    });
    tearDown(() => pc.stop());

    test('DNS failure on the MagicDNS address falls through to the LAN address', () async {
      final g = RemoteGateway(
          baseUrl: 'http://nv-test-host.tailfd5434.ts.net:9319',
          alternates: [pc.url],
          token: 't',
          autoReconnect: false,
          lanTimeout: const Duration(seconds: 2),
          wanTimeout: const Duration(seconds: 2));
      await g.connect();
      expect(g.activeUrl, pc.url);
      expect(g.transport, 'lan');
      final r = await g.setDefaultModel('oc/new');
      expect(r.model, 'oc/new');
      await g.close();
    });

    test('REST call on a dead LAN address reconnects over the relay and succeeds', () async {
      final relayPcGateway = MockPc();
      await relayPcGateway.start();
      final pcKeys = await LinkKeyPair.generate();
      final dev = await LinkKeyPair.generate();
      final fake = FakeLinkPc(pcKeys, relayPcGateway.url);
      final changes = <LinkInfo>[];
      final g = RemoteGateway(
          baseUrl: pc.url,
          token: 't',
          autoReconnect: false,
          lanTimeout: const Duration(seconds: 1),
          wanTimeout: const Duration(seconds: 2),
          lanProbeEvery: const Duration(hours: 1),
          link: LinkInfo(pcId: 'hkPbq-MaVpvc2ZsNQZYXL6', pcPk: b64e(pcKeys.publicBytes), relayUrl: 'wss://relay.example.test', pairCode: 'c1'),
          deviceKey: () async => dev,
          relayConnector: (url, id) async => fake.connect(),
          onLinkChanged: changes.add);
      await g.connect();
      expect(g.transport, 'lan');
      await pc.stop(); // the PC's LAN address disappears (left home, VPN off…)
      final r = await g.setDefaultModel('oc/relay');
      expect(r.model, 'oc/relay');
      expect(relayPcGateway.model, 'oc/relay');
      expect(g.transport, 'relay');
      expect(g.route, 'relay');
      expect(changes.last.enrolled, isTrue); // paired with the QR code once, remembered
      expect(changes.last.pairCode, isNull);
      // RPC also runs over the tunnel
      await g.ping();
      expect(g.status, RemoteStatus.connected);
      await g.close();
      await relayPcGateway.stop();
      pc = MockPc();
      await pc.start(); // for tearDown
    });

    test('no route at all: RemoteUnreachable with an Indonesian message', () async {
      final g = RemoteGateway(
          baseUrl: 'http://nv-test-host.tailfd5434.ts.net:9319',
          token: 't',
          autoReconnect: false,
          wanTimeout: const Duration(seconds: 1));
      Object? err;
      try {
        await g.connect();
      } catch (e) {
        err = e;
      }
      expect(err, isA<RemoteUnreachable>());
      expect(g.lastError, isNot(contains('SocketException')));
      expect(g.lastError, startsWith('PC tidak terjangkau'));
      await g.close();
    });

    test('a revoked phone gets a clear message, not a retry loop', () async {
      final pcKeys = await LinkKeyPair.generate();
      final dev = await LinkKeyPair.generate();
      final fake = FakeLinkPc(pcKeys, pc.url, deny: 'revoked');
      final g = RemoteGateway(
          baseUrl: 'http://127.0.0.1:9',
          token: 't',
          autoReconnect: false,
          lanTimeout: const Duration(milliseconds: 500),
          wanTimeout: const Duration(seconds: 1),
          link: LinkInfo(pcId: 'hkPbq-MaVpvc2ZsNQZYXL6', pcPk: b64e(pcKeys.publicBytes), relayUrl: 'wss://r.test', enrolled: true),
          deviceKey: () async => dev,
          relayConnector: (url, id) async => fake.connect());
      await expectLater(g.connect(), throwsA(isA<TunnelDenied>()));
      expect(g.lastError, contains('dicabut'));
      await g.close();
    });

    test('Bluetooth is tried before the relay when enabled', () async {
      final pcKeys = await LinkKeyPair.generate();
      final dev = await LinkKeyPair.generate();
      final viaBt = FakeLinkPc(pcKeys, pc.url);
      final viaRelay = FakeLinkPc(pcKeys, pc.url);
      final g = RemoteGateway(
          baseUrl: 'http://127.0.0.1:9',
          token: 't',
          autoReconnect: false,
          lanTimeout: const Duration(milliseconds: 500),
          wanTimeout: const Duration(seconds: 2),
          lanProbeEvery: const Duration(hours: 1),
          link: LinkInfo(
              pcId: 'hkPbq-MaVpvc2ZsNQZYXL6',
              pcPk: b64e(pcKeys.publicBytes),
              relayUrl: 'wss://r.test',
              enrolled: true,
              bluetooth: const BluetoothTarget(address: 'AA:BB:CC:DD:EE:FF', channel: 3)),
          deviceKey: () async => dev,
          bluetoothEnabled: true,
          bluetoothConnector: (t) async {
            final l = viaBt.connect();
            return _Kind(l, 'bluetooth');
          },
          relayConnector: (url, id) async => viaRelay.connect());
      await g.connect();
      expect(g.transport, 'bluetooth');
      expect(viaRelay.connections, 0);
      await g.close();
    });
  });
}

/// Re-labels a memory link (the transport kind drives the status chip).
class _Kind implements FrameLink {
  _Kind(this.inner, this.kind);
  final MemoryFrameLink inner;
  @override
  final String kind;
  @override
  Stream<String> get frames => inner.frames;
  @override
  Stream<PeerPresence> get presence => inner.presence;
  @override
  void send(String frame) => inner.send(frame);
  @override
  Future<void> close() => inner.close();
  @override
  Future<void> get done => inner.done;
}
