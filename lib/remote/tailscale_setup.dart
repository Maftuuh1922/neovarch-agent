// Tailscale is the phone's primary way to reach the PC from anywhere (v1.4.7):
// the built-in relay is not deployed and the LAN only works on the same Wi-Fi.
// This decides which setup step the phone is on (install the Tailscale app,
// sign in with the same account as the PC, turn the VPN on, come back and try
// again) and labels the live route. The planning is pure Dart (unit-tested);
// [TailscalePhone] is the thin Android bridge (MainActivity "tailscaleStatus").
import 'dart:async';

import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;

import 'pairing.dart';

const kTailscalePackage = 'com.tailscale.ipn';
const kTailscaleMarketUri = 'market://details?id=$kTailscalePackage';
const kTailscalePlayUrl = 'https://play.google.com/store/apps/details?id=$kTailscalePackage';

/// What the phone knows about Tailscale right now. null = unknown (not
/// Android, or the platform call failed).
class TailscalePhoneState {
  const TailscalePhoneState({this.installed, this.vpnActive, this.pcReachable, this.pcHasTailscale = false});

  /// The Tailscale app (com.tailscale.ipn) is installed.
  final bool? installed;

  /// A VPN (normally Tailscale's) is up on this phone.
  final bool? vpnActive;

  /// One of the PC's Tailscale addresses answered.
  final bool? pcReachable;

  /// The pairing carries a Tailscale address of the PC (100.x / *.ts.net).
  final bool pcHasTailscale;

  TailscalePhoneState copyWith({bool? installed, bool? vpnActive, bool? pcReachable, bool? pcHasTailscale}) => TailscalePhoneState(
        installed: installed ?? this.installed,
        vpnActive: vpnActive ?? this.vpnActive,
        pcReachable: pcReachable ?? this.pcReachable,
        pcHasTailscale: pcHasTailscale ?? this.pcHasTailscale,
      );
}

/// The four steps of the card, in order.
enum TailscaleStep { install, signIn, connect, retry }

class TailscaleSetupPlan {
  const TailscaleSetupPlan({required this.ready, required this.current, required this.done, required this.message});

  /// The Tailscale route works (nothing to show).
  final bool ready;

  /// The step to highlight.
  final TailscaleStep current;
  final Set<TailscaleStep> done;

  /// One Indonesian sentence for the top of the card.
  final String message;
}

/// Pick the step the user is on. Sign-in cannot be seen from outside the
/// Tailscale app, so "installed but VPN off" points at signing in and
/// connecting (both done in the Tailscale app).
TailscaleSetupPlan planTailscaleSetup(TailscalePhoneState s) {
  if (s.pcReachable == true) {
    return const TailscaleSetupPlan(
        ready: true, current: TailscaleStep.retry, done: {TailscaleStep.install, TailscaleStep.signIn, TailscaleStep.connect}, message: 'Tailscale siap.');
  }
  if (s.installed == false) {
    return const TailscaleSetupPlan(
        ready: false,
        current: TailscaleStep.install,
        done: {},
        message: 'HP ini belum punya Tailscale. Pasang sekali, lalu HP bisa tersambung ke PC dari mana saja.');
  }
  if (s.vpnActive == false) {
    return const TailscaleSetupPlan(
        ready: false,
        current: TailscaleStep.signIn,
        done: {TailscaleStep.install},
        message: 'Tailscale sudah terpasang tetapi belum menyala. Buka Tailscale, masuk dengan akun yang sama seperti di PC, lalu nyalakan.');
  }
  if (!s.pcHasTailscale) {
    return const TailscaleSetupPlan(
        ready: false,
        current: TailscaleStep.retry,
        done: {TailscaleStep.install, TailscaleStep.signIn, TailscaleStep.connect},
        message: 'Tailscale di HP sudah aktif, tetapi QR ini belum berisi alamat Tailscale PC. Nyalakan Tailscale di PC, lalu pindai QR baru.');
  }
  if (s.vpnActive == true) {
    return const TailscaleSetupPlan(
        ready: false,
        current: TailscaleStep.signIn,
        done: {TailscaleStep.install, TailscaleStep.connect},
        message: 'Tailscale di HP menyala, tetapi PC belum terjangkau. Pastikan akunnya sama dengan di PC dan Tailscale di PC menyala.');
  }
  // Unknown platform state: only the probe result is known.
  return const TailscaleSetupPlan(
      ready: false,
      current: TailscaleStep.install,
      done: {},
      message: 'PC belum terjangkau lewat Tailscale. Pasang dan nyalakan Tailscale di HP dan PC dengan akun yang sama.');
}

/// The card is shown while not connected and Tailscale is not ready; once
/// connected over the LAN it shows folded (a hint for when you leave the Wi-Fi).
bool showTailscaleSetup({required bool connected, required String route, required TailscaleSetupPlan plan}) {
  if (plan.ready) return false;
  if (!connected) return true;
  return route == 'lan';
}

/// Status chip for the live route.
String routeChipLabel(String route) => switch (route) {
      'tailscale' => 'Lewat Tailscale',
      'lan' => 'Langsung (LAN)',
      'relay' => 'Lewat relay',
      'bluetooth' => 'Lewat Bluetooth',
      _ => 'Langsung',
    };

/// The PC's Tailscale addresses among [urls] (tailnet IPs first).
List<String> tailscaleUrls(Iterable<String> urls) => [for (final u in orderedGatewayUrls(urls)) if (gatewayRoute(u) == 'tailscale') u];

/// True when any of the PC's Tailscale addresses answers `/api/status` (any
/// HTTP status counts: the PC is there). Never throws.
Future<bool> probeTailscaleUrls(Iterable<String> urls, {http.Client? client, Duration timeout = const Duration(seconds: 3)}) async {
  final list = tailscaleUrls(urls);
  if (list.isEmpty) return false;
  final c = client ?? http.Client();
  try {
    final results = await Future.wait(list.map((u) async {
      try {
        final b = Uri.parse(u);
        await c.get(b.replace(path: '${b.path.replaceAll(RegExp(r'/+$'), '')}/api/status')).timeout(timeout);
        return true;
      } catch (_) {
        return false;
      }
    }));
    return results.contains(true);
  } finally {
    if (client == null) c.close();
  }
}

/// Android bridge (MainActivity "neovarch/device"). Every call is safe off
/// Android: unknown values come back null / false.
class TailscalePhone {
  TailscalePhone({MethodChannel? channel}) : _ch = channel ?? const MethodChannel('neovarch/device');
  final MethodChannel _ch;

  /// {installed, vpn}; nulls when unknown.
  Future<({bool? installed, bool? vpn})> status() async {
    try {
      final m = await _ch.invokeMapMethod<String, dynamic>('tailscaleStatus');
      return (installed: m?['installed'] as bool?, vpn: m?['vpn'] as bool?);
    } catch (_) {
      return (installed: null, vpn: null);
    }
  }

  /// Play Store page of Tailscale (market://, falls back to the https page).
  Future<bool> openStore() async {
    if (await _open('url', kTailscaleMarketUri)) return true;
    return _open('url', kTailscalePlayUrl);
  }

  /// Opens the Tailscale app (false when it is not installed).
  Future<bool> openApp() => _open('app', kTailscalePackage);

  Future<bool> _open(String kind, String target) async {
    try {
      return await _ch.invokeMethod<String>('openIntent', {'kind': kind, 'target': target}) == 'dibuka';
    } catch (_) {
      return false;
    }
  }
}

/// Full check for the card: platform state + a probe of the PC's Tailscale addresses.
Future<TailscalePhoneState> checkTailscale(List<String> pcUrls, {TailscalePhone? phone, http.Client? client}) async {
  final st = await (phone ?? TailscalePhone()).status();
  final hasTs = tailscaleUrls(pcUrls).isNotEmpty;
  final reach = hasTs && st.vpn != false ? await probeTailscaleUrls(pcUrls, client: client) : false;
  return TailscalePhoneState(installed: st.installed, vpnActive: st.vpn, pcReachable: reach, pcHasTailscale: hasTs);
}
