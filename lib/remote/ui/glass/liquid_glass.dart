// LiquidGlass: the reusable liquid glass surface for chat bubbles and cards.
//
//   backdrop blur (σ by style) + saturation boost  →  adaptive fill tint
//   (accent + backdrop) → soft inner highlight → 1px specular rim (bright
//   top-left fading out) → soft outside-only shadow, on continuous
//   (superellipse) corners.
//
// The fill opacity and light/dark text are resolved per element from the
// wallpaper luminance under its on-screen rect (GlassScope.backdrop), so
// text stays ≥ 4.5:1 over any photo. Descendants read the result through
// [GlassForeground] (and, with `themed: true`, a matching Theme so shared
// widgets like AssistantMessage / MarkdownView follow it).
//
// Performance: one RepaintBoundary per surface; inside a [BackdropGroup]
// the filters share one backdrop read (BackdropFilter.grouped), so a long
// chat list does not cost one backdrop copy per bubble.
import 'dart:ui' as ui show ImageFilter;

import 'package:flutter/material.dart';
import 'package:flutter/physics.dart' show SpringDescription, SpringSimulation;

import '../../../theme/app_theme.dart' show NvColors;
import '../../../theme/neovarch_mobile_theme.dart';
import '../../../ui/widgets/motion.dart' show reduceMotion;
import 'glass_style.dart';
import 'glass_tone.dart';

/// The resolved glass tone for the subtree (text colours, accent, error).
class GlassForeground extends InheritedWidget {
  const GlassForeground({super.key, required this.tone, this.isCode = false, required super.child});
  final GlassTone tone;

  /// True inside a code block (prevents re-wrapping).
  final bool isCode;

  static GlassForeground? maybeOf(BuildContext context) => context.dependOnInheritedWidgetOfExactType<GlassForeground>();

  @override
  bool updateShouldNotify(GlassForeground old) => old.tone != tone || old.isCode != isCode;
}

/// Backdrop filter: blur + saturation boost (Rec. 709 luma weights).
ui.ImageFilter liquidGlassFilter(double sigma, double saturation) {
  const lr = 0.2126, lg = 0.7152, lb = 0.0722;
  final s = saturation, a = 1 - s;
  return ui.ImageFilter.compose(
    outer: ColorFilter.matrix(<double>[
      lr * a + s, lg * a, lb * a, 0, 0, //
      lr * a, lg * a + s, lb * a, 0, 0, //
      lr * a, lg * a, lb * a + s, 0, 0, //
      0, 0, 0, 1, 0,
    ]),
    inner: ui.ImageFilter.blur(sigmaX: sigma, sigmaY: sigma, tileMode: TileMode.mirror),
  );
}

final Map<Object, ThemeData> _themeCache = {};

/// A Theme matching [tone]: the Neovarch theme for the foreground brightness
/// (light text → dark set) with text, accent, error and code colours from
/// the tone and transparent surfaces, so shared widgets render on glass.
ThemeData glassThemeFor(GlassTone tone, {bool code = false}) {
  final p = NV.palette;
  final key = Object.hash(p.accent, p.onAccent, p.brightness, tone.lightText, tone.text, tone.secondary, tone.accent, tone.error, tone.fill, code);
  final hit = _themeCache[key];
  if (hit != null) return hit;
  final ThemeData base;
  try {
    NV.palette = NvPalette.from(p.accent, tone.lightText ? Brightness.dark : Brightness.light, onAccent: p.onAccent);
    base = buildNeovarchMobileTheme();
  } finally {
    NV.palette = p;
  }
  final hc = base.extension<NvColors>()!;
  final line = tone.text.withValues(alpha: 0.16);
  final tt = base.textTheme.apply(bodyColor: tone.text, displayColor: tone.text);
  final t = base.copyWith(
    colorScheme: base.colorScheme.copyWith(primary: tone.accent, onSurface: tone.text, onSurfaceVariant: tone.secondary, error: tone.error),
    textTheme: tt.copyWith(
      bodySmall: tt.bodySmall?.copyWith(color: tone.secondary),
      labelSmall: tt.labelSmall?.copyWith(color: tone.secondary),
    ),
    iconTheme: base.iconTheme.copyWith(color: tone.secondary),
    dividerColor: line,
    textButtonTheme: TextButtonThemeData(
      style: (base.textButtonTheme.style ?? const ButtonStyle()).copyWith(
        foregroundColor: WidgetStatePropertyAll(tone.text),
        iconColor: WidgetStatePropertyAll(tone.secondary),
        overlayColor: WidgetStatePropertyAll(tone.text.withValues(alpha: 0.08)),
      ),
    ),
    extensions: [
      NvColors(
        card: Colors.transparent,
        muted: tone.text.withValues(alpha: 0.07),
        mutedForeground: tone.secondary,
        popover: hc.popover,
        border: line,
        strokeSoft: tone.text.withValues(alpha: 0.12),
        midground: tone.accent,
        destructive: tone.error,
        success: tone.text,
        warning: tone.error,
        info: tone.secondary,
        sidebar: hc.sidebar,
        sidebarBorder: hc.sidebarBorder,
        userBubble: tone.fill,
        userBubbleBorder: line,
        codeBg: code ? tone.fill : tone.text.withValues(alpha: 0.10),
        monoFamily: hc.monoFamily,
        displayFamily: hc.displayFamily,
        brand: hc.brand,
        corner: hc.corner,
        paper: null,
      ),
    ],
  );
  if (_themeCache.length > 32) _themeCache.clear();
  return _themeCache[key] = t;
}

/// Wraps [child] in the foreground of [tone]: default text/icon colours,
/// and (when [themed]) the matching Theme.
Widget glassForeground(GlassTone tone, Widget child, {bool themed = false, bool code = false}) {
  Widget c = IconTheme.merge(data: IconThemeData(color: tone.secondary), child: DefaultTextStyle.merge(style: TextStyle(color: tone.text), child: child));
  if (themed || code) c = Theme(data: glassThemeFor(tone, code: code), child: c);
  return GlassForeground(tone: tone, isCode: code, child: c);
}

/// Liquid glass surface.
class LiquidGlass extends StatefulWidget {
  const LiquidGlass({
    super.key,
    required this.child,
    this.style,
    this.role = GlassRole.neutral,
    this.borderRadius = const BorderRadius.all(Radius.circular(20)),
    this.padding = EdgeInsets.zero,
    this.sigma,
    this.shadow = true,
    this.themed = false,
    this.appear = false,
    this.tone,
  });

  final Widget child;

  /// Variant; null = the nearest [GlassScope] (default [GlassStyle.reguler]).
  final GlassStyle? style;
  final GlassRole role;
  final BorderRadius borderRadius;
  final EdgeInsetsGeometry padding;

  /// Blur override (default: the style's sigma).
  final double? sigma;
  final bool shadow;

  /// Also provide a Theme matching the glass to the subtree.
  final bool themed;

  /// Play the "materialize" entrance (scale 0.96→1, blur-in, fade).
  final bool appear;

  /// Fixed tone (skips backdrop sampling).
  final GlassTone? tone;

  @override
  State<LiquidGlass> createState() => _LiquidGlassState();
}

class _LiquidGlassState extends State<LiquidGlass> with SingleTickerProviderStateMixin {
  Rect? _rect;
  ScrollPosition? _scroll;
  AnimationController? _appear;
  bool _scheduled = false;

  static const spring = SpringDescription(mass: 1, stiffness: 420, damping: 36);

  @override
  void initState() {
    super.initState();
    if (widget.appear) {
      _appear = AnimationController.unbounded(vsync: this, value: 0);
    }
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final pos = Scrollable.maybeOf(context)?.position;
    if (pos != _scroll) {
      _scroll?.removeListener(_schedule);
      _scroll = pos?..addListener(_schedule);
    }
    final a = _appear;
    if (a != null && a.value == 0 && !a.isAnimating) {
      if (reduceMotion(context)) {
        a.value = 1;
      } else {
        a.animateWith(SpringSimulation(spring, 0, 1, 0)).whenCompleteOrCancel(() {
          if (mounted) a.value = 1;
        });
      }
    }
  }

  @override
  void dispose() {
    _scroll?.removeListener(_schedule);
    _appear?.dispose();
    super.dispose();
  }

  void _schedule() {
    if (_scheduled) return;
    _scheduled = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _scheduled = false;
      if (!mounted) return;
      final box = context.findRenderObject();
      if (box is! RenderBox || !box.attached || !box.hasSize) return;
      final r = box.localToGlobal(Offset.zero) & box.size;
      if (_rect == null || (r.topLeft - _rect!.topLeft).distance > 2 || r.size != _rect!.size) {
        final before = _resolve(context, _rect);
        _rect = r;
        if (_resolve(context, r) != before) setState(() {});
      }
    });
  }

  GlassTone _resolve(BuildContext context, Rect? rect) {
    if (widget.tone != null) return widget.tone!;
    final scope = GlassScope.maybeOf(context);
    final style = NV.liteMode ? GlassStyle.tanpa : (widget.style ?? scope?.style ?? GlassStyle.reguler);
    final map = scope?.backdrop;
    final sample = map == null
        ? BackdropSample.solid(NV.bg)
        : map.sample(rect ?? (Offset.zero & (map.screen.isEmpty ? const Size(1, 1) : map.screen)));
    final hc = MediaQuery.maybeHighContrastOf(context) ?? false;
    final t = resolveGlassTone(sample: sample, accent: NV.red, style: style, role: widget.role, previousLightText: _lastLight, highContrast: hc);
    return t;
  }

  bool? _lastLight;

  @override
  Widget build(BuildContext context) {
    _schedule();
    // "Mode ringan": no backdrop filter, the near-solid "tanpa" surface.
    final style = NV.liteMode ? GlassStyle.tanpa : (widget.style ?? GlassScope.styleOf(context));
    final tone = _resolve(context, _rect);
    _lastLight = tone.lightText;
    final br = widget.borderRadius;
    final a = _appear;
    Widget build(double v) {
      // follows "Kekuatan kaca" (NV.glassSigma, default 22) proportionally
      final sigma = (widget.sigma ?? style.sigma * (NV.glassSigma.value / NV.glassBlur)) * v.clamp(0.0, 1.0);
      Widget content = glassForeground(tone, Padding(padding: widget.padding, child: widget.child), themed: widget.themed, code: widget.role == GlassRole.code);
      if (v < 1) content = Opacity(opacity: v.clamp(0.0, 1.0), child: content);
      Widget s = CustomPaint(
        painter: _GlassFillPainter(br, tone.fill.withValues(alpha: tone.fill.a * v.clamp(0.0, 1.0)), highlight: style != GlassStyle.tanpa, lightText: tone.lightText),
        foregroundPainter: _GlassRimPainter(br, tone.rim.withValues(alpha: tone.rim.a * v.clamp(0.0, 1.0))),
        child: content,
      );
      if (style != GlassStyle.tanpa && sigma > 0.01) {
        final f = liquidGlassFilter(sigma, style.saturation);
        // Grouped (shared backdrop read) at rest; the animating entrance has
        // its own sigma so it cannot share the group's filter.
        s = v >= 1 ? BackdropFilter.grouped(filter: f, child: s) : BackdropFilter(filter: f, child: s);
      }
      s = ClipRSuperellipse(borderRadius: br, child: s);
      if (widget.shadow) s = CustomPaint(painter: _GlassShadowPainter(br, v.clamp(0.0, 1.0), tone.lightText), child: s);
      if (v < 1) s = Transform.scale(scale: 0.96 + 0.04 * v, child: s);
      return s;
    }

    final body = a == null || a.value >= 1
        ? build(1)
        : AnimatedBuilder(animation: a, builder: (context, _) => build(a.value >= 1 ? 1 : a.value));
    return RepaintBoundary(child: KeyedSubtree(key: const ValueKey('liquid-glass'), child: body));
  }
}

Path _shape(BorderRadius br, Rect r) => RoundedSuperellipseBorder(borderRadius: br).getOuterPath(r);

class _GlassFillPainter extends CustomPainter {
  _GlassFillPainter(this.br, this.fill, {required this.highlight, required this.lightText});
  final BorderRadius br;
  final Color fill;
  final bool highlight, lightText;
  @override
  void paint(Canvas canvas, Size size) {
    final r = Offset.zero & size;
    final path = _shape(br, r);
    canvas.drawPath(path, Paint()..color = fill);
    if (!highlight) return;
    // soft inner highlight: a top sheen fading out by ~45% height
    canvas.drawPath(
      path,
      Paint()
        ..shader = LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [Colors.white.withValues(alpha: lightText ? 0.07 : 0.22), Colors.white.withValues(alpha: 0)],
          stops: const [0, 0.45],
        ).createShader(r),
    );
  }

  @override
  bool shouldRepaint(_GlassFillPainter o) => o.br != br || o.fill != fill || o.highlight != highlight || o.lightText != lightText;
}

/// 1px specular rim: bright top-left → transparent, faint pick-up bottom-right.
class _GlassRimPainter extends CustomPainter {
  _GlassRimPainter(this.br, this.rim);
  final BorderRadius br;
  final Color rim;
  @override
  void paint(Canvas canvas, Size size) {
    if (size.isEmpty || rim.a == 0) return;
    final r = Offset.zero & size;
    Color al(double f) => rim.withValues(alpha: (rim.a * f).clamp(0.0, 1.0));
    canvas.drawPath(
      _shape(br, r.deflate(0.5)),
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1
        ..shader = LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [al(1), al(0.23), al(0.0), al(0.23)],
          stops: const [0, 0.35, 0.7, 1],
        ).createShader(r),
    );
  }

  @override
  bool shouldRepaint(_GlassRimPainter o) => o.br != br || o.rim != rim;
}

/// Soft shadow painted only outside the shape (never darkens the glass).
class _GlassShadowPainter extends CustomPainter {
  _GlassShadowPainter(this.br, this.v, this.lightText);
  final BorderRadius br;
  final double v;
  final bool lightText;
  @override
  void paint(Canvas canvas, Size size) {
    if (size.isEmpty || v == 0) return;
    final r = Offset.zero & size;
    final shape = _shape(br, r);
    final outside = Path.combine(PathOperation.difference, Path()..addRect(r.inflate(40)), shape);
    canvas.save();
    canvas.clipPath(outside);
    canvas.drawPath(
      _shape(br, r.shift(const Offset(0, 6))),
      Paint()
        // spec §5.2: 0 6px 20px, α ~0.12 over light / ~0.24 over dark
        ..color = Colors.black.withValues(alpha: (lightText ? 0.24 : 0.12) * v)
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 10),
    );
    canvas.restore();
  }

  @override
  bool shouldRepaint(_GlassShadowPainter o) => o.br != br || o.v != v || o.lightText != lightText;
}

/// Darker glass for code blocks inside a glass surface (no extra blur: the
/// surrounding glass already refracts). Outside glass it is a no-op.
class GlassCode extends StatelessWidget {
  const GlassCode({super.key, required this.child});
  final Widget child;
  @override
  Widget build(BuildContext context) {
    final parent = GlassForeground.maybeOf(context);
    if (parent == null || parent.isCode) return child;
    final tone = resolveGlassTone(sample: BackdropSample.solid(parent.tone.composite), accent: NV.red, role: GlassRole.code);
    return glassForeground(tone, child, code: true);
  }
}
