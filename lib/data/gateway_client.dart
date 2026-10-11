// JSON-RPC 2.0 over WebSocket to the Neovarch core gateway (`/api/ws`):
//
//   client → {jsonrpc:'2.0', id, method, params}
//   server → {id, result} | {id, error:{code,message}}
//   server → {method:'event', params:{type, session_id, payload}}
//   server → {id:'<string>', method, params}   (server request; we answer)
//
// Auth: `?token=` on the URL, plus `Authorization: Bearer` and any extra
// headers on native platforms. Events carry a monotonically increasing `seq`
// (core v1.4+) so a reconnecting client can replay what it missed.
import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/web_socket_channel.dart';

import 'ws_connect.dart';

class GatewayEventFrame {
  final String type;
  final String? sessionId;
  final Map<String, dynamic> payload;
  /// Core event sequence number (null on older cores and synthetic frames).
  final int? seq;
  final bool replayed;
  const GatewayEventFrame(this.type, this.sessionId, this.payload, {this.seq, this.replayed = false});
}

class RpcError implements Exception {
  final int code;
  final String message;
  const RpcError(this.code, this.message);
  @override
  String toString() => message;
}

const jsonRpcMethodNotFound = -32601;

Uri buildGatewayWsUri(String baseUrl, {String? token, String path = '/api/ws', Map<String, String> query = const {}}) {
  var u = Uri.parse(baseUrl.trim());
  final scheme = (u.scheme == 'https' || u.scheme == 'wss') ? 'wss' : 'ws';
  final basePath = u.path.replaceAll(RegExp(r'/+$'), '');
  final p = basePath.endsWith(path) ? basePath : '$basePath$path';
  return Uri(
    scheme: scheme,
    host: u.host,
    port: u.hasPort ? u.port : null,
    path: p,
    queryParameters: {
      ...u.queryParameters,
      if (token != null && token.isNotEmpty) 'token': token,
      ...query,
    },
  );
}

/// A JSON-RPC frame stream that is not a direct WebSocket (the encrypted relay /
/// Bluetooth tunnel carries the same frames as `/api/ws`).
abstract class RpcPipe {
  Stream<String> get stream;
  void add(String frame);
  Future<void> close();
}

class _WsPipe implements RpcPipe {
  _WsPipe(this.ch);
  final WebSocketChannel ch;
  @override
  Stream<String> get stream => ch.stream.map((e) => '$e');
  @override
  void add(String frame) => ch.sink.add(frame);
  @override
  Future<void> close() async => ch.sink.close();
}

class GatewayClient {
  GatewayClient({required this.baseUrl, this.token, this.headers = const {}, this.connectTimeout = const Duration(seconds: 15), this.pipeOpener});
  final String baseUrl;
  final String? token;
  final Map<String, String> headers;
  final Duration connectTimeout;

  /// When set, frames go through this pipe instead of a WebSocket to [baseUrl].
  final Future<RpcPipe> Function()? pipeOpener;

  /// Extra query parameters for the next connect (e.g. `since`/`boot_id`).
  Map<String, String> connectQuery = const {};

  RpcPipe? _ch;
  StreamSubscription? _sub;
  int _seq = 0;
  final Map<String, Completer<dynamic>> _pending = {};
  final _events = StreamController<GatewayEventFrame>.broadcast();
  Completer<void>? _connecting;
  bool get connected => _ch != null;
  String? lastError;

  Stream<GatewayEventFrame> get events => _events.stream;

  Future<void> ensureConnected() async {
    if (_ch != null) return;
    if (_connecting != null) return _connecting!.future;
    final c = _connecting = Completer<void>();
    WebSocketChannel? ws;
    RpcPipe? pipe;
    try {
      if (pipeOpener != null) {
        pipe = await pipeOpener!().timeout(connectTimeout);
      } else {
        final uri = buildGatewayWsUri(baseUrl, token: token, query: connectQuery);
        ws = connectWs(uri, {
          if (token != null && token!.isNotEmpty) 'Authorization': 'Bearer $token',
          ...headers,
        });
        await ws.ready.timeout(connectTimeout);
        pipe = _WsPipe(ws);
      }
      _ch = pipe;
      _sub = pipe.stream.listen(_onFrame, onDone: _onClose, onError: (e) {
        lastError = '$e';
        _onClose();
      });
      c.complete();
    } catch (e) {
      try {
        unawaited(ws?.sink.close());
        unawaited(pipe?.close());
      } catch (_) {}
      lastError = 'tidak bisa terhubung ke gateway: $e';
      c.completeError(RpcError(0, lastError!));
    } finally {
      _connecting = null;
    }
    return c.future;
  }

  void _onClose() {
    _ch = null;
    _sub?.cancel();
    _sub = null;
    for (final p in _pending.values) {
      if (!p.isCompleted) p.completeError(const RpcError(0, 'koneksi gateway terputus'));
    }
    _pending.clear();
    _events.add(const GatewayEventFrame('gateway.disconnected', null, {}));
  }

  void _onFrame(dynamic raw) {
    Map<String, dynamic> f;
    try {
      f = Map<String, dynamic>.from(jsonDecode('$raw') as Map);
    } catch (_) {
      return;
    }
    final id = f['id'];
    final method = f['method'];
    if (method == 'event' && f['params'] is Map) {
      final p = Map<String, dynamic>.from(f['params'] as Map);
      final payload = p['payload'] is Map ? Map<String, dynamic>.from(p['payload'] as Map) : <String, dynamic>{};
      _events.add(GatewayEventFrame('${p['type']}', p['session_id'] as String?, payload,
          seq: (p['seq'] as num?)?.toInt(), replayed: p['replayed'] == true));
      return;
    }
    if (method is String && id != null) {
      // A server request. Approvals arrive this way on some versions.
      final params = f['params'] is Map ? Map<String, dynamic>.from(f['params'] as Map) : <String, dynamic>{};
      _events.add(GatewayEventFrame('server.$method', params['session_id'] as String?, {...params, '_rid': id}));
      if (!method.startsWith('approval')) {
        _send({'jsonrpc': '2.0', 'id': id, 'error': {'code': jsonRpcMethodNotFound, 'message': 'no handler for server request: $method'}});
      }
      return;
    }
    if (id != null) {
      final c = _pending.remove('$id');
      if (c == null || c.isCompleted) return;
      if (f['error'] is Map) {
        final e = f['error'] as Map;
        c.completeError(RpcError((e['code'] as num?)?.toInt() ?? -1, '${e['message'] ?? 'galat gateway'}'));
      } else {
        c.complete(f['result']);
      }
    }
  }

  void _send(Map<String, dynamic> frame) => _ch?.add(jsonEncode(frame));

  void respondServerRequest(dynamic rid, dynamic result) =>
      _send({'jsonrpc': '2.0', 'id': rid, 'result': result});

  Future<dynamic> call(String method, [Map<String, dynamic> params = const {}, Duration timeout = const Duration(seconds: 60)]) async {
    await ensureConnected();
    final id = 'm${++_seq}';
    final c = Completer<dynamic>();
    _pending[id] = c;
    _send({'jsonrpc': '2.0', 'id': id, 'method': method, 'params': params});
    return c.future.timeout(timeout, onTimeout: () {
      _pending.remove(id);
      throw RpcError(0, 'request timed out after ${timeout.inSeconds}s: $method');
    });
  }

  void close() {
    _sub?.cancel();
    _ch?.close();
    _ch = null;
  }
}
