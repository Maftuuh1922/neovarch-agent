// Liquid glass building blocks for the appearance screen (usable app-wide):
// card, section capsule, chip, switch and slider. All of them read the
// adaptive [NvPanelTone] (fill solved for legibility over the wallpaper) and
// [AppCornerRadius]; with "reduce transparency" they turn opaque and drop the
// specular rim, with "reduce motion" they stop animating.
import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show HapticFeedback;

import '../../../theme/neovarch_mobile_theme.dart';
import '../nv_widgets.dart' show NvGlassRimPainter, nvGlassFilter;
import 'corner_radius.dart';
import 'panel_tone.dart';

/// Spacing rhythm (4-pt grid) used across the appearance screen.
abstract final class NvSpace {
  static const xs = 4.0;
  static const s = 8.0;
  static const m = 12.0;
  static const l = 16.0;
  static const xl = 20.0;
  static const xxl = 28.0;
}

Duration nvMotion(BuildContext context, int ms) => NvGlassFx.reducedMotion(context) ? Duration.zero : Duration(milliseconds: ms);

/// Glass surface: backdrop blur + saturation lift, adaptive fill, hairline,
/// 1px specular rim. [radius] defaults to the user's card radius.
class NvGlassSurface extends StatelessWidget {
  const NvGlassSurface({super.key, required this.child, this.radius, this.padding = EdgeInsets.zero, this.fill, this.rimStrength = 1.0, this.blur, this.chroma = false});
  final Widget child;
  final double? radius;
  final EdgeInsetsGeometry padding;
  final Color? fill;
  final double rimStrength;
  final double? blur;
  final bool chroma;

  @override
  Widget build(BuildContext context) {
    final tone = NvPanelToneScope.of(context);
    final r = radius ?? AppCornerRadius.of(context).card;
    final br = BorderRadius.circular(r);
    final body = CustomPaint(
      foregroundPainter: tone.reduced ? null : NvGlassRimPainter(borderRadius: br, rim: tone.rim, strength: rimStrength, chroma: chroma),
      child: AnimatedContainer(
        duration: nvMotion(context, 220),
        curve: Curves.easeOutCubic,
        decoration: BoxDecoration(
          color: fill ?? tone.fill,
          borderRadius: br,
          border: Border.all(color: tone.hairline, width: 0.8),
        ),
        padding: padding,
        child: child,
      ),
    );
    // reduce transparency or "Mode ringan": no backdrop blur
    if (tone.reduced || NV.liteMode) return ClipRRect(borderRadius: br, child: body);
    return ClipRRect(
      borderRadius: br,
      child: ValueListenableBuilder<double>(
        valueListenable: NV.glassSigma,
        child: body,
        builder: (context, sigma, child) => BackdropFilter(filter: nvGlassFilter(blur ?? sigma), child: child!),
      ),
    );
  }
}

/// Card with a title row (tinted icon tile, title, optional caption and
/// trailing) and content. The title lives inside the glass, so it is
/// always legible.
class NvGlassCard extends StatelessWidget {
  const NvGlassCard({super.key, this.icon, this.title, this.caption, this.trailing, required this.child, this.padding = const EdgeInsets.fromLTRB(NvSpace.l, NvSpace.l, NvSpace.l, NvSpace.l), this.bleed = false});
  final IconData? icon;
  final String? title;
  final String? caption;
  final Widget? trailing;
  final Widget child;
  final EdgeInsets padding;
  /// Child gets the full card width (it pads itself, e.g. a scroll row
  /// that should run under the card edges); the title keeps [padding].
  final bool bleed;

  @override
  Widget build(BuildContext context) {
    final tone = NvPanelToneScope.of(context);
    final radii = AppCornerRadius.of(context);
    final hPad = EdgeInsets.only(left: padding.left, right: padding.right);
    final tileR = radii.inner(radii.card, padding.left).clamp(0.0, 10.0);
    return NvGlassSurface(
      padding: bleed ? EdgeInsets.only(top: padding.top, bottom: padding.bottom) : padding,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
        if (title != null) ...[
          Padding(padding: bleed ? hPad : EdgeInsets.zero, child: Row(children: [
            if (icon != null) ...[
              Container(
                width: 30,
                height: 30,
                decoration: BoxDecoration(
                  color: Color.lerp(NV.red, tone.dark ? const Color(0xFF000000) : const Color(0xFFFFFFFF), 0.15),
                  borderRadius: BorderRadius.circular(tileR),
                ),
                child: Icon(icon, size: 17, color: NV.onRed),
              ),
              const SizedBox(width: NvSpace.m),
            ],
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                Text(title!, maxLines: 1, overflow: TextOverflow.ellipsis,
                    style: TextStyle(fontFamily: NV.sans, fontSize: 16, fontWeight: FontWeight.w600, letterSpacing: -0.2, color: tone.text, height: 1.2)),
                if (caption != null) ...[
                  const SizedBox(height: 2),
                  Text(caption!, maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(fontFamily: NV.sans, fontSize: 12.5, color: tone.muted, height: 1.3)),
                ],
              ]),
            ),
            if (trailing != null) ...[const SizedBox(width: NvSpace.s), trailing!],
          ])),
          const SizedBox(height: NvSpace.l),
        ],
        child,
      ]),
    );
  }
}

/// Small glass capsule for a section header that floats over the wallpaper.
class NvGlassCapsule extends StatelessWidget {
  const NvGlassCapsule(this.label, {super.key, this.icon});
  final String label;
  final IconData? icon;
  @override
  Widget build(BuildContext context) {
    final tone = NvPanelToneScope.of(context);
    return Align(
      alignment: Alignment.centerLeft,
      child: NvGlassSurface(
        radius: 999,
        rimStrength: 0.8,
        padding: const EdgeInsets.symmetric(horizontal: NvSpace.m, vertical: 6),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          if (icon != null) ...[Icon(icon, size: 14, color: tone.text), const SizedBox(width: 6)],
          Text(label.toUpperCase(),
              style: TextStyle(fontFamily: NV.sans, fontSize: 12, fontWeight: FontWeight.w700, letterSpacing: 0.9, color: tone.text, height: 1.2)),
        ]),
      ),
    );
  }
}

/// Section header over the wallpaper (glass capsule), page-width padded.
class NvGlassSectionHeader extends StatelessWidget {
  const NvGlassSectionHeader(this.label, {super.key, this.icon, this.padding = const EdgeInsets.fromLTRB(NvSpace.xl, NvSpace.xxl, NvSpace.xl, NvSpace.m)});
  final String label;
  final IconData? icon;
  final EdgeInsets padding;
  @override
  Widget build(BuildContext context) => Padding(padding: padding, child: NvGlassCapsule(label, icon: icon));
}

/// Subtle glass chip (e.g. "Reset"): accent-washed glass, theme text.
class NvGlassChip extends StatelessWidget {
  const NvGlassChip({super.key, required this.label, this.icon, this.onPressed});
  final String label;
  final IconData? icon;
  final VoidCallback? onPressed;
  @override
  Widget build(BuildContext context) {
    final tone = NvPanelToneScope.of(context);
    final on = onPressed != null;
    final fg = on ? tone.text : tone.muted.withValues(alpha: 0.55);
    final fill = Color.alphaBlend(NV.red.withValues(alpha: on ? 0.16 : 0.06), tone.track);
    return Semantics(
      button: true,
      enabled: on,
      label: label,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: onPressed,
        child: AnimatedOpacity(
          duration: nvMotion(context, 180),
          opacity: on ? 1 : 0.7,
          child: Container(
            constraints: const BoxConstraints(minHeight: 32),
            padding: const EdgeInsets.symmetric(horizontal: NvSpace.m, vertical: 6),
            decoration: BoxDecoration(
              color: fill,
              borderRadius: BorderRadius.circular(999),
              border: Border.all(color: tone.hairline),
            ),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              if (icon != null) ...[Icon(icon, size: 14, color: fg), const SizedBox(width: 6)],
              Text(label, style: TextStyle(fontFamily: NV.sans, fontSize: 13, fontWeight: FontWeight.w600, color: fg)),
            ]),
          ),
        ),
      ),
    );
  }
}

/// iOS-26-style glass switch: accent track when on, a glass thumb that
/// stretches while it travels.
class NvGlassSwitch extends StatefulWidget {
  const NvGlassSwitch({super.key, required this.value, required this.onChanged});
  final bool value;
  final ValueChanged<bool>? onChanged;
  @override
  State<NvGlassSwitch> createState() => _NvGlassSwitchState();
}

class _NvGlassSwitchState extends State<NvGlassSwitch> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, value: widget.value ? 1 : 0, duration: const Duration(milliseconds: 320));
  bool _down = false;

  @override
  void didUpdateWidget(NvGlassSwitch old) {
    super.didUpdateWidget(old);
    if (old.value != widget.value) {
      if (NvGlassFx.reducedMotion(context)) {
        _c.value = widget.value ? 1 : 0;
      } else {
        _c.animateTo(widget.value ? 1 : 0, curve: Curves.easeOutBack);
      }
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final tone = NvPanelToneScope.of(context);
    const w = 52.0, h = 32.0, pad = 3.0;
    return Semantics(
      toggled: widget.value,
      enabled: widget.onChanged != null,
      child: GestureDetector(
        onTapDown: (_) => setState(() => _down = true),
        onTapCancel: () => setState(() => _down = false),
        onTapUp: (_) => setState(() => _down = false),
        onTap: widget.onChanged == null
            ? null
            : () {
                HapticFeedback.selectionClick();
                widget.onChanged!(!widget.value);
              },
        child: AnimatedBuilder(
          animation: _c,
          builder: (context, _) {
            final t = _c.value.clamp(0.0, 1.0);
            // stretch in the middle of the travel or while pressed
            final stretch = (1 - (2 * t - 1).abs()) * 8 + (_down ? 5 : 0);
            final tw = h - 2 * pad + stretch;
            final x = pad + (w - 2 * pad - tw) * t;
            final track = Color.lerp(tone.track, NV.red, t)!;
            return SizedBox(
              width: w,
              height: h,
              child: Stack(children: [
                Positioned.fill(
                  child: DecoratedBox(
                    decoration: BoxDecoration(color: track, borderRadius: BorderRadius.circular(h / 2), border: Border.all(color: tone.hairline)),
                  ),
                ),
                Positioned(
                  left: x,
                  top: pad,
                  width: tw,
                  height: h - 2 * pad,
                  child: CustomPaint(
                    foregroundPainter: tone.reduced
                        ? null
                        : NvGlassRimPainter(borderRadius: BorderRadius.circular(h), rim: const Color(0xFFFFFFFF).withValues(alpha: 0.9), strength: 1),
                    child: DecoratedBox(
                      decoration: BoxDecoration(
                        color: const Color(0xFFFFFFFF).withValues(alpha: _down ? 0.86 : 0.97),
                        borderRadius: BorderRadius.circular(h),
                        boxShadow: tone.reduced ? null : const [BoxShadow(color: Color(0x33000000), blurRadius: 6, offset: Offset(0, 2))],
                      ),
                    ),
                  ),
                ),
              ]),
            );
          },
        ),
      ),
    );
  }
}

/// Glass slider: thin capsule track (accent-filled up to the value, or a
/// custom [trackGradient]), a glass pill thumb that swells while dragged.
/// Tap anywhere on the track to jump.
class NvGlassSlider extends StatefulWidget {
  const NvGlassSlider({super.key, required this.value, required this.min, required this.max, required this.onChanged, this.onChangeEnd, this.trackGradient, this.thumbColor, this.divisions, this.semanticLabel, this.trackHeight = 6});
  final double value, min, max;
  final ValueChanged<double>? onChanged;
  final ValueChanged<double>? onChangeEnd;
  final Gradient? trackGradient;
  /// Fill shown inside the thumb (e.g. the picked colour).
  final Color? thumbColor;
  final int? divisions;
  final String? semanticLabel;
  final double trackHeight;
  @override
  State<NvGlassSlider> createState() => _NvGlassSliderState();
}

class _NvGlassSliderState extends State<NvGlassSlider> {
  bool _drag = false;
  int? _lastTick;

  double _norm(double v) => widget.max == widget.min ? 0 : ((v - widget.min) / (widget.max - widget.min)).clamp(0.0, 1.0);

  void _at(double dx, double width) {
    final cb = widget.onChanged;
    if (cb == null) return;
    const inset = 14.0;
    final t = ((dx - inset) / (width - 2 * inset)).clamp(0.0, 1.0);
    var v = widget.min + t * (widget.max - widget.min);
    if (widget.divisions != null && widget.divisions! > 0) {
      final step = (widget.max - widget.min) / widget.divisions!;
      v = widget.min + (((v - widget.min) / step).round() * step);
      final tick = ((v - widget.min) / step).round();
      if (tick != _lastTick) {
        _lastTick = tick;
        HapticFeedback.selectionClick();
      }
    }
    cb(v.clamp(widget.min, widget.max));
  }

  @override
  Widget build(BuildContext context) {
    final tone = NvPanelToneScope.of(context);
    final enabled = widget.onChanged != null;
    final t = _norm(widget.value);
    final dur = nvMotion(context, 160);
    return Semantics(
      slider: true,
      label: widget.semanticLabel,
      value: widget.value.toStringAsFixed(widget.max - widget.min > 4 ? 0 : 2),
      enabled: enabled,
      child: LayoutBuilder(builder: (context, c) {
        final w = c.maxWidth;
        const inset = 14.0;
        final tw = _drag ? 36.0 : 28.0, th = _drag ? 26.0 : 20.0;
        final cx = inset + (w - 2 * inset) * t;
        return GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTapDown: enabled ? (d) => _at(d.localPosition.dx, w) : null,
          onTapUp: enabled ? (_) => widget.onChangeEnd?.call(widget.value) : null,
          onHorizontalDragStart: enabled
              ? (d) {
                  setState(() => _drag = true);
                  _at(d.localPosition.dx, w);
                }
              : null,
          onHorizontalDragUpdate: enabled ? (d) => _at(d.localPosition.dx, w) : null,
          onHorizontalDragEnd: enabled
              ? (_) {
                  setState(() => _drag = false);
                  widget.onChangeEnd?.call(widget.value);
                }
              : null,
          child: SizedBox(
            height: 40,
            child: Stack(clipBehavior: Clip.none, alignment: Alignment.centerLeft, children: [
              Positioned(
                left: inset - widget.trackHeight / 2,
                right: inset - widget.trackHeight / 2,
                top: (40 - widget.trackHeight) / 2,
                height: widget.trackHeight,
                child: widget.trackGradient != null
                    ? DecoratedBox(
                        decoration: BoxDecoration(
                          gradient: widget.trackGradient,
                          borderRadius: BorderRadius.circular(widget.trackHeight),
                          border: Border.all(color: tone.hairline, width: 0.6),
                        ),
                      )
                    : DecoratedBox(
                        decoration: BoxDecoration(
                          borderRadius: BorderRadius.circular(widget.trackHeight),
                          gradient: LinearGradient(
                            colors: [enabled ? NV.red : tone.muted.withValues(alpha: 0.5), enabled ? NV.red : tone.muted.withValues(alpha: 0.5), tone.track, tone.track],
                            stops: [0, t, t, 1],
                          ),
                        ),
                      ),
              ),
              AnimatedPositioned(
                duration: dur,
                curve: Curves.easeOutCubic,
                left: cx - tw / 2,
                top: (40 - th) / 2,
                width: tw,
                height: th,
                child: _GlassThumb(fill: widget.thumbColor, reduced: tone.reduced, active: _drag, enabled: enabled),
              ),
            ]),
          ),
        );
      }),
    );
  }
}

class _GlassThumb extends StatelessWidget {
  const _GlassThumb({this.fill, required this.reduced, required this.active, required this.enabled});
  final Color? fill;
  final bool reduced, active, enabled;
  @override
  Widget build(BuildContext context) {
    final br = BorderRadius.circular(999);
    final white = const Color(0xFFFFFFFF).withValues(alpha: enabled ? (active ? 0.72 : 0.96) : 0.55);
    return CustomPaint(
      foregroundPainter: reduced ? null : NvGlassRimPainter(borderRadius: br, rim: const Color(0xFFFFFFFF), chroma: active, strength: active ? 1.2 : 0.9),
      child: DecoratedBox(
        decoration: BoxDecoration(
          color: white,
          borderRadius: br,
          boxShadow: reduced ? null : const [BoxShadow(color: Color(0x40000000), blurRadius: 8, offset: Offset(0, 2))],
        ),
        child: fill == null
            ? null
            : Padding(
                padding: const EdgeInsets.all(3.5),
                child: DecoratedBox(decoration: BoxDecoration(color: fill, borderRadius: br)),
              ),
      ),
    );
  }
}
