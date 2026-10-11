// "Mode ringan" switch (Profil › Tampilan) and the one-time suggestion on
// phones with little RAM.
import 'package:flutter/cupertino.dart' show CupertinoIcons;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../theme/neovarch_mobile_theme.dart';
import '../appearance.dart';
import '../lite_mode.dart';
import 'nv_widgets.dart';

class LiteModePanel extends ConsumerWidget {
  const LiteModePanel({super.key, this.margin = const EdgeInsets.symmetric(horizontal: 16)});
  final EdgeInsets margin;
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final look = ref.watch(appearanceProvider);
    return NvPanel(
      key: const ValueKey('lite-mode-panel'),
      margin: margin,
      padding: const EdgeInsets.fromLTRB(14, 6, 14, 10),
      child: SwitchListTile.adaptive(
        key: const ValueKey('lite-mode'),
        contentPadding: EdgeInsets.zero,
        secondary: Icon(CupertinoIcons.speedometer, color: NV.muted),
        title: Text('Mode ringan', style: TextStyle(fontFamily: NV.sans, fontSize: 15, color: NV.text)),
        subtitle: Text(
          look.liteMode
              ? 'Aktif: efek kaca (blur) dimatikan, permukaan solid. Lebih lancar di HP dengan RAM kecil.'
              : 'Matikan efek kaca (blur) supaya aplikasi lebih lancar di HP dengan RAM kecil.',
          style: TextStyle(fontFamily: NV.sans, fontSize: 12.5, color: NV.muted, height: 1.35),
        ),
        value: look.liteMode,
        onChanged: look.setLiteMode,
      ),
    );
  }
}

/// Shows the suggestion once when this phone has little RAM and Mode ringan
/// is off. [margin] keeps the snackbar above the floating nav bar.
Future<void> maybeSuggestLiteMode(BuildContext context, WidgetRef ref, {EdgeInsets? margin}) async {
  final look = ref.read(appearanceProvider);
  final info = await liteSuggestion(look.prefs, liteOn: look.liteMode);
  if (info == null || !context.mounted) return;
  final ram = ramLabel(info);
  ScaffoldMessenger.of(context).showSnackBar(SnackBar(
    key: const ValueKey('lite-suggest'),
    duration: const Duration(seconds: 12),
    margin: margin,
    content: Text('${ram != null ? 'HP ini punya RAM $ram. ' : ''}Aktifkan Mode ringan agar aplikasi lebih lancar? '
        'Bisa diubah lagi di Profil › Tampilan.'),
    action: SnackBarAction(label: 'Aktifkan', onPressed: () => ref.read(appearanceProvider).setLiteMode(true)),
  ));
}
