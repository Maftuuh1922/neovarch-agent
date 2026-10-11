// The phone app: a remote for the Neovarch desktop. No local agent runtime,
// providers or keys here — every action goes to the desktop's gateway.
import 'dart:async' show unawaited;
import 'dart:ui' as ui;

import 'package:flutter/foundation.dart' show kDebugMode, LicenseEntryWithLineBreaks, LicenseRegistry;
import 'package:flutter/services.dart' show rootBundle;
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter/rendering.dart' show RenderRepaintBoundary;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../state/app_controller.dart' show settingsProvider;
import '../../state/settings_controller.dart';
import '../../theme/neovarch_mobile_theme.dart';
import '../appearance.dart';
import '../l10n/app_language.dart';
import '../remote_controller.dart';
import '../saved_desktops.dart';
import '../apk_update.dart' show notifyUpdateAvailable;
import '../changelog.dart' show WhatsNew;
import '../update_check.dart';
import 'appearance/corner_radius.dart';
import 'connect_screen.dart';
import 'remote_intro_screen.dart';
import 'remote_launch.dart';
import 'remote_shell.dart';

bool _licensesAdded = false;

/// Bundled font licences shown on the licences page (Inter + the others).
void registerFontLicenses() {
  if (_licensesAdded) return;
  _licensesAdded = true;
  LicenseRegistry.addLicense(() async* {
    for (final (pkg, file) in const [
      ('Inter (font)', 'OFL-Inter.txt'),
      ('JetBrains Mono (font)', 'OFL-JetBrainsMono.txt'),
      ('Instrument Serif (font)', 'OFL-InstrumentSerif.txt'),
      ('IBM Plex Sans (font)', 'OFL-IBMPlexSans.txt'),
    ]) {
      try {
        yield LicenseEntryWithLineBreaks([pkg], await rootBundle.loadString('assets/fonts/$file'));
      } catch (_) {}
    }
  });
}

Future<void> runRemoteApp(
    {required SharedPreferences prefs, required SettingsController settings, bool skipSplash = false, String? openSession}) async {
  registerFontLicenses();
  // before anything below writes preferences: is this the first run of a
  // newer version (→ "Apa yang baru" once in the shell)?
  WhatsNew.prepare(prefs, SettingsController.appVersion);
  final desktops = SavedDesktops(prefs)..load();
  final remote = RemoteController(desktops)..updateChecker = UpdateChecker(prefs: prefs);
  remote.onNewUpdate = notifyUpdateAvailable;
  final look = AppearanceController(prefs);
  final corners = CornerRadiusController(prefs);
  final language = AppLanguageController(prefs);
  remote.onAppearance = look.applyPc;
  runApp(ProviderScope(
    overrides: [
      settingsProvider.overrideWith((ref) => settings),
      remoteProvider.overrideWith((ref) => remote),
      appearanceProvider.overrideWith((ref) => look),
      cornerRadiusProvider.overrideWith((ref) => corners),
      appLanguageProvider.overrideWith((ref) => language),
    ],
    child: RemoteNeovarchApp(skipSplash: skipSplash),
  ));
  // Android 13+: a language picked in the system's per-app settings wins.
  unawaited(language.syncFromSystem());
  await remote.start();
  // Web preview: open a stored session straight away.
  if (openSession != null && remote.connected) await remote.openSession(openSession);
}

ThemeData? _theme;
int _themeRev = -1;
double _themeCorner = -1;

/// Rebuilt only when the palette (PC appearance / local override) or the
/// corner radius ("Kelengkungan sudut", [NV.corner]) changes.
ThemeData themeFor(AppearanceController look) {
  if (_theme == null || _themeRev != look.revision || _themeCorner != NV.corner) {
    _theme = buildNeovarchMobileTheme();
    _themeRev = look.revision;
    _themeCorner = NV.corner;
  }
  return _theme!;
}

class RemoteNeovarchApp extends ConsumerWidget {
  const RemoteNeovarchApp({super.key, this.skipSplash = false});
  final bool skipSplash;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(settingsProvider);
    final remote = ref.watch(remoteProvider);
    final look = ref.watch(appearanceProvider);
    final corners = ref.watch(cornerRadiusProvider);
    final language = ref.watch(appLanguageProvider);
    final paired = remote.desktop != null || remote.desktops.items.isNotEmpty;
    final theme = themeFor(look);
    return MaterialApp(
      title: 'Neovarch Remote',
      debugShowCheckedModeBanner: false,
      // Follows the PC's look (accent + dark/light) unless overridden on the
      // phone; flat, rounded, no gradients/shadows/glow in every variant.
      theme: theme,
      darkTheme: theme,
      themeMode: look.dark ? ThemeMode.dark : ThemeMode.light,
      // Theme changes cross-fade (snapshot of the old look fades out).
      themeAnimationDuration: Duration.zero,
      // Profil › Bahasa / the intro's first step: Bahasa Indonesia or English.
      locale: language.locale,
      supportedLocales: supportedAppLocales,
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
      builder: (context, child) => AppCornerRadius(
          controller: corners,
          child: LanguageScope(
              language: language, child: PaletteScope(revision: look.revision, look: look, child: child!))),
      // Every cold start opens on the intro in the saved theme; the first
      // launch then shows the onboarding slides.
      home: NvLaunchIntro(
        enabled: !skipSplash,
        child: !s.introSeen ? const RemoteIntroScreen() : (paired ? const RemoteShell() : const ConnectScreen(onboarding: true)),
      ),
    );
  }
}

/// Repaints the whole tree (state kept) when the palette revision changes,
/// cross-fading from a snapshot of the old look (~380 ms), and feeds the
/// phone's dark/light setting to the "Sistem" theme mode.
class PaletteScope extends StatefulWidget {
  const PaletteScope({super.key, required this.revision, required this.child, this.look});
  final int revision;
  final AppearanceController? look;
  final Widget child;
  @override
  State<PaletteScope> createState() => _PaletteScopeState();
}

class _PaletteScopeState extends State<PaletteScope> with SingleTickerProviderStateMixin, WidgetsBindingObserver {
  final _boundary = GlobalKey();
  late final AnimationController _fade = AnimationController(vsync: this, duration: const Duration(milliseconds: 380));
  ui.Image? _old;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _hook();
  }

  void _hook() => widget.look?.onBeforeChange = _snapshot;

  @override
  void didChangePlatformBrightness() {
    widget.look?.setSystemBrightness(WidgetsBinding.instance.platformDispatcher.platformBrightness);
  }

  /// Called while the old look is still the last painted frame.
  void _snapshot() {
    if (!mounted || MediaQuery.maybeDisableAnimationsOf(context) == true) return;
    final ro = _boundary.currentContext?.findRenderObject();
    if (ro is! RenderRepaintBoundary || !ro.hasSize || (kDebugMode && ro.debugNeedsPaint)) return;
    try {
      final img = ro.toImageSync(pixelRatio: MediaQuery.devicePixelRatioOf(context));
      _old?.dispose();
      setState(() => _old = img);
      _fade.forward(from: 0).whenComplete(() {
        if (!mounted) return;
        setState(() {
          _old?.dispose();
          _old = null;
        });
      });
    } catch (_) {
      // no snapshot: the change simply applies at once
    }
  }

  @override
  void didUpdateWidget(PaletteScope old) {
    super.didUpdateWidget(old);
    if (old.look != widget.look) {
      if (old.look?.onBeforeChange == _snapshot) old.look?.onBeforeChange = null;
      _hook();
    }
    if (old.revision != widget.revision) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) rebuildAllChildren(context);
      });
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    if (widget.look?.onBeforeChange == _snapshot) widget.look?.onBeforeChange = null;
    _fade.dispose();
    _old?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final old = _old;
    return Stack(textDirection: TextDirection.ltr, children: [
      Positioned.fill(child: RepaintBoundary(key: _boundary, child: widget.child)),
      if (old != null)
        Positioned.fill(
          child: IgnorePointer(
            child: FadeTransition(
              key: const ValueKey('nv-theme-crossfade'),
              opacity: ReverseAnimation(CurvedAnimation(parent: _fade, curve: Curves.easeOutCubic)),
              child: RawImage(image: old, fit: BoxFit.fill),
            ),
          ),
        ),
    ]);
  }
}

/// Re-resolves "Ikuti sistem" when the phone's language changes and repaints
/// every screen (state kept) when the app language changes, so even const
/// widgets pick up the new strings.
class LanguageScope extends StatefulWidget {
  const LanguageScope({super.key, required this.language, required this.child});
  final AppLanguageController language;
  final Widget child;
  @override
  State<LanguageScope> createState() => _LanguageScopeState();
}

class _LanguageScopeState extends State<LanguageScope> with WidgetsBindingObserver {
  late int _rev = widget.language.revision;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void didChangeLocales(List<Locale>? locales) => widget.language.systemLocalesChanged();

  @override
  void didUpdateWidget(LanguageScope old) {
    super.didUpdateWidget(old);
    if (widget.language.revision != _rev) {
      _rev = widget.language.revision;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) rebuildAllChildren(context);
      });
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => widget.child;
}

/// The current palette's theme (tests / previews).
ThemeData get neovarchMobileTheme => buildNeovarchMobileTheme();
