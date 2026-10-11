// "Bahasa" picker: Profil › Bahasa (with "Ikuti sistem") and the first intro
// step (Bahasa Indonesia / English, the phone's language preselected). Both
// write the same setting ([AppLanguageController]); the UI switches at once.
import 'package:flutter/cupertino.dart' show CupertinoIcons;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../theme/neovarch_mobile_theme.dart';
import '../l10n/app_language.dart';
import '../l10n/strings.dart';
import 'nv_widgets.dart';

/// Option label in its own language (so it is readable whatever is active).
String languageName(AppLanguage l) => switch (l) {
      AppLanguage.system => tr('Ikuti sistem'),
      AppLanguage.id => 'Bahasa Indonesia',
      AppLanguage.en => 'English',
    };

class LanguagePanel extends ConsumerWidget {
  const LanguagePanel({super.key, this.showSystem = true, this.margin = const EdgeInsets.symmetric(horizontal: 16)});

  /// Intro: only the two languages; the phone's language is the preselected one.
  final bool showSystem;
  final EdgeInsets margin;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final lang = ref.watch(appLanguageProvider);
    final options = [if (showSystem) AppLanguage.system, AppLanguage.id, AppLanguage.en];
    // Without "Ikuti sistem" the selected row is the language in effect.
    final selected = showSystem || lang.choice != AppLanguage.system ? lang.choice : AppLanguage.values.byName(lang.code);
    return NvList(
      margin: margin,
      children: [
        for (final l in options)
          NvRow(
            key: ValueKey('language-${l.name}'),
            icon: l == AppLanguage.system ? CupertinoIcons.device_phone_portrait : CupertinoIcons.globe,
            title: languageName(l),
            subtitle: l == AppLanguage.system
                ? tr('Sekarang: {lang}', {'lang': lang.code == 'en' ? 'English' : 'Bahasa Indonesia'})
                : null,
            trailing: Icon(
              selected == l ? CupertinoIcons.checkmark_alt_circle_fill : CupertinoIcons.circle,
              size: 20,
              color: selected == l ? NV.red : NV.muted,
            ),
            onTap: () => ref.read(appLanguageProvider).set(l),
          ),
      ],
    );
  }
}
