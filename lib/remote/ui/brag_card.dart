// Kartu Neovarch: the shareable brag card. One widget, three styles and two
// formats, rendered at a fixed logical size (360×640 story / 360×360 feed) and
// exported at 3× (1080×1920 / 1080×1080).
//
//  * Kaca        frosted glass over the user's wallpaper (or soft accent light)
//  * Gelap       near-black card, accent lines, mono labels
//  * Warna-warni flat accent background with a scattered icon pattern
//
// Content: avatar + name/@github, Kantor 3D snapshot, stats (agen aktif, tugas
// selesai, sesi/pesan, model), contribution graph, QR to the landing page and
// "Dibuat dengan Neovarch". No gradients: blur, flat tints and solid shapes only.
import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/cupertino.dart' show CupertinoIcons;
import 'package:flutter/material.dart';
import 'package:qr/qr.dart';

import '../../theme/neovarch_mobile_theme.dart';
import '../share/brag_card_data.dart';
import '../social_models.dart';
import 'nv_widgets.dart' show NvGlassRimPainter;
import 'remote_background.dart' show NvAppBackground;
import 'remote_social_screen.dart' show NvAvatar;

/// Colours of one style, resolved from the current palette.
class BragColors {
  const BragColors({required this.ground, required this.panel, required this.text, required this.muted, required this.accent, required this.line, required this.cell, required this.dark});
  final Color ground, panel, text, muted, accent, line, cell;
  final bool dark;

  factory BragColors.of(BragStyle style) {
    final a = NV.red;
    switch (style) {
      case BragStyle.kaca:
        final dark = NV.palette.dark;
        return BragColors(
          ground: NV.bg,
          panel: Color.lerp(NV.surface, a, dark ? 0.10 : 0.05)!.withValues(alpha: dark ? 0.46 : 0.60),
          text: NV.text,
          muted: NV.muted,
          accent: a,
          line: NV.text.withValues(alpha: dark ? 0.12 : 0.14),
          cell: NV.text.withValues(alpha: dark ? 0.06 : 0.07),
          dark: dark,
        );
      case BragStyle.gelap:
        return BragColors(
          ground: const Color(0xFF09090B),
          panel: const Color(0xFF141417),
          text: const Color(0xFFF4F2ED),
          muted: const Color(0xFFA8A29E),
          accent: _readableOn(a, const Color(0xFF141417)),
          line: const Color(0xFF2A2A30),
          cell: const Color(0xFF1C1C21),
          dark: true,
        );
      case BragStyle.warna:
        // ink = whichever of near-black / white reads better; then nudge the
        // ground away from the ink until it passes 4.5:1 (mid reds, greens).
        const black = Color(0xFF111111);
        final light = _contrast(a, black) > _contrast(a, Colors.white);
        final ink = light ? black : Colors.white;
        var ground = a;
        for (var i = 0; i < 8 && _contrast(ground, ink) < 4.6; i++) {
          ground = Color.lerp(ground, light ? Colors.white : Colors.black, 0.08)!;
        }
        return BragColors(
          ground: ground,
          panel: ink.withValues(alpha: light ? 0.08 : 0.14),
          text: ink,
          muted: ink.withValues(alpha: 0.74),
          accent: ink,
          line: ink.withValues(alpha: 0.22),
          cell: ink.withValues(alpha: 0.10),
          dark: !light,
        );
    }
  }

  /// Heatmap level 0..4.
  Color heat(int level) => level <= 0 ? cell : Color.lerp(cell, accent, 0.25 + 0.1875 * level)!;
}

/// An accent that is too dark on the near-black card is lifted towards white.
Color _readableOn(Color c, Color bg) {
  var out = c;
  for (var i = 0; i < 5 && _contrast(out, bg) < 3.2; i++) {
    out = Color.lerp(out, Colors.white, 0.22)!;
  }
  return out;
}

double _contrast(Color a, Color b) {
  final la = a.computeLuminance() + 0.05, lb = b.computeLuminance() + 0.05;
  return la > lb ? la / lb : lb / la;
}

class NeovarchBragCard extends StatelessWidget {
  const NeovarchBragCard({
    super.key,
    required this.data,
    this.style = BragStyle.kaca,
    this.format = BragFormat.story,
    this.showStats = true,
    this.showOffice = true,
    this.showRadar = true,
    this.background,
    this.avatar,
  });

  final BragCardData data;
  final BragStyle style;
  final BragFormat format;
  final bool showStats, showOffice;

  /// Pamerkan radar (only drawn when the PC counted something).
  final bool showRadar;

  /// Overrides the wallpaper behind the Kaca style (tests / screenshots).
  final Widget? background;
  final ImageProvider? avatar;

  @override
  Widget build(BuildContext context) {
    final c = BragColors.of(style);
    final l = format.logical;
    final story = format == BragFormat.story;
    final radius = BorderRadius.circular(story ? 28 : 24);
    final content = Padding(
      padding: story ? const EdgeInsets.fromLTRB(20, 20, 20, 18) : const EdgeInsets.fromLTRB(16, 15, 16, 13),
      child: story
          ? _StoryLayout(data: data, c: c, showStats: showStats, showOffice: showOffice, showRadar: showRadar, avatar: avatar)
          : _FeedLayout(data: data, c: c, showStats: showStats, showOffice: showOffice, showRadar: showRadar, avatar: avatar),
    );
    return SizedBox(
      key: ValueKey('brag-card-${style.name}-${format.name}'),
      width: l.w,
      height: l.h,
      child: Material(
        type: MaterialType.transparency,
        child: DefaultTextStyle(
          style: TextStyle(fontFamily: Theme.of(context).textTheme.bodyMedium?.fontFamily, fontSize: 13, color: c.text),
          child: ClipRect(
            child: Stack(fit: StackFit.expand, children: [
              ColoredBox(color: c.ground),
              if (style == BragStyle.kaca) ...[
                _SoftLights(accent: c.accent, dark: c.dark),
                background ?? const NvAppBackground(),
              ],
              if (style == BragStyle.warna) _IconPattern(ink: c.text),
              if (style == BragStyle.gelap) _GridLines(line: c.line),
              Padding(
                padding: story ? const EdgeInsets.fromLTRB(18, 40, 18, 40) : const EdgeInsets.all(14),
                child: _Panel(style: style, c: c, radius: radius, child: content),
              ),
              if (story)
                Positioned(
                  left: 0,
                  right: 0,
                  bottom: 18,
                  child: Center(
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                      decoration: style == BragStyle.kaca ? BoxDecoration(color: c.panel, borderRadius: BorderRadius.circular(999)) : null,
                      child: Text('Dibuat dengan Neovarch',
                          key: const ValueKey('brag-footer'), style: NV.monoLabel(size: 9.5, color: c.text.withValues(alpha: 0.8))),
                    ),
                  ),
                ),
            ]),
          ),
        ),
      ),
    );
  }
}

/// Blurred flat accent discs behind the glass (no gradients).
class _SoftLights extends StatelessWidget {
  const _SoftLights({required this.accent, required this.dark});
  final Color accent;
  final bool dark;
  @override
  Widget build(BuildContext context) => ImageFiltered(
        imageFilter: ui.ImageFilter.blur(sigmaX: 48, sigmaY: 48, tileMode: TileMode.decal),
        child: CustomPaint(painter: _DiscPainter(accent, dark)),
      );
}

class _DiscPainter extends CustomPainter {
  _DiscPainter(this.accent, this.dark);
  final Color accent;
  final bool dark;
  @override
  void paint(Canvas canvas, Size s) {
    final p = Paint()..color = accent.withValues(alpha: dark ? 0.55 : 0.32);
    canvas.drawCircle(Offset(s.width * 0.18, s.height * 0.16), s.width * 0.42, p);
    canvas.drawCircle(Offset(s.width * 0.92, s.height * 0.62), s.width * 0.36, p..color = accent.withValues(alpha: dark ? 0.40 : 0.24));
    canvas.drawCircle(Offset(s.width * 0.30, s.height * 0.96), s.width * 0.30, p..color = accent.withValues(alpha: dark ? 0.32 : 0.20));
  }

  @override
  bool shouldRepaint(_DiscPainter o) => o.accent != accent || o.dark != dark;
}

/// Warna-warni: icons scattered like stickers (deterministic positions).
class _IconPattern extends StatelessWidget {
  const _IconPattern({required this.ink});
  final Color ink;
  static const _icons = [
    CupertinoIcons.sparkles,
    CupertinoIcons.bolt_fill,
    CupertinoIcons.chevron_left_slash_chevron_right,
    CupertinoIcons.star_fill,
    CupertinoIcons.cube_fill,
    CupertinoIcons.heart_fill,
    CupertinoIcons.flame_fill,
    CupertinoIcons.desktopcomputer,
  ];
  @override
  Widget build(BuildContext context) => LayoutBuilder(builder: (context, box) {
        final rnd = math.Random(7);
        final cols = 5, rows = (box.maxHeight / (box.maxWidth / cols)).ceil();
        final cw = box.maxWidth / cols;
        return Stack(children: [
          for (var r = 0; r < rows; r++)
            for (var k = 0; k < cols; k++)
              Positioned(
                left: k * cw + rnd.nextDouble() * cw * 0.5,
                top: r * cw + rnd.nextDouble() * cw * 0.5,
                child: Transform.rotate(
                  angle: (rnd.nextDouble() - 0.5) * 0.9,
                  child: Icon(_icons[(r * cols + k) % _icons.length], size: 16 + rnd.nextDouble() * 14, color: ink.withValues(alpha: 0.13)),
                ),
              ),
        ]);
      });
}

/// Gelap: a faint square grid.
class _GridLines extends StatelessWidget {
  const _GridLines({required this.line});
  final Color line;
  @override
  Widget build(BuildContext context) => CustomPaint(painter: _GridPainter(line.withValues(alpha: 0.35)));
}

class _GridPainter extends CustomPainter {
  _GridPainter(this.color);
  final Color color;
  @override
  void paint(Canvas canvas, Size s) {
    final p = Paint()
      ..color = color
      ..strokeWidth = 0.5;
    for (var x = 0.0; x <= s.width; x += 24) {
      canvas.drawLine(Offset(x, 0), Offset(x, s.height), p);
    }
    for (var y = 0.0; y <= s.height; y += 24) {
      canvas.drawLine(Offset(0, y), Offset(s.width, y), p);
    }
  }

  @override
  bool shouldRepaint(_GridPainter o) => o.color != color;
}

class _Panel extends StatelessWidget {
  const _Panel({required this.style, required this.c, required this.radius, required this.child});
  final BragStyle style;
  final BragColors c;
  final BorderRadius radius;
  final Widget child;
  @override
  Widget build(BuildContext context) {
    final body = Container(
      key: const ValueKey('brag-panel'),
      decoration: BoxDecoration(
        borderRadius: radius,
        color: c.panel,
        border: style == BragStyle.kaca ? null : Border.all(color: style == BragStyle.gelap ? c.line : c.text.withValues(alpha: 0.28), width: 1),
      ),
      child: style == BragStyle.kaca
          ? CustomPaint(foregroundPainter: NvGlassRimPainter(borderRadius: radius, rim: NV.glassRim, chroma: true, strength: 1.3), child: child)
          : child,
    );
    if (style != BragStyle.kaca) return ClipRRect(borderRadius: radius, child: body);
    return ClipRRect(
      borderRadius: radius,
      child: BackdropFilter(filter: ui.ImageFilter.blur(sigmaX: 22, sigmaY: 22), child: body),
    );
  }
}

// ---------------------------------------------------------------- layouts --

class _StoryLayout extends StatelessWidget {
  const _StoryLayout({required this.data, required this.c, required this.showStats, required this.showOffice, this.showRadar = true, this.avatar});
  final BragCardData data;
  final BragColors c;
  final bool showStats, showOffice, showRadar;
  final ImageProvider? avatar;
  @override
  Widget build(BuildContext context) {
    final office = showOffice && data.officeShot != null;
    final stats = showStats && !data.stats.isEmpty;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _Brand(c: c),
      const SizedBox(height: 12),
      _Head(data: data, c: c, size: 52, nameSize: 24),
      const SizedBox(height: 12),
      if (office) ...[
        _OfficeShot(data: data, c: c, height: stats ? (data.stats.tileCount > 4 ? 92 : 112) : 170),
        const SizedBox(height: 12),
      ],
      if (stats) ...[
        _StatsGrid(stats: data.stats, c: c, columns: 2, compact: true, valueSize: 19),
        const SizedBox(height: 10),
      ],
      if (data.heatmap != null) ...[
        _Label('KONTRIBUSI 12 BULAN', c),
        const SizedBox(height: 6),
        BragHeat(heatmap: data.heatmap!, c: c, height: office || stats ? 38 : 70),
        const SizedBox(height: 4),
        Text('${data.heatmap!.total} kontribusi · streak ${data.heatmap!.streak} hari', style: NV.monoLabel(size: 8.5, color: c.muted)),
      ],
      if (showRadar && data.radar != null && !data.radar!.isEmpty)
        Expanded(child: Padding(padding: const EdgeInsets.symmetric(vertical: 6), child: BragRadarChart(radar: data.radar!, c: c)))
      else
        const Spacer(),
      _QrRow(link: data.link, c: c, qr: 74),
    ]);
  }
}

class _FeedLayout extends StatelessWidget {
  const _FeedLayout({required this.data, required this.c, required this.showStats, required this.showOffice, this.showRadar = true, this.avatar});
  final BragCardData data;
  final BragColors c;
  final bool showStats, showOffice, showRadar;
  final ImageProvider? avatar;
  @override
  Widget build(BuildContext context) {
    final office = showOffice && data.officeShot != null;
    final stats = showStats && !data.stats.isEmpty;
    final side = stats
        ? _StatsGrid(stats: data.stats, c: c, columns: data.stats.tileCount > 4 ? 3 : 2, compact: true)
        : (data.heatmap != null ? BragHeat(heatmap: data.heatmap!, c: c, height: 64) : const SizedBox.shrink());
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Row(children: [
        Expanded(child: _Head(data: data, c: c, size: 40, nameSize: 19)),
        const SizedBox(width: 8),
        _Mark(c: c, size: 18),
      ]),
      const SizedBox(height: 10),
      if (office)
        _OfficeShot(data: data, c: c, height: 84)
      else if (stats && data.heatmap != null)
        BragHeat(heatmap: data.heatmap!, c: c, height: 48),
      if (showRadar && data.radar != null && !data.radar!.isEmpty)
        Expanded(child: Padding(padding: const EdgeInsets.symmetric(vertical: 4), child: BragRadarChart(radar: data.radar!, c: c)))
      else
        const Spacer(),
      Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
        Expanded(child: side),
        const SizedBox(width: 10),
        _QrTile(link: data.link, c: c, size: 78),
      ]),
      const SizedBox(height: 8),
      Row(children: [
        Expanded(child: Text('Dibuat dengan Neovarch', key: const ValueKey('brag-footer'), maxLines: 1, style: NV.monoLabel(size: 8.5, color: c.muted))),
        Text('pindai QR untuk unduh', maxLines: 1, style: NV.monoLabel(size: 8, color: c.muted)),
      ]),
    ]);
  }
}

String _shortLink(String url) => url.replaceFirst(RegExp(r'^https?://'), '').replaceFirst(RegExp(r'/$'), '');

class _Label extends StatelessWidget {
  const _Label(this.text, this.c);
  final String text;
  final BragColors c;
  @override
  Widget build(BuildContext context) => Text(text, style: NV.monoLabel(size: 8.5, color: c.muted));
}

class _Mark extends StatelessWidget {
  const _Mark({required this.c, this.size = 16});
  final BragColors c;
  final double size;
  @override
  Widget build(BuildContext context) => Image.asset('assets/brand/monogram.png', width: size, height: size, color: c.text.withValues(alpha: 0.9));
}

class _Brand extends StatelessWidget {
  const _Brand({required this.c});
  final BragColors c;
  @override
  Widget build(BuildContext context) => Row(children: [
        _Mark(c: c),
        const SizedBox(width: 6),
        Text('NEOVARCH AGENT', style: NV.monoLabel(size: 9.5, color: c.text.withValues(alpha: 0.85))),
        const Spacer(),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
          decoration: BoxDecoration(borderRadius: BorderRadius.circular(999), border: Border.all(color: c.line)),
          child: Text('KARTU', style: NV.monoLabel(size: 8, color: c.muted)),
        ),
      ]);
}

class _Head extends StatelessWidget {
  const _Head({required this.data, required this.c, required this.size, required this.nameSize});
  final BragCardData data;
  final BragColors c;
  final double size, nameSize;
  @override
  Widget build(BuildContext context) => Row(children: [
        Container(
          padding: const EdgeInsets.all(2),
          decoration: BoxDecoration(shape: BoxShape.circle, border: Border.all(color: c.accent, width: 1.6)),
          child: NvAvatar(name: data.name, url: data.avatarUrl, size: size),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
            Text(data.name, key: const ValueKey('brag-name'), maxLines: 1, overflow: TextOverflow.ellipsis, style: NV.display(size: nameSize, color: c.text)),
            if (data.login != null)
              Text('@${data.login}', key: const ValueKey('brag-login'), maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontFamily: NV.mono, fontSize: nameSize * 0.45, color: c.muted)),
          ]),
        ),
      ]);
}

class _OfficeShot extends StatelessWidget {
  const _OfficeShot({required this.data, required this.c, required this.height});
  final BragCardData data;
  final BragColors c;
  final double height;
  @override
  Widget build(BuildContext context) {
    final s = data.stats;
    final caption = s.agentsTotal == null ? 'KANTOR 3D' : 'KANTOR · ${s.agentsActive ?? 0}/${s.agentsTotal} BEKERJA';
    return Container(
      key: const ValueKey('brag-office'),
      height: height,
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(borderRadius: BorderRadius.circular(18), color: c.cell, border: Border.all(color: c.line)),
      child: Stack(fit: StackFit.expand, children: [
        Image.memory(data.officeShot!, fit: BoxFit.cover, gaplessPlayback: true, errorBuilder: (_, _, _) => const SizedBox.shrink()),
        Positioned(
          left: 8,
          bottom: 8,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            decoration: BoxDecoration(borderRadius: BorderRadius.circular(999), color: Colors.black.withValues(alpha: 0.55)),
            child: Text(caption, style: NV.monoLabel(size: 8, color: Colors.white)),
          ),
        ),
      ]),
    );
  }
}

class _StatsGrid extends StatelessWidget {
  const _StatsGrid({required this.stats, required this.c, this.columns = 2, this.compact = false, this.valueSize});
  final BragStats stats;
  final BragColors c;
  final int columns;
  final bool compact;
  final double? valueSize;
  @override
  Widget build(BuildContext context) {
    final cells = <(String, String)>[
      if (stats.agentsActive != null) ('${stats.agentsActive}${stats.agentsTotal != null ? '/${stats.agentsTotal}' : ''}', 'agen aktif'),
      if (stats.tasksDone != null) ('${stats.tasksDone}', 'tugas selesai'),
      if (stats.sessions != null) ('${stats.sessions}', 'sesi'),
      if (stats.messages != null) (_compactNum(stats.messages!), 'pesan'),
      if (stats.tokensToday != null) (compactTokens(stats.tokensToday!), 'token hari ini'),
      if (stats.tokensTotal != null) (compactTokens(stats.tokensTotal!), 'total token'),
    ];
    final rows = <Widget>[];
    for (var i = 0; i < cells.length; i += columns) {
      rows.add(Row(children: [
        for (var k = i; k < i + columns; k++) ...[
          if (k > i) SizedBox(width: compact ? 6 : 8),
          Expanded(child: k < cells.length ? _Stat(value: cells[k].$1, label: cells[k].$2, c: c, compact: compact, valueSize: valueSize) : const SizedBox.shrink()),
        ],
      ]));
      rows.add(SizedBox(height: compact ? 6 : 8));
    }
    return Column(key: const ValueKey('brag-stats'), crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
      ...rows,
      if (stats.model != null)
        Container(
          key: const ValueKey('brag-model'),
          padding: EdgeInsets.symmetric(horizontal: 10, vertical: compact ? 4 : 6),
          decoration: BoxDecoration(borderRadius: BorderRadius.circular(999), color: c.cell, border: Border.all(color: c.line)),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(CupertinoIcons.sparkles, size: compact ? 10 : 12, color: c.accent),
            const SizedBox(width: 5),
            Flexible(
              child: Text('model · ${stats.model}',
                  maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontFamily: NV.mono, fontSize: compact ? 9 : 10.5, color: c.text)),
            ),
          ]),
        ),
    ]);
  }
}

/// 950 → "950", 12 400 → "12rb", 3 400 000 → "3,4jt", 2 100 000 000 → "2,1M".
String compactTokens(int n) {
  if (n >= 1000000000) return '${(n / 1000000000).toStringAsFixed(1).replaceAll('.', ',')}M';
  if (n >= 1000000) return '${(n / 1000000).toStringAsFixed(1).replaceAll('.', ',')}jt';
  return _compactNum(n);
}

String _compactNum(int n) => n >= 10000 ? '${(n / 1000).toStringAsFixed(0)}rb' : (n >= 1000 ? '${(n / 1000).toStringAsFixed(1).replaceAll('.', ',')}rb' : '$n');

class _Stat extends StatelessWidget {
  const _Stat({required this.value, required this.label, required this.c, this.compact = false, this.valueSize});
  final String value, label;
  final BragColors c;
  final bool compact;
  final double? valueSize;
  @override
  Widget build(BuildContext context) => Container(
        padding: EdgeInsets.fromLTRB(10, compact ? 5 : 8, 8, compact ? 5 : 8),
        decoration: BoxDecoration(borderRadius: BorderRadius.circular(compact ? 10 : 14), color: c.cell, border: Border.all(color: c.line)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
          Text(value, maxLines: 1, style: NV.display(size: valueSize ?? (compact ? 16 : 22), color: c.text).copyWith(height: 1.1)),
          Text(label, maxLines: 1, overflow: TextOverflow.ellipsis, style: NV.monoLabel(size: compact ? 7.5 : 8.5, color: c.muted)),
        ]),
      );
}

/// Contribution graph in the card's colours, last ~52 weeks fitted to width.
class BragHeat extends StatelessWidget {
  const BragHeat({super.key, required this.heatmap, required this.c, required this.height});
  final SocialHeatmap heatmap;
  final BragColors c;
  final double height;
  @override
  Widget build(BuildContext context) => SizedBox(
        key: const ValueKey('brag-heat'),
        height: height,
        child: CustomPaint(size: Size.infinite, painter: _HeatPainter(heatmap, c)),
      );
}

class _HeatPainter extends CustomPainter {
  _HeatPainter(this.h, this.c);
  final SocialHeatmap h;
  final BragColors c;
  @override
  void paint(Canvas canvas, Size size) {
    var weeks = h.weeks();
    if (weeks.isEmpty) return;
    // as many recent weeks as fit with square-ish cells
    final cell0 = size.height / 7;
    final fit = math.max(1, (size.width / cell0).floor());
    if (weeks.length > fit) weeks = weeks.sublist(weeks.length - fit);
    final step = math.min(size.width / weeks.length, size.height / 7);
    final gap = step * 0.18, cell = step - gap;
    final x0 = size.width - weeks.length * step + gap / 2;
    final p = Paint();
    for (var w = 0; w < weeks.length; w++) {
      for (var d = 0; d < 7; d++) {
        final v = weeks[w][d];
        if (v < 0) continue;
        p.color = c.heat(SocialHeatmap.level(v, h.max));
        canvas.drawRRect(RRect.fromRectAndRadius(Rect.fromLTWH(x0 + w * step, d * step, cell, cell), Radius.circular(cell * 0.28)), p);
      }
    }
  }

  @override
  bool shouldRepaint(_HeatPainter o) => o.h != h || o.c.accent != c.accent || o.c.cell != c.cell;
}

/// Pamerkan spider chart (6 axes, scores from the PC core). Hides itself when
/// the space left on the card is too small to read.
class BragRadarChart extends StatelessWidget {
  const BragRadarChart({super.key, required this.radar, required this.c});
  final BragRadar radar;
  final BragColors c;

  static const labels = {'coding': 'Coding', 'riset': 'Riset', 'ppt': 'PPT', 'browser': 'Browser', 'otomasi': 'Otomasi', 'token': 'Token'};

  @override
  Widget build(BuildContext context) => LayoutBuilder(builder: (context, box) {
        if (box.maxHeight < 72 || box.maxWidth < 120) return const SizedBox.shrink();
        return Column(key: const ValueKey('brag-radar'), crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          _Label('RADAR · ${radar.days} HARI', c),
          Expanded(child: CustomPaint(size: Size.infinite, painter: BragRadarPainter(radar, c, labelStyle: NV.monoLabel(size: 8, color: c.text)))),
        ]);
      });
}

class BragRadarPainter extends CustomPainter {
  BragRadarPainter(this.radar, this.c, {required this.labelStyle});
  final BragRadar radar;
  final BragColors c;
  final TextStyle labelStyle;

  /// Corner of axis [i] of [n] at [f] of radius [r] (axis 0 up, clockwise).
  static Offset point(int i, int n, double f, Offset center, double r) {
    final a = -math.pi / 2 + i * 2 * math.pi / n;
    return center + Offset(math.cos(a), math.sin(a)) * r * f;
  }

  @override
  void paint(Canvas canvas, Size size) {
    final n = radar.axes.length;
    if (n < 3) return;
    final center = Offset(size.width / 2, size.height / 2);
    final r = math.max(8.0, math.min(size.width / 2 - 44, size.height / 2 - 14));
    final grid = Paint()
      ..style = PaintingStyle.stroke
      ..color = c.line
      ..strokeWidth = 0.8;
    for (final f in const [0.25, 0.5, 0.75, 1.0]) {
      canvas.drawPath(Path()..addPolygon([for (var i = 0; i < n; i++) point(i, n, f, center, r)], true), grid);
    }
    for (var i = 0; i < n; i++) {
      canvas.drawLine(center, point(i, n, 1, center, r), grid);
    }
    final pts = [for (var i = 0; i < n; i++) point(i, n, math.max(0.04, radar.axes[i].score / 100), center, r)];
    final shape = Path()..addPolygon(pts, true);
    canvas.drawPath(shape, Paint()..color = c.accent.withValues(alpha: 0.30));
    canvas.drawPath(
        shape,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeJoin = StrokeJoin.round
          ..color = c.accent
          ..strokeWidth = 1.6);
    final dot = Paint()..color = c.accent;
    for (final p in pts) {
      canvas.drawCircle(p, 2.2, dot);
    }
    for (var i = 0; i < n; i++) {
      final a = radar.axes[i];
      final label = '${BragRadarChart.labels[a.id] ?? a.id} ${a.id == 'token' ? compactTokens(a.value) : _compactNum(a.value)}';
      final tp = TextPainter(text: TextSpan(text: label, style: labelStyle), textDirection: TextDirection.ltr, maxLines: 1)..layout(maxWidth: 88);
      final at = point(i, n, 1, center, r + 6);
      final dx = at.dx - center.dx;
      final x = dx.abs() < 2 ? at.dx - tp.width / 2 : (dx > 0 ? at.dx : at.dx - tp.width);
      final y = at.dy < center.dy - 2 ? at.dy - tp.height : (at.dy > center.dy + 2 ? at.dy : at.dy - tp.height / 2);
      tp.paint(canvas, Offset(x.clamp(0, math.max(0, size.width - tp.width)).toDouble(), y.clamp(0, math.max(0, size.height - tp.height)).toDouble()));
    }
  }

  @override
  bool shouldRepaint(BragRadarPainter o) => o.radar != radar || o.c.accent != c.accent || o.c.line != c.line || o.labelStyle != labelStyle;
}

class _QrRow extends StatelessWidget {
  const _QrRow({required this.link, required this.c, required this.qr});
  final String link;
  final BragColors c;
  final double qr;
  @override
  Widget build(BuildContext context) => Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
        _QrTile(link: link, c: c, size: qr),
        const SizedBox(width: 12),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
            Text('Coba Neovarch', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: c.text)),
            const SizedBox(height: 2),
            Text('Agen AI di PC-mu, dipantau dari HP.', maxLines: 2, style: TextStyle(fontSize: 11.5, height: 1.3, color: c.muted)),
            const SizedBox(height: 4),
            Text(_shortLink(link), maxLines: 1, overflow: TextOverflow.ellipsis, style: NV.monoLabel(size: 8, color: c.muted)),
          ]),
        ),
      ]);
}

/// White rounded tile with the QR in near-black (always scannable).
class _QrTile extends StatelessWidget {
  const _QrTile({required this.link, required this.c, required this.size});
  final String link;
  final BragColors c;
  final double size;
  @override
  Widget build(BuildContext context) => Container(
        key: const ValueKey('brag-qr'),
        width: size,
        height: size,
        padding: EdgeInsets.all(size * 0.07),
        decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(size * 0.16)),
        child: CustomPaint(painter: BragQrPainter(link)),
      );
}

class BragQrPainter extends CustomPainter {
  BragQrPainter(this.data) : image = QrImage(QrCode.fromData(data: data, errorCorrectLevel: QrErrorCorrectLevel.M));
  final String data;
  final QrImage image;
  @override
  void paint(Canvas canvas, Size size) {
    final n = image.moduleCount;
    final m = size.shortestSide / n;
    final p = Paint()
      ..color = const Color(0xFF111111)
      ..isAntiAlias = false;
    for (var r = 0; r < n; r++) {
      for (var k = 0; k < n; k++) {
        if (image.isDark(r, k)) canvas.drawRect(Rect.fromLTWH(k * m, r * m, m + 0.3, m + 0.3), p);
      }
    }
  }

  @override
  bool shouldRepaint(BragQrPainter o) => o.data != data;
}
