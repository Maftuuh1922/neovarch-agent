// Phone theme: follows the PC's appearance (accent preset/custom hex +
// dark/light, from `GET /api/appearance` and the `appearance.changed` push)
// unless the user set a local override on this phone. The last PC look is
// cached so the app starts in it before the socket is up.
import 'dart:io' show Platform;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/legacy.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../theme/neovarch_mobile_theme.dart';
import 'ui/appearance/panel_tone.dart' show NvGlassFx;
import 'wallpaper_palette.dart';

/// Accent presets. The first six match the desktop theme picker; the rest
/// are phone extras. Every one tints the whole UI (surfaces, glass, nav,
/// chips, buttons), not just the accent.
const accentPresets = <(String, Color)>[
  ('Merah', Color(0xFFEE1C1C)),
  ('Biru', Color(0xFF2563EB)),
  ('Hijau', Color(0xFF16A34A)),
  ('Ungu', Color(0xFF7C3AED)),
  ('Oranye', Color(0xFFEA580C)),
  ('Monokrom', Color(0xFFA3A3A3)),
  ('Mawar', Color(0xFFE11D48)),
  ('Merah muda', Color(0xFFDB2777)),
  ('Nila', Color(0xFF4F46E5)),
  ('Langit', Color(0xFF0284C7)),
  ('Toska', Color(0xFF0D9488)),
  ('Limau', Color(0xFF65A30D)),
  ('Kuning', Color(0xFFCA8A04)),
  ('Cokelat', Color(0xFF9A6B4F)),
];

Color? parseHexColor(String? raw) {
  var s = (raw ?? '').trim();
  if (s.startsWith('#')) s = s.substring(1);
  if (s.length == 3) s = s.split('').map((c) => '$c$c').join();
  if (s.length != 6 || int.tryParse(s, radix: 16) == null) return null;
  return Color(0xFF000000 | int.parse(s, radix: 16));
}

String hexOf(Color c) => '#${(c.toARGB32() & 0xFFFFFF).toRadixString(16).padLeft(6, '0').toUpperCase()}';

/// Light / dark / follow the phone's system setting (local theme only; the
/// PC look always carries its own dark/light).
enum NvBrightnessMode { dark, light, system }

/// Bundled background presets (existing art, tinted by the accent slider).
const backgroundPresets = <(String, String)>[
  ('Remote', 'assets/art/feat-remote.webp'),
  ('Otomasi', 'assets/art/feat-automation.webp'),
  ('Portal', 'assets/art/portal-banner.webp'),
];

/// App background behind the shell tabs, so the liquid glass has something
/// to refract. [source] is '' (flat, the default), `asset:<path>` or
/// `file:<path>` (a gallery image copied into the app documents dir).
@immutable
class NvBackground {
  const NvBackground({this.source = '', this.blur = 6, this.dim = 0.4, this.tint = 0.15, this.saturation = 1.0, this.glass = NV.glassBlur});
  final String source;
  final double blur; // 0..30 sigma
  final double dim; // 0..0.8 overlay of the theme background colour
  final double tint; // 0..0.6 accent overlay
  final double saturation; // 0..2
  final double glass; // glass blur strength 0..40 ("Kekuatan kaca")
  bool get active => source.isNotEmpty;
  bool get isFile => source.startsWith('file:');
  bool get isAsset => source.startsWith('asset:');
  String get path => source.substring(source.indexOf(':') + 1);

  NvBackground copyWith({String? source, double? blur, double? dim, double? tint, double? saturation, double? glass}) => NvBackground(
      source: source ?? this.source,
      blur: (blur ?? this.blur).clamp(0.0, 30.0),
      dim: (dim ?? this.dim).clamp(0.0, 0.8),
      tint: (tint ?? this.tint).clamp(0.0, 0.6),
      saturation: (saturation ?? this.saturation).clamp(0.0, 2.0),
      glass: (glass ?? this.glass).clamp(0.0, 40.0));

  @override
  bool operator ==(Object other) =>
      other is NvBackground && other.source == source && other.blur == blur && other.dim == dim && other.tint == tint && other.saturation == saturation && other.glass == glass;
  @override
  int get hashCode => Object.hash(source, blur, dim, tint, saturation, glass);
}

class AppearanceController extends ChangeNotifier {
  AppearanceController(this._prefs, {Brightness? systemBrightness}) {
    _system = systemBrightness ?? _platformBrightness();
    _load();
    _apply();
  }
  final SharedPreferences _prefs;
  /// For sibling phone settings stored next to the theme (launcher icon).
  SharedPreferences get prefs => _prefs;

  static const _kFollow = 'nv.theme.follow';
  static const _kAccent = 'nv.theme.accent';
  static const _kBase = 'nv.theme.base';
  static const _kPcAccent = 'nv.theme.pc.accent';
  static const _kPcBase = 'nv.theme.pc.base';
  static const _kBgSource = 'nv.bg.source';
  static const _kBgBlur = 'nv.bg.blur';
  static const _kBgDim = 'nv.bg.dim';
  static const _kBgTint = 'nv.bg.tint';
  static const _kBgSat = 'nv.bg.saturation';
  static const _kGlass = 'nv.glass.blur';
  static const _kGlassStyle = 'nv.glass.style';
  static const _kWallColors = 'nv.bg.autoColor';
  static const _kWallSwatches = 'nv.bg.swatches';
  static const kLite = 'nv.perf.lite';

  /// Resolved boot colours, read natively by MainActivity (window background
  /// before Flutter draws) so a cold start opens straight in this look.
  static const kBootBg = 'nv.boot.bg';
  static const kBootDark = 'nv.boot.dark';

  /// True: use the PC's look. False: [localAccent] / [localMode].
  bool followPc = true;
  Color localAccent = NvPalette.defaultAccent;
  NvBrightnessMode localMode = NvBrightnessMode.dark;

  Color pcAccent = NvPalette.defaultAccent;
  bool pcDark = true;
  Color? pcOnAccent;

  Brightness _system = Brightness.dark;

  /// Background image + glass strength (no palette change, no cross-fade).
  NvBackground background = const NvBackground();

  /// "Gaya kaca" (stored by name: reguler, bening, gelap, warna, tanpa).
  NvGlassStyle glassStyle = NvGlassStyle.reguler;

  /// "Mode ringan": no backdrop blur anywhere (NvGlass, the glass cards,
  /// LiquidGlass bubbles) — solid surfaces instead, for slower phones.
  bool liteMode = false;

  /// "Warna dari wallpaper": the accent follows the background image.
  /// On by default; a manual accent pick turns it off.
  bool wallpaperColors = true;
  /// Suggested accents extracted from the current wallpaper (3–5).
  List<Color> wallpaperSwatches = const [];

  /// Extracts the palette of a background (swappable in tests).
  static Future<WallpaperPalette?> Function(NvBackground b, bool dark) paletteLoader = _loadPalette;
  static Future<WallpaperPalette?> _loadPalette(NvBackground b, bool dark) async {
    // widget tests: no real image decoding (it would leave timers pending)
    if (const bool.fromEnvironment('dart.vm.product') == false && Platform.environment.containsKey('FLUTTER_TEST')) return null;
    final img = imageForSource(b.source);
    return img == null ? null : extractWallpaperPalette(img, dark: dark);
  }

  /// Called right before the palette changes, while the old frame is still
  /// on screen (the app snapshots it to cross-fade into the new look).
  VoidCallback? onBeforeChange;

  /// Bumped on every palette change; the app rebuilds every element on it.
  int revision = 0;

  bool get localDark => switch (localMode) {
        NvBrightnessMode.dark => true,
        NvBrightnessMode.light => false,
        NvBrightnessMode.system => _system == Brightness.dark,
      };

  Color get accent => followPc ? pcAccent : localAccent;
  bool get dark => followPc ? pcDark : localDark;
  NvPalette get palette => NvPalette.from(accent, dark ? Brightness.dark : Brightness.light, onAccent: followPc ? pcOnAccent : null);

  static Brightness _platformBrightness() {
    try {
      return WidgetsBinding.instance.platformDispatcher.platformBrightness;
    } catch (_) {
      return Brightness.dark;
    }
  }

  void _load() {
    followPc = _prefs.getBool(_kFollow) ?? true;
    localAccent = parseHexColor(_prefs.getString(_kAccent)) ?? NvPalette.defaultAccent;
    localMode = switch (_prefs.getString(_kBase)) {
      'light' => NvBrightnessMode.light,
      'system' => NvBrightnessMode.system,
      _ => NvBrightnessMode.dark,
    };
    pcAccent = parseHexColor(_prefs.getString(_kPcAccent)) ?? NvPalette.defaultAccent;
    pcDark = (_prefs.getString(_kPcBase) ?? 'dark') != 'light';
    const d = NvBackground();
    background = d.copyWith(
      source: _prefs.getString(_kBgSource) ?? '',
      blur: _prefs.getDouble(_kBgBlur) ?? d.blur,
      dim: _prefs.getDouble(_kBgDim) ?? d.dim,
      tint: _prefs.getDouble(_kBgTint) ?? d.tint,
      saturation: _prefs.getDouble(_kBgSat) ?? d.saturation,
      glass: _prefs.getDouble(_kGlass) ?? d.glass,
    );
    NV.glassSigma.value = background.glass;
    glassStyle = NvGlassStyle.parse(_prefs.getString(_kGlassStyle));
    liteMode = _prefs.getBool(kLite) ?? false;
    _bindGlass();
    wallpaperColors = _prefs.getBool(_kWallColors) ?? true;
    wallpaperSwatches = [for (final h in _prefs.getStringList(_kWallSwatches) ?? const <String>[]) ?parseHexColor(h)];
  }

  /// The style goes app-wide; "Tanpa efek" is the appearance UI's
  /// reduce-transparency switch.
  void _bindGlass() {
    NV.glassStyle = glassStyle;
    NV.liteMode = liteMode;
    NvGlassFx.reduceTransparency.value = glassStyle == NvGlassStyle.tanpa || liteMode;
  }

  /// Turns "Mode ringan" on/off (persisted; every glass widget repaints).
  void setLiteMode(bool v) {
    if (v == liteMode) return;
    onBeforeChange?.call();
    liteMode = v;
    _bindGlass();
    _prefs.setBool(kLite, v);
    revision++;
    notifyListeners();
  }

  void setGlassStyle(NvGlassStyle s) {
    if (s == glassStyle) return;
    onBeforeChange?.call();
    glassStyle = s;
    _bindGlass();
    _prefs.setString(_kGlassStyle, s.name);
    revision++;
    notifyListeners();
  }

  /// Turns "Warna dari wallpaper" on/off; on = re-extract from the current image.
  Future<void> setWallpaperColors(bool v) async {
    wallpaperColors = v;
    await _prefs.setBool(_kWallColors, v);
    notifyListeners();
    if (v) await refreshWallpaperPalette();
  }

  /// Extracts the wallpaper palette and, with [wallpaperColors] on, uses its
  /// seed as the accent.
  Future<void> refreshWallpaperPalette() async {
    if (!background.active) return;
    final src = background.source;
    final p = await paletteLoader(background, dark);
    if (p == null || background.source != src) return;
    applyWallpaperPalette(p);
  }

  /// Stores the swatches; with [wallpaperColors] on, the seed becomes the accent.
  void applyWallpaperPalette(WallpaperPalette p) {
    wallpaperSwatches = p.swatches;
    _prefs.setStringList(_kWallSwatches, [for (final c in p.swatches) hexOf(c)]);
    if (wallpaperColors) {
      _setLocalAccent(p.seed);
    } else {
      notifyListeners();
    }
  }

  /// A suggested wallpaper swatch picked by the user (keeps the toggle on).
  void pickWallpaperSwatch(Color c) => _setLocalAccent(c);

  /// Live background change (sliders, picker); persisted at once.
  void setBackground(NvBackground b) {
    if (b == background) return;
    final newImage = b.source != background.source;
    background = b;
    NV.glassSigma.value = b.glass;
    _prefs
      ..setString(_kBgSource, b.source)
      ..setDouble(_kBgBlur, b.blur)
      ..setDouble(_kBgDim, b.dim)
      ..setDouble(_kBgTint, b.tint)
      ..setDouble(_kBgSat, b.saturation)
      ..setDouble(_kGlass, b.glass);
    notifyListeners();
    if (newImage) {
      if (b.active) {
        // a newly chosen wallpaper: colours from it (unless turned off)
        refreshWallpaperPalette();
      } else {
        wallpaperSwatches = const [];
        _prefs.remove(_kWallSwatches);
      }
    }
  }

  /// "Reset": flat background, default sliders and glass strength.
  void resetBackground() => setBackground(const NvBackground());

  bool _same(NvPalette p) => NV.palette.accent == p.accent && NV.palette.brightness == p.brightness && NV.palette.onAccent == p.onAccent;

  void _apply() {
    final p = palette;
    if (_same(p) && revision > 0) return;
    if (revision > 0) onBeforeChange?.call();
    NV.palette = p;
    revision++;
    _prefs
      ..setString(kBootBg, hexOf(p.bg))
      ..setString(kBootDark, p.dark ? '1' : '0');
    notifyListeners();
  }

  /// From `GET /api/appearance` or the `appearance.changed` push.
  void applyPc(Map<String, dynamic> a) {
    final c = parseHexColor('${a['accent'] ?? ''}');
    if (c == null) return;
    pcAccent = c;
    pcDark = '${a['base'] ?? 'dark'}' != 'light';
    pcOnAccent = parseHexColor('${a['on_accent'] ?? ''}');
    // optional "Gaya kaca" from the PC theme (same names as on the phone)
    final gs = a['glass_style'];
    if (gs is String && followPc) {
      glassStyle = NvGlassStyle.parse(gs);
      _bindGlass();
      _prefs.setString(_kGlassStyle, glassStyle.name);
    }
    _prefs.setString(_kPcAccent, hexOf(c));
    _prefs.setString(_kPcBase, pcDark ? 'dark' : 'light');
    _apply();
  }

  void setFollowPc(bool v) {
    followPc = v;
    _prefs.setBool(_kFollow, v);
    _apply();
  }

  /// The phone's dark/light setting changed (matters for [NvBrightnessMode.system]).
  void setSystemBrightness(Brightness b) {
    if (_system == b) return;
    _system = b;
    _apply();
  }

  void _setLocalAccent(Color c) {
    localAccent = c.withAlpha(255);
    followPc = false;
    _prefs
      ..setBool(_kFollow, false)
      ..setString(_kAccent, hexOf(localAccent))
      ..setString(_kBase, localMode.name);
    _apply();
    notifyListeners();
  }

  /// Local override (turns following the PC off). A manual accent also
  /// turns "Warna dari wallpaper" off.
  void setLocal({Color? accent, bool? dark, NvBrightnessMode? mode}) {
    if (accent != null) {
      localAccent = accent.withAlpha(255);
      if (wallpaperColors && background.active) {
        wallpaperColors = false;
        _prefs.setBool(_kWallColors, false);
      }
    }
    if (mode != null) {
      localMode = mode;
    } else if (dark != null) {
      localMode = dark ? NvBrightnessMode.dark : NvBrightnessMode.light;
    }
    followPc = false;
    _prefs
      ..setBool(_kFollow, false)
      ..setString(_kAccent, hexOf(localAccent))
      ..setString(_kBase, localMode.name);
    _apply();
  }
}

final appearanceProvider = ChangeNotifierProvider<AppearanceController>((ref) => throw UnimplementedError());

/// Marks every element below [context] dirty so widgets that read the
/// palette tokens (`NV.*`, incl. const ones) repaint in the new colours
/// without losing their state.
void rebuildAllChildren(BuildContext context) {
  void rebuild(Element el) {
    el.markNeedsBuild();
    el.visitChildren(rebuild);
  }

  (context as Element).visitChildren(rebuild);
}
