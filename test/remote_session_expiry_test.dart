import 'package:flutter_test/flutter_test.dart';
import 'package:neovarch_agent/remote/link/tunnel.dart';
import 'package:neovarch_agent/remote/remote_errors.dart';

void main() {
  test('401 session_expired from the PC is recognised', () {
    expect(isSessionExpiredResponse(401, '{"detail":"Sesi kedaluwarsa, pasangkan ulang","code":"session_expired"}'), isTrue);
    expect(isSessionExpiredResponse(401, '{"detail":"Unauthorized"}'), isFalse);
    expect(isSessionExpiredResponse(200, '{"code":"session_expired"}'), isFalse);
    expect(isSessionExpiredResponse(401, 'not json'), isFalse);
  });

  test('expired sessions get one clear Indonesian sentence', () {
    expect(friendlyRemoteError(const SessionExpired()), startsWith('Sesi kedaluwarsa, pasangkan ulang'));
    expect(const TunnelDenied('expired').toString(), startsWith('Sesi kedaluwarsa, pasangkan ulang'));
    expect('nvd_abc'.startsWith(deviceTokenPrefix), isTrue);
  });
}
