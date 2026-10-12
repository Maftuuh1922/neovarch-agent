// PC screen ▸ "Layanan latar": whether the PC keeps Neovarch running after its
// window is closed, the service status, and stop / restart for the agent and
// the gateway. Talks to /api/remote/background (core/neovarch/background.py).
import 'package:flutter/cupertino.dart' show CupertinoIcons;
import 'package:flutter/material.dart';

import '../../theme/neovarch_mobile_theme.dart';
import '../../ui/widgets/common.dart';
import '../pc_background.dart';
import '../remote_gateway.dart' show RemoteRestError;
import 'nv_widgets.dart';

class PcBackgroundPanel extends StatefulWidget {
  const PcBackgroundPanel({super.key, required this.api, this.onRestarting});
  /// A restart was asked for: the chat shows "PC sedang restart…" and reconnects.
  final VoidCallback? onRestarting;
  final PcBackgroundApi api;

  @override
  State<PcBackgroundPanel> createState() => _PcBackgroundPanelState();
}

class _PcBackgroundPanelState extends State<PcBackgroundPanel> {
  PcBackgroundStatus? _st;
  String? _error;
  String? _message;
  bool _busy = false;
  bool _unsupported = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(covariant PcBackgroundPanel old) {
    super.didUpdateWidget(old);
    if (old.api != widget.api) _load();
  }

  Future<void> _load() async {
    try {
      final st = await widget.api.backgroundStatus();
      if (!mounted) return;
      setState(() {
        _st = st;
        _error = null;
        _unsupported = false;
      });
    } on RemoteRestError catch (e) {
      if (!mounted) return;
      setState(() {
        _unsupported = e.status == 404;
        _error = e.status == 404 ? null : e.message;
      });
    } catch (e) {
      if (mounted) setState(() => _error = 'Status layanan latar tidak bisa dibaca: $e');
    }
  }

  Future<void> _run(Future<void> Function() fn) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _message = null;
    });
    try {
      await fn();
      if (mounted) setState(() => _error = null);
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _set({bool? runInBackground, bool? startAtLogin}) => _run(() async {
        final st = await widget.api.setBackground(runInBackground: runInBackground, startAtLogin: startAtLogin);
        if (!mounted) return;
        setState(() {
          _st = st;
          if (st.willStop) _message = 'Aplikasi PC sedang tertutup, jadi gateway dihentikan sekarang.';
        });
      });

  Future<void> _action(PcBackgroundAction a) async {
    if (a == PcBackgroundAction.stopGateway || a == PcBackgroundAction.restartGateway) {
      final stop = a == PcBackgroundAction.stopGateway;
      final yes = await confirmDialog(context,
          title: stop ? 'Hentikan gateway di PC?' : 'Mulai ulang gateway di PC?',
          body: stop
              ? 'HP akan terputus dan tidak bisa menyalakannya lagi dari jauh. Untuk memulai lagi, buka aplikasi Neovarch di PC.'
              : 'HP terputus beberapa detik lalu tersambung lagi sendiri. Agen yang sedang berjalan ikut berhenti.',
          confirm: stop ? 'Hentikan' : 'Mulai ulang',
          destructive: stop);
      if (!yes) return;
    }
    if (a == PcBackgroundAction.restartGateway || a == PcBackgroundAction.restartAgent) widget.onRestarting?.call();
    await _run(() async {
      final msg = await widget.api.backgroundAction(a);
      if (mounted) setState(() => _message = msg);
      if (a == PcBackgroundAction.stopAgent || a == PcBackgroundAction.restartAgent) await _load();
    });
  }

  @override
  Widget build(BuildContext context) {
    if (_unsupported) {
      return const Padding(
        padding: EdgeInsets.symmetric(horizontal: 16),
        child: NvNotice('Perbarui aplikasi Neovarch di PC untuk mengatur layanan latar dari HP.', icon: CupertinoIcons.info),
      );
    }
    final st = _st;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      NvList(children: [
        NvRow(
          key: const ValueKey('pc-bg-status'),
          icon: CupertinoIcons.waveform_path_ecg,
          accent: st != null && st.serviceState == 'running',
          title: st == null ? 'Memuat status…' : st.serviceLabel,
          subtitle: st == null
              ? null
              : 'aktif ${st.uptimeLabel} · ${st.runningAgents}/${st.sessions} agen berjalan'
                  '${st.relayState == 'online' ? ' · relay online' : ''}',
          trailing: IconButton(
            tooltip: 'Muat ulang',
            onPressed: _busy ? null : _load,
            icon: const Icon(CupertinoIcons.refresh, size: 18),
          ),
        ),
        NvRow(
          key: const ValueKey('pc-bg-run'),
          icon: CupertinoIcons.moon_stars,
          title: 'Jalan di latar',
          subtitle: 'Gateway & relay tetap hidup saat jendela PC ditutup',
          onTap: st == null || _busy ? null : () => _set(runInBackground: !st.runInBackground),
          trailing: Switch(
            value: st?.runInBackground ?? false,
            onChanged: st == null || _busy ? null : (v) => _set(runInBackground: v),
          ),
        ),
        NvRow(
          key: const ValueKey('pc-bg-login'),
          icon: CupertinoIcons.power,
          title: 'Mulai saat login',
          subtitle: 'Neovarch terbuka (di tray) saat masuk ke PC',
          onTap: st == null || _busy ? null : () => _set(startAtLogin: !st.startAtLogin),
          trailing: Switch(
            value: st?.startAtLogin ?? false,
            onChanged: st == null || _busy ? null : (v) => _set(startAtLogin: v),
          ),
        ),
      ]),
      const SizedBox(height: 10),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: Wrap(spacing: 8, runSpacing: 8, children: [
          for (final a in PcBackgroundAction.values)
            OutlinedButton(
              key: ValueKey('pc-bg-${a.wire}'),
              onPressed: st == null || _busy ? null : () => _action(a),
              child: Text(a.label, maxLines: 1),
            ),
        ]),
      ),
      if (_message != null) ...[
        const SizedBox(height: 8),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 20),
          child: Text(_message!, key: const ValueKey('pc-bg-message'), style: TextStyle(fontSize: 13, color: NV.muted)),
        ),
      ],
      if (_error != null) ...[
        const SizedBox(height: 8),
        Padding(padding: const EdgeInsets.symmetric(horizontal: 16), child: NvNotice(_error!)),
      ],
    ]);
  }
}
