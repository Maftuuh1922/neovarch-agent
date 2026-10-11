// Raw frame transports for the encrypted link. A FrameLink carries opaque
// text frames to the PC in order; the encryption sits on top (tunnel.dart).
//
//   RelayFrameLink      wss://<relay>/v1/phone/<pcId>   (relay/ in the repo)
//   BluetoothFrameLink  RFCOMM via the app's platform channel (bluetooth_link.dart)
import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/web_socket_channel.dart';

import '../../data/ws_connect.dart';

/// Room status reported by the relay (never sent over Bluetooth).
enum PeerPresence { unknown, online, offline }

abstract class FrameLink {
  /// Frames from the PC (control frames of the transport are filtered out).
  Stream<String> get frames;

  /// PC presence as reported by the transport.
  Stream<PeerPresence> get presence;
  void send(String frame);
  Future<void> close();

  /// Completes when the link is gone (either side).
  Future<void> get done;

  /// 'relay' or 'bluetooth'.
  String get kind;
}

/// Normalise a relay URL as the PC does: https → wss, bare host → wss://host.
String? normalizeRelayUrl(String? url) {
  var u = (url ?? '').trim().replaceAll(RegExp(r'/+$'), '');
  if (u.isEmpty) return null;
  if (u.startsWith('https://')) {
    u = 'wss://${u.substring(8)}';
  } else if (u.startsWith('http://')) {
    u = 'ws://${u.substring(7)}';
  } else if (!u.contains('://')) {
    u = 'wss://$u';
  }
  if (!(u.startsWith('wss://') || u.startsWith('ws://'))) return null;
  return Uri.tryParse(u)?.host.isNotEmpty == true ? u : null;
}

typedef WsConnector = WebSocketChannel Function(Uri uri, Map<String, String> headers);

class RelayFrameLink implements FrameLink {
  RelayFrameLink._(this._ch, this.pingEvery) {
    _sub = _ch.stream.listen((raw) {
      final s = '$raw';
      if (s == 'pong') return;
      if (s.startsWith('{"relay"')) {
        try {
          final m = jsonDecode(s) as Map;
          final st = m['relay'];
          _presence.add(st == 'pc_online' ? PeerPresence.online : st == 'pc_offline' ? PeerPresence.offline : PeerPresence.unknown);
        } catch (_) {}
        return;
      }
      _frames.add(s);
    }, onDone: _finish, onError: (_) => _finish(), cancelOnError: true);
    _ping = Timer.periodic(pingEvery, (_) => send('ping'));
  }

  /// Connect to `<relay>/v1/phone/<pcId>`; throws when the relay does not answer within [timeout].
  static Future<RelayFrameLink> connect(String relayUrl, String pcId,
      {Duration timeout = const Duration(seconds: 8), Duration pingEvery = const Duration(seconds: 25), WsConnector? connector}) async {
    final base = normalizeRelayUrl(relayUrl);
    if (base == null) throw ArgumentError('bad relay url');
    final uri = Uri.parse('$base/v1/phone/${Uri.encodeComponent(pcId)}');
    final ch = (connector ?? connectWs)(uri, const {});
    try {
      await ch.ready.timeout(timeout);
    } catch (e) {
      try {
        unawaited(ch.sink.close());
      } catch (_) {}
      rethrow;
    }
    return RelayFrameLink._(ch, pingEvery);
  }

  final WebSocketChannel _ch;
  final Duration pingEvery;
  late final StreamSubscription _sub;
  late final Timer _ping;
  final _frames = StreamController<String>.broadcast();
  final _presence = StreamController<PeerPresence>.broadcast();
  final _done = Completer<void>();

  @override
  String get kind => 'relay';
  @override
  Stream<String> get frames => _frames.stream;
  @override
  Stream<PeerPresence> get presence => _presence.stream;
  @override
  Future<void> get done => _done.future;

  void _finish() {
    if (_done.isCompleted) return;
    _ping.cancel();
    _done.complete();
    _frames.close();
    _presence.close();
  }

  @override
  void send(String frame) {
    if (_done.isCompleted) return;
    try {
      _ch.sink.add(frame);
    } catch (_) {
      _finish();
    }
  }

  @override
  Future<void> close() async {
    await _sub.cancel();
    try {
      await _ch.sink.close();
    } catch (_) {}
    _finish();
  }
}

/// In-memory pair for tests: what one side sends the other receives.
class MemoryFrameLink implements FrameLink {
  MemoryFrameLink({this.kind = 'relay'});
  @override
  final String kind;
  final _in = StreamController<String>.broadcast();
  final _presence = StreamController<PeerPresence>.broadcast();
  final _done = Completer<void>();
  final sent = <String>[];
  void Function(String frame)? onSend;

  /// Deliver a frame as if it came from the PC.
  void deliver(String frame) {
    if (!_done.isCompleted) _in.add(frame);
  }

  void setPresence(PeerPresence p) => _presence.add(p);

  @override
  Stream<String> get frames => _in.stream;
  @override
  Stream<PeerPresence> get presence => _presence.stream;
  @override
  Future<void> get done => _done.future;
  @override
  void send(String frame) {
    if (_done.isCompleted) return;
    sent.add(frame);
    onSend?.call(frame);
  }

  @override
  Future<void> close() async {
    if (_done.isCompleted) return;
    _done.complete();
    await _in.close();
    await _presence.close();
  }
}
