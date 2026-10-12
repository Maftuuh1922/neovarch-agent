// Building blocks of the Neovarch Remote look (see neovarch_mobile_theme):
// header with a mono kicker over a serif title, "// LABEL" sections,
// rounded 16px panels with 1px borders, 14px chat blocks, a floating nav bar
// with a red top indicator. Flat colours only.
import 'dart:math' as math;

import 'dart:ui' show ImageFilter;

import 'package:flutter/cupertino.dart' show CupertinoIcons;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart' show RenderProxyBox;
import 'package:flutter/physics.dart' show SpringDescription, SpringSimulation;
import 'package:flutter/services.dart' show HapticFeedback;

import '../../models/models.dart';
import '../../theme/neovarch_mobile_theme.dart';
import '../../ui/widgets/common.dart' show clockOf, LogView, reduceMotion;
import '../l10n/strings.dart';
import 'nv_mascot_avatar.dart';

/// Screen header: `// KICKER` in mono, a serif title, optional status line and
/// actions on the right. Replaces the stock AppBar on every remote tab.
class NvHeader extends StatelessWidget {
  const NvHeader({super.key, required this.kicker, required this.title, this.status, this.actions = const [], this.onBack, this.inset});
  final String kicker;
  final String title;
  final Widget? status;
  final List<Widget> actions;
  final VoidCallback? onBack;
  /// Horizontal inset; defaults to the screen-edge gutter. Pass 0 when the
  /// header already sits inside padded content.
  final double? inset;

  @override
  Widget build(BuildContext context) {
    final top = MediaQuery.paddingOf(context).top;
    final kick = Text(tr(kicker).toUpperCase(), style: NV.monoLabel(color: NV.redInk));
    final head = Text(tr(title), maxLines: 1, overflow: TextOverflow.ellipsis, style: NV.display(size: 34));
    final Widget body;
    if (onBack != null) {
      // Kicker on its own line, then the back button and the title on one
      // row, centred on each other; the kicker starts where the title does.
      body = Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
        Padding(padding: const EdgeInsets.only(left: 52), child: kick),
        const SizedBox(height: 6),
        Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
          NvIconButton(icon: CupertinoIcons.chevron_back, tooltip: tr('Kembali'), onPressed: onBack),
          const SizedBox(width: 12),
          Expanded(child: head),
          for (final a in actions) Padding(padding: const EdgeInsets.only(left: 6), child: a),
        ]),
        if (status != null) ...[const SizedBox(height: 6), Padding(padding: const EdgeInsets.only(left: 52), child: status!)],
      ]);
    } else {
      body = Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
            kick,
            const SizedBox(height: 6),
            head,
            if (status != null) ...[const SizedBox(height: 6), status!],
          ]),
        ),
        for (final a in actions) Padding(padding: const EdgeInsets.only(left: 6, bottom: 2), child: a),
      ]);
    }
    return Padding(
      padding: EdgeInsets.fromLTRB(inset ?? (onBack != null ? 16 : 20), top + 14, inset ?? 12, 12),
      child: body,
    );
  }
}

/// Square-ish 40px icon button on a bordered rounded tile.
class NvIconButton extends StatelessWidget {
  const NvIconButton({super.key, required this.icon, required this.onPressed, this.tooltip, this.accent = false, this.size = 40, this.onLongPress});
  final IconData icon;
  final VoidCallback? onPressed;
  final VoidCallback? onLongPress;
  final String? tooltip;
  final bool accent;
  final double size;
  @override
  Widget build(BuildContext context) {
    final enabled = onPressed != null;
    final btn = Material(
      color: accent && enabled ? NV.red : NV.glass,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(NV.rCtl),
        side: BorderSide(color: accent && enabled ? NV.red : NV.glassBorder),
      ),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onPressed,
        onLongPress: onLongPress,
        child: SizedBox(
          width: size,
          height: size,
          child: Icon(icon, size: size * 0.48, color: !enabled ? NV.faint : (accent ? NV.onRed : NV.text)),
        ),
      ),
    );
    return tooltip == null ? btn : Tooltip(message: tooltip!, child: btn);
  }
}

/// `// LABEL` section header in mono with an optional trailing widget.
class NvSection extends StatelessWidget {
  const NvSection(this.label, {super.key, this.trailing, this.padding = const EdgeInsets.fromLTRB(20, 22, 20, 10), this.count});
  final String label;
  final Widget? trailing;
  final EdgeInsets padding;
  final int? count;
  @override
  Widget build(BuildContext context) => Padding(
        padding: padding,
        child: Row(children: [
          Text(tr(label).toUpperCase(), style: NV.monoLabel()),
          if (count != null) ...[const SizedBox(width: 8), NvPill('$count')],
          const SizedBox(width: 10),
          Expanded(child: Divider(color: NV.border, height: 1)),
          if (trailing != null) ...[const SizedBox(width: 8), trailing!],
        ]),
      );
}

/// Rounded 16px surface with a 1px border.
class NvPanel extends StatelessWidget {
  const NvPanel({super.key, required this.child, this.padding = const EdgeInsets.all(16), this.margin = EdgeInsets.zero, this.color, this.borderColor, this.onTap});
  final Widget child;
  final EdgeInsets padding;
  final EdgeInsets margin;
  final Color? color;
  final Color? borderColor;
  final VoidCallback? onTap;
  @override
  Widget build(BuildContext context) => Padding(
        padding: margin,
        child: Material(
          color: color ?? NV.glass,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(NV.rCard), side: BorderSide(color: borderColor ?? NV.glassBorder)),
          clipBehavior: Clip.antiAlias,
          child: onTap == null ? Padding(padding: padding, child: child) : InkWell(onTap: onTap, child: Padding(padding: padding, child: child)),
        ),
      );
}

/// Full-radius small badge (counts, priorities, states).
class NvPill extends StatelessWidget {
  const NvPill(this.label, {super.key, Color? color, this.filled = false}) : _color = color; // ignore: prefer_initializing_formals
  final String label;
  final Color? _color;
  Color get color => _color ?? NV.muted;
  final bool filled;
  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2.5),
        decoration: BoxDecoration(
          color: filled ? color : color.withValues(alpha: 0.12),
          borderRadius: BorderRadius.circular(999),
          border: Border.all(color: filled ? color : color.withValues(alpha: 0.35)),
        ),
        child: Text(label, maxLines: 1, softWrap: false, overflow: TextOverflow.ellipsis, style: NV.monoLabel(size: 10, color: filled ? NV.onRed : color)),
      );
}

class NvDot extends StatelessWidget {
  const NvDot(this.color, {super.key, this.size = 8});
  final Color color;
  final double size;
  @override
  Widget build(BuildContext context) =>
      Container(width: size, height: size, decoration: BoxDecoration(color: color, shape: BoxShape.circle));
}

/// Row inside a panel list: rounded icon tile, title, subtitle, trailing.
class NvRow extends StatelessWidget {
  const NvRow({super.key, required this.icon, required this.title, this.subtitle, this.trailing, this.onTap, this.accent = false, this.mono = false});
  final IconData icon;
  final String title;
  final String? subtitle;
  final Widget? trailing;
  final VoidCallback? onTap;
  final bool accent;
  final bool mono;
  @override
  Widget build(BuildContext context) => InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          child: Row(children: [
            Container(
              width: 38,
              height: 38,
              decoration: BoxDecoration(
                color: accent ? NV.redWash : NV.raised,
                borderRadius: BorderRadius.circular(NV.rCtl),
                border: Border.all(color: accent ? NV.darkRed : NV.border),
              ),
              child: Icon(icon, size: 19, color: accent ? NV.red : NV.muted),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(title, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w500, color: NV.text)),
                if (subtitle != null && subtitle!.isNotEmpty) ...[
                  const SizedBox(height: 2),
                  Text(subtitle!,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: mono ? NV.monoLabel(size: 11, color: NV.muted).copyWith(letterSpacing: 0.2) : TextStyle(fontSize: 12.5, color: NV.muted)),
                ],
              ]),
            ),
            if (trailing != null) ...[const SizedBox(width: 8), trailing!],
          ]),
        ),
      );
}

/// Several [NvRow]s in one bordered panel with hairline separators.
class NvList extends StatelessWidget {
  const NvList({super.key, required this.children, this.margin = const EdgeInsets.symmetric(horizontal: 16)});
  final List<Widget> children;
  final EdgeInsets margin;
  @override
  Widget build(BuildContext context) => NvPanel(
        margin: margin,
        padding: EdgeInsets.zero,
        child: Column(children: [
          for (var i = 0; i < children.length; i++) ...[
            if (i > 0) Divider(indent: 64, height: 1, color: NV.border),
            children[i],
          ],
        ]),
      );
}

/// Key/value line in mono label + body text.
class NvKv extends StatelessWidget {
  const NvKv(this.k, this.v, {super.key, this.mono = false, this.valueColor});
  final String k;
  final String v;
  final bool mono;
  final Color? valueColor;
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 5),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(width: 112, child: Text(k.toUpperCase(), style: NV.monoLabel(size: 10))),
          Expanded(
            child: Text(v,
                style: mono
                    ? TextStyle(fontFamily: NV.mono, fontSize: 12.5, color: valueColor ?? NV.text)
                    : TextStyle(fontSize: 14, color: valueColor ?? NV.text, fontWeight: FontWeight.w500)),
          ),
        ]),
      );
}

/// Empty / idle state with a piece of the dithered red art.
class NvEmpty extends StatelessWidget {
  const NvEmpty({super.key, required this.title, this.body, this.art, this.action, this.kicker});
  final String title;
  final String? body;
  final String? art;
  final String? kicker;
  final Widget? action;
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
          if (art != null)
            ClipRRect(
              borderRadius: BorderRadius.circular(NV.rCard),
              child: Container(
                foregroundDecoration: BoxDecoration(borderRadius: BorderRadius.circular(NV.rCard), border: Border.all(color: NV.border)),
                child: AspectRatio(aspectRatio: 16 / 9, child: Image.asset(art!, fit: BoxFit.cover, filterQuality: FilterQuality.medium)),
              ),
            ),
          const SizedBox(height: 18),
          if (kicker != null) ...[Text(kicker!.toUpperCase(), style: NV.monoLabel(color: NV.redInk)), const SizedBox(height: 8)],
          Text(title, style: NV.display(size: 28)),
          if (body != null) ...[
            const SizedBox(height: 8),
            Text(body!, style: TextStyle(fontSize: 14, height: 1.5, color: NV.muted)),
          ],
          if (action != null) ...[const SizedBox(height: 16), action!],
        ]),
      );
}

/// Error / warning strip: rounded 12px, tinted, left rule kept inside.
class NvNotice extends StatelessWidget {
  const NvNotice(this.message, {super.key, Color? color, this.icon = CupertinoIcons.exclamationmark_circle, this.action}) : _color = color; // ignore: prefer_initializing_formals
  final String message;
  final Color? _color;
  Color get color => _color ?? NV.red;
  final IconData icon;
  final Widget? action;
  @override
  Widget build(BuildContext context) => Container(
        width: double.infinity,
        padding: const EdgeInsets.fromLTRB(14, 12, 10, 12),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.08),
          borderRadius: BorderRadius.circular(NV.rCtl),
          border: Border.all(color: color.withValues(alpha: 0.4)),
        ),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Padding(padding: const EdgeInsets.only(top: 1), child: Icon(icon, size: 18, color: color)),
          const SizedBox(width: 10),
          Expanded(child: Text(message, style: TextStyle(fontSize: 13.5, height: 1.45, color: NV.text))),
          ?action,
        ]),
      );
}

/// The user's turn: a rounded 14px block on a red-tinted surface with a red
/// left rule and a mono "// KAMU" label. Not a Material bubble.
class NvUserMessage extends StatelessWidget {
  const NvUserMessage({super.key, required this.msg, this.scale = 1});
  final ChatMsg msg;
  final double scale;
  @override
  Widget build(BuildContext context) {
    final w = MediaQuery.sizeOf(context).width;
    return Align(
      alignment: Alignment.centerRight,
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: math.min(560, w * 0.86)),
        child: ClipRRect(
          borderRadius: BorderRadius.circular(NV.rMsg),
          child: Container(
            decoration: BoxDecoration(
              color: NV.redWash,
              borderRadius: BorderRadius.circular(NV.rMsg),
              border: Border.all(color: NV.darkRed.withValues(alpha: 0.7)),
            ),
            child: IntrinsicHeight(
              child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                Container(width: 3, color: NV.red),
                Flexible(
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(13, 10, 14, 12),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                      Text('KAMU${msg.ts > 0 ? '  ·  ${clockOf(msg.ts)}' : ''}', style: NV.monoLabel(size: 9.5, color: NV.redInk)),
                      const SizedBox(height: 5),
                      SelectableText(msg.content, style: TextStyle(fontSize: 14.5 * scale, height: 1.5, color: NV.text)),
                    ]),
                  ),
                ),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}

/// Mono label above an assistant turn ("// NEOVARCH · PC KANTOR").
class NvAgentLabel extends StatelessWidget {
  const NvAgentLabel(this.label, {super.key, this.live = false});
  final String label;
  final bool live;
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Row(children: [
          NvMascotAvatar(size: 18, animated: live),
          const SizedBox(width: 8),
          Flexible(child: Text(label.toUpperCase(), maxLines: 1, overflow: TextOverflow.ellipsis, style: NV.monoLabel(size: 9.5))),
          if (live) ...[const SizedBox(width: 8), const _LiveDot()],
        ]),
      );
}

class _LiveDot extends StatefulWidget {
  const _LiveDot();
  @override
  State<_LiveDot> createState() => _LiveDotState();
}

class _LiveDotState extends State<_LiveDot> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 900));
  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!reduceMotion(context) && !_c.isAnimating) _c.repeat(reverse: true);
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => FadeTransition(opacity: Tween(begin: 0.3, end: 1.0).animate(_c), child: NvDot(NV.red, size: 6));
}

/// A tool call the agent wants to run: rounded panel, red rule, command in
/// mono, choices as rounded buttons.
class NvApprovalCard extends StatelessWidget {
  const NvApprovalCard({super.key, required this.command, required this.description, required this.choices, required this.onChoice, this.origin, this.margin = const EdgeInsets.fromLTRB(16, 0, 16, 10), this.color});
  /// Panel fill; pass a solid colour when the card floats over content.
  final Color? color;
  final String command;
  final String description;
  final List<String> choices;
  final void Function(String) onChoice;
  final String? origin;
  final EdgeInsets margin;

  static String label(String c) => switch (c) {
        'once' => 'Izinkan sekali',
        'session' => 'Izinkan sesi ini',
        'always' => 'Selalu izinkan',
        'deny' => 'Tolak',
        _ => c,
      };

  @override
  Widget build(BuildContext context) {
    final allow = choices.where((c) => c != 'deny').toList();
    final deny = choices.contains('deny');
    return NvPanel(
      margin: margin,
      color: color,
      borderColor: NV.darkRed,
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Icon(CupertinoIcons.checkmark_shield, size: 16, color: NV.red),
          const SizedBox(width: 8),
          Text('PERLU PERSETUJUAN', style: NV.monoLabel(color: NV.redInk)),
          const SizedBox(width: 10),
          Expanded(
            child: origin != null && origin!.isNotEmpty
                ? Align(alignment: Alignment.centerRight, child: NvPill(origin!, color: NV.muted))
                : const SizedBox.shrink(),
          ),
        ]),
        if (description.isNotEmpty) ...[
          const SizedBox(height: 10),
          Text(description, style: TextStyle(fontSize: 14, height: 1.45, color: NV.text)),
        ],
        const SizedBox(height: 10),
        ClipRRect(borderRadius: BorderRadius.circular(NV.rCtl), child: LogView(command, maxHeight: 120)),
        const SizedBox(height: 12),
        Row(children: [
          if (allow.isNotEmpty)
            Expanded(child: FilledButton(onPressed: () => onChoice(allow.first), child: Text(label(allow.first), maxLines: 1, overflow: TextOverflow.ellipsis))),
          if (deny) ...[
            const SizedBox(width: 8),
            Expanded(child: OutlinedButton(onPressed: () => onChoice('deny'), child: const Text('Tolak'))),
          ],
        ]),
        if (allow.length > 1) ...[
          const SizedBox(height: 8),
          Wrap(spacing: 8, runSpacing: 8, children: [
            for (final c in allow.skip(1))
              OutlinedButton(
                style: OutlinedButton.styleFrom(minimumSize: const Size(0, 40), padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8)),
                onPressed: () => onChoice(c),
                child: Text(label(c), style: const TextStyle(fontSize: 13)),
              ),
          ]),
        ],
      ]),
    );
  }
}

/// iOS-style liquid glass tab bar: a floating translucent pill (strong
/// backdrop blur + saturation, accent-tinted fill, bright specular rim) with
/// a clear glass lens on the active tab that magnifies what is under it and
/// springs between tabs, stretching a little while it moves.
class NvNavBar extends StatefulWidget {
  const NvNavBar({super.key, required this.index, required this.onTap, required this.items, this.badges = const {}, this.dots = const {}, this.avatars = const {}});
  final int index;
  final ValueChanged<int> onTap;
  final List<(IconData, IconData, String)> items;
  final Map<int, int> badges;
  final Map<int, Color> dots;
  /// Optional photo per tab (e.g. Profil): drawn as a circular avatar in
  /// place of the icon, accent ring when active, dimmed when not. A null
  /// value falls back to the item's icons.
  final Map<int, ImageProvider?> avatars;

  /// Avatar diameter in the bar.
  static const avatarSize = 26.0;

  /// Label magnification of the lens at rest (it zooms more while held).
  static const restMagnification = 1.08;

  /// Horizontal room kept between the magnified label and the lens rim.
  static const lensPadding = 11.0;

  static TextStyle labelStyle([Color? color]) => NV.monoLabel(size: 9.5, color: color).copyWith(shadows: NV.glassTextShadows);

  @override
  State<NvNavBar> createState() => _NvNavBarState();
}

/// Sizes the nav lens so the widest (magnified) tab label always sits inside
/// it with [NvNavBar.lensPadding] on each side: the lens grows past its tab
/// slot when needed (centred, so it reaches a little into the neighbours,
/// at most [maxOverreach] of a slot), and if even that is not enough on a
/// narrow screen the magnification is lowered instead.
class NvLensFit {
  NvLensFit._(this.width, this.labelWidth);
  /// Resting lens width (before the liquid stretch).
  final double width;
  /// Widest unmagnified label, in logical px.
  final double labelWidth;

  static const maxOverreach = 0.24;

  factory NvLensFit.of(BuildContext context, double tabW, List<String> labels) {
    final scaler = MediaQuery.maybeTextScalerOf(context) ?? TextScaler.noScaling;
    var widest = 0.0;
    for (final l in labels) {
      final tp = TextPainter(text: TextSpan(text: l, style: NvNavBar.labelStyle()), textDirection: TextDirection.ltr, textScaler: scaler, maxLines: 1)..layout();
      widest = math.max(widest, tp.width);
      tp.dispose();
    }
    final need = widest * NvNavBar.restMagnification + 2 * NvNavBar.lensPadding;
    final width = need.clamp(tabW, tabW * (1 + maxOverreach)).toDouble();
    return NvLensFit._(width, widest);
  }

  /// The magnification to use for a lens [lensW] wide: [wanted], lowered
  /// (never below 1) so the widest label keeps its padding.
  double magFor(double lensW, double wanted) {
    if (labelWidth <= 0) return wanted;
    final fits = (lensW - 2 * NvNavBar.lensPadding) / labelWidth;
    return math.max(1.0, math.min(wanted, fits));
  }
}

class _NvNavBarState extends State<NvNavBar> with SingleTickerProviderStateMixin {
  late final AnimationController _pos = AnimationController.unbounded(vsync: this, value: widget.index.toDouble());
  static const _spring = SpringDescription(mass: 1, stiffness: 420, damping: 29);

  /// Finger is on the pill (horizontal drag): the lens follows it 1:1.
  bool _dragging = false;
  /// Tab currently under the lens while dragging (haptic tick on change).
  int _hover = 0;
  double _tabW = 1;

  @override
  void didUpdateWidget(NvNavBar old) {
    super.didUpdateWidget(old);
    if (old.index == widget.index || _dragging) return;
    _springTo(widget.index, _pos.velocity);
  }

  void _springTo(int target, double velocity) {
    if (reduceMotion(context)) {
      _pos.value = target.toDouble();
    } else {
      _pos.animateWith(SpringSimulation(_spring, _pos.value, target.toDouble(), velocity));
    }
  }

  double _posAt(double dx) {
    final n = widget.items.length;
    final raw = dx / _tabW - 0.5;
    // Rubber band a little past the ends, like iOS.
    if (raw < 0) return raw * 0.25;
    if (raw > n - 1) return (n - 1) + (raw - (n - 1)) * 0.25;
    return raw;
  }

  void _dragStart(DragStartDetails d) {
    _pos.stop();
    setState(() => _dragging = true);
    _hover = widget.index;
    _dragUpdate(DragUpdateDetails(globalPosition: d.globalPosition, localPosition: d.localPosition));
  }

  void _dragUpdate(DragUpdateDetails d) {
    _pos.value = _posAt(d.localPosition.dx);
    final h = _pos.value.round().clamp(0, widget.items.length - 1);
    if (h != _hover) {
      _hover = h;
      HapticFeedback.selectionClick();
    }
  }

  void _dragEnd(DragEndDetails d) {
    final v = (d.primaryVelocity ?? 0) / _tabW; // tabs per second
    // A quick flick goes to the next tab in its direction; a slow release
    // snaps to the nearest one.
    final p = _pos.value;
    final target = (v.abs() > 2.5 ? (v > 0 ? p.floor() + 1 : p.ceil() - 1) : p.round()).clamp(0, widget.items.length - 1);
    setState(() => _dragging = false);
    _springTo(target, v);
    if (target != _hover) HapticFeedback.selectionClick();
    if (target != widget.index) widget.onTap(target);
  }

  void _dragCancel() {
    if (!_dragging) return;
    setState(() => _dragging = false);
    _springTo(widget.index, 0);
  }

  @override
  void dispose() {
    _pos.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final items = widget.items;
    return LayoutBuilder(builder: (context, outer) {
      final h = outer.maxHeight.isFinite ? outer.maxHeight : 64.0;
      return NvGlass(
        key: const ValueKey('nv-nav-bar'),
        radius: NV.navFor(h),
        tint: NV.navGlass,
        padding: const EdgeInsets.all(4),
        child: LayoutBuilder(builder: (context, c) {
          final w = c.maxWidth / items.length;
          _tabW = w;
          final fit = NvLensFit.of(context, w, [for (final it in items) it.$3.toUpperCase()]);
          return GestureDetector(
            key: const ValueKey('nv-nav-drag'),
            behavior: HitTestBehavior.translucent,
            onHorizontalDragStart: _dragStart,
            onHorizontalDragUpdate: _dragUpdate,
            onHorizontalDragEnd: _dragEnd,
            onHorizontalDragCancel: _dragCancel,
            child: AnimatedBuilder(
              animation: _pos,
              builder: (context, _) {
                final p = _pos.value.clamp(-0.3, items.length - 0.7);
                // liquid stretch while moving, back to a round capsule at rest;
                // while held the lens lifts (a little bigger, stronger zoom).
                final stretch = _dragging ? 0.12 : (_pos.velocity.abs() * 0.045).clamp(0.0, 0.32);
                final lensW = fit.width * (1 + stretch);
                final lift = _dragging ? 4.0 : 0.0;
                final lensH = c.maxHeight + lift;
                final mag = fit.magFor(lensW, _dragging ? 1.24 : NvNavBar.restMagnification);
                return Stack(clipBehavior: Clip.none, children: [
                  Row(children: [
                    for (var i = 0; i < items.length; i++)
                      Expanded(child: _tab(context, i, (1 - (p - i).abs()).clamp(0.0, 1.0))),
                  ]),
                  Positioned(
                    left: w * p + (w - lensW) / 2,
                    top: -lift / 2,
                    width: lensW,
                    height: lensH,
                    child: IgnorePointer(
                      child: NvLens(key: const ValueKey('nv-nav-lens'), size: Size(lensW, lensH), magnification: mag, radius: NV.inner(NV.navFor(h), 4)),
                    ),
                  ),
                ]);
              },
            ),
          );
        }),
      );
    });
  }

  Widget _tab(BuildContext context, int i, double on) {
    final it = widget.items[i];
    final sel = i == widget.index;
    final iconColor = Color.lerp(NV.muted, NV.red, on)!;
    final labelColor = Color.lerp(NV.muted, NV.text, on)!;
    return Semantics(
      button: true,
      selected: sel,
      label: it.$3,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: () {
          HapticFeedback.selectionClick();
          widget.onTap(i);
        },
        child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
          Stack(clipBehavior: Clip.none, children: [
            if (widget.avatars[i] != null)
              _NavAvatar(key: ValueKey('nv-nav-avatar-$i'), image: widget.avatars[i]!, on: on)
            else
              Icon(on > 0.5 ? it.$2 : it.$1, size: 21, color: iconColor),
            if ((widget.badges[i] ?? 0) > 0)
              Positioned(
                right: -10,
                top: -6,
                child: Container(
                  constraints: const BoxConstraints(minWidth: 16),
                  height: 16,
                  padding: const EdgeInsets.symmetric(horizontal: 4),
                  alignment: Alignment.center,
                  decoration: BoxDecoration(color: NV.red, borderRadius: BorderRadius.circular(999), border: Border.all(color: NV.surface, width: 1.5)),
                  child: Text('${widget.badges[i]}', style: TextStyle(fontFamily: NV.sans, fontWeight: FontWeight.w600, fontSize: 10, color: NV.onRed, height: 1.1)),
                ),
              )
            else if (widget.dots[i] != null)
              Positioned(right: -3, top: -2, child: NvDot(widget.dots[i]!, size: 8)),
          ]),
          const SizedBox(height: 4),
          Text(it.$3.toUpperCase(), style: NvNavBar.labelStyle(labelColor)),
        ]),
      ),
    );
  }
}

class _NavAvatar extends StatelessWidget {
  const _NavAvatar({super.key, required this.image, required this.on});
  final ImageProvider image;
  final double on; // 0 inactive … 1 active
  @override
  Widget build(BuildContext context) {
    const d = NvNavBar.avatarSize;
    return Opacity(
      opacity: 0.55 + 0.45 * on,
      child: Container(
        width: d,
        height: d,
        padding: const EdgeInsets.all(1.5),
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          border: Border.all(color: Color.lerp(NV.border, NV.red, on)!, width: 1.5),
        ),
        child: ClipOval(
          child: Image(
            image: image,
            width: d,
            height: d,
            fit: BoxFit.cover,
            gaplessPlayback: true,
            errorBuilder: (context, e, s) => Icon(CupertinoIcons.person_crop_circle_fill, size: 21, color: NV.muted),
          ),
        ),
      ),
    );
  }
}

/// The clear glass capsule of the active tab: magnifies (refracts) what is
/// under it, with a light accent tint, a bright rim and a faint chromatic
/// edge. Used by [NvNavBar]; also usable for round glass buttons.
class NvLens extends StatelessWidget {
  const NvLens({super.key, required this.size, this.magnification = 1.14, this.radius});
  final Size size;
  final double magnification;
  /// Corner radius; null = capsule.
  final double? radius;
  @override
  Widget build(BuildContext context) {
    final r = math.min(radius ?? size.shortestSide / 2, size.shortestSide / 2);
    final paint = CustomPaint(
      size: size,
      painter: _LensFillPainter(radius: r, fill: NV.lensFill),
      foregroundPainter: NvGlassRimPainter(borderRadius: BorderRadius.circular(r), rim: NV.glassRim, chroma: true, strength: 1.25),
    );
    return RawMagnifier(
      size: size,
      magnificationScale: magnification,
      decoration: MagnifierDecoration(shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(r)), shadows: const []),
      child: paint,
    );
  }
}

class _LensFillPainter extends CustomPainter {
  _LensFillPainter({required this.radius, required this.fill});
  final double radius;
  final Color fill;
  @override
  void paint(Canvas canvas, Size size) {
    final rr = RRect.fromRectAndRadius(Offset.zero & size, Radius.circular(radius));
    canvas.drawRRect(rr, Paint()..color = fill);
  }

  @override
  bool shouldRepaint(_LensFillPainter old) => old.radius != radius || old.fill != fill;
}

/// Rounded top sheet title: `// KICKER` + serif title.
class NvSheetTitle extends StatelessWidget {
  const NvSheetTitle({super.key, required this.kicker, required this.title, this.trailing});
  final String kicker;
  final String title;
  final Widget? trailing;
  @override
  Widget build(BuildContext context) => Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(kicker.toUpperCase(), style: NV.monoLabel(color: NV.redInk)),
            const SizedBox(height: 6),
            Text(title, style: NV.display(size: 28)),
          ]),
        ),
        ?trailing,
      ]);
}


/// The specular edge of liquid glass: a 1px rim that is bright where light
/// hits (top-left), fades along the sides and picks up again bottom-right,
/// plus a soft inner top sheen. [chroma] adds a faint red/cyan split at the
/// edge like a real lens. Glass only; the rest of the app stays flat.
class NvGlassRimPainter extends CustomPainter {
  NvGlassRimPainter({required this.borderRadius, required this.rim, this.chroma = false, this.strength = 1.0});
  final BorderRadius borderRadius;
  final Color rim;
  final bool chroma;
  final double strength;

  @override
  void paint(Canvas canvas, Size size) {
    if (size.isEmpty) return;
    final rect = Offset.zero & size;
    final a = (rim.a * strength).clamp(0.0, 1.0);
    Color al(double f) => rim.withValues(alpha: (a * f).clamp(0.0, 1.0));
    final outer = borderRadius.toRRect(rect.deflate(0.5));
    if (chroma) {
      final w = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.2;
      canvas.drawRRect(outer.shift(const Offset(-0.7, 0)), w..color = const Color(0xFF3FD0FF).withValues(alpha: 0.18 * strength));
      canvas.drawRRect(outer.shift(const Offset(0.7, 0)), w..color = const Color(0xFFFF4F7A).withValues(alpha: 0.16 * strength));
    }
    canvas.drawRRect(
      outer,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.0
        ..shader = LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [al(1), al(0.28), al(0.08), al(0.55)],
          stops: const [0, 0.32, 0.68, 1],
        ).createShader(rect),
    );
    // inner sheen along the top edge
    final inner = borderRadius.toRRect(rect.deflate(1.6));
    canvas.drawRRect(
      inner,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.0
        ..shader = LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [al(0.45), al(0.0)],
          stops: const [0, 0.45],
        ).createShader(rect),
    );
  }

  @override
  bool shouldRepaint(NvGlassRimPainter old) =>
      old.borderRadius != borderRadius || old.rim != rim || old.chroma != chroma || old.strength != strength;
}

/// Backdrop for liquid glass: strong blur plus a saturation lift so the
/// colours behind the glass glow through (iOS 26 "Liquid Glass").
ImageFilter nvGlassFilter(double sigma) => ImageFilter.compose(
      outer: const ColorFilter.matrix(<double>[
        // saturation 1.4 (Rec. 709 luma weights)
        1.3150, -0.2861, -0.0289, 0, 0, //
        -0.0850, 1.1139, -0.0289, 0, 0, //
        -0.0850, -0.2861, 1.3711, 0, 0, //
        0, 0, 0, 1, 0,
      ]),
      inner: ImageFilter.blur(sigmaX: sigma, sigmaY: sigma, tileMode: TileMode.mirror),
    );

/// Liquid glass surface: backdrop blur + saturation, a translucent
/// accent-tinted fill, a hairline and a specular rim. No drop shadow.
class NvGlass extends StatelessWidget {
  const NvGlass({super.key, required this.child, this.radius, this.padding = EdgeInsets.zero, this.blur, this.tint, this.border = true, this.borderRadius, this.rim = true, this.backdrop = true, this.style});
  final Widget child;
  /// Null: the card radius ([NV.rCard], follows "Kelengkungan sudut").
  final double? radius;
  final BorderRadius? borderRadius;
  final EdgeInsetsGeometry padding;
  /// Fixed blur sigma; null follows the user's "Kekuatan kaca" ([NV.glassSigma]).
  final double? blur;
  final Color? tint;
  final bool border;
  final bool rim;
  /// False: no BackdropFilter (tint + rim only) — for small glass over an
  /// already-blurred, soft backdrop, so a screen doesn't stack many blurs.
  final bool backdrop;
  /// Glass style override (previews); null = the app-wide [NV.glassStyle].
  final NvGlassStyle? style;
  @override
  Widget build(BuildContext context) {
    final br = borderRadius ?? BorderRadius.circular(radius ?? NV.rCard);
    // "Mode ringan": the app-wide look becomes the solid "tanpa" surface; an
    // explicit preview style keeps its colours but loses the blur.
    final st = style ?? (NV.liteMode ? NvGlassStyle.tanpa : NV.glassStyle);
    // Tanpa efek: the caller's tint is made opaque; others keep it.
    final fill = st == NvGlassStyle.tanpa
        ? NV.glassFill(st)
        : (st == NvGlassStyle.reguler || tint == null ? (tint ?? NV.glassFill(st)) : Color.lerp(tint, NV.glassFill(st), 0.6)!);
    final inner = CustomPaint(
      foregroundPainter: rim ? NvGlassRimPainter(borderRadius: br, rim: NV.glassRimFor(st)) : null,
      child: DecoratedBox(
        key: const ValueKey('nv-glass'),
        decoration: BoxDecoration(
          color: fill,
          borderRadius: br,
          border: border ? Border.all(color: NV.glassBorder) : null,
        ),
        child: Padding(padding: padding, child: child),
      ),
    );
    final scale = NV.glassSigmaScale(st);
    if (!backdrop || scale == 0 || NV.liteMode) return ClipRRect(borderRadius: br, child: inner);
    return ClipRRect(
      borderRadius: br,
      child: ValueListenableBuilder<double>(
        valueListenable: NV.glassSigma,
        child: inner,
        builder: (context, sigma, inner) => BackdropFilter(filter: nvGlassFilter((blur ?? sigma) * scale), child: inner!),
      ),
    );
  }
}

/// Reports its child's laid-out height after each layout that changes it
/// (used to pad a list under a floating dock).
class NvSizeReporter extends SingleChildRenderObjectWidget {
  const NvSizeReporter({super.key, required this.onHeight, super.child});
  final ValueChanged<double> onHeight;
  @override
  RenderObject createRenderObject(BuildContext context) => NvRenderSizeReporter(onHeight);
  @override
  void updateRenderObject(BuildContext context, NvRenderSizeReporter renderObject) => renderObject.onHeight = onHeight;
}

class NvRenderSizeReporter extends RenderProxyBox {
  NvRenderSizeReporter(this.onHeight);
  ValueChanged<double> onHeight;
  double? _last;
  @override
  void performLayout() {
    super.performLayout();
    final h = size.height;
    if (_last == h) return;
    _last = h;
    WidgetsBinding.instance.addPostFrameCallback((_) => onHeight(h));
  }
}

/// Liquid-glass segmented control ("Kantor | Tugas"): a glass capsule with
/// the same clear lens as the nav bar gliding under the selected segment.
class NvGlassSegmented extends StatelessWidget {
  const NvGlassSegmented({super.key, required this.labels, required this.index, required this.onChanged, this.height = 40});
  final List<String> labels;
  final int index;
  final ValueChanged<int> onChanged;
  final double height;

  @override
  Widget build(BuildContext context) {
    final dur = reduceMotion(context) ? Duration.zero : const Duration(milliseconds: 320);
    return SizedBox(
      height: height,
      child: NvGlass(
        radius: height / 2,
        tint: NV.navGlass,
        padding: const EdgeInsets.all(3),
        child: LayoutBuilder(builder: (context, c) {
          final w = c.maxWidth / labels.length;
          return Stack(children: [
            AnimatedPositioned(
              duration: dur,
              curve: Curves.easeOutBack,
              left: w * index,
              top: 0,
              bottom: 0,
              width: w,
              child: IgnorePointer(child: NvLens(size: Size(w, c.maxHeight), magnification: 1.0)),
            ),
            Row(children: [
              for (var i = 0; i < labels.length; i++)
                Expanded(
                  child: Semantics(
                    button: true,
                    selected: i == index,
                    child: GestureDetector(
                      key: ValueKey('segment-${labels[i]}'),
                      behavior: HitTestBehavior.opaque,
                      onTap: () {
                        if (i == index) return;
                        HapticFeedback.selectionClick();
                        onChanged(i);
                      },
                      child: Center(
                        child: AnimatedDefaultTextStyle(
                          duration: dur,
                          style: NV.monoLabel(size: 10, color: i == index ? NV.text : NV.muted).copyWith(shadows: NV.glassTextShadows),
                          // five labels on a narrow phone shrink instead of clipping
                          child: Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 3),
                            child: FittedBox(fit: BoxFit.scaleDown, child: Text(labels[i].toUpperCase(), maxLines: 1)),
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
            ]),
          ]);
        }),
      ),
    );
  }
}

/// Small liquid-glass chip (e.g. "2 menunggu persetujuan" pinned on Chat).
class NvGlassChip extends StatelessWidget {
  const NvGlassChip({super.key, required this.label, this.icon, this.onTap, this.color});
  final String label;
  final IconData? icon;
  final VoidCallback? onTap;
  final Color? color;
  @override
  Widget build(BuildContext context) {
    final c = color ?? NV.red;
    return GestureDetector(
      onTap: onTap,
      child: NvGlass(
        radius: 18,
        tint: Color.lerp(NV.navGlass, c, 0.18),
        padding: const EdgeInsets.fromLTRB(12, 8, 14, 8),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          if (icon != null) ...[Icon(icon, size: 16, color: c), const SizedBox(width: 8)],
          Flexible(child: Text(label, maxLines: 1, overflow: TextOverflow.ellipsis, style: NV.monoLabel(size: 10, color: NV.text).copyWith(shadows: NV.glassTextShadows))),
          const SizedBox(width: 6),
          Icon(CupertinoIcons.chevron_right, size: 13, color: NV.muted),
        ]),
      ),
    );
  }
}

/// Accent-tinted liquid-glass button (intro "Lanjut"): backdrop blur, accent
/// glass fill, specular rim; presses scale down with a highlight.
class NvGlassButton extends StatefulWidget {
  const NvGlassButton({super.key, required this.onPressed, required this.child, this.minSize = const Size(148, 50)});
  final VoidCallback? onPressed;
  final Widget child;
  final Size minSize;
  @override
  State<NvGlassButton> createState() => _NvGlassButtonState();
}

class _NvGlassButtonState extends State<NvGlassButton> {
  bool _down = false;
  void _set(bool v) {
    if (_down != v) setState(() => _down = v);
  }

  @override
  Widget build(BuildContext context) {
    final still = reduceMotion(context);
    final enabled = widget.onPressed != null;
    final r = widget.minSize.height / 2;
    final fg = NV.onRed;
    return Semantics(
      button: true,
      enabled: enabled,
      child: GestureDetector(
        onTapDown: enabled ? (_) => _set(true) : null,
        onTapUp: enabled ? (_) => _set(false) : null,
        onTapCancel: () => _set(false),
        onTap: widget.onPressed == null
            ? null
            : () {
                HapticFeedback.lightImpact();
                widget.onPressed!();
              },
        child: AnimatedScale(
          scale: _down ? 0.95 : 1,
          duration: still ? Duration.zero : const Duration(milliseconds: 140),
          curve: Curves.easeOut,
          child: ConstrainedBox(
            constraints: BoxConstraints(minWidth: widget.minSize.width, minHeight: widget.minSize.height),
            child: NvGlass(
              key: const ValueKey('nv-glass-button'),
              radius: r,
              tint: NV.red.withValues(alpha: enabled ? 0.70 : 0.30),
              padding: const EdgeInsets.symmetric(horizontal: 22),
              child: Stack(alignment: Alignment.center, children: [
                // press highlight
                Positioned.fill(
                  child: AnimatedOpacity(
                    opacity: _down ? 1 : 0,
                    duration: still ? Duration.zero : const Duration(milliseconds: 120),
                    child: const DecoratedBox(
                      decoration: BoxDecoration(
                        gradient: RadialGradient(colors: [Color(0x40FFFFFF), Color(0x00FFFFFF)], radius: 1.1),
                      ),
                    ),
                  ),
                ),
                SizedBox(
                  height: widget.minSize.height,
                  child: Center(
                    child: DefaultTextStyle.merge(
                      style: TextStyle(fontFamily: NV.sans, fontSize: 16, fontWeight: FontWeight.w600, color: fg),
                      child: IconTheme.merge(data: IconThemeData(color: fg, size: 18), child: widget.child),
                    ),
                  ),
                ),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}
