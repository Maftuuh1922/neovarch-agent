// App language (Profil › Bahasa, and the first intro step): Bahasa Indonesia,
// English, or "Ikuti sistem" (the default: the phone's language).
//
// Stored in shared_preferences (`app.language` = system | id | en; the
// Android side reads the same key for home-screen widgets and notifications).
// On Android 13+ the choice is also handed to the system's per-app language
// (LocaleManager, `res/xml/locales_config.xml`), so Settings › Apps ›
// Neovarch › Language shows and changes the same setting; a change made there
// is picked up on the next start ([AppLanguageController.syncFromSystem]).
import 'dart:ui' show Locale, PlatformDispatcher;

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/legacy.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'strings.dart';

enum AppLanguage { system, id, en }

/// Language codes the app ships (Indonesian first: it is the source language).
const supportedLanguageCodes = ['id', 'en'];
const supportedAppLocales = [Locale('id'), Locale('en')];

/// The phone's languages → `id` or `en`. Indonesian and the regional
/// languages of Indonesia/Malaysia read Indonesian; everything else English.
String resolveSystemLanguage(List<Locale> locales) {
  for (final l in locales) {
    final c = l.languageCode.toLowerCase();
    if (const {'id', 'in', 'jv', 'su', 'ms'}.contains(c)) return 'id';
    if (c == 'en') return 'en';
  }
  return locales.isEmpty ? 'id' : 'en';
}

class AppLanguageController extends ChangeNotifier {
  AppLanguageController(this._prefs, {MethodChannel? channel, List<Locale> Function()? systemLocales})
      : _channel = channel ?? const MethodChannel('neovarch/device'),
        _systemLocales = systemLocales ?? (() => PlatformDispatcher.instance.locales) {
    choice = parse(_prefs?.getString(prefKey));
    L10n.code = code;
  }

  /// Not persisted (tests, previews); "Ikuti sistem" reads Indonesian unless told otherwise.
  AppLanguageController.memory({List<Locale> Function()? systemLocales})
      : this(null, systemLocales: systemLocales ?? (() => const [Locale('id')]));

  static const prefKey = 'app.language';

  final SharedPreferences? _prefs;
  final MethodChannel _channel;
  final List<Locale> Function() _systemLocales;

  AppLanguage choice = AppLanguage.system;

  /// Bumped on every change (screens keyed on it rebuild their strings).
  int revision = 0;

  static AppLanguage parse(String? v) => AppLanguage.values.firstWhere((l) => l.name == v, orElse: () => AppLanguage.system);

  /// The language in effect: `id` or `en`.
  String get code => choice == AppLanguage.system ? resolveSystemLanguage(_systemLocales()) : choice.name;

  Locale get locale => Locale(code);

  bool get _android => !kIsWeb && defaultTargetPlatform == TargetPlatform.android && _prefs != null;

  Future<void> set(AppLanguage next) async {
    if (next == choice) return;
    choice = next;
    await _prefs?.setString(prefKey, next.name);
    _changed();
    if (_android) {
      try {
        await _channel.invokeMethod('setAppLanguage', {'language': next == AppLanguage.system ? '' : next.name});
      } catch (_) {
        // older native side: the Flutter UI still switches
      }
    }
  }

  /// The phone's language changed (didChangeLocales): re-resolve "Ikuti sistem".
  void systemLocalesChanged() {
    if (choice == AppLanguage.system && L10n.code != code) _changed();
  }

  /// Android 13+: adopt a language picked in the system's per-app settings.
  Future<void> syncFromSystem() async {
    if (!_android) return;
    try {
      final tag = await _channel.invokeMethod<String>('getAppLanguage');
      if (tag == null) return; // below Android 13: our own setting is the truth
      final c = tag.split(RegExp('[-_]')).first.toLowerCase();
      final fromSystem = c.isEmpty ? AppLanguage.system : (c == 'en' ? AppLanguage.en : (c == 'id' || c == 'in' ? AppLanguage.id : null));
      if (fromSystem != null && fromSystem != choice) {
        choice = fromSystem;
        await _prefs?.setString(prefKey, fromSystem.name);
        _changed();
      }
    } catch (_) {}
  }

  void _changed() {
    L10n.code = code;
    revision++;
    notifyListeners();
  }
}

final appLanguageProvider = ChangeNotifierProvider<AppLanguageController>((ref) => AppLanguageController.memory());
