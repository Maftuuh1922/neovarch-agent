// Neovarch Remote (Android/iOS) — the phone's own design system, shared with
// Neovarch Desktop and the landing page:
//   flat dark-red palette, no gradients / glows / elevation shadows (only
//   liquid glass gets a subtle specular rim, see NvGlass),
//   one rounded system (16 cards & sheets · 12 controls · 20 dialogs ·
//   14 chat blocks · full for avatars & badges), 1px borders,
//   iOS-like type (1.4.2): Inter Display for large titles, Inter for body,
//   captions and section headers; JetBrains Mono only for code/tokens.
// Every Material component theme is set explicitly so no stock purple/blue
// (or Material You dynamic colour) can leak in.
import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../ui/widgets/motion.dart';
import 'app_theme.dart';

/// One resolved colour set. The phone follows the PC's appearance (accent +
/// dark/light, `GET /api/appearance` / `appearance.changed`) unless the user
/// set a local override; see `state/appearance.dart`.
class NvPalette {
  const NvPalette({
    required this.brightness,
    required this.accent,
    required this.onAccent,
    required this.bg,
    required this.surface,
    required this.raised,
    required this.border,
    required this.borderStrong,
    required this.text,
    required this.muted,
    required this.faint,
    required this.darkAccent,
    required this.wash,
  });
  final Brightness brightness;
  final Color accent, onAccent, bg, surface, raised, border, borderStrong, text, muted, faint, darkAccent, wash;
  bool get dark => brightness == Brightness.dark;

  static const defaultAccent = Color(0xFFEE1C1C);

  /// The original Neovarch dark red set (exactly the v1.3 tokens).
  static const red = NvPalette(
    brightness: Brightness.dark,
    accent: Color(0xFFEE1C1C),
    onAccent: Color(0xFFF4F2ED),
    bg: Color(0xFF0D0606),
    surface: Color(0xFF140808),
    raised: Color(0xFF1B0C0C),
    border: Color(0xFF2A1212),
    borderStrong: Color(0xFF3D1B1B),
    text: Color(0xFFF4F2ED),
    muted: Color(0xFFB8ADA6),
    faint: Color(0xFF7D706A),
    darkAccent: Color(0xFF8F0A0A),
    wash: Color(0xFF2A0B0B),
  );

  /// Flat colours only: every token is the base neutral lightly tinted by the
  /// accent (Color.lerp), never a gradient.
  factory NvPalette.from(Color accent, Brightness b, {Color? onAccent}) {
    final a = accent.withAlpha(255);
    if (b == Brightness.dark && a.toARGB32() == defaultAccent.toARGB32()) return red;
    Color t(int base, double f) => Color.lerp(Color(base), a, f)!;
    // White when it reaches AA (4.5:1), else whichever of white/black reads better.
    final cw = _contrast(a, const Color(0xFFFFFFFF)), cb = _contrast(a, const Color(0xFF000000));
    final on = onAccent ?? (cw >= 4.5 || cw >= cb ? const Color(0xFFFFFFFF) : const Color(0xFF000000));
    if (b == Brightness.dark) {
      // Same tint strength as the original red set (bg/surface/border/wash
      // visibly carry the hue), so a new accent recolours the whole UI.
      return NvPalette(
        brightness: b,
        accent: a,
        onAccent: on,
        bg: t(0xFF0A0A0A, 0.06),
        surface: t(0xFF101010, 0.085),
        raised: t(0xFF161616, 0.11),
        border: t(0xFF222222, 0.17),
        borderStrong: t(0xFF303030, 0.24),
        text: Color.lerp(const Color(0xFFF4F2ED), a, 0.04)!,
        muted: Color.lerp(const Color(0xFFB3ADA8), a, 0.10)!,
        faint: Color.lerp(const Color(0xFF78716C), a, 0.12)!,
        darkAccent: Color.lerp(a, const Color(0xFF000000), 0.45)!,
        wash: t(0xFF0D0D0D, 0.22),
      );
    }
    // 1.4.4 light-mode contrast: a pale accent (amber, yellow, lime) is
    // deepened until it reads as an icon / fill edge on the light surface
    // (3:1); text in the accent uses [accentInk] (4.5:1).
    // reference: light glass composited over a black wallpaper (~#CCC), so
    // accent icons hold up on glass too; on the plain background it is ~4:1.
    final la = _toContrast(a, const Color(0xFFCCCCCC), 3.0);
    final cw2 = _contrast(la, const Color(0xFFFFFFFF)), cb2 = _contrast(la, const Color(0xFF000000));
    final on2 = onAccent ?? (cw2 >= 4.5 || cw2 >= cb2 ? const Color(0xFFFFFFFF) : const Color(0xFF000000));
    Color tl(int base, double f) => Color.lerp(Color(base), la, f)!;
    return NvPalette(
      brightness: b,
      accent: la,
      onAccent: on2,
      bg: tl(0xFFF6F4F1, 0.06),
      surface: tl(0xFFFFFFFF, 0.035),
      raised: tl(0xFFEEEBE7, 0.08),
      border: tl(0xFFDDD8D1, 0.16),
      borderStrong: tl(0xFFC9C2B9, 0.22),
      text: Color.lerp(const Color(0xFF151111), la, 0.05)!,
      // darker secondary/tertiary than before so they hold AA on light glass
      muted: Color.lerp(const Color(0xFF433C39), la, 0.06)!,
      faint: Color.lerp(const Color(0xFF66605B), la, 0.06)!,
      darkAccent: Color.lerp(la, const Color(0xFF000000), 0.35)!,
      wash: tl(0xFFFFFFFF, 0.16),
    );
  }

  /// The accent as a text colour: deepened (light) or lifted (dark) until it
  /// reaches AA 4.5:1 on [bg].
  Color get accentInk {
    final c = _toContrast(_toContrast(accent, bg, 4.5), wash, 4.5);
    // light mode: also 3:1 over the wallpaper veil on a black photo (~#B0B0B0)
    return dark ? c : _toContrast(c, const Color(0xFFB0B0B0), 3.2);
  }

  /// Moves [c] toward black (on a light [bg]) or white (on a dark one) until
  /// it reaches [ratio] against [bg].
  static Color _toContrast(Color c, Color bg, double ratio) {
    if (_contrast(c, bg) >= ratio) return c;
    final to = _lum(bg) > 0.4 ? const Color(0xFF000000) : const Color(0xFFFFFFFF);
    for (var i = 1; i <= 20; i++) {
      final x = Color.lerp(c, to, i / 20)!;
      if (_contrast(x, bg) >= ratio) return x;
    }
    return to;
  }

  /// WCAG contrast ratio of two opaque colours.
  static double contrast(Color a, Color b) => _contrast(a, b);

  static double _lum(Color c) {
    double ch(double v) => v <= 0.03928 ? v / 12.92 : math.pow((v + 0.055) / 1.055, 2.4).toDouble();
    return 0.2126 * ch(c.r) + 0.7152 * ch(c.g) + 0.0722 * ch(c.b);
  }

  static double _contrast(Color a, Color b) {
    final la = _lum(a), lb = _lum(b);
    return (math.max(la, lb) + 0.05) / (math.min(la, lb) + 0.05);
  }
}

/// "Gaya kaca" — liquid glass variants. The names are the stored / synced
/// values (same names as GlassStyle in the chat-glass branch).
enum NvGlassStyle {
  reguler,
  bening,
  gelap,
  warna,
  tanpa;

  String get label => switch (this) {
        NvGlassStyle.reguler => 'Reguler',
        NvGlassStyle.bening => 'Bening',
        NvGlassStyle.gelap => 'Gelap',
        NvGlassStyle.warna => 'Warna',
        NvGlassStyle.tanpa => 'Tanpa efek',
      };

  static NvGlassStyle parse(String? s) => NvGlassStyle.values.firstWhere((v) => v.name == s, orElse: () => NvGlassStyle.reguler);
}

/// Design tokens. Colours read the current [NvPalette] (set by the app from
/// the PC appearance or the local override); radii and fonts are fixed.
abstract final class NV {
  static NvPalette palette = NvPalette.red;

  static Color get bg => palette.bg;
  static Color get surface => palette.surface;
  static Color get raised => palette.raised;
  static Color get border => palette.border;
  static Color get borderStrong => palette.borderStrong;
  static Color get text => palette.text;
  static Color get muted => palette.muted;
  static Color get faint => palette.faint;
  static Color get red => palette.accent; // the accent (red by default)
  static Color get onRed => palette.onAccent;
  /// Accent for text (kickers, counts, links): AA 4.5:1 on the background.
  static Color get redInk => palette.accentInk;
  static Color get darkRed => palette.darkAccent;
  static Color get redWash => palette.wash; // accent-tinted surface (selection, user message)
  // Status colours stay inside the palette: no stock green / amber.
  static Color get ok => text; // connected / online
  static Color get warn => muted; // connecting / waiting

  /// "Gaya kaca" applied app-wide (set by AppearanceController).
  static NvGlassStyle glassStyle = NvGlassStyle.reguler;

  /// "Mode ringan" (set by AppearanceController): glass widgets skip their
  /// BackdropFilter and paint a solid surface instead.
  static bool liteMode = false;

  /// Liquid glass: translucent, accent-tinted fill over a strong backdrop
  /// blur; the bright rim / specular edge is painted by `NvGlass`.
  /// Every tint is derived from the accent (wallpaper-derived when that is
  /// on) — no fixed cream/amber surfaces. Values follow
  /// /workspace/work/liquid-glass-spec.md §5.2 (emulation presets).
  static Color get glass => glassFill(glassStyle);
  static Color glassFill(NvGlassStyle st, {bool nav = false}) {
    final d = palette.dark;
    final a = palette.accent;
    if (!d) {
      // 1.4.4 light mode: dark text sits on these fills over any wallpaper,
      // so every style keeps enough light fill to hold 4.5:1 for body and
      // secondary text even over a black backdrop (see remote_v144 contrast
      // test); the blur + rim still read as glass.
      return switch (st) {
        NvGlassStyle.reguler => Color.lerp(palette.surface, a, nav ? 0.08 : 0.05)!.withValues(alpha: nav ? 0.80 : 0.80),
        NvGlassStyle.bening => Color.lerp(const Color(0xFFFFFFFF), a, 0.04)!.withValues(alpha: 0.74),
        NvGlassStyle.gelap => Color.lerp(palette.surface, const Color(0xFF000000), 0.07)!.withValues(alpha: 0.84),
        NvGlassStyle.warna => Color.lerp(a, palette.surface, 0.82)!.withValues(alpha: 0.86),
        NvGlassStyle.tanpa => Color.lerp(palette.surface, a, 0.05)!.withValues(alpha: 0.96),
      };
    }
    return switch (st) {
      NvGlassStyle.reguler => Color.lerp(palette.surface, a, nav ? 0.16 : 0.10)!.withValues(alpha: nav ? 0.50 : 0.55),
      // Clear: nearly no fill (spec: white α .04–.06) + a light dimming so
      // labels keep their contrast over bright wallpapers.
      NvGlassStyle.bening => Color.lerp(const Color(0xFF000000), a, 0.10)!.withValues(alpha: 0.16),
      // Dark smoked glass, neutral taken from the accent hue.
      NvGlassStyle.gelap => Color.lerp(const Color(0xFF0B0B0D), a, 0.08)!.withValues(alpha: 0.68),
      // Tinted: the accent tone-mapped toward the surface.
      NvGlassStyle.warna => Color.lerp(a, palette.surface, 0.45)!.withValues(alpha: 0.58),
      // Reduce transparency: an opaque surface in the mode colour.
      NvGlassStyle.tanpa => Color.lerp(palette.surface, a, 0.05)!.withValues(alpha: 0.96),
    };
  }

  /// Light mode with a wallpaper: the minimum light veil over the picture so
  /// headers and text drawn straight on it keep their contrast.
  static const lightWallpaperVeil = 0.74;

  /// Backdrop blur multiplier per style (0 = no BackdropFilter).
  static double glassSigmaScale(NvGlassStyle st) => switch (st) {
        NvGlassStyle.reguler => 1.0,
        NvGlassStyle.bening => 0.3,
        NvGlassStyle.gelap => 1.15,
        NvGlassStyle.warna => 1.0,
        NvGlassStyle.tanpa => 0.0,
      };

  static Color get glassBorder => palette.text.withValues(alpha: palette.dark ? 0.10 : 0.12);
  /// Specular rim colour (top-left highlight of a glass edge).
  static Color get glassRim => glassRimFor(glassStyle);
  static Color glassRimFor(NvGlassStyle st) => switch (st) {
        NvGlassStyle.bening => const Color(0xFFFFFFFF).withValues(alpha: palette.dark ? 0.55 : 0.95),
        NvGlassStyle.gelap => const Color(0xFFFFFFFF).withValues(alpha: 0.30),
        NvGlassStyle.tanpa => palette.text.withValues(alpha: 0.16),
        _ => const Color(0xFFFFFFFF).withValues(alpha: palette.dark ? 0.32 : 0.85),
      };
  /// Text on glass: a faint shadow only where the glass is clear.
  static List<Shadow> get glassTextShadows => glassStyle == NvGlassStyle.bening
      ? (palette.dark
          ? [Shadow(color: const Color(0xFF000000).withValues(alpha: 0.55), blurRadius: 3, offset: const Offset(0, 1))]
          : [Shadow(color: const Color(0xFFFFFFFF).withValues(alpha: 0.6), blurRadius: 3)])
      : const [];
  /// Tab bar glass: a touch more accent so the bar reads as tinted glass.
  static Color get navGlass => glassFill(glassStyle, nav: true);
  /// Clear lens on the active tab.
  static Color get lensFill => glassStyle == NvGlassStyle.tanpa
      ? Color.lerp(palette.surface, palette.accent, 0.18)!
      : Color.lerp(const Color(0xFFFFFFFF), palette.accent, palette.dark ? 0.35 : 0.12)!.withValues(alpha: palette.dark ? 0.10 : 0.16);
  static const glassBlur = 22.0;
  /// Live glass blur strength ("Kekuatan kaca"); [NvGlass] listens to it.
  static final glassSigma = ValueNotifier<double>(glassBlur);

  /// User "Kelengkungan sudut" (outer card radius, 0–32 dp), set by
  /// `CornerRadiusController` (lib/remote/ui/appearance/corner_radius.dart).
  /// Every radius below derives from it (concentric: inner = outer − padding).
  static double corner = defaultCorner;
  static const defaultCorner = 24.0;
  static double get rCard => corner;
  static double get rCtl => ctlFor(corner);
  static double get rDialog => math.min(corner + 4, 36);
  static double get rMsg => corner * 0.75;
  /// Controls (buttons, inputs, tiles): half the card radius, at least
  /// card − 12 (the usual card padding) so nested shapes stay concentric.
  static double ctlFor(double c) => c <= 0 ? 0 : math.max(c * 0.5, c - 12);
  /// Concentric inner radius for a shape inset by [padding] inside [outer].
  static double inner(double outer, double padding) => math.max(0, outer - padding);
  /// Floating bars of height [h]: a capsule from ~24 dp up, squarer below.
  static double navFor(double h) => math.min(h / 2, corner * 1.4);

  // iOS-like type: Inter (OFL, closest open SF Pro look-alike) for UI text,
  // Inter Display for large titles. Mono only for code, tokens, addresses.
  // SF Pro itself is not bundled (Apple-platform-only licence).
  static const display_ = 'InterDisplay';
  static const serif = display_; // legacy name: headings
  static const sans = 'Inter';
  static const mono = 'JetBrainsMono';

  /// iOS tracking: tighter as text gets bigger (≈ SF Pro's optical tracking).
  static double tracking(double size) => size >= 28
      ? -0.022 * size
      : size >= 20
          ? -0.016 * size
          : size >= 15
              ? -0.008 * size
              : 0.0;

  static BorderRadius get card => BorderRadius.circular(rCard);
  static BorderRadius get ctl => BorderRadius.circular(rCtl);

  /// Kicker / section caption (iOS footnote-caps style, Inter semibold).
  /// Callers pass the old mono sizes (9.5–11); mapped up to iOS caption 12–13.
  static TextStyle monoLabel({double size = 10.5, Color? color, FontWeight weight = FontWeight.w500}) => TextStyle(
      fontFamily: sans, fontSize: size + 2, letterSpacing: 0.1, fontWeight: FontWeight.w600, color: color ?? muted, height: 1.3);

  /// Real code/tokens (hex, addresses, tokens) stay monospaced.
  static TextStyle code({double size = 12, Color? color, FontWeight weight = FontWeight.w500}) =>
      TextStyle(fontFamily: mono, fontSize: size, letterSpacing: 0, fontWeight: weight, color: color ?? muted, height: 1.3);

  /// Large title / title (Inter Display bold, tight tracking).
  static TextStyle display({double size = 34, Color? color}) => TextStyle(
      fontFamily: display_, fontSize: size, height: 1.12, letterSpacing: tracking(size), color: color ?? text, fontWeight: FontWeight.w700);
}

ThemeData buildNeovarchMobileTheme() {
  final scheme = ColorScheme(
    brightness: NV.palette.brightness,
    primary: NV.red,
    onPrimary: NV.onRed,
    primaryContainer: NV.redWash,
    onPrimaryContainer: NV.text,
    primaryFixed: NV.red,
    primaryFixedDim: NV.darkRed,
    onPrimaryFixed: NV.text,
    onPrimaryFixedVariant: NV.text,
    secondary: NV.muted,
    onSecondary: NV.bg,
    secondaryContainer: NV.raised,
    onSecondaryContainer: NV.text,
    secondaryFixed: NV.muted,
    secondaryFixedDim: NV.faint,
    onSecondaryFixed: NV.bg,
    onSecondaryFixedVariant: NV.bg,
    tertiary: NV.darkRed,
    onTertiary: NV.text,
    tertiaryContainer: NV.redWash,
    onTertiaryContainer: NV.text,
    tertiaryFixed: NV.darkRed,
    tertiaryFixedDim: NV.darkRed,
    onTertiaryFixed: NV.text,
    onTertiaryFixedVariant: NV.text,
    error: NV.red,
    onError: NV.text,
    errorContainer: NV.redWash,
    onErrorContainer: NV.text,
    surface: NV.bg,
    onSurface: NV.text,
    surfaceDim: NV.bg,
    surfaceBright: NV.raised,
    surfaceContainerLowest: NV.bg,
    surfaceContainerLow: NV.surface,
    surfaceContainer: NV.surface,
    surfaceContainerHigh: NV.raised,
    surfaceContainerHighest: NV.raised,
    onSurfaceVariant: NV.muted,
    outline: NV.border,
    outlineVariant: NV.border,
    shadow: Colors.transparent,
    scrim: const Color(0xB3000000),
    inverseSurface: NV.text,
    onInverseSurface: NV.bg,
    inversePrimary: NV.darkRed,
    surfaceTint: Colors.transparent,
  );

  final base = (NV.palette.dark ? ThemeData.dark(useMaterial3: true) : ThemeData.light(useMaterial3: true)).textTheme.apply(
        fontFamily: NV.sans,
        bodyColor: NV.text,
        displayColor: NV.text,
      );
  TextStyle serif(TextStyle? t, double size) => (t ?? const TextStyle())
      .copyWith(fontFamily: NV.serif, fontSize: size, fontWeight: FontWeight.w700, height: 1.12, letterSpacing: NV.tracking(size), color: NV.text);
  final text = base.copyWith(
    // iOS scale: large title 34, title1 28, title2 22, title3 20, headline 17
    // semibold, body 17, callout 16, subheadline 15, footnote 13, caption 12.
    displayLarge: serif(base.displayLarge, 48),
    displayMedium: serif(base.displayMedium, 40),
    displaySmall: serif(base.displaySmall, 34),
    headlineLarge: serif(base.headlineLarge, 34),
    headlineMedium: serif(base.headlineMedium, 28),
    headlineSmall: serif(base.headlineSmall, 22),
    titleLarge: serif(base.titleLarge, 20),
    titleMedium: base.titleMedium?.copyWith(fontSize: 17, fontWeight: FontWeight.w600, letterSpacing: NV.tracking(17)),
    titleSmall: base.titleSmall?.copyWith(fontSize: 15, fontWeight: FontWeight.w600, letterSpacing: NV.tracking(15)),
    bodyLarge: base.bodyLarge?.copyWith(fontSize: 17, height: 1.35, letterSpacing: NV.tracking(17)),
    bodyMedium: base.bodyMedium?.copyWith(fontSize: 15, height: 1.4, letterSpacing: NV.tracking(15)),
    bodySmall: base.bodySmall?.copyWith(fontSize: 13, height: 1.4, color: NV.muted),
    labelLarge: base.labelLarge?.copyWith(fontSize: 16, fontWeight: FontWeight.w600, letterSpacing: NV.tracking(16)),
    labelMedium: base.labelMedium?.copyWith(fontSize: 13, fontWeight: FontWeight.w500, color: NV.muted),
    labelSmall: base.labelSmall?.copyWith(fontSize: 12, fontWeight: FontWeight.w500, color: NV.muted),
  );

  final line = BorderSide(color: NV.border, width: 1);
  final ctlShape = RoundedRectangleBorder(borderRadius: NV.ctl);
  final ctlShapeLined = RoundedRectangleBorder(borderRadius: NV.ctl, side: line);
  final cardShape = RoundedRectangleBorder(borderRadius: NV.card, side: line);
  const btnPad = EdgeInsets.symmetric(horizontal: 18, vertical: 14);
  const btnText = TextStyle(fontFamily: NV.sans, fontSize: 16, fontWeight: FontWeight.w600, letterSpacing: -0.1);
  // Subdued press feedback: a faint warm wash, no sparkle, no coloured ripple.
  final press = NV.text.withValues(alpha: 0.08);
  WidgetStateProperty<Color?> overlay([Color? c]) =>
      WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.pressed) || s.contains(WidgetState.focused) || s.contains(WidgetState.hovered) ? (c ?? press) : null);
  OutlineInputBorder inBorder(Color c, [double w = 1]) =>
      OutlineInputBorder(borderRadius: NV.ctl, borderSide: BorderSide(color: c, width: w));

  return ThemeData(
    useMaterial3: true,
    brightness: NV.palette.brightness,
    colorScheme: scheme,
    fontFamily: NV.sans,
    textTheme: text,
    primaryTextTheme: text,
    scaffoldBackgroundColor: NV.bg,
    canvasColor: NV.bg,
    cardColor: NV.surface,
    dividerColor: NV.border,
    disabledColor: NV.faint,
    hintColor: NV.faint,
    focusColor: press,
    hoverColor: press,
    highlightColor: Colors.transparent,
    splashColor: press,
    splashFactory: InkRipple.splashFactory,
    shadowColor: Colors.transparent,
    applyElevationOverlayColor: false,
    materialTapTargetSize: MaterialTapTargetSize.padded,
    visualDensity: VisualDensity.standard,
    iconTheme: IconThemeData(color: NV.text, size: 22),
    primaryIconTheme: IconThemeData(color: NV.text),
    pageTransitionsTheme: const PageTransitionsTheme(builders: {
      TargetPlatform.android: NvPageTransitionsBuilder(),
      TargetPlatform.iOS: NvPageTransitionsBuilder(),
      TargetPlatform.linux: NvPageTransitionsBuilder(),
      TargetPlatform.macOS: NvPageTransitionsBuilder(),
      TargetPlatform.windows: NvPageTransitionsBuilder(),
      TargetPlatform.fuchsia: NvPageTransitionsBuilder(),
    }),
    dividerTheme: DividerThemeData(color: NV.border, thickness: 1, space: 1),
    appBarTheme: AppBarTheme(
      backgroundColor: NV.bg,
      foregroundColor: NV.text,
      surfaceTintColor: Colors.transparent,
      shadowColor: Colors.transparent,
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: false,
      titleSpacing: 20,
      toolbarHeight: 60,
      iconTheme: IconThemeData(color: NV.text, size: 22),
      actionsIconTheme: IconThemeData(color: NV.muted, size: 22),
      titleTextStyle: TextStyle(fontFamily: NV.serif, fontSize: 28, fontWeight: FontWeight.w700, letterSpacing: NV.tracking(28), color: NV.text, height: 1.1),
    ),
    cardTheme: CardThemeData(
      color: NV.surface,
      shadowColor: Colors.transparent,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      margin: EdgeInsets.zero,
      clipBehavior: Clip.antiAlias,
      shape: cardShape,
    ),
    bottomSheetTheme: BottomSheetThemeData(
      backgroundColor: NV.surface,
      modalBackgroundColor: NV.surface,
      surfaceTintColor: Colors.transparent,
      shadowColor: Colors.transparent,
      elevation: 0,
      modalElevation: 0,
      showDragHandle: true,
      dragHandleColor: NV.borderStrong,
      dragHandleSize: Size(40, 4),
      clipBehavior: Clip.antiAlias,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(NV.rCard)),
        side: line,
      ),
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: NV.surface,
      surfaceTintColor: Colors.transparent,
      shadowColor: Colors.transparent,
      elevation: 0,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(NV.rDialog), side: line),
      titleTextStyle: TextStyle(fontFamily: NV.serif, fontSize: 22, fontWeight: FontWeight.w700, letterSpacing: NV.tracking(22), color: NV.text, height: 1.15),
      contentTextStyle: TextStyle(fontFamily: NV.sans, fontSize: 14, color: NV.muted, height: 1.5),
      barrierColor: const Color(0xB3000000),
    ),
    popupMenuTheme: PopupMenuThemeData(
      color: NV.raised,
      surfaceTintColor: Colors.transparent,
      shadowColor: Colors.transparent,
      elevation: 0,
      shape: cardShape,
      textStyle: TextStyle(fontFamily: NV.sans, fontSize: 14, color: NV.text),
    ),
    menuTheme: MenuThemeData(
      style: MenuStyle(
        backgroundColor: WidgetStatePropertyAll(NV.raised),
        surfaceTintColor: const WidgetStatePropertyAll(Colors.transparent),
        shadowColor: const WidgetStatePropertyAll(Colors.transparent),
        elevation: const WidgetStatePropertyAll(0),
        shape: WidgetStatePropertyAll(cardShape),
      ),
    ),
    dropdownMenuTheme: DropdownMenuThemeData(
      menuStyle: MenuStyle(
        backgroundColor: WidgetStatePropertyAll(NV.raised),
        surfaceTintColor: const WidgetStatePropertyAll(Colors.transparent),
        elevation: const WidgetStatePropertyAll(0),
        shape: WidgetStatePropertyAll(cardShape),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: NV.surface,
      isDense: false,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 15),
      hintStyle: TextStyle(color: NV.faint, fontFamily: NV.sans),
      labelStyle: TextStyle(color: NV.muted, fontFamily: NV.sans),
      floatingLabelStyle: TextStyle(color: NV.text, fontFamily: NV.sans),
      helperStyle: TextStyle(color: NV.faint, fontSize: 12, fontFamily: NV.sans),
      errorStyle: TextStyle(color: NV.red, fontSize: 12),
      prefixIconColor: NV.muted,
      suffixIconColor: NV.muted,
      border: inBorder(NV.border),
      enabledBorder: inBorder(NV.border),
      disabledBorder: inBorder(NV.border.withValues(alpha: 0.5)),
      focusedBorder: inBorder(NV.red),
      errorBorder: inBorder(NV.darkRed),
      focusedErrorBorder: inBorder(NV.red),
    ),
    textSelectionTheme: TextSelectionThemeData(
      cursorColor: NV.red,
      selectionColor: NV.red.withValues(alpha: 0.35),
      selectionHandleColor: NV.red,
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: ButtonStyle(
        backgroundColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.disabled) ? NV.raised : NV.red),
        foregroundColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.disabled) ? NV.faint : NV.onRed),
        overlayColor: overlay(NV.bg.withValues(alpha: 0.12)),
        elevation: const WidgetStatePropertyAll(0),
        shadowColor: const WidgetStatePropertyAll(Colors.transparent),
        shape: WidgetStatePropertyAll(ctlShape),
        padding: const WidgetStatePropertyAll(btnPad),
        minimumSize: const WidgetStatePropertyAll(Size(64, 48)),
        textStyle: const WidgetStatePropertyAll(btnText),
      ),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ButtonStyle(
        backgroundColor: WidgetStatePropertyAll(NV.raised),
        foregroundColor: WidgetStatePropertyAll(NV.text),
        overlayColor: overlay(),
        elevation: const WidgetStatePropertyAll(0),
        shadowColor: const WidgetStatePropertyAll(Colors.transparent),
        shape: WidgetStatePropertyAll(ctlShapeLined),
        padding: const WidgetStatePropertyAll(btnPad),
        textStyle: const WidgetStatePropertyAll(btnText),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: ButtonStyle(
        foregroundColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.disabled) ? NV.faint : NV.text),
        backgroundColor: const WidgetStatePropertyAll(Colors.transparent),
        overlayColor: overlay(),
        side: WidgetStateProperty.resolveWith((s) => BorderSide(color: s.contains(WidgetState.disabled) ? NV.border : NV.borderStrong)),
        shape: WidgetStatePropertyAll(ctlShape),
        padding: const WidgetStatePropertyAll(btnPad),
        minimumSize: const WidgetStatePropertyAll(Size(64, 48)),
        textStyle: const WidgetStatePropertyAll(btnText),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: ButtonStyle(
        foregroundColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.disabled) ? NV.faint : NV.red),
        overlayColor: overlay(),
        shape: WidgetStatePropertyAll(ctlShape),
        textStyle: const WidgetStatePropertyAll(btnText),
      ),
    ),
    iconButtonTheme: IconButtonThemeData(
      style: ButtonStyle(
        foregroundColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.disabled) ? NV.faint : NV.text),
        overlayColor: overlay(),
        shape: WidgetStatePropertyAll(ctlShape),
      ),
    ),
    floatingActionButtonTheme: FloatingActionButtonThemeData(
      backgroundColor: NV.red,
      foregroundColor: NV.onRed,
      splashColor: NV.bg.withValues(alpha: 0.12),
      elevation: 0,
      focusElevation: 0,
      hoverElevation: 0,
      highlightElevation: 0,
      disabledElevation: 0,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(NV.rCard)),
      extendedTextStyle: btnText,
    ),
    chipTheme: ChipThemeData(
      backgroundColor: NV.surface,
      selectedColor: NV.redWash,
      disabledColor: NV.surface,
      secondarySelectedColor: NV.redWash,
      checkmarkColor: NV.red,
      deleteIconColor: NV.muted,
      surfaceTintColor: Colors.transparent,
      shadowColor: Colors.transparent,
      selectedShadowColor: Colors.transparent,
      elevation: 0,
      pressElevation: 0,
      side: WidgetStateBorderSide.resolveWith(
          (s) => BorderSide(color: s.contains(WidgetState.selected) ? NV.red : NV.border)),
      labelStyle: TextStyle(fontFamily: NV.sans, color: NV.text, fontSize: 13),
      secondaryLabelStyle: TextStyle(fontFamily: NV.sans, color: NV.text, fontSize: 13),
      shape: ctlShape,
      showCheckmark: false,
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
    ),
    segmentedButtonTheme: SegmentedButtonThemeData(
      style: ButtonStyle(
        backgroundColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? NV.redWash : NV.surface),
        foregroundColor: WidgetStatePropertyAll(NV.text),
        side: WidgetStatePropertyAll(line),
        shape: WidgetStatePropertyAll(ctlShape),
        overlayColor: overlay(),
      ),
    ),
    switchTheme: SwitchThemeData(
      thumbColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? NV.text : NV.muted),
      trackColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? NV.red : NV.raised),
      trackOutlineColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? NV.red : NV.borderStrong),
      overlayColor: overlay(),
    ),
    checkboxTheme: CheckboxThemeData(
      fillColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? NV.red : Colors.transparent),
      checkColor: WidgetStatePropertyAll(NV.onRed),
      side: BorderSide(color: NV.borderStrong, width: 1.2),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(5)),
    ),
    radioTheme: RadioThemeData(
      fillColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? NV.red : NV.muted),
    ),
    sliderTheme: SliderThemeData(
      activeTrackColor: NV.red,
      inactiveTrackColor: NV.border,
      thumbColor: NV.text,
      overlayColor: press,
      valueIndicatorColor: NV.raised,
    ),
    listTileTheme: ListTileThemeData(
      iconColor: NV.muted,
      textColor: NV.text,
      selectedColor: NV.text,
      selectedTileColor: NV.redWash,
      tileColor: Colors.transparent,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16),
      shape: ctlShape,
      titleTextStyle: TextStyle(fontFamily: NV.sans, fontSize: 15, color: NV.text, fontWeight: FontWeight.w500),
      subtitleTextStyle: TextStyle(fontFamily: NV.sans, fontSize: 12.5, color: NV.muted),
    ),
    expansionTileTheme: ExpansionTileThemeData(
      iconColor: NV.muted,
      collapsedIconColor: NV.muted,
      textColor: NV.text,
      collapsedTextColor: NV.text,
      shape: ctlShape,
      collapsedShape: ctlShape,
    ),
    snackBarTheme: SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      backgroundColor: NV.raised,
      elevation: 0,
      contentTextStyle: TextStyle(fontFamily: NV.sans, color: NV.text, fontSize: 14),
      actionTextColor: NV.red,
      closeIconColor: NV.muted,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(NV.rCard), side: BorderSide(color: NV.borderStrong)),
    ),
    bannerTheme: MaterialBannerThemeData(
      backgroundColor: NV.surface,
      surfaceTintColor: Colors.transparent,
      shadowColor: Colors.transparent,
      dividerColor: NV.border,
      elevation: 0,
      contentTextStyle: TextStyle(fontFamily: NV.sans, color: NV.text, fontSize: 13.5),
    ),
    badgeTheme: BadgeThemeData(
      backgroundColor: NV.red,
      textColor: NV.onRed,
      textStyle: TextStyle(fontFamily: NV.sans, fontSize: 12, fontWeight: FontWeight.w500),
    ),
    tabBarTheme: TabBarThemeData(
      labelColor: NV.text,
      unselectedLabelColor: NV.muted,
      indicatorColor: NV.red,
      dividerColor: NV.border,
      overlayColor: WidgetStatePropertyAll(press),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: NV.surface,
      surfaceTintColor: Colors.transparent,
      shadowColor: Colors.transparent,
      indicatorColor: NV.redWash,
      indicatorShape: ctlShape,
      elevation: 0,
      labelTextStyle: WidgetStateProperty.resolveWith((s) => NV.monoLabel(color: s.contains(WidgetState.selected) ? NV.text : NV.muted)),
      iconTheme: WidgetStateProperty.resolveWith((s) => IconThemeData(color: s.contains(WidgetState.selected) ? NV.red : NV.muted)),
    ),
    navigationRailTheme: NavigationRailThemeData(
      backgroundColor: NV.surface,
      indicatorColor: NV.redWash,
      selectedIconTheme: IconThemeData(color: NV.red),
      unselectedIconTheme: IconThemeData(color: NV.muted),
    ),
    drawerTheme: DrawerThemeData(
      backgroundColor: NV.surface,
      surfaceTintColor: Colors.transparent,
      shadowColor: Colors.transparent,
      elevation: 0,
    ),
    progressIndicatorTheme: ProgressIndicatorThemeData(
      color: NV.red,
      linearTrackColor: NV.border,
      circularTrackColor: Colors.transparent,
      refreshBackgroundColor: NV.surface,
    ),
    tooltipTheme: TooltipThemeData(
      decoration: BoxDecoration(color: NV.raised, borderRadius: BorderRadius.circular(8), border: Border.all(color: NV.borderStrong)),
      textStyle: TextStyle(fontFamily: NV.sans, color: NV.text, fontSize: 12),
      waitDuration: const Duration(milliseconds: 300),
    ),
    scrollbarTheme: ScrollbarThemeData(
      thumbColor: WidgetStatePropertyAll(NV.borderStrong.withValues(alpha: 0.9)),
      radius: const Radius.circular(8),
    ),
    datePickerTheme: DatePickerThemeData(
      backgroundColor: NV.surface,
      surfaceTintColor: Colors.transparent,
      shadowColor: Colors.transparent,
      elevation: 0,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(NV.rDialog), side: line),
    ),
    timePickerTheme: TimePickerThemeData(
      backgroundColor: NV.surface,
      elevation: 0,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(NV.rDialog), side: line),
    ),
    searchBarTheme: SearchBarThemeData(
      backgroundColor: WidgetStatePropertyAll(NV.surface),
      surfaceTintColor: const WidgetStatePropertyAll(Colors.transparent),
      shadowColor: const WidgetStatePropertyAll(Colors.transparent),
      elevation: const WidgetStatePropertyAll(0),
      shape: WidgetStatePropertyAll(ctlShapeLined),
    ),
    extensions: [
      NvColors(
        card: NV.surface,
        muted: NV.raised,
        mutedForeground: NV.muted,
        popover: NV.surface,
        border: NV.border,
        strokeSoft: NV.border,
        midground: NV.red,
        destructive: NV.red,
        success: NV.ok,
        warning: NV.warn,
        info: NV.muted,
        sidebar: NV.surface,
        sidebarBorder: NV.border,
        userBubble: NV.redWash,
        userBubbleBorder: NV.darkRed,
        codeBg: Color.lerp(NV.bg, NV.palette.dark ? const Color(0xFF000000) : const Color(0xFFFFFFFF), 0.3)!,
        monoFamily: NV.mono,
        displayFamily: NV.serif,
        brand: false,
        corner: NV.rCtl,
        paper: null,
      ),
    ],
  );
}
