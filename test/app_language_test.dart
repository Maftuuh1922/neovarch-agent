
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:neovarch_agent/remote/l10n/app_language.dart';
import 'package:neovarch_agent/remote/l10n/strings.dart';
import 'package:neovarch_agent/remote/ui/language_panel.dart';

void main() {
  tearDown(() => L10n.code = 'id');

  test('the phone language decides "Ikuti sistem"', () {
    expect(resolveSystemLanguage(const [Locale('id', 'ID')]), 'id');
    expect(resolveSystemLanguage(const [Locale('in')]), 'id');
    expect(resolveSystemLanguage(const [Locale('jv')]), 'id');
    expect(resolveSystemLanguage(const [Locale('en', 'US')]), 'en');
    expect(resolveSystemLanguage(const [Locale('de'), Locale('id')]), 'id');
    expect(resolveSystemLanguage(const [Locale('fr')]), 'en');
  });

  test('choice is saved, applied to tr() and survives a restart', () async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    final c = AppLanguageController(prefs, systemLocales: () => const [Locale('id')]);
    expect(c.choice, AppLanguage.system);
    expect(c.code, 'id');
    expect(tr('Lanjut'), 'Lanjut');
    await c.set(AppLanguage.en);
    expect(prefs.getString(AppLanguageController.prefKey), 'en');
    expect(tr('Lanjut'), 'Continue');
    expect(tr('Terhubung ke {name}', {'name': 'PC Kantor'}), 'Connected to PC Kantor');
    expect(tr('belum diterjemahkan'), 'belum diterjemahkan'); // untranslated stays Indonesian
    final again = AppLanguageController(prefs, systemLocales: () => const [Locale('id')]);
    expect(again.choice, AppLanguage.en);
    await again.set(AppLanguage.system);
    expect(again.code, 'id');
    expect(tr('Lanjut'), 'Lanjut');
  });

  test('"Ikuti sistem" follows the phone when it changes', () {
    var locales = const [Locale('id')];
    final c = AppLanguageController.memory(systemLocales: () => locales);
    var notified = 0;
    c.addListener(() => notified++);
    locales = const [Locale('en')];
    c.systemLocalesChanged();
    expect(c.code, 'en');
    expect(L10n.code, 'en');
    expect(notified, 1);
  });

  testWidgets('language panel switches at once', (tester) async {
    final c = AppLanguageController.memory();
    await tester.pumpWidget(ProviderScope(
      overrides: [appLanguageProvider.overrideWith((ref) => c)],
      child: const MaterialApp(home: Scaffold(body: LanguagePanel())),
    ));
    expect(find.text('Ikuti sistem'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('language-en')));
    await tester.pump();
    expect(c.choice, AppLanguage.en);
    expect(find.text('Follow system'), findsOneWidget);
    expect(find.text('Now: English'), findsOneWidget);
  });
}
