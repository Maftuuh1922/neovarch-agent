// Tailscale-first remote (v1.4.7): connect order, the setup-card plan, the
// route chip, the probe and the dead built-in relay being ignored.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:neovarch_agent/remote/link/link_info.dart';
import 'package:neovarch_agent/remote/pairing.dart';
import 'package:neovarch_agent/remote/tailscale_setup.dart';
import 'package:neovarch_agent/remote/ui/tailscale_setup_card.dart';

void main() {
  group('connect order', () {
    const lan = 'http://192.168.1.5:9319';
    const magic = 'http://pc.tail1234.ts.net:9319';
    const ip = 'http://100.84.12.7:9319';
    const other = 'http://example.com:9319';

    test('Tailscale first: tailnet IP, MagicDNS, LAN, other', () {
      expect(orderedGatewayUrls([lan, other, magic, ip]), [ip, magic, lan, other]);
    });

    test('VPN off: LAN first, then Tailscale', () {
      expect(orderedGatewayUrls([ip, magic, lan], tailscaleFirst: false), [lan, ip, magic]);
    });

    test('a QR whose first address is LAN still tries Tailscale first', () {
      final p = GatewayPairing.parse('neovarch://pair?v=1&url=${Uri.encodeComponent(lan)}&alt=${Uri.encodeComponent(ip)}&token=t')!;
      expect(p.allUrls, [ip, lan]);
    });
  });

  group('built-in relay', () {
    const pcId = 'AAAAAAAAAAAAAAAAAAAAAA';
    final pk = 'B' * 43;

    test('the undeployed default never counts as a relay', () {
      expect(LinkInfo(pcId: pcId, pcPk: pk, relayUrl: 'wss://relay.neovarchlabs.web.id').canRelay, isFalse);
      expect(LinkInfo(pcId: pcId, pcPk: pk, relayUrl: 'wss://relay.neovarchlabs.web.id/').canRelay, isFalse);
      expect(LinkInfo(pcId: pcId, pcPk: pk).canRelay, isFalse);
    });

    test('a self-hosted relay still works', () {
      expect(LinkInfo(pcId: pcId, pcPk: pk, relayUrl: 'wss://relay.saya.example').canRelay, isTrue);
    });
  });

  group('setup plan', () {
    test('not installed → step 1', () {
      final p = planTailscaleSetup(const TailscalePhoneState(installed: false, vpnActive: false, pcHasTailscale: true));
      expect(p.ready, isFalse);
      expect(p.current, TailscaleStep.install);
      expect(p.done, isEmpty);
    });

    test('installed, VPN off → sign in / turn on in the Tailscale app', () {
      final p = planTailscaleSetup(const TailscalePhoneState(installed: true, vpnActive: false, pcHasTailscale: true));
      expect(p.current, TailscaleStep.signIn);
      expect(p.done, {TailscaleStep.install});
    });

    test('VPN on but the QR has no Tailscale address → scan a new QR', () {
      final p = planTailscaleSetup(const TailscalePhoneState(installed: true, vpnActive: true, pcReachable: false));
      expect(p.current, TailscaleStep.retry);
      expect(p.message, contains('QR baru'));
    });

    test('VPN on, PC not reachable → same account', () {
      final p = planTailscaleSetup(const TailscalePhoneState(installed: true, vpnActive: true, pcReachable: false, pcHasTailscale: true));
      expect(p.current, TailscaleStep.signIn);
      expect(p.message, contains('akunnya sama'));
    });

    test('PC reachable → ready (card hidden)', () {
      final p = planTailscaleSetup(const TailscalePhoneState(installed: true, vpnActive: true, pcReachable: true, pcHasTailscale: true));
      expect(p.ready, isTrue);
      expect(showTailscaleSetup(connected: false, route: '', plan: p), isFalse);
    });

    test('card: shown when offline, folded hint on LAN, hidden on Tailscale', () {
      final p = planTailscaleSetup(const TailscalePhoneState(installed: false));
      expect(showTailscaleSetup(connected: false, route: '', plan: p), isTrue);
      expect(showTailscaleSetup(connected: true, route: 'lan', plan: p), isTrue);
      expect(showTailscaleSetup(connected: true, route: 'tailscale', plan: p), isFalse);
    });

    test('route chip', () {
      expect(routeChipLabel('tailscale'), 'Lewat Tailscale');
      expect(routeChipLabel('lan'), 'Langsung (LAN)');
    });
  });

  group('probe', () {
    test('any answer from a Tailscale address counts; LAN addresses are not probed', () async {
      final hit = <String>[];
      final c = MockClient((r) async {
        hit.add(r.url.host);
        return http.Response('{"detail":"unauthorized"}', 401);
      });
      expect(await probeTailscaleUrls(['http://192.168.1.5:9319', 'http://100.84.12.7:9319'], client: c), isTrue);
      expect(hit, ['100.84.12.7']);
    });

    test('no Tailscale address → false without a request', () async {
      var calls = 0;
      final c = MockClient((r) async {
        calls++;
        return http.Response('', 200);
      });
      expect(await probeTailscaleUrls(['http://192.168.1.5:9319'], client: c), isFalse);
      expect(calls, 0);
    });

    test('unreachable → false', () async {
      final c = MockClient((r) async => throw http.ClientException('Network is unreachable'));
      expect(await probeTailscaleUrls(['http://100.84.12.7:9319'], client: c), isFalse);
    });
  });

  group('TailscaleSetupCard', () {
    Future<void> pump(WidgetTester t, TailscalePhoneState st, {bool connected = false, String route = '', Future<void> Function()? onRetry}) async {
      await t.pumpWidget(MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: TailscaleSetupCard(
              pcUrls: const ['http://100.84.12.7:9319'],
              connected: connected,
              route: route,
              onRetry: onRetry ?? () async {},
              check: () async => st,
            ),
          ),
        ),
      ));
      await t.pumpAndSettle();
    }

    testWidgets('not installed: steps + Play Store button', (t) async {
      await pump(t, const TailscalePhoneState(installed: false, vpnActive: false, pcHasTailscale: true));
      expect(find.text('Siapkan Tailscale'), findsOneWidget);
      expect(find.text('Pasang Tailscale'), findsOneWidget);
      expect(find.byKey(const ValueKey('ts-install')), findsOneWidget);
      expect(find.byKey(const ValueKey('ts-open')), findsNothing);
      expect(find.text('Coba lagi'), findsOneWidget);
    });

    testWidgets('installed, VPN off: Buka Tailscale', (t) async {
      await pump(t, const TailscalePhoneState(installed: true, vpnActive: false, pcHasTailscale: true));
      expect(find.byKey(const ValueKey('ts-install')), findsNothing);
      expect(find.byKey(const ValueKey('ts-open')), findsOneWidget);
    });

    testWidgets('ready: nothing shown', (t) async {
      await pump(t, const TailscalePhoneState(installed: true, vpnActive: true, pcReachable: true, pcHasTailscale: true));
      expect(find.text('Siapkan Tailscale'), findsNothing);
    });

    testWidgets('connected over LAN: folded hint, expands on tap', (t) async {
      await pump(t, const TailscalePhoneState(installed: false), connected: true, route: 'lan');
      expect(find.text('Siapkan Tailscale'), findsOneWidget);
      expect(find.text('Pasang Tailscale'), findsNothing);
      await t.tap(find.text('Siapkan Tailscale'));
      await t.pumpAndSettle();
      expect(find.text('Pasang Tailscale'), findsOneWidget);
    });

    testWidgets('Coba lagi re-checks and reconnects', (t) async {
      var retried = 0;
      await pump(t, const TailscalePhoneState(installed: false), onRetry: () async => retried++);
      await t.tap(find.byKey(const ValueKey('ts-retry')));
      await t.pumpAndSettle();
      expect(retried, 1);
    });

    testWidgets('route chip text', (t) async {
      await t.pumpWidget(const MaterialApp(home: Scaffold(body: Center(child: RouteChip('tailscale')))));
      expect(find.text('Lewat Tailscale'), findsOneWidget);
    });
  });
}
