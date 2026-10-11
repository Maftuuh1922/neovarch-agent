// User-facing wording for connection failures. Raw exception text
// ("ClientException with SocketException: Failed host lookup …") is never
// shown on the phone; it maps to one short Indonesian sentence.
import 'dart:async';
import 'dart:convert';

import 'link/link_crypto.dart' show LinkError;
import 'link/tunnel.dart' show TunnelDenied;

/// Thrown by RemoteGateway when no route (LAN, Bluetooth, relay) reaches the PC.
class RemoteUnreachable implements Exception {
  const RemoteUnreachable({this.relayAvailable = false});
  final bool relayAvailable;
  @override
  String toString() => relayAvailable ? 'PC tidak terjangkau. Mencoba lewat relay…' : 'PC tidak terjangkau. Pastikan PC menyala dan Neovarch berjalan.';
}

/// Prefix of a per-device session token the PC hands out after pairing.
const deviceTokenPrefix = 'nvd_';

/// The PC unpaired this phone after it was not used for a while
/// (`remote.pairing_idle_days`, default 30): scan a new QR.
class SessionExpired implements Exception {
  const SessionExpired();
  @override
  String toString() => 'Sesi kedaluwarsa, pasangkan ulang: pindai QR baru di PC.';
}

/// `401 {"code": "session_expired"}` from the PC.
bool isSessionExpiredResponse(int status, String body) {
  if (status != 401) return false;
  try {
    final j = jsonDecode(body);
    return j is Map && j['code'] == 'session_expired';
  } catch (_) {
    return false;
  }
}

/// True for errors that mean "this address/route did not answer" (DNS failure,
/// refused, reset, timeout, TLS), as opposed to an answer from the PC.
bool isNetworkError(Object e) {
  if (e is TimeoutException || e is LinkError || e is RemoteUnreachable) return true;
  final s = '${e.runtimeType} $e';
  return s.contains('SocketException') ||
      s.contains('ClientException') ||
      s.contains('HandshakeException') ||
      s.contains('Failed host lookup') ||
      s.contains('Connection refused') ||
      s.contains('Connection reset') ||
      s.contains('Network is unreachable') ||
      s.contains('WebSocketChannelException') ||
      s.contains('HttpException') ||
      s.contains('koneksi gateway terputus') ||
      s.contains('tidak bisa terhubung ke gateway');
}

/// One Indonesian sentence for [e]; never the raw exception text for network errors.
String friendlyRemoteError(Object e, {bool relayAvailable = false}) {
  if (e is TunnelDenied || e is RemoteUnreachable || e is SessionExpired) return '$e';
  if (isNetworkError(e)) return RemoteUnreachable(relayAvailable: relayAvailable).toString();
  final s = '$e';
  if (s.length > 200) return '${s.substring(0, 200)}…';
  return s;
}
