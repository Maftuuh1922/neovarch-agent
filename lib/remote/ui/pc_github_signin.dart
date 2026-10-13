// "Masuk di PC dulu": the phone never asks for a GitHub username, Client ID or
// login. Its profile and friends always follow the GitHub account signed in on
// the paired PC. When the PC is signed out this card says so and offers one
// button that asks the PC to start ITS device flow (`POST /api/social/login`);
// the code is shown here so it can be entered on github.com/login/device from
// the phone or the PC. The PC pushes `social.changed` when it is done and the
// profile appears by itself.
import 'package:flutter/cupertino.dart' show CupertinoIcons;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../theme/neovarch_mobile_theme.dart';
import '../remote_controller.dart';
import 'connect_screen.dart';
import 'nv_widgets.dart';

/// Test seam: opening the verification page.
void Function(Uri url) pcGithubOpenUrl = (url) => launchUrl(url, mode: LaunchMode.externalApplication);

/// Test seam: "Pasang ulang" opens the QR pairing screen (scanning a new QR
/// from the PC replaces this PC's token on the phone).
void Function(BuildContext context) openRepairPairing =
    (context) => Navigator.push(context, MaterialPageRoute<void>(builder: (_) => const ConnectScreen()));

/// The Profil / Teman error banner. "Pasang ulang" only when the PC really
/// refused this phone's pairing token ([RemoteController.socialNeedsRepair]);
/// otherwise just "Ulangi".
class SocialErrorBanner extends ConsumerWidget {
  const SocialErrorBanner({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final r = ref.watch(remoteProvider);
    final msg = r.socialError;
    if (msg == null) return const SizedBox.shrink();
    final retry = TextButton(key: const ValueKey('profile-retry'), onPressed: r.refreshSocial, child: const Text('Ulangi'));
    return NvNotice(msg,
        key: ValueKey(r.socialNeedsRepair ? 'profile-repair' : 'profile-error'),
        action: r.socialNeedsRepair
            ? Column(crossAxisAlignment: CrossAxisAlignment.end, mainAxisSize: MainAxisSize.min, children: [
                TextButton(
                    key: const ValueKey('profile-repair-pair'),
                    onPressed: () => openRepairPairing(context),
                    child: const Text('Pasang ulang')),
                retry,
              ])
            : retry);
  }
}

class PcGithubSignInCard extends ConsumerWidget {
  const PcGithubSignInCard({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final r = ref.watch(remoteProvider);
    final flow = r.socialLogin;
    final pending = flow['state'] == 'pending' && (flow['user_code'] ?? '').toString().isNotEmpty;
    final code = '${flow['user_code'] ?? ''}';
    final uri = '${flow['verification_uri'] ?? 'https://github.com/login/device'}';
    final flowError = flow['state'] == 'error' ? '${flow['error'] ?? 'Gagal masuk, ulangi.'}' : null;
    final error = r.socialLoginError ?? flowError;
    final rejected = r.socialGithubTokenInvalid;
    return NvPanel(
      key: const ValueKey('pc-github-signin'),
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 16),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
        Text(rejected ? 'TOKEN GITHUB DI PC DITOLAK' : 'PC BELUM MASUK KE GITHUB', style: NV.monoLabel(size: 9.5, color: NV.redInk)),
        const SizedBox(height: 6),
        Text(rejected ? 'Masuk GitHub lagi' : 'Masuk di PC dulu', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: NV.text)),
        const SizedBox(height: 4),
        Text(
          rejected
              ? 'GitHub menolak token yang tersimpan di Neovarch PC (kedaluwarsa atau dicabut). '
                  'Sambungan HP ke PC baik-baik saja — tidak perlu pasang ulang, cukup masuk GitHub lagi.'
              : 'Profil, grafik kontribusi, dan teman di HP ini ikut akun GitHub yang masuk di Neovarch PC. '
                  'Tidak perlu username atau login di HP.',
          key: const ValueKey('pc-github-explain'),
          style: TextStyle(fontSize: 13, color: NV.muted, height: 1.4),
        ),
        const SizedBox(height: 12),
        if (pending) ...[
          Text('Buka github.com/login/device (di HP ini atau di PC), lalu masukkan kode:',
              style: TextStyle(fontSize: 13, color: NV.text, height: 1.4)),
          const SizedBox(height: 10),
          Row(children: [
            Expanded(
              child: SelectableText(code,
                  key: const ValueKey('pc-github-code'),
                  style: TextStyle(fontFamily: NV.mono, fontSize: 24, fontWeight: FontWeight.w600, letterSpacing: 2, color: NV.text)),
            ),
            IconButton(
              key: const ValueKey('pc-github-copy'),
              tooltip: 'Salin kode',
              onPressed: () {
                Clipboard.setData(ClipboardData(text: code));
                ScaffoldMessenger.maybeOf(context)?.showSnackBar(const SnackBar(content: Text('Kode disalin')));
              },
              icon: Icon(CupertinoIcons.doc_on_doc, size: 18, color: NV.muted),
            ),
          ]),
          const SizedBox(height: 8),
          FilledButton.icon(
            key: const ValueKey('pc-github-open'),
            onPressed: () {
              Clipboard.setData(ClipboardData(text: code));
              pcGithubOpenUrl(Uri.parse(uri));
            },
            icon: const Icon(CupertinoIcons.arrow_up_right_square, size: 18),
            label: const Text('Buka GitHub & salin kode'),
          ),
          const SizedBox(height: 8),
          Text('Setelah disetujui, profil muncul otomatis di sini.', style: TextStyle(fontSize: 12, color: NV.muted)),
        ] else
          FilledButton.icon(
            key: const ValueKey('pc-github-login'),
            onPressed: r.socialLoginStarting || !r.canStartPcGithubLogin ? null : r.startPcGithubLogin,
            icon: const Icon(CupertinoIcons.desktopcomputer, size: 18),
            label: Text(r.socialLoginStarting ? 'Meminta PC…' : (rejected ? 'Masuk GitHub lagi di PC' : 'Masuk GitHub di PC')),
          ),
        if (error != null) ...[
          const SizedBox(height: 10),
          NvNotice(error, key: const ValueKey('pc-github-error')),
        ],
      ]),
    );
  }
}
