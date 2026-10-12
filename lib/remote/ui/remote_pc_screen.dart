// PC: connection status, what the desktop agent is doing, saved desktops,
// and the phone's own preferences.
import 'package:flutter/cupertino.dart' show CupertinoIcons;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../state/app_controller.dart' show settingsProvider;
import '../../state/settings_controller.dart';
import '../../theme/neovarch_mobile_theme.dart';
import 'remote_intro_screen.dart';
import '../../ui/widgets/common.dart';
import '../pairing.dart';
import '../remote_controller.dart';
import '../remote_gateway.dart';
import 'connect_screen.dart';
import 'nv_widgets.dart';
import 'pc_background_panel.dart';
import 'tailscale_setup_card.dart';
import 'appearance/appearance_section.dart' show NvAppearanceSection;

class RemotePcScreen extends ConsumerWidget {
  const RemotePcScreen({super.key, this.onOpenChat});
  final VoidCallback? onOpenChat;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final r = ref.watch(remoteProvider);
    final s = ref.watch(settingsProvider);
    final d = r.desktop;
    final ok = r.connected;
    final dot = ok ? NV.ok : (r.status == RemoteStatus.failed ? NV.red : NV.warn);
    void open(Widget w) => Navigator.push(context, MaterialPageRoute(builder: (_) => w));
    final version = '${r.serverInfo['version'] ?? ''}';

    return Scaffold(
      body: RefreshIndicator(
        onRefresh: () async {
          if (!ok) await r.reconnect();
          await r.refreshAll();
        },
        child: ListView(padding: EdgeInsets.only(bottom: 24 + MediaQuery.paddingOf(context).bottom), children: [
          const NvHeader(kicker: 'perangkat', title: 'PC'),
          // Status card: the paired desktop at a glance.
          NvPanel(
            margin: const EdgeInsets.symmetric(horizontal: 16),
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 14),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Container(
                  width: 48,
                  height: 48,
                  decoration: BoxDecoration(
                    color: NV.redWash,
                    borderRadius: BorderRadius.circular(NV.rCtl),
                    border: Border.all(color: NV.darkRed),
                  ),
                  child: Icon(CupertinoIcons.desktopcomputer, size: 24, color: NV.red),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(d?.name ?? 'Belum ada PC', maxLines: 1, overflow: TextOverflow.ellipsis, style: NV.display(size: 28)),
                    const SizedBox(height: 4),
                    if (d != null)
                      Text(d.url, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontFamily: NV.mono, fontSize: 11.5, color: NV.muted)),
                  ]),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
                  decoration: BoxDecoration(
                    color: dot.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(999),
                    border: Border.all(color: dot.withValues(alpha: 0.4)),
                  ),
                  child: Row(mainAxisSize: MainAxisSize.min, children: [
                    NvDot(dot, size: 6),
                    const SizedBox(width: 6),
                    Text(ok ? 'ONLINE' : 'OFFLINE', style: NV.monoLabel(size: 9.5, color: dot)),
                  ]),
                ),
              ]),
              const SizedBox(height: 14),
              Divider(height: 1, color: NV.border),
              const SizedBox(height: 14),
              // three numbers in a row
              Row(children: [
                _Stat(label: 'sesi aktif', value: '${r.active.length}'),
                _Stat(label: 'persetujuan', value: '${r.approvals.length}', hot: r.approvals.isNotEmpty),
                _Stat(label: 'versi', value: version.isEmpty ? '—' : version, mono: true),
              ]),
              const SizedBox(height: 12),
              // status on the same column grid as the numbers above:
              // label in column 1, value from column 2, one shared baseline
              Row(crossAxisAlignment: CrossAxisAlignment.baseline, textBaseline: TextBaseline.alphabetic, children: [
                Expanded(child: Text('STATUS', style: NV.monoLabel(size: 9.5))),
                Expanded(
                  flex: 2,
                  child: Text(r.statusLabel,
                      maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 14, color: dot, fontWeight: FontWeight.w500)),
                ),
              ]),
              if (ok && r.gateway != null) ...[
                const SizedBox(height: 8),
                Row(crossAxisAlignment: CrossAxisAlignment.baseline, textBaseline: TextBaseline.alphabetic, children: [
                  Expanded(child: Text('JALUR', style: NV.monoLabel(size: 9.5))),
                  Expanded(
                    flex: 2,
                    child: Row(children: [
                      Flexible(
                        child: Text(
                          key: const ValueKey('pc-route'),
                          '${routeLabel(r.gateway!.activeUrl, transport: r.gateway!.transport)}${r.gateway!.lastRtt != null ? ' · ${r.gateway!.lastRtt!.inMilliseconds} ms' : ''}',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(fontSize: 14, color: NV.text, fontWeight: FontWeight.w500),
                        ),
                      ),
                      const SizedBox(width: 8),
                      RouteChip(r.gateway!.route),
                    ]),
                  ),
                ]),
              ],
              if (r.error != null && !ok) ...[const SizedBox(height: 8), NvNotice(r.error!)],
              const SizedBox(height: 14),
              Row(children: [
                Expanded(
                  // Red only when there is something to do (not connected).
                  child: ok
                      ? OutlinedButton(onPressed: r.reconnect, child: const Text('Sambung ulang', maxLines: 1))
                      : FilledButton(onPressed: d == null ? null : r.reconnect, child: const Text('Sambungkan', maxLines: 1)),
                ),
                if (d != null) ...[
                  const SizedBox(width: 8),
                  Expanded(child: OutlinedButton(onPressed: r.disconnect, child: const Text('Putuskan'))),
                ],
              ]),
            ]),
          ),
          // Tailscale is the primary remote path (v1.4.7): guided steps when the
          // phone cannot use it yet (folded while connected over the LAN).
          if (d != null && r.status != RemoteStatus.connecting)
            TailscaleSetupCard(
              pcUrls: [d.url, ...d.alternates],
              connected: ok,
              route: ok && r.gateway != null ? r.gateway!.route : '',
              onRetry: () async {
                try {
                  await r.reconnect();
                } catch (_) {}
              },
              onScan: () => open(const ConnectScreen()),
            ),
          if (r.active.isNotEmpty) ...[
            NvSection('sedang berjalan di pc', count: r.active.length),
            NvList(children: [
              for (final a in r.active)
                NvRow(
                  icon: a.status == 'running' ? CupertinoIcons.bolt_fill : CupertinoIcons.chat_bubble,
                  accent: a.status == 'running',
                  title: a.title.isNotEmpty ? a.title : a.id,
                  subtitle: '${a.status}${a.model.isNotEmpty ? ' · ${a.model}' : ''}',
                  mono: true,
                  trailing: Icon(CupertinoIcons.chevron_right, size: 18, color: NV.faint),
                  onTap: () async {
                    await r.openActive(a);
                    onOpenChat?.call();
                  },
                ),
            ]),
          ],
          if (ok && r.gateway != null) ...[
            const NvSection('layanan latar'),
            PcBackgroundPanel(api: r.gateway!, onRestarting: r.notePcRestarting),
          ],
          NvSection('pc tersimpan',
              trailing: TextButton.icon(
                onPressed: () => open(const ConnectScreen()),
                icon: const Icon(CupertinoIcons.add, size: 18),
                label: const Text('Tambah'),
              )),
          if (r.desktops.items.isEmpty)
            Padding(
              padding: EdgeInsets.symmetric(horizontal: 20),
              child: Text('Belum ada PC tersimpan.', style: TextStyle(color: NV.muted, fontSize: 13.5)),
            )
          else
            NvList(children: [
              for (final x in r.desktops.items)
                NvRow(
                  icon: x.id == d?.id ? CupertinoIcons.largecircle_fill_circle : CupertinoIcons.circle,
                  accent: x.id == d?.id,
                  title: x.name,
                  subtitle: '${x.url}${x.lastConnected != null ? ' · ${relTime(x.lastConnected!.toIso8601String())}' : ''}',
                  mono: true,
                  onTap: x.id == d?.id ? null : () => r.connectTo(x),
                  trailing: NvIconButton(
                    tooltip: 'Lupakan',
                    icon: CupertinoIcons.trash,
                    size: 36,
                    onPressed: () async {
                      final yes = await confirmDialog(context,
                          title: 'Lupakan ${x.name}?',
                          body: 'Alamat dan token PC ini dihapus dari HP. Untuk memakainya lagi, pindai ulang QR di PC.',
                          confirm: 'Lupakan',
                          destructive: true);
                      if (yes) await r.forget(x);
                    },
                  ),
                ),
            ]),
          const NvSection('hp ini'),
          NvList(children: [
            _SwitchRow(
              icon: CupertinoIcons.bell,
              title: 'Notifikasi persetujuan',
              subtitle: 'Kabari saat agen di PC menunggu persetujuan',
              value: r.notifyApprovals,
              onChanged: r.setNotifyApprovals,
            ),
            if (d != null)
              _SwitchRow(
                key: const ValueKey('pc-bluetooth'),
                icon: CupertinoIcons.bluetooth,
                title: 'Bluetooth',
                subtitle: d.link?.bluetooth != null
                    ? 'Sambung ke PC di dekat Anda tanpa internet'
                    : 'Aktifkan juga Bluetooth di PC (Pengaturan ▸ Remote), lalu sambungkan sekali lewat Wi-Fi',
                value: d.bluetooth,
                onChanged: (v) => r.setBluetooth(v),
              ),
            _SwitchRow(
              icon: CupertinoIcons.lightbulb,
              title: 'Tampilkan proses berpikir',
              subtitle: 'Blok penalaran agen di chat',
              value: s.showReasoning,
              onChanged: (v) => ref.read(settingsProvider).update((x) => x.showReasoning = v),
            ),
            NvRow(
              icon: CupertinoIcons.play_rectangle,
              title: 'Putar ulang intro',
              trailing: Icon(CupertinoIcons.chevron_right, size: 18, color: NV.faint),
              onTap: () => open(const RemoteIntroScreen(replay: true)),
            ),
            NvRow(
              key: const ValueKey('pc-licenses'),
              icon: CupertinoIcons.doc_text,
              title: 'Lisensi sumber terbuka',
              subtitle: 'Font Inter (SIL OFL 1.1), Cupertino Icons (MIT), dan lainnya',
              trailing: Icon(CupertinoIcons.chevron_right, size: 18, color: NV.faint),
              onTap: () => showLicensePage(
                  context: context, applicationName: 'Neovarch Remote', applicationVersion: SettingsController.appVersion),
            ),
          ]),
          const SizedBox(height: 24),
          Center(child: Text('NEOVARCH REMOTE · V${SettingsController.appVersion}', style: NV.monoLabel(size: 9.5, color: NV.faint))),
        ]),
      ),
    );
  }
}

class _Stat extends StatelessWidget {
  const _Stat({required this.label, required this.value, this.hot = false, this.mono = false});
  final String label;
  final String value;
  final bool hot;
  final bool mono;
  @override
  Widget build(BuildContext context) => Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label.toUpperCase(), style: NV.monoLabel(size: 9.5)),
          const SizedBox(height: 4),
          Text(value,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: mono
                  ? TextStyle(fontFamily: NV.mono, fontSize: 15, color: NV.text, height: 1.6)
                  : NV.display(size: 30, color: hot ? NV.red : NV.text)),
        ]),
      );
}

class _SwitchRow extends StatelessWidget {
  const _SwitchRow({super.key, required this.icon, required this.title, required this.subtitle, required this.value, required this.onChanged});
  final IconData icon;
  final String title;
  final String subtitle;
  final bool value;
  final ValueChanged<bool> onChanged;
  @override
  Widget build(BuildContext context) => NvRow(
        icon: icon,
        title: title,
        subtitle: subtitle,
        onTap: () => onChanged(!value),
        trailing: Switch(value: value, onChanged: onChanged),
      );
}

/// How the phone reaches the PC right now: "Langsung (LAN)", "Lewat relay",
/// "Lewat Bluetooth" (or the VPN / host for other direct addresses).
String routeLabel(String url, {String transport = 'lan'}) => switch (transport) {
      'relay' => 'Lewat relay · terenkripsi',
      'bluetooth' => 'Lewat Bluetooth',
      _ => switch (gatewayRoute(url)) {
          'lan' => 'Langsung (LAN) · ${Uri.tryParse(url)?.host ?? url}',
          'tailscale' => 'Langsung (VPN) · ${Uri.tryParse(url)?.host ?? url}',
          _ => 'Langsung · ${Uri.tryParse(url)?.host ?? url}',
        },
    };

/// Short chip text for the status pill.
String transportChip(String transport, String url) => switch (transport) {
      'relay' => 'Lewat relay',
      'bluetooth' => 'Lewat Bluetooth',
      _ => gatewayRoute(url) == 'lan' ? 'Langsung (LAN)' : 'Langsung',
    };

/// Theme picker ("Tampilan"): follow the PC (default) or a local look —
/// liquid glass cards for theme mode, accent (curated swatches, wallpaper
/// colours, HSV custom), corner roundness and the app background. Every
/// change applies live. See lib/remote/ui/appearance/.
class AppearancePanel extends StatelessWidget {
  const AppearancePanel({super.key, this.showFollowPc = true, this.showBackground = true, this.margin = const EdgeInsets.symmetric(horizontal: 16)});
  /// Onboarding hides "Ikuti tema PC" (no PC yet); picking there is a local override.
  final bool showFollowPc;
  /// "Latar belakang" + "Kekuatan kaca" controls.
  final bool showBackground;
  final EdgeInsets margin;
  @override
  Widget build(BuildContext context) => NvAppearanceSection(showFollowPc: showFollowPc, showBackground: showBackground, margin: margin);
}
