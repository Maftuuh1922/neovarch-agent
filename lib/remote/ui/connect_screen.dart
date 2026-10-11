// "Hubungkan ke PC": scan the desktop's pairing QR or type the gateway
// address + token. Also the first screen after the intro on a fresh phone.
import 'package:flutter/cupertino.dart' show CupertinoIcons;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/platform_caps.dart';
import '../../theme/neovarch_mobile_theme.dart';
import '../../ui/widgets/common.dart';
import '../pairing.dart';
import '../remote_controller.dart';
import '../appearance.dart' show appearanceProvider;
import 'nv_widgets.dart';
import 'remote_background.dart' show NvAccentArt, showAppearanceSheet;
import 'scan_screen.dart';
import '../l10n/strings.dart';

class ConnectScreen extends ConsumerStatefulWidget {
  const ConnectScreen({super.key, this.onboarding = false});
  final bool onboarding;
  @override
  ConsumerState<ConnectScreen> createState() => _ConnectScreenState();
}

class _ConnectScreenState extends ConsumerState<ConnectScreen> {
  final _addr = TextEditingController();
  final _token = TextEditingController();
  final _name = TextEditingController();
  bool _busy = false;
  bool _manual = false;
  bool _showToken = false;
  String? _error;

  @override
  void dispose() {
    _addr.dispose();
    _token.dispose();
    _name.dispose();
    super.dispose();
  }

  Future<void> _pair(GatewayPairing p) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    final err = await ref.read(remoteProvider).pair(p);
    if (!mounted) return;
    setState(() {
      _busy = false;
      _error = err;
    });
    if (err == null) {
      toast(context, tr('Terhubung ke {name}', {'name': p.displayName}));
      if (Navigator.of(context).canPop()) Navigator.of(context).pop();
    }
  }

  Future<void> _scan() async {
    final raw = await Navigator.push<String>(context, MaterialPageRoute(builder: (_) => const ScanScreen()));
    if (raw == null || !mounted) return;
    final p = GatewayPairing.parse(raw);
    if (p == null) {
      setState(() => _error = tr('QR tidak dikenali.'));
      return;
    }
    if (p.token.isEmpty) {
      // A QR with only an address: finish by typing the token.
      setState(() {
        _manual = true;
        _addr.text = p.url;
        _error = tr('QR ini tidak memuat token. Salin token dari PC lalu tekan Hubungkan.');
      });
      return;
    }
    await _pair(p);
  }

  Future<void> _submitManual() async {
    final p = GatewayPairing.parse(_addr.text);
    if (p == null) {
      setState(() => _error = tr('Alamat tidak valid. Contoh: 192.168.1.5:9319'));
      return;
    }
    final token = _token.text.trim().isNotEmpty ? _token.text.trim() : p.token;
    await _pair(p.copyWith(token: token, name: _name.text.trim().isEmpty ? null : _name.text.trim()));
  }

  @override
  Widget build(BuildContext context) {
    final remote = ref.watch(remoteProvider);
    ref.watch(appearanceProvider); // follow live theme changes
    final saved = remote.desktops.items;
    final palette = NvIconButton(
      key: const ValueKey('connect-appearance'),
      icon: CupertinoIcons.paintbrush,
      tooltip: tr('Tampilan'),
      onPressed: () => showAppearanceSheet(context),
    );
    final top = MediaQuery.paddingOf(context).top;
    return Scaffold(
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 520),
          child: ListView(padding: EdgeInsets.fromLTRB(16, widget.onboarding ? top + 16 : 0, 16, 32 + MediaQuery.paddingOf(context).bottom), children: [
            if (!widget.onboarding)
              Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: NvHeader(
                    kicker: 'perangkat · tambah', title: 'Tambah PC', inset: 0, onBack: () => Navigator.of(context).maybePop(), actions: [palette]),
              ),
            // Art plate and intro copy on first run only; "Tambah PC" goes
            // straight to the steps and the pairing actions.
            if (widget.onboarding) ...[
              // Top rail: "Tampilan" (theme + background) before any PC.
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Row(children: [
                  Text('NEOVARCH REMOTE', style: NV.monoLabel(color: NV.muted)),
                  const Spacer(),
                  palette,
                ]),
              ),
              // Dithered art plate (recoloured to the accent) with the wordmark.
              ClipRRect(
                borderRadius: BorderRadius.circular(NV.rCard),
                child: Container(
                  foregroundDecoration: BoxDecoration(borderRadius: BorderRadius.circular(NV.rCard), border: Border.all(color: NV.border)),
                  child: AspectRatio(
                    aspectRatio: 4 / 3,
                    child: Stack(fit: StackFit.expand, children: [
                      const NvAccentArt('assets/art/feat-remote.webp', alignment: Alignment(0.35, 0)),
                      Positioned(
                        left: 14,
                        top: 14,
                        child: Container(
                          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                          decoration: BoxDecoration(color: NV.bg, borderRadius: BorderRadius.circular(999), border: Border.all(color: NV.border)),
                          child: Text('HP = REMOTE · PC = OTAK', style: NV.monoLabel(size: 9.5, color: NV.text)),
                        ),
                      ),
                      Positioned(left: 16, bottom: 14, child: Wordmark(height: 30, color: NV.text, haloColor: NV.red)),
                    ]),
                  ),
                ),
              ),
              const SizedBox(height: 22),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 4),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('REMOTE', style: NV.monoLabel(color: NV.redInk)),
                  const SizedBox(height: 8),
                  Text(tr('Hubungkan ke PC'), style: NV.display(size: 34)),
                  const SizedBox(height: 10),
                  Text(
                    tr('Agen Neovarch berjalan di aplikasi desktop. HP ini hanya remote: kirim perintah, pantau tugas, dan setujui aksi agen dari jaringan yang sama.'),
                    style: TextStyle(fontSize: 17, height: 1.4, letterSpacing: NV.tracking(17), color: NV.muted),
                  ),
                ]),
              ),
              const SizedBox(height: 18),
            ] else
              const SizedBox(height: 6),
            NvPanel(
              padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                for (final (i, t) in [
                  'Buka Neovarch Desktop di PC.',
                  'Masuk ke Pengaturan → Remote / Perangkat, aktifkan akses remote.',
                  'Pindai QR yang muncul, atau ketik alamat dan token-nya di bawah.',
                ].indexed) ...[
                  if (i > 0) Padding(padding: EdgeInsets.symmetric(vertical: 10), child: Divider(height: 1, color: NV.border)),
                  Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Container(
                      width: 26,
                      height: 26,
                      alignment: Alignment.center,
                      decoration: BoxDecoration(color: NV.redWash, shape: BoxShape.circle, border: Border.all(color: NV.darkRed)),
                      child: Text('${i + 1}', style: TextStyle(fontFamily: NV.sans, fontWeight: FontWeight.w600, fontSize: 12.5, color: NV.redInk)),
                    ),
                    const SizedBox(width: 12),
                    Expanded(child: Padding(padding: const EdgeInsets.only(top: 3), child: Text(tr(t), style: TextStyle(fontSize: 14, height: 1.45, color: NV.text)))),
                  ]),
                ],
              ]),
            ),
            const SizedBox(height: 18),
            if (_error != null) ...[NvNotice(_error!), const SizedBox(height: 12)],
            if (canUseCamera)
              FilledButton.icon(
                style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(56)),
                onPressed: _busy ? null : _scan,
                icon: const Icon(CupertinoIcons.qrcode_viewfinder),
                label: Text(tr('Pindai QR dari PC')),
              ),
            const SizedBox(height: 10),
            if (!_manual)
              OutlinedButton.icon(
                style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(52)),
                onPressed: _busy ? null : () => setState(() => _manual = true),
                icon: const Icon(CupertinoIcons.keyboard),
                label: Text(tr('Masukkan alamat & token')),
              )
            else ...[
              const NvSection('manual', padding: EdgeInsets.fromLTRB(4, 10, 4, 12)),
                TextField(
                  controller: _addr,
                  keyboardType: TextInputType.url,
                  autocorrect: false,
                  decoration: InputDecoration(
                    labelText: tr('Alamat gateway PC'),
                    hintText: tr('192.168.1.5:9319 atau tautan pemasangan'),
                    helperText: tr('Port bawaan 9319. Tautan neovarch://pair… juga bisa ditempel di sini.'),
                  ),
                ),
                const SizedBox(height: 10),
                TextField(
                  controller: _token,
                  obscureText: !_showToken,
                  autocorrect: false,
                  decoration: InputDecoration(
                    labelText: tr('Token'),
                    hintText: tr('token dari Remote / Perangkat di PC'),
                    suffixIcon: IconButton(
                      tooltip: tr(_showToken ? 'Sembunyikan' : 'Tampilkan'),
                      icon: Icon(_showToken ? CupertinoIcons.eye_slash : CupertinoIcons.eye),
                      onPressed: () => setState(() => _showToken = !_showToken),
                    ),
                  ),
                ),
                const SizedBox(height: 10),
                TextField(controller: _name, decoration: InputDecoration(labelText: tr('Nama PC (opsional)'), hintText: 'PC Kantor')),
                const SizedBox(height: 14),
                FilledButton(
                  style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(52)),
                  onPressed: _busy ? null : _submitManual,
                  child: Text(tr(_busy ? 'Menghubungkan…' : 'Hubungkan')),
                ),
              ],
            if (_busy) Padding(padding: const EdgeInsets.only(top: 16), child: CenterLoader(label: tr('menghubungi PC…'))),
            if (saved.isNotEmpty) ...[
              const NvSection('pc tersimpan', padding: EdgeInsets.fromLTRB(4, 26, 4, 10)),
              NvList(margin: EdgeInsets.zero, children: [
                for (final d in saved)
                  NvRow(
                    icon: CupertinoIcons.desktopcomputer,
                    title: d.name,
                    subtitle: d.url,
                    mono: true,
                    trailing: Icon(CupertinoIcons.chevron_right, size: 18, color: NV.faint),
                    onTap: () async {
                      await ref.read(remoteProvider).connectTo(d);
                      if (context.mounted && Navigator.of(context).canPop()) Navigator.of(context).pop();
                    },
                  ),
              ]),
            ],
            const SizedBox(height: 22),
            Padding(
              padding: EdgeInsets.symmetric(horizontal: 4),
              child: Text(
                tr('Cukup pindai sekali. Di Wi-Fi yang sama HP tersambung langsung; di luar rumah otomatis lewat relay terenkripsi — tanpa aplikasi tambahan. Kunci disimpan terenkripsi di HP.'),
                style: TextStyle(fontSize: 12.5, height: 1.5, color: NV.faint),
              ),
            ),
          ]),
        ),
      ),
    );
  }
}
