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
import 'nv_widgets.dart';

/// Test seam: opening the verification page.
void Function(Uri url) pcGithubOpenUrl = (url) => launchUrl(url, mode: LaunchMode.externalApplication);

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
    return NvPanel(
      key: const ValueKey('pc-github-signin'),
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 16),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
        Text('PC BELUM MASUK KE GITHUB', style: NV.monoLabel(size: 9.5, color: NV.redInk)),
        const SizedBox(height: 6),
        Text('Masuk di PC dulu', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: NV.text)),
        const SizedBox(height: 4),
        Text(
          'Profil, grafik kontribusi, dan teman di HP ini ikut akun GitHub yang masuk di Neovarch PC. '
          'Tidak perlu username atau login di HP.',
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
            label: Text(r.socialLoginStarting ? 'Meminta PC…' : 'Masuk GitHub di PC'),
          ),
        if (error != null) ...[
          const SizedBox(height: 10),
          NvNotice(error, key: const ValueKey('pc-github-error')),
        ],
      ]),
    );
  }
}
