// "Siapkan Tailscale": the guided steps on the PC tab when the phone cannot use
// Tailscale yet (v1.4.7, Tailscale is the primary remote path). Re-checks by
// itself when the app comes back to the foreground (after the Play Store or the
// Tailscale app).
import 'dart:async';

import 'package:flutter/cupertino.dart' show CupertinoIcons;
import 'package:flutter/material.dart';

import '../../theme/neovarch_mobile_theme.dart';
import '../tailscale_setup.dart';
import 'nv_widgets.dart';

class TailscaleSetupCard extends StatefulWidget {
  const TailscaleSetupCard({
    super.key,
    required this.pcUrls,
    required this.connected,
    required this.route,
    required this.onRetry,
    this.onScan,
    this.check,
    this.phone,
  });

  /// Every address of the paired PC (QR url + alternates).
  final List<String> pcUrls;
  final bool connected;

  /// `lan` / `tailscale` / `relay` / … of the live connection.
  final String route;

  /// "Coba lagi": reconnect to the PC.
  final Future<void> Function() onRetry;

  /// "Pindai QR": open the scanner (a new QR carries the PC's Tailscale address).
  final VoidCallback? onScan;

  /// Test seam (default: [checkTailscale]).
  final Future<TailscalePhoneState> Function()? check;
  final TailscalePhone? phone;

  @override
  State<TailscaleSetupCard> createState() => _TailscaleSetupCardState();
}

class _TailscaleSetupCardState extends State<TailscaleSetupCard> with WidgetsBindingObserver {
  TailscalePhoneState? _state;
  bool _checking = false;
  bool? _expanded; // null = follow connected (folded while connected over LAN)
  late final TailscalePhone _phone = widget.phone ?? TailscalePhone();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    unawaited(_recheck());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) unawaited(_recheck(retryWhenReady: true));
  }

  @override
  void didUpdateWidget(covariant TailscaleSetupCard old) {
    super.didUpdateWidget(old);
    if (old.connected != widget.connected || old.pcUrls.join(',') != widget.pcUrls.join(',')) {
      scheduleMicrotask(() {
        if (mounted) unawaited(_recheck());
      });
    }
  }

  Future<void> _recheck({bool retryWhenReady = false}) async {
    if (_checking) return;
    _checking = true;
    if (_state != null && mounted) setState(() {});
    TailscalePhoneState next;
    try {
      next = await (widget.check ?? () => checkTailscale(widget.pcUrls, phone: _phone))();
    } catch (_) {
      next = const TailscalePhoneState();
    }
    if (!mounted) return;
    setState(() {
      _state = next;
      _checking = false;
    });
    // Came back from the Tailscale app with the PC reachable: connect right away.
    if (retryWhenReady && !widget.connected && planTailscaleSetup(next).ready) unawaited(widget.onRetry());
  }

  Future<void> _retry() async {
    await _recheck();
    await widget.onRetry();
  }

  @override
  Widget build(BuildContext context) {
    final st = _state;
    if (st == null) return const SizedBox.shrink();
    final plan = planTailscaleSetup(st);
    if (!showTailscaleSetup(connected: widget.connected, route: widget.route, plan: plan)) return const SizedBox.shrink();
    final expanded = _expanded ?? !widget.connected;

    return NvPanel(
      key: const ValueKey('tailscale-setup'),
      margin: const EdgeInsets.fromLTRB(16, 12, 16, 0),
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        InkWell(
          onTap: () => setState(() => _expanded = !expanded),
          child: Row(children: [
            Icon(CupertinoIcons.lock_shield, size: 20, color: NV.red),
            const SizedBox(width: 10),
            Expanded(child: Text('Siapkan Tailscale', style: TextStyle(fontSize: 15.5, fontWeight: FontWeight.w600, color: NV.text))),
            if (_checking) SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 1.6, color: NV.muted)),
            const SizedBox(width: 6),
            Icon(expanded ? CupertinoIcons.chevron_up : CupertinoIcons.chevron_down, size: 16, color: NV.faint),
          ]),
        ),
        const SizedBox(height: 6),
        Text(
          widget.connected ? 'Sekarang tersambung lewat Wi‑Fi. Siapkan Tailscale agar tetap tersambung saat keluar rumah.' : plan.message,
          style: TextStyle(fontSize: 13, height: 1.35, color: NV.muted),
        ),
        if (expanded) ...[
          const SizedBox(height: 12),
          _Step(
            n: 1,
            title: 'Pasang Tailscale',
            done: plan.done.contains(TailscaleStep.install),
            current: plan.current == TailscaleStep.install,
            action: st.installed == true
                ? null
                : _ActionButton(key: const ValueKey('ts-install'), label: 'Buka Play Store', onTap: () => unawaited(_phone.openStore())),
          ),
          _Step(
            n: 2,
            title: 'Masuk dengan akun yang sama seperti di PC',
            done: plan.done.contains(TailscaleStep.signIn),
            current: plan.current == TailscaleStep.signIn,
          ),
          _Step(
            n: 3,
            title: 'Nyalakan koneksi',
            done: plan.done.contains(TailscaleStep.connect),
            current: plan.current == TailscaleStep.connect || plan.current == TailscaleStep.signIn,
            action: st.installed == false
                ? null
                : _ActionButton(key: const ValueKey('ts-open'), label: 'Buka Tailscale', onTap: () => unawaited(_phone.openApp())),
          ),
          _Step(
            n: 4,
            title: 'Kembali ke sini, tekan Coba lagi atau pindai QR baru',
            done: false,
            current: plan.current == TailscaleStep.retry,
            last: true,
          ),
          const SizedBox(height: 10),
          Row(children: [
            Expanded(
              child: FilledButton(
                key: const ValueKey('ts-retry'),
                onPressed: _checking ? null : () => unawaited(_retry()),
                child: const Text('Coba lagi', maxLines: 1),
              ),
            ),
            if (widget.onScan != null) ...[
              const SizedBox(width: 8),
              Expanded(child: OutlinedButton(onPressed: widget.onScan, child: const Text('Pindai QR', maxLines: 1))),
            ],
          ]),
        ],
      ]),
    );
  }
}

class _Step extends StatelessWidget {
  const _Step({required this.n, required this.title, required this.done, required this.current, this.action, this.last = false});
  final int n;
  final String title;
  final bool done, current, last;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final color = done ? NV.ok : (current ? NV.red : NV.faint);
    return Padding(
      padding: EdgeInsets.only(bottom: last ? 0 : 10),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(
          width: 22,
          height: 22,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: color.withValues(alpha: done || current ? 0.14 : 0.06),
            border: Border.all(color: color.withValues(alpha: 0.5)),
          ),
          child: done
              ? Icon(CupertinoIcons.checkmark, size: 12, color: color)
              : Text('$n', style: NV.monoLabel(size: 10, color: color)),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Text(title,
                  style: TextStyle(
                      fontSize: 13.5,
                      color: done ? NV.muted : NV.text,
                      fontWeight: current ? FontWeight.w600 : FontWeight.w400,
                      decoration: done ? TextDecoration.lineThrough : null)),
            ),
            if (action != null && !done) ...[const SizedBox(height: 6), action!],
          ]),
        ),
      ]),
    );
  }
}

class _ActionButton extends StatelessWidget {
  const _ActionButton({super.key, required this.label, required this.onTap});
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => OutlinedButton(
        onPressed: onTap,
        style: OutlinedButton.styleFrom(minimumSize: const Size(0, 34), padding: const EdgeInsets.symmetric(horizontal: 12)),
        child: Text(label, maxLines: 1),
      );
}

/// "Lewat Tailscale" / "Langsung (LAN)" chip for the live route.
class RouteChip extends StatelessWidget {
  const RouteChip(this.route, {super.key});
  final String route;

  @override
  Widget build(BuildContext context) {
    final c = route == 'tailscale' ? NV.ok : NV.muted;
    return Container(
      key: const ValueKey('route-chip'),
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: c.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: c.withValues(alpha: 0.35)),
      ),
      child: Text(routeChipLabel(route), style: NV.monoLabel(size: 9.5, color: c)),
    );
  }
}
