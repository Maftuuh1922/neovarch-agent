// Chat pieces in liquid glass: user bubble (accent-tinted glass), agent turn
// (neutral glass, themed so the shared transcript widgets follow it),
// sender label capsule, header bar, notices / error banner and plain text
// that adapts to the wallpaper under it. All colours come from GlassTone
// (accent + backdrop); nothing is hardcoded cream / amber.
import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../../models/models.dart';
import '../../../theme/neovarch_mobile_theme.dart';
import '../../../ui/widgets/common.dart' show clockOf;
import '../../../ui/widgets/motion.dart' show reduceMotion;
import 'glass_style.dart';
import 'glass_tone.dart';
import 'liquid_glass.dart';
import '../nv_mascot_avatar.dart';

const _rBubble = BorderRadius.all(Radius.circular(20));

/// Samples the backdrop under this widget's on-screen rect (re-sampled on
/// scroll) and builds with it.
class BackdropSampleBuilder extends StatefulWidget {
  const BackdropSampleBuilder({super.key, required this.builder});
  final Widget Function(BuildContext context, BackdropSample sample) builder;
  @override
  State<BackdropSampleBuilder> createState() => _BackdropSampleBuilderState();
}

class _BackdropSampleBuilderState extends State<BackdropSampleBuilder> {
  Rect? _rect;
  ScrollPosition? _scroll;
  bool _scheduled = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final pos = Scrollable.maybeOf(context)?.position;
    if (pos != _scroll) {
      _scroll?.removeListener(_schedule);
      _scroll = pos?..addListener(_schedule);
    }
  }

  @override
  void dispose() {
    _scroll?.removeListener(_schedule);
    super.dispose();
  }

  BackdropSample _sample(Rect? r) {
    final map = GlassScope.maybeOf(context)?.backdrop;
    if (map == null) return BackdropSample.solid(NV.bg);
    return map.sample(r ?? (Offset.zero & (map.screen.isEmpty ? const Size(1, 1) : map.screen)));
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
        final before = _sample(_rect);
        _rect = r;
        if (_sample(r) != before) setState(() {});
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    _schedule();
    return widget.builder(context, _sample(_rect));
  }
}

/// Text straight on the wallpaper (greeting): light or dark by the
/// backdrop, with a soft halo when the photo is too busy for 4.5:1.
class GlassLegibleText extends StatelessWidget {
  const GlassLegibleText(this.text, {super.key, required this.style, this.textAlign, this.maxLines, this.overflow});
  final String text;
  final TextStyle style;
  final TextAlign? textAlign;
  final int? maxLines;
  final TextOverflow? overflow;
  @override
  Widget build(BuildContext context) => BackdropSampleBuilder(builder: (context, s) {
        final f = legibleTextOn(s, NV.red);
        final halo = f.lightText ? Colors.black : Colors.white;
        return Text(text,
            textAlign: textAlign,
            maxLines: maxLines,
            overflow: overflow,
            style: style.copyWith(color: f.color, shadows: [
              Shadow(color: halo.withValues(alpha: f.needsHalo ? 0.55 : 0.25), blurRadius: f.needsHalo ? 14 : 8),
            ]));
      });
}

/// The user's turn: accent-tinted liquid glass, right aligned.
class GlassUserMessage extends StatelessWidget {
  const GlassUserMessage({super.key, required this.msg, this.scale = 1, this.appear = false});
  final ChatMsg msg;
  final double scale;
  final bool appear;
  @override
  Widget build(BuildContext context) {
    final w = MediaQuery.sizeOf(context).width;
    return Align(
      alignment: Alignment.centerRight,
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: math.min(560, w * 0.86)),
        child: LiquidGlass(
          key: const ValueKey('glass-user-message'),
          role: GlassRole.accent,
          appear: appear,
          borderRadius: _rBubble,
          padding: const EdgeInsets.fromLTRB(14, 10, 14, 12),
          child: Builder(builder: (context) {
            final t = GlassForeground.maybeOf(context)!.tone;
            return Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
              Text('KAMU${msg.ts > 0 ? '  ·  ${clockOf(msg.ts)}' : ''}', style: NV.monoLabel(size: 9.5, color: t.secondary)),
              const SizedBox(height: 5),
              SelectableText(msg.content, style: TextStyle(fontSize: 14.5 * scale, height: 1.5, color: t.text)),
            ]);
          }),
        ),
      ),
    );
  }
}

/// Sender label ("NEOVARCH · PC KANTOR") on a small glass capsule.
class GlassSenderLabel extends StatelessWidget {
  const GlassSenderLabel(this.label, {super.key, this.live = false, this.avatar});
  final String label;
  final bool live;
  /// The agent's avatar (agent-identity-spec, 18 dp); null = the Neovarch
  /// mascot, animated while [live] (the turn is running), static otherwise.
  final Widget? avatar;
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Align(
          alignment: Alignment.centerLeft,
          child: LiquidGlass(
            key: const ValueKey('glass-sender-label'),
            shadow: false,
            borderRadius: const BorderRadius.all(Radius.circular(999)),
            padding: const EdgeInsets.fromLTRB(4, 4, 10, 4),
            child: Builder(builder: (context) {
              final t = GlassForeground.maybeOf(context)!.tone;
              return Row(mainAxisSize: MainAxisSize.min, children: [
                avatar ?? NvMascotAvatar(size: 18, animated: live),
                const SizedBox(width: 7),
                Flexible(child: Text(label.toUpperCase(), maxLines: 1, overflow: TextOverflow.ellipsis, style: NV.monoLabel(size: 9.5, color: t.secondary))),
                if (live) ...[const SizedBox(width: 7), _LiveDot(color: t.accent)],
              ]);
            }),
          ),
        ),
      );
}

class _LiveDot extends StatefulWidget {
  const _LiveDot({required this.color});
  final Color color;
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
  Widget build(BuildContext context) => FadeTransition(
        opacity: Tween(begin: 0.3, end: 1.0).animate(_c),
        child: Container(width: 6, height: 6, decoration: BoxDecoration(color: widget.color, shape: BoxShape.circle)),
      );
}

/// An agent turn: sender capsule + the turn on neutral, themed glass (the
/// shared AssistantMessage / MarkdownView / FailureCard follow the glass).
class GlassAgentTurn extends StatelessWidget {
  const GlassAgentTurn({super.key, required this.label, required this.child, this.live = false, this.appear = false, this.avatar});
  final String label;
  final Widget? avatar;
  final bool live;
  final bool appear;
  final Widget child;
  @override
  Widget build(BuildContext context) => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        GlassSenderLabel(label, live: live, avatar: avatar),
        LiquidGlass(
          key: const ValueKey('glass-agent-turn'),
          themed: true,
          appear: appear,
          borderRadius: _rBubble,
          padding: const EdgeInsets.fromLTRB(14, 10, 10, 6),
          child: child,
        ),
      ]);
}

/// Notice / error banner on glass: only the icon carries colour (harmonized
/// red for errors), the text stays neutral.
class GlassNotice extends StatelessWidget {
  const GlassNotice(this.message, {super.key, this.error = true, this.icon, this.action});
  final String message;
  final bool error;
  final IconData? icon;
  final Widget? action;
  @override
  Widget build(BuildContext context) => LiquidGlass(
        key: const ValueKey('glass-notice'),
        role: error ? GlassRole.error : GlassRole.neutral,
        themed: true,
        borderRadius: const BorderRadius.all(Radius.circular(18)),
        padding: const EdgeInsets.fromLTRB(14, 12, 10, 12),
        child: Builder(builder: (context) {
          final t = GlassForeground.maybeOf(context)!.tone;
          return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Padding(
              padding: const EdgeInsets.only(top: 1),
              child: Icon(icon ?? Icons.error_outline_rounded, size: 18, color: error ? t.error : t.secondary),
            ),
            const SizedBox(width: 10),
            Expanded(child: Text(message, style: TextStyle(fontSize: 13.5, height: 1.45, color: t.text))),
            ?action,
          ]);
        }),
      );
}

/// Chat header on a glass bar: kicker, title, status line, actions; every
/// colour from the glass tone (legible on any wallpaper).
class GlassChatHeader extends StatelessWidget {
  const GlassChatHeader({super.key, required this.kicker, required this.title, this.status, this.online = true, this.actions = const []});
  final String kicker;
  final String title;
  final String? status;
  final bool online;
  final List<GlassHeaderAction> actions;
  @override
  Widget build(BuildContext context) {
    final top = MediaQuery.paddingOf(context).top;
    return LiquidGlass(
      key: const ValueKey('glass-chat-header'),
      borderRadius: const BorderRadius.vertical(bottom: Radius.circular(26)),
      padding: EdgeInsets.fromLTRB(20, top + 12, 12, 12),
      child: Builder(builder: (context) {
        final t = GlassForeground.maybeOf(context)!.tone;
        return Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
              Text(kicker.toUpperCase(), style: NV.monoLabel(color: t.secondary)),
              const SizedBox(height: 4),
              Text(title, key: const ValueKey('glass-header-title'), maxLines: 1, overflow: TextOverflow.ellipsis, style: NV.display(size: 30, color: t.text)),
              if (status != null) ...[
                const SizedBox(height: 6),
                Row(children: [
                  Container(width: 7, height: 7, decoration: BoxDecoration(color: online ? t.accent : t.faint, shape: BoxShape.circle)),
                  const SizedBox(width: 8),
                  Flexible(
                    child: Text(status!,
                        key: const ValueKey('glass-header-status'),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: NV.monoLabel(size: 10, color: t.secondary).copyWith(letterSpacing: 0.4)),
                  ),
                ]),
              ],
            ]),
          ),
          for (final a in actions) Padding(padding: const EdgeInsets.only(left: 6, bottom: 2), child: a),
        ]);
      }),
    );
  }
}

/// Round icon button for glass bars (tone-coloured, no own fill colour).
class GlassHeaderAction extends StatelessWidget {
  const GlassHeaderAction({super.key, required this.icon, required this.tooltip, this.onPressed});
  final IconData icon;
  final String tooltip;
  final VoidCallback? onPressed;
  @override
  Widget build(BuildContext context) {
    final t = GlassForeground.maybeOf(context)?.tone;
    final fg = t?.text ?? NV.text;
    return Tooltip(
      message: tooltip,
      child: Material(
        color: fg.withValues(alpha: 0.10),
        shape: CircleBorder(side: BorderSide(color: fg.withValues(alpha: 0.14))),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onPressed,
          child: SizedBox(width: 40, height: 40, child: Icon(icon, size: 19, color: onPressed == null ? (t?.faint ?? NV.faint) : fg)),
        ),
      ),
    );
  }
}
