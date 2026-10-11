// Profil & Teman on the phone follows the PC's GitHub account: no username,
// Client ID or login form on the phone; "Masuk di PC dulu" + a button that asks
// the PC to start its own device flow; the profile appears when the PC pushes
// `social.changed`.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:neovarch_agent/data/gateway_client.dart' show GatewayEventFrame;
import 'package:neovarch_agent/remote/appearance.dart';
import 'package:neovarch_agent/remote/remote_controller.dart';
import 'package:neovarch_agent/remote/remote_gateway.dart';
import 'package:neovarch_agent/remote/saved_desktops.dart';
import 'package:neovarch_agent/remote/social_models.dart';
import 'package:neovarch_agent/remote/ui/pc_github_signin.dart';
import 'package:neovarch_agent/remote/ui/profile_header_slot.dart';
import 'package:neovarch_agent/remote/ui/remote_app.dart' show neovarchMobileTheme;
import 'package:neovarch_agent/remote/ui/remote_social_screen.dart';
import 'package:neovarch_agent/state/app_controller.dart' show settingsProvider;
import 'package:neovarch_agent/state/settings_controller.dart';

/// A fake PC core: signed out until [signIn]; `POST /api/social/login` starts
/// a pending device flow (the same code on every tap).
class _FakePc {
  bool signedIn = false;
  bool pending = false;
  final calls = <String>[];

  void signIn() {
    signedIn = true;
    pending = false;
  }

  Map<String, dynamic> get flow => signedIn
      ? {'state': 'done', 'login': 'maftuuh'}
      : pending
          ? {'state': 'pending', 'user_code': 'ABCD-1234', 'verification_uri': 'https://github.com/login/device'}
          : {'state': 'idle'};

  RemoteGateway gateway() => RemoteGateway(
        baseUrl: 'http://192.168.1.20:9319',
        token: 'tok',
        autoReconnect: false,
        httpClient: MockClient((req) async {
          calls.add('${req.method} ${req.url.path}');
          Object out = {};
          switch (req.url.path) {
            case '/api/social/status':
              out = {'signed_in': signedIn, 'login': signedIn ? 'maftuuh' : null, 'client_id_configured': true, 'login_flow': flow};
            case '/api/social/login':
              if (!signedIn) pending = true;
              out = flow;
            case '/api/social/profile':
              out = {
                'login': 'maftuuh',
                'name': 'Maftuh',
                'bio': 'Bikin agen',
                'heatmap': {'start': '2025-10-12', 'end': '2026-10-11', 'counts': [for (var i = 0; i < 365; i++) i % 4]},
                'stack': {'languages': [{'name': 'Dart', 'share': 0.6}, {'name': 'Python', 'share': 0.4}]},
              };
            case '/api/social/friends':
              out = {'signed_in': true, 'friends': [{'login': 'budi', 'name': 'Budi', 'coding': true, 'has_neovarch': true}], 'pending': []};
          }
          return http.Response(jsonEncode(out), 200, headers: {'content-type': 'application/json'});
        }),
      );
}

void main() {
  late SharedPreferences prefs;
  late SettingsController settings;

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    prefs = await SharedPreferences.getInstance();
    settings = SettingsController(prefs);
    await settings.load();
    socialAvatarProvider = (url) => null;
  });

  RemoteController connected(_FakePc pc) => RemoteController(SavedDesktops(prefs)..load())
    ..gateway = pc.gateway()
    ..status = RemoteStatus.connected;

  Widget host(RemoteController r, Widget child) => ProviderScope(
        overrides: [
          settingsProvider.overrideWith((ref) => settings),
          remoteProvider.overrideWith((ref) => r),
          appearanceProvider.overrideWith((ref) => AppearanceController(prefs)),
        ],
        child: MaterialApp(theme: neovarchMobileTheme, home: Scaffold(body: ListView(children: [child]))),
      );

  Future<void> settle(WidgetTester tester) async {
    for (var i = 0; i < 6; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
  }

  group('controller', () {
    test('signed-out PC: login via the PC, then social.changed syncs the profile', () async {
      final pc = _FakePc();
      final r = connected(pc);
      await r.refreshSocial();
      expect(r.socialChecked, isTrue);
      expect(r.socialSignedIn, isFalse);
      expect(r.socialProfile, isNull);

      expect(await r.startPcGithubLogin(), isNull);
      expect(pc.calls, contains('POST /api/social/login'));
      expect(r.socialLogin['state'], 'pending');
      expect(r.socialLogin['user_code'], 'ABCD-1234');

      // the user approves on github.com; the PC pushes social.changed
      pc.signIn();
      r.debugEvent(const GatewayEventFrame('social.changed', null, {'what': 'login', 'state': 'done'}));
      await Future<void>.delayed(const Duration(milliseconds: 50));
      expect(r.socialSignedIn, isTrue);
      expect(r.socialProfile!.login, 'maftuuh');
      expect(r.socialFriends!.friends.single.login, 'budi');
      expect(r.socialLogin, isEmpty);
    });

    test('social.changed refreshes even before the Profil tab was opened', () async {
      final pc = _FakePc()..signIn();
      final r = connected(pc);
      r.debugEvent(const GatewayEventFrame('social.changed', null, {'what': 'profile'}));
      await Future<void>.delayed(const Duration(milliseconds: 50));
      expect(pc.calls, contains('GET /api/social/status'));
      expect(r.socialProfile?.name, 'Maftuh');
    });

    test('not connected: no login attempt', () async {
      final r = RemoteController(SavedDesktops(prefs)..load());
      expect(r.canStartPcGithubLogin, isFalse);
      expect(await r.startPcGithubLogin(), 'Belum terhubung ke PC.');
    });
  });

  group('Profil header', () {
    testWidgets('PC signed out: "Masuk di PC dulu", no username field; button shows the PC code', (tester) async {
      final pc = _FakePc();
      final r = connected(pc);
      await tester.runAsync(r.refreshSocial);
      await tester.pumpWidget(host(r, const ProfileHeaderSlot(autoLoad: false)));
      await settle(tester);
      expect(find.text('Masuk di PC dulu'), findsOneWidget);
      expect(find.byType(TextField), findsNothing);
      expect(find.byKey(const ValueKey('github-login-field')), findsNothing);
      expect(find.textContaining('Client ID'), findsNothing);

      await tester.tap(find.byKey(const ValueKey('pc-github-login')));
      await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 50)));
      await settle(tester);
      expect(find.byKey(const ValueKey('pc-github-code')), findsOneWidget);
      expect(find.text('ABCD-1234'), findsOneWidget);

      Uri? opened;
      pcGithubOpenUrl = (u) => opened = u;
      await tester.tap(find.byKey(const ValueKey('pc-github-open')));
      expect(opened.toString(), 'https://github.com/login/device');

      // the PC finishes the sign-in and pushes social.changed
      pc.signIn();
      r.debugEvent(const GatewayEventFrame('social.changed', null, {'what': 'login', 'state': 'done'}));
      await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 50)));
      await settle(tester);
      expect(find.byKey(const ValueKey('pc-github-signin')), findsNothing);
      expect(find.byKey(const ValueKey('github-header')), findsOneWidget);
      expect(find.text('@maftuuh · lewat PC'), findsOneWidget);
      expect(find.byKey(const ValueKey('contribution-card')), findsOneWidget);
    });

    testWidgets('not connected and nothing synced: points at the PC, no form', (tester) async {
      final r = RemoteController(SavedDesktops(prefs)..load());
      await tester.pumpWidget(host(r, const ProfileHeaderSlot(autoLoad: false)));
      await settle(tester);
      expect(find.byKey(const ValueKey('profile-not-connected')), findsOneWidget);
      expect(find.byType(TextField), findsNothing);
    });

    testWidgets('PC signed in: the synced profile, no edit button', (tester) async {
      final r = connected(_FakePc())
        ..socialChecked = true
        ..socialSignedIn = true
        ..socialProfile = SocialProfile.fromJson({'login': 'maftuuh', 'name': 'Maftuh'});
      await tester.pumpWidget(host(r, const ProfileHeaderSlot(autoLoad: false)));
      await settle(tester);
      expect(find.text('Maftuh'), findsOneWidget);
      expect(find.byKey(const ValueKey('github-edit')), findsNothing);
      expect(find.byType(TextField), findsNothing);
    });

    testWidgets('friends group on the Profil tab does not repeat the sign-in card', (tester) async {
      final r = connected(_FakePc())..socialChecked = true;
      await tester.pumpWidget(host(r, const SocialSection(autoLoad: false, showProfile: false)));
      await settle(tester);
      expect(find.byKey(const ValueKey('social-signed-out')), findsOneWidget);
      expect(find.byKey(const ValueKey('pc-github-signin')), findsNothing);
    });
  });
}
