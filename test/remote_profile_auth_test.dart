// Profil & Teman after 1.4.7: "token ditolak oleh PC — pasangkan ulang" while
// chat on the same phone was connected. The PC's social routes answered
// GitHub-side sign-in problems (GitHub refused the PC's stored token, or the
// PC is signed out of GitHub) with HTTP 401 + a `code`, and the phone read
// every 401/403 as "the PC refused my pairing token". Only the core's auth
// middleware answers without a `code`; that alone is a pairing problem and
// only then the banner offers "Pasang ulang".
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:neovarch_agent/remote/appearance.dart';
import 'package:neovarch_agent/remote/remote_controller.dart';
import 'package:neovarch_agent/remote/remote_errors.dart';
import 'package:neovarch_agent/remote/remote_gateway.dart';
import 'package:neovarch_agent/remote/saved_desktops.dart';
import 'package:neovarch_agent/remote/ui/pc_github_signin.dart';
import 'package:neovarch_agent/remote/ui/profile_header_slot.dart';
import 'package:neovarch_agent/remote/ui/remote_app.dart' show neovarchMobileTheme;
import 'package:neovarch_agent/state/app_controller.dart' show settingsProvider;
import 'package:neovarch_agent/state/settings_controller.dart';

typedef _Reply = (int, Map<String, dynamic>);

class _Pc {
  _Pc(this.routes);
  final Map<String, _Reply> routes;
  final seen = <http.BaseRequest>[];
  final bodies = <String>[];

  RemoteGateway gateway() => RemoteGateway(
        baseUrl: 'http://192.168.1.20:9319',
        token: 'nvd_live_session_token',
        autoReconnect: false,
        httpClient: MockClient((req) async {
          seen.add(req);
          bodies.add(req.body);
          final (status, body) = routes['${req.method} ${req.url.path}'] ?? (404, {'detail': 'nope'});
          return http.Response(jsonEncode(body), status, headers: {'content-type': 'application/json'});
        }),
      );
}

// What cores ≤ 1.4.7 answered when GitHub refused the PC's token / it is signed out.
const _oldGithubRejected = (401, {'detail': 'Token GitHub tidak valid lagi; masuk ulang.', 'code': 'unauthorized'});
const _oldSignedOut = (401, {'detail': 'Belum masuk dengan GitHub.', 'code': 'signed_out'});
// The core's auth middleware: the pairing token really is refused.
const _middleware401 = (401, {'detail': 'Unauthorized'});

void main() {
  test('isPairingRejected: only a 401/403 without a route code is the pairing', () {
    expect(isPairingRejected(401, '{"detail":"Unauthorized"}'), isTrue);
    expect(isPairingRejected(403, ''), isTrue);
    expect(isPairingRejected(401, '{"detail":"x","code":"unauthorized"}'), isFalse);
    expect(isPairingRejected(401, '{"detail":"x","code":"signed_out"}'), isFalse);
    expect(isPairingRejected(409, '{"detail":"x"}'), isFalse);
    expect(isPairingRejected(200, '{}'), isFalse);
  });

  group('gateway', () {
    test('a GitHub-side 401 from an old core is not "pasangkan ulang"', () async {
      final pc = _Pc({'GET /api/social/profile': _oldGithubRejected});
      final g = pc.gateway();
      final e = await g.socialProfile().then<RemoteRestError?>((_) => null, onError: (Object e) => e as RemoteRestError);
      expect(e, isNotNull);
      expect(e!.pairingRejected, isFalse);
      expect(e.code, 'unauthorized');
      expect(e.message, isNot(contains('pasangkan ulang')));
      // the REST call carried the same live session token as the chat socket
      expect(pc.seen.single.headers['Authorization'], 'Bearer nvd_live_session_token');
      await g.close();
    });

    test('the middleware 401 is a real pairing rejection', () async {
      final pc = _Pc({'GET /api/social/status': _middleware401});
      final g = pc.gateway();
      final e = await g.socialStatus().then<RemoteRestError?>((_) => null, onError: (Object e) => e as RemoteRestError);
      expect(e!.pairingRejected, isTrue);
      expect(e.message, kPairingRejectedMessage);
      await g.close();
    });

    test('socialLoginStart(force: true) asks the PC to restart its device flow', () async {
      final pc = _Pc({'POST /api/social/login': (200, {'state': 'pending', 'user_code': 'ABCD-1234'})});
      final g = pc.gateway();
      await g.socialLoginStart(force: true);
      expect(jsonDecode(pc.bodies.single), {'force': true});
      await g.socialLoginStart();
      expect(jsonDecode(pc.bodies.last), <String, dynamic>{});
      await g.close();
    });
  });

  group('controller', () {
    late SharedPreferences prefs;
    setUp(() async {
      SharedPreferences.setMockInitialValues({});
      prefs = await SharedPreferences.getInstance();
    });

    RemoteController ctl(_Pc pc) => RemoteController(SavedDesktops(prefs)..load())
      ..gateway = pc.gateway()
      ..status = RemoteStatus.connected;

    test('old core: GitHub refused the PC token -> sign-in card, no pairing banner', () async {
      final r = ctl(_Pc({
        'GET /api/social/status': (200, {'signed_in': true, 'login': 'aku'}),
        'GET /api/social/profile': _oldGithubRejected,
        'GET /api/social/friends': _oldGithubRejected,
      }));
      await r.refreshSocial();
      expect(r.socialError, isNull);
      expect(r.socialNeedsRepair, isFalse);
      expect(r.socialSignedIn, isFalse);
      expect(r.socialChecked, isTrue);
      expect(r.socialGithubTokenInvalid, isTrue);
    });

    test('old core: signed out of GitHub -> plain sign-in card', () async {
      final r = ctl(_Pc({
        'GET /api/social/status': (200, {'signed_in': true}),
        'GET /api/social/profile': _oldSignedOut,
        'GET /api/social/friends': _oldSignedOut,
      }));
      await r.refreshSocial();
      expect(r.socialError, isNull);
      expect(r.socialSignedIn, isFalse);
      expect(r.socialGithubTokenInvalid, isFalse);
    });

    test('new core: status says the GitHub token is invalid', () async {
      final pc = _Pc({
        'GET /api/social/status': (200, {'signed_in': false, 'github_token_invalid': true, 'login': 'aku', 'login_flow': {'state': 'idle'}}),
        'POST /api/social/login': (200, {'state': 'pending', 'user_code': 'WXYZ-9876'}),
      });
      final r = ctl(pc);
      await r.refreshSocial();
      expect(r.socialGithubTokenInvalid, isTrue);
      expect(r.socialError, isNull);
      await r.startPcGithubLogin();
      expect(jsonDecode(pc.bodies.last), {'force': true}); // old cores keep the token without force
      expect(r.socialLogin['user_code'], 'WXYZ-9876');
    });

    test('real pairing rejection -> banner with "Pasang ulang"', () async {
      final r = ctl(_Pc({'GET /api/social/status': _middleware401}));
      await r.refreshSocial();
      expect(r.socialNeedsRepair, isTrue);
      expect(r.socialError, kPairingRejectedMessage);
    });

    test('signed in and auth valid -> no banner at all', () async {
      final r = ctl(_Pc({
        'GET /api/social/status': (200, {'signed_in': true, 'login': 'aku'}),
        'GET /api/social/profile': (200, {'login': 'aku', 'name': 'Aku'}),
        'GET /api/social/friends': (200, {'signed_in': true, 'friends': [], 'pending': []}),
      }));
      await r.refreshSocial();
      expect(r.socialError, isNull);
      expect(r.socialNeedsRepair, isFalse);
      expect(r.socialSignedIn, isTrue);
      expect(r.socialProfile!.login, 'aku');
    });
  });

  group('screen', () {
    late SharedPreferences prefs;
    late SettingsController settings;
    setUp(() async {
      SharedPreferences.setMockInitialValues({});
      prefs = await SharedPreferences.getInstance();
      settings = SettingsController(prefs);
      await settings.load();
    });

    Widget host(RemoteController r) => ProviderScope(
          overrides: [
            settingsProvider.overrideWith((ref) => settings),
            remoteProvider.overrideWith((ref) => r),
            appearanceProvider.overrideWith((ref) => AppearanceController(prefs)),
          ],
          child: MaterialApp(
              theme: neovarchMobileTheme,
              home: const Scaffold(body: SingleChildScrollView(child: ProfileHeaderSlot(autoLoad: false)))),
        );

    RemoteController ctl(_Pc pc) => RemoteController(SavedDesktops(prefs)..load())
      ..gateway = pc.gateway()
      ..status = RemoteStatus.connected;

    testWidgets('GitHub refused the PC token: "Masuk GitHub lagi", no pasangkan ulang', (tester) async {
      final r = ctl(_Pc({
        'GET /api/social/status': (200, {'signed_in': true}),
        'GET /api/social/profile': _oldGithubRejected,
        'GET /api/social/friends': _oldGithubRejected,
      }));
      await tester.runAsync(r.refreshSocial);
      await tester.pumpWidget(host(r));
      await tester.pump();
      expect(find.text('Masuk GitHub lagi'), findsOneWidget);
      expect(find.text('Masuk GitHub lagi di PC'), findsOneWidget);
      expect(find.textContaining('pasangkan ulang'), findsNothing);
      expect(find.text('Pasang ulang'), findsNothing);
      expect(find.byKey(const ValueKey('profile-repair')), findsNothing);
    });

    testWidgets('pairing really refused: "Pasang ulang" opens pairing', (tester) async {
      var opened = 0;
      final prev = openRepairPairing;
      openRepairPairing = (_) => opened++;
      addTearDown(() => openRepairPairing = prev);
      final r = ctl(_Pc({'GET /api/social/status': _middleware401}));
      await tester.runAsync(r.refreshSocial);
      await tester.pumpWidget(host(r));
      await tester.pump();
      expect(find.byKey(const ValueKey('profile-repair')), findsOneWidget);
      expect(find.text('Ulangi'), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('profile-repair-pair')));
      await tester.pump();
      expect(opened, 1);
    });
  });
}
