// Encrypted tunnel to the PC over a FrameLink (relay or Bluetooth).
//
// After the handshake (link_crypto.dart) the tunnel carries:
//   * one JSON-RPC stream (the same frames as /api/ws on the LAN), and
//   * REST requests/responses (same paths as on the LAN),
// so RemoteGateway works unchanged on top of it. See docs/relay.md.
import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import '../../data/gateway_client.dart';
import 'frame_link.dart';
import 'link_crypto.dart';

/// The PC refused this phone (`unknown_device`, `revoked`, `expired`, `bad_code`).
class TunnelDenied implements Exception {
  final String reason;
  const TunnelDenied(this.reason);
  @override
  String toString() => switch (reason) {
        'revoked' => 'HP ini sudah dicabut di PC. Pindai ulang QR di PC untuk memasangkan lagi.',
        'expired' => 'Sesi kedaluwarsa, pasangkan ulang: pindai QR baru di PC.',
        'bad_code' => 'Kode pemasangan sudah kedaluwarsa atau sudah dipakai. Pindai ulang QR di PC.',
        _ => 'PC belum mengenal HP ini. Pindai ulang QR di PC.',
      };
}

class TunnelResponse {
  const TunnelResponse(this.status, this.headers, this.body, {this.error});
  final int status; // 0 = the PC could not reach its own gateway
  final Map<String, String> headers;
  final Uint8List body;
  final String? error;
  String get text => utf8.decode(body, allowMalformed: true);
}

class Tunnel {
  Tunnel._(this.link, this._session, this.pcName, this.deviceId) {
    _sub = link.frames.listen((f) {
      _rx = _rx.then((_) => _onFrame(f));
    }, onDone: _onGone);
    unawaited(link.done.then((_) => _onGone()));
  }

  final FrameLink link;
  final LinkSession _session;
  final String pcName;
  final String deviceId;
  late final StreamSubscription<String> _sub;
  Future<void> _rx = Future.value();
  Future<void> _tx = Future.value();
  int _rid = 0;
  final Map<int, Completer<TunnelResponse>> _pending = {};
  _TunnelPipe? _pipe;
  bool _closed = false;
  final _gone = Completer<void>();

  String get kind => link.kind;
  bool get isOpen => !_closed;
  Future<void> get done => _gone.future;

  /// Handshake + auth. With [pairCode] a new device enrolls itself (QR pairing
  /// over the relay/Bluetooth); without it the device must already be known.
  static Future<Tunnel> open(FrameLink link,
      {required LinkKeyPair device,
      required List<int> pcPublicKey,
      String? pairCode,
      String deviceName = 'HP',
      Duration timeout = const Duration(seconds: 10)}) async {
    final eph = await LinkKeyPair.generate();
    final first = Completer<String>();
    final early = <String>[];
    var linkDone = false;
    Completer<void>? wake;
    final sub = link.frames.listen((f) {
      if (!first.isCompleted) {
        first.complete(f);
      } else {
        early.add(f);
        wake?.complete();
        wake = null;
      }
    }, onDone: () {
      linkDone = true;
      if (!first.isCompleted) first.completeError(const LinkError('link closed'));
      wake?.complete();
      wake = null;
    });
    try {
      link.send(jsonEncode(linkHello(device, eph)));
      final welcomeRaw = await first.future.timeout(timeout);
      Map<String, dynamic> welcome;
      try {
        welcome = Map<String, dynamic>.from(jsonDecode(welcomeRaw) as Map);
      } catch (_) {
        throw const LinkError('bad welcome');
      }
      final session = await LinkSession.phoneFinish(device, eph, pcPublicKey, welcome);
      final auth = pairCode != null && pairCode.isNotEmpty ? {'t': 'pair', 'code': pairCode, 'name': deviceName} : {'t': 'auth'};
      for (final f in await session.encrypt(auth)) {
        link.send(f);
      }
      // Wait for ready/denied (frames may already be buffered in [early]).
      Map<String, dynamic>? reply;
      final deadline = DateTime.now().add(timeout);
      var i = 0;
      while (reply == null) {
        while (i >= early.length) {
          if (linkDone) throw const LinkError('link closed');
          final left = deadline.difference(DateTime.now());
          if (left <= Duration.zero) throw TimeoutException('PC tidak menjawab', timeout);
          final w = wake = Completer<void>();
          await w.future.timeout(left, onTimeout: () {});
        }
        reply = await session.decrypt(early[i++]);
      }
      if (reply['t'] == 'denied') throw TunnelDenied('${reply['reason'] ?? 'unknown_device'}');
      if (reply['t'] != 'ready') throw const LinkError('unexpected reply');
      await sub.cancel();
      final t = Tunnel._(link, session, '${reply['name'] ?? ''}', '${reply['device'] ?? ''}');
      for (final f in early.sublist(i)) {
        t._rx = t._rx.then((_) => t._onFrame(f));
      }
      return t;
    } catch (_) {
      await sub.cancel();
      await link.close();
      rethrow;
    }
  }

  void _send(Map<String, dynamic> m) {
    if (_closed) return;
    _tx = _tx.then((_) async {
      if (_closed) return;
      for (final f in await _session.encrypt(m)) {
        link.send(f);
      }
    }).catchError((Object _) {
      unawaited(close());
    });
  }

  Future<void> _onFrame(String f) async {
    if (_closed) return;
    Map<String, dynamic>? m;
    try {
      m = await _session.decrypt(f);
    } on LinkError {
      await close();
      return;
    }
    if (m == null) return;
    switch (m['t']) {
      case 'ws':
        _pipe?._incoming('${m['d'] ?? ''}');
      case 'ws.opened':
        _pipe?._opened();
      case 'ws.closed':
        _pipe?._gone();
      case 'http.res':
        final c = _pending.remove((m['id'] as num?)?.toInt());
        if (c == null || c.isCompleted) return;
        final h = <String, String>{for (final e in ((m['h'] as Map?) ?? const {}).entries) '${e.key}'.toLowerCase(): '${e.value}'};
        Uint8List body;
        try {
          body = base64.decode('${m['b'] ?? ''}');
        } catch (_) {
          body = Uint8List(0);
        }
        c.complete(TunnelResponse((m['s'] as num?)?.toInt() ?? 0, h, body, error: m['e'] as String?));
      case 'denied':
        await close();
    }
  }

  /// One REST call through the tunnel (same paths and query as on the LAN).
  Future<TunnelResponse> request(String method, String pathAndQuery,
      {Map<String, String> headers = const {}, List<int>? body, Duration timeout = const Duration(seconds: 30)}) {
    if (_closed) return Future.error(const LinkError('tunnel closed'));
    final id = ++_rid;
    final c = _pending[id] = Completer<TunnelResponse>();
    _send({
      't': 'http',
      'id': id,
      'm': method,
      'p': pathAndQuery,
      'h': headers,
      if (body != null && body.isNotEmpty) 'b': base64.encode(body),
    });
    return c.future.timeout(timeout, onTimeout: () {
      _pending.remove(id);
      throw TimeoutException('PC tidak menjawab lewat ${kind == 'bluetooth' ? 'Bluetooth' : 'relay'}', timeout);
    });
  }

  /// The JSON-RPC stream (what /api/ws is on the LAN). One at a time.
  Future<RpcPipe> openRpc({Duration timeout = const Duration(seconds: 10)}) async {
    _pipe?._gone();
    final p = _pipe = _TunnelPipe(this);
    _send({'t': 'ws.open'});
    await p._ready.future.timeout(timeout);
    return p;
  }

  void _onGone() {
    if (_closed) return;
    _closed = true;
    for (final c in _pending.values) {
      if (!c.isCompleted) c.completeError(const LinkError('tunnel closed'));
    }
    _pending.clear();
    _pipe?._gone();
    if (!_gone.isCompleted) _gone.complete();
  }

  Future<void> close() async {
    if (_closed && _gone.isCompleted) return;
    _onGone();
    await _sub.cancel();
    await link.close();
  }
}

class _TunnelPipe implements RpcPipe {
  _TunnelPipe(this._t);
  final Tunnel _t;
  final _ready = Completer<void>();
  final _ctrl = StreamController<String>();
  bool _isGone = false;

  void _opened() {
    if (!_ready.isCompleted) _ready.complete();
  }

  void _incoming(String d) {
    if (!_isGone) _ctrl.add(d);
  }

  void _gone() {
    if (_isGone) return;
    _isGone = true;
    if (!_ready.isCompleted) _ready.completeError(const LinkError('PC menutup kanal'));
    _ctrl.close();
  }

  @override
  Stream<String> get stream => _ctrl.stream;

  @override
  void add(String frame) {
    if (!_isGone) _t._send({'t': 'ws', 'd': frame});
  }

  @override
  Future<void> close() async {
    if (_isGone) return;
    _t._send({'t': 'ws.close'});
    _gone();
  }
}
