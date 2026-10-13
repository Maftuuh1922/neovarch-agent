// "Mode ringan": the switch (first thing in Profil › Tampilan), the
// "Mode ringan aktif · Matikan" chip shown while it is on, and the one-time
// suggestion on phones with little RAM.
import 'package:flutter/cupertino.dart' show CupertinoIcons;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../theme/neovarch_mobile_theme.dart';
import '../appearance.dart';
import '../l10n/strings.dart';
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
        secondary: Icon(CupertinoIcons.speedometer, color: look.liteMode ? NV.red : NV.muted),
        title: Text(tr('Mode ringan'), style: TextStyle(fontFamily: NV.sans, fontSize: 15, color: NV.text)),
        subtitle: Text(
          look.liteMode
              ? tr('Aktif: efek kaca (blur) dimatikan, permukaan solid. Matikan untuk mengembalikan kaca dan blur.')
              : tr('Matikan efek kaca (blur) supaya aplikasi lebih lancar di HP dengan RAM kecil.'),
          style: TextStyle(fontFamily: NV.sans, fontSize: 12.5, color: NV.muted, height: 1.35),
        ),
        value: look.liteMode,
        onChanged: (v) => look.setLiteMode(v),
      ),
    );
  }
}

/// "Mode ringan aktif · Matikan": visible only while Mode ringan is on;
/// one tap turns it off (glass and blur come back at once).
class LiteModeChip extends ConsumerWidget {
  const LiteModeChip({super.key, this.margin = const EdgeInsets.fromLTRB(16, 0, 16, 10)});
  final EdgeInsets margin;
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final look = ref.watch(appearanceProvider);
    if (!look.liteMode) return const SizedBox.shrink();
    return Padding(
      padding: margin,
      child: Align(
        alignment: Alignment.centerLeft,
        child: Semantics(
          button: true,
          label: tr('Mode ringan aktif. Ketuk untuk mematikan.'),
          excludeSemantics: true,
          child: Material(
            key: const ValueKey('lite-mode-chip'),
            color: NV.redWash,
            shape: StadiumBorder(side: BorderSide(color: NV.red.withValues(alpha: 0.45))),
            clipBehavior: Clip.antiAlias,
            child: InkWell(
              onTap: () => look.setLiteMode(false),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
                child: Row(mainAxisSize: MainAxisSize.min, children: [
                  Icon(CupertinoIcons.speedometer, size: 15, color: NV.redInk),
                  const SizedBox(width: 6),
                  Flexible(
                    child: Text(tr('Mode ringan aktif'),
                        maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontFamily: NV.sans, fontSize: 13, color: NV.text)),
                  ),
                  Text(' · ', style: TextStyle(fontFamily: NV.sans, fontSize: 13, color: NV.muted)),
                  Text(tr('Matikan'),
                      key: const ValueKey('lite-mode-chip-off'),
                      style: TextStyle(fontFamily: NV.sans, fontSize: 13, fontWeight: FontWeight.w600, color: NV.redInk)),
                ]),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// Shows the suggestion once when this phone has little RAM and Mode ringan
/// is off. [margin] keeps the snackbar above the floating nav bar. It only
/// ever turns Mode ringan on when the user taps "Aktifkan".
Future<void> maybeSuggestLiteMode(BuildContext context, WidgetRef ref, {EdgeInsets? margin}) async {
  final look = ref.read(appearanceProvider);
  final info = await liteSuggestion(look.prefs, liteOn: look.liteMode);
  if (info == null || !context.mounted) return;
  final ram = ramLabel(info);
  ScaffoldMessenger.of(context).showSnackBar(SnackBar(
    key: const ValueKey('lite-suggest'),
    duration: const Duration(seconds: 12),
    margin: margin,
    content: Text('${ram != null ? tr('HP ini punya RAM {ram}. ', {'ram': ram}) : ''}'
        '${tr('Aktifkan Mode ringan agar aplikasi lebih lancar? Bisa dimatikan lagi di Profil (paling atas).')}'),
    action: SnackBarAction(label: tr('Aktifkan'), onPressed: () => ref.read(appearanceProvider).setLiteMode(true)),
  ));
}
