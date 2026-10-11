// First launch of the phone remote: a "Pilih bahasa" step (Bahasa Indonesia /
// English, the phone's language preselected, applied at once), three short
// slides plus a "Pilih tema" step (accent presets / hue / hex, Gelap·Terang·Sistem, applied live).
// Everything follows the current accent and brightness; the red slide art is
// recoloured to the accent (unchanged in Merah). Replayable from the PC tab.
//
// 1.4.2 liquid glass: a slowly drifting accent glow behind everything (the
// glass refracts it), glass chips / Tutup pill / Lanjut button / page-dot
// capsule with a gliding lens, glass numeral + title ([NvGlassText]).
// Motion: drag-following parallax (art slower than text), art scale/blur-in,
// staggered text (60 ms apart), chips pop on a spring. One controller per
// page plus one for the backdrop; reduce-motion = all static.
import 'package:flutter/cupertino.dart' show CupertinoIcons;
import 'dart:math' as math;
import 'dart:ui' show ImageFilter;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../state/app_controller.dart' show settingsProvider;
import '../../theme/neovarch_mobile_theme.dart';
import '../../ui/widgets/brand.dart' show Wordmark;
import '../../ui/widgets/motion.dart' show reduceMotion;
import '../appearance.dart' show appearanceProvider;
import '../l10n/app_language.dart' show appLanguageProvider;
import '../l10n/strings.dart';
import 'language_panel.dart';
import 'nv_glass_text.dart';
import 'nv_widgets.dart';
import 'remote_background.dart' show NvAccentArt;
import 'remote_pc_screen.dart' show AppearancePanel;

class _Slide {
  const _Slide(this.art, this.align, this.kicker, this.title, this.body, this.points);
  final String art;
  final Alignment align;
  final String kicker;
  final String title;
  final String body;
  final List<String> points;
}

const _slides = [
  _Slide('assets/art/feat-remote.webp', Alignment(0.35, 0), 'pc = otak · hp = remote', 'Agen di PC,\nremote di saku.',
      'Neovarch berjalan di aplikasi desktop. HP ini hanya remote: kirim perintah dan lihat hasilnya.',
      ['Tanpa kunci API di HP', 'Satu PC atau beberapa']),
  _Slide('assets/art/feat-automation.webp', Alignment(0.2, 0), 'tugas · kanban', 'Pantau kerja\npara agen.',
      'Papan tugas di PC tampil di sini: siapa mengerjakan apa, sampai mana, dan apa yang menunggu review.',
      ['Pindahkan tugas', 'Kirim arahan']),
  _Slide('assets/art/portal-banner.webp', Alignment(0.6, 0), 'persetujuan · aman', 'Kamu yang\nmemutuskan.',
      'Perintah berisiko berhenti dulu sampai kamu setujui dari HP. Token pemasangan disimpan terenkripsi.',
      ['Izinkan sekali', 'Tolak kapan saja']),
];

/// Language step (first page), slides, then the theme step (last page).
const introPageCount = 5;
const introLanguagePage = 0;
const introThemePage = 4;
const _firstSlidePage = 1;

class RemoteIntroScreen extends ConsumerStatefulWidget {
  const RemoteIntroScreen({super.key, this.replay = false, this.initialPage = 0});
  final bool replay;
  final int initialPage;
  @override
  ConsumerState<RemoteIntroScreen> createState() => _RemoteIntroScreenState();
}

class _RemoteIntroScreenState extends ConsumerState<RemoteIntroScreen> with SingleTickerProviderStateMixin {
  late final PageController _pc = PageController(initialPage: widget.initialPage.clamp(0, introPageCount - 1));
  late int _index = widget.initialPage.clamp(0, introPageCount - 1);
  /// Backdrop drift (the only screen-level animation).
  late final AnimationController _glow = AnimationController(vsync: this, duration: const Duration(seconds: 24));

  double get _page => _pc.hasClients && _pc.position.haveDimensions ? (_pc.page ?? _index.toDouble()) : _index.toDouble();

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    for (final s in _slides) {
      precacheImage(AssetImage(s.art), context);
    }
    if (reduceMotion(context)) {
      _glow.stop();
    } else if (!_glow.isAnimating) {
      _glow.repeat();
    }
  }

  @override
  void dispose() {
    _glow.dispose();
    _pc.dispose();
    super.dispose();
  }

  void _done() {
    final s = ref.read(settingsProvider);
    if (!s.introSeen) s.update((x) => x.introSeen = true);
    if (widget.replay && Navigator.of(context).canPop()) Navigator.of(context).pop();
  }

  void _next() {
    if (_index >= introPageCount - 1) return _done();
    if (reduceMotion(context)) {
      _pc.jumpToPage(_index + 1);
    } else {
      _pc.nextPage(duration: const Duration(milliseconds: 420), curve: Curves.easeOutCubic);
    }
  }

  @override
  Widget build(BuildContext context) {
    final pad = MediaQuery.paddingOf(context);
    final last = _index == introPageCount - 1;
    ref.watch(appearanceProvider); // repaint on theme changes (live preview)
    ref.watch(appLanguageProvider); // the language step switches every string at once
    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: (NV.palette.dark ? SystemUiOverlayStyle.light : SystemUiOverlayStyle.dark).copyWith(
        statusBarColor: Colors.transparent,
        systemNavigationBarColor: NV.bg,
        systemNavigationBarDividerColor: NV.bg,
      ),
      child: Scaffold(
        backgroundColor: NV.bg,
        body: Stack(children: [
          Positioned.fill(child: RepaintBoundary(child: IntroGlow(animation: _glow))),
          Padding(
            padding: EdgeInsets.fromLTRB(0, pad.top + 10, 0, pad.bottom + 16),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              // Top rail: wordmark, slide counter, skip.
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 0, 12, 6),
                child: Row(children: [
                  Wordmark(height: 22, color: NV.text, haloColor: NV.red),
                  const Spacer(),
                  Text('${_index + 1} / $introPageCount', style: NV.monoLabel(size: 10, color: NV.muted)),
                  const SizedBox(width: 10),
                  _GlassPill(key: const ValueKey('intro-skip'), label: tr(widget.replay ? 'Tutup' : 'Lewati'), onTap: _done),
                ]),
              ),
              Expanded(
                child: PageView.builder(
                  controller: _pc,
                  itemCount: introPageCount,
                  onPageChanged: (i) => setState(() => _index = i),
                  itemBuilder: (context, i) => i == introLanguagePage
                      ? const _LanguageStep()
                      : i == introThemePage
                          ? _ThemeStep(active: _index == i)
                          : _SlideView(
                              slide: _slides[i - _firstSlidePage],
                              number: i - _firstSlidePage + 1,
                              active: _index == i,
                              page: _pc,
                              delta: () => _page - i),
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 12, 20, 0),
                child: Row(children: [
                  IntroDots(key: const ValueKey('intro-dots'), count: introPageCount, page: _pc, pageOf: () => _page),
                  const Spacer(),
                  NvGlassButton(
                    key: const ValueKey('intro-next'),
                    onPressed: _next,
                    child: Row(mainAxisSize: MainAxisSize.min, children: [
                      Text(tr(last ? (widget.replay ? 'Selesai' : 'Hubungkan PC') : 'Lanjut')),
                      const SizedBox(width: 8),
                      const Icon(CupertinoIcons.arrow_right, size: 18),
                    ]),
                  ),
                ]),
              ),
            ]),
          ),
        ]),
      ),
    );
  }
}

/// Soft accent glow blobs drifting slowly behind the intro (static with
/// reduce-motion). Radial gradients are already soft, so no blur filter.
class IntroGlow extends StatelessWidget {
  const IntroGlow({super.key, required this.animation});
  final Animation<double> animation;
  @override
  Widget build(BuildContext context) => CustomPaint(
        key: const ValueKey('intro-glow'),
        painter: _GlowPainter(animation, NV.red, NV.bg, NV.palette.dark),
      );
}

class _GlowPainter extends CustomPainter {
  _GlowPainter(this.t, this.accent, this.bg, this.dark) : super(repaint: t);
  final Animation<double> t;
  final Color accent;
  final Color bg;
  final bool dark;
  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRect(Offset.zero & size, Paint()..color = bg);
    final a = t.value * 2 * math.pi;
    final blobs = <(Offset, double, double)>[
      (Offset(0.18 + 0.10 * math.sin(a), 0.22 + 0.06 * math.cos(a)), 0.62, dark ? 0.30 : 0.20),
      (Offset(0.86 + 0.08 * math.cos(a + 1.3), 0.52 + 0.08 * math.sin(a + 1.3)), 0.55, dark ? 0.22 : 0.15),
      (Offset(0.30 + 0.12 * math.sin(a + 2.6), 0.92 + 0.05 * math.cos(a + 2.6)), 0.70, dark ? 0.18 : 0.12),
    ];
    for (final (c, r, alpha) in blobs) {
      final center = Offset(c.dx * size.width, c.dy * size.height);
      final radius = r * size.shortestSide;
      final g = RadialGradient(colors: [accent.withValues(alpha: alpha), accent.withValues(alpha: 0)])
          .createShader(Rect.fromCircle(center: center, radius: radius));
      canvas.drawCircle(center, radius, Paint()..shader = g);
    }
  }

  @override
  bool shouldRepaint(_GlowPainter old) => old.accent != accent || old.bg != bg || old.dark != dark;
}

/// Page indicator: a small glass capsule with dots; the active dot is a
/// clear lens that glides with the page (drag-following) and stretches
/// between dots.
class IntroDots extends StatelessWidget {
  const IntroDots({super.key, required this.count, required this.page, required this.pageOf});
  final int count;
  final Listenable page;
  final double Function() pageOf;
  static const step = 16.0, dot = 6.0, lensW = 24.0, h = 24.0;
  @override
  Widget build(BuildContext context) {
    final w = step * (count - 1) + lensW + 8;
    return SizedBox(
      width: w,
      height: h,
      child: NvGlass(
        radius: h / 2,
        tint: NV.navGlass,
        child: AnimatedBuilder(
          animation: page,
          builder: (context, _) {
            final p = pageOf().clamp(0.0, count - 1.0);
            final f = (p - p.round()).abs(); // 0 at rest, 0.5 halfway
            final lw = lensW * (1 + f * 0.9);
            final cx = 4 + lensW / 2 + p * step;
            return Stack(clipBehavior: Clip.none, children: [
              for (var i = 0; i < count; i++)
                Positioned(
                  left: 4 + lensW / 2 + i * step - dot / 2,
                  top: (h - dot) / 2,
                  child: Container(
                    key: ValueKey('intro-dot-$i'),
                    width: dot,
                    height: dot,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: Color.lerp(NV.faint, NV.red, (1 - (p - i).abs()).clamp(0.0, 1.0)),
                    ),
                  ),
                ),
              Positioned(
                key: const ValueKey('intro-dot-lens'),
                left: cx - lw / 2,
                top: 2,
                width: lw,
                height: h - 4,
                child: IgnorePointer(child: NvLens(size: Size(lw, h - 4), magnification: 1.25)),
              ),
            ]);
          },
        ),
      ),
    );
  }
}

/// Small glass capsule text button ("Tutup" / "Lewati").
class _GlassPill extends StatelessWidget {
  const _GlassPill({super.key, required this.label, required this.onTap});
  final String label;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => Semantics(
        button: true,
        child: GestureDetector(
          onTap: onTap,
          child: NvGlass(
            radius: 16,
            backdrop: false,
            tint: Color.lerp(NV.glass, NV.red, 0.10),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 7),
            child: Text(label, style: TextStyle(fontFamily: NV.sans, fontSize: 14, fontWeight: FontWeight.w600, color: NV.text)),
          ),
        ),
      );
}

class _SlideView extends StatefulWidget {
  const _SlideView({required this.slide, required this.number, required this.active, required this.page, required this.delta});
  final _Slide slide;
  final int number;
  final bool active;
  final Listenable page;
  /// Signed distance of this page from the current scroll position.
  final double Function() delta;
  @override
  State<_SlideView> createState() => _SlideViewState();
}

/// Stagger timings (ms): line k starts at k * [_staggerMs].
const _staggerMs = 60.0, _lineMs = 420.0, _entranceMs = 900;

class _SlideViewState extends State<_SlideView> with SingleTickerProviderStateMixin {
  late final AnimationController _in = AnimationController(vsync: this, duration: const Duration(milliseconds: _entranceMs));

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (reduceMotion(context)) {
      _in.value = 1;
    } else if (widget.active && _in.value == 0 && !_in.isAnimating) {
      _in.forward();
    }
  }

  @override
  void didUpdateWidget(_SlideView old) {
    super.didUpdateWidget(old);
    if (widget.active && !old.active) {
      if (reduceMotion(context)) {
        _in.value = 1;
      } else {
        _in.forward(from: 0);
      }
    }
  }

  @override
  void dispose() {
    _in.dispose();
    super.dispose();
  }

  /// Progress of staggered line [k] (0..1).
  double _line(int k) => Curves.easeOutCubic.transform(((_in.value * _entranceMs - k * _staggerMs) / _lineMs).clamp(0.0, 1.0));

  Widget _stagger(int k, Widget child) => AnimatedBuilder(
        animation: _in,
        child: child,
        builder: (context, child) {
          final v = _line(k);
          return Opacity(opacity: v, child: Transform.translate(offset: Offset(0, 16 * (1 - v)), child: child));
        },
      );

  Widget _chip(int k, String p) => AnimatedBuilder(
        animation: _in,
        builder: (context, child) {
          final raw = ((_in.value * _entranceMs - k * _staggerMs) / 520).clamp(0.0, 1.0);
          final s = 0.7 + 0.3 * Curves.elasticOut.transform(raw);
          return Opacity(opacity: Curves.easeOut.transform(raw), child: Transform.scale(scale: s, child: child));
        },
        child: NvGlass(
          key: ValueKey('intro-chip-$p'),
          radius: NV.rCtl,
          backdrop: false,
          tint: Color.lerp(NV.glass, NV.red, 0.14),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Container(
              width: 6,
              height: 6,
              decoration: BoxDecoration(color: NV.red, shape: BoxShape.circle, boxShadow: [BoxShadow(color: NV.red.withValues(alpha: 0.6), blurRadius: 6)]),
            ),
            const SizedBox(width: 8),
            Text(p, style: TextStyle(fontSize: 13, color: NV.text)),
          ]),
        ),
      );

  @override
  Widget build(BuildContext context) {
    final slide = widget.slide;
    final still = reduceMotion(context);
    return LayoutBuilder(builder: (context, c) {
      // The plate takes what is left after the copy; never below 160px.
      final plateH = (c.maxHeight - 300).clamp(160.0, 420.0);
      final width = c.maxWidth;
      final art = SizedBox(
        height: plateH,
        child: ClipRRect(
          borderRadius: BorderRadius.circular(NV.rCard),
          child: CustomPaint(
            foregroundPainter: NvGlassRimPainter(borderRadius: BorderRadius.circular(NV.rCard), rim: NV.glassRim, chroma: true, strength: 1.2),
            child: Stack(fit: StackFit.expand, children: [
              NvAccentArt(slide.art, alignment: slide.align),
              // inner glow along the top edge (light catching the glass)
              DecoratedBox(
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    begin: Alignment.topCenter,
                    end: Alignment.bottomCenter,
                    stops: const [0, 0.22, 0.7, 1],
                    colors: [Colors.white.withValues(alpha: 0.16), Colors.white.withValues(alpha: 0), Colors.transparent, NV.bg.withValues(alpha: 0.35)],
                  ),
                ),
              ),
              Positioned(
                left: 14,
                bottom: 6,
                child: NvGlassText('0${widget.number}',
                    key: ValueKey('intro-numeral-${widget.number}'), entrance: false, textAlign: TextAlign.left, style: NV.display(size: 64)),
              ),
            ]),
          ),
        ),
      );
      final text = Padding(
        padding: const EdgeInsets.symmetric(horizontal: 4),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _stagger(0, Text(tr(slide.kicker).toUpperCase(), style: NV.monoLabel(color: NV.redInk))),
          const SizedBox(height: 10),
          _stagger(1, NvGlassText(tr(slide.title), entrance: false, sheen: false, textAlign: TextAlign.left, style: NV.display(size: 34))),
          const SizedBox(height: 12),
          _stagger(2, Text(tr(slide.body), style: TextStyle(fontSize: 17, height: 1.4, letterSpacing: NV.tracking(17), color: NV.muted))),
          const SizedBox(height: 14),
          Wrap(spacing: 8, runSpacing: 8, children: [
            for (final (k, p) in slide.points.indexed) _chip(3 + k, tr(p)),
          ]),
        ]),
      );
      return SingleChildScrollView(
        physics: const ClampingScrollPhysics(),
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const SizedBox(height: 8),
          // Parallax: the page moves by -d·W; the art is pulled back (moves
          // ~half as fast) and the text pushed ahead. Follows the finger.
          AnimatedBuilder(
            animation: Listenable.merge([widget.page, _in]),
            child: RepaintBoundary(child: art),
            builder: (context, child) {
              final d = widget.delta().clamp(-1.0, 1.0);
              final enter = Curves.easeOutCubic.transform((_in.value * _entranceMs / 600).clamp(0.0, 1.0));
              final scale = (1 - 0.06 * d.abs()) * (0.96 + 0.04 * enter);
              final blur = still ? 0.0 : (d.abs() * 6 + (1 - enter) * 5);
              Widget out = Transform.scale(scale: scale, child: child);
              if (blur > 0.05) out = ImageFiltered(imageFilter: ImageFilter.blur(sigmaX: blur, sigmaY: blur), child: out);
              return Transform.translate(offset: Offset(d * width * 0.45, 0), child: out);
            },
          ),
          const SizedBox(height: 20),
          AnimatedBuilder(
            animation: widget.page,
            child: text,
            builder: (context, child) => Transform.translate(offset: Offset(-widget.delta().clamp(-1.0, 1.0) * width * 0.12, 0), child: child),
          ),
        ]),
      );
    });
  }
}

/// "Pilih tema": the same picker as PC → Tampilan, without "Ikuti tema PC"
/// (no PC yet). Any pick is a local override; untouched, the phone keeps
/// following the PC's theme once paired.
class _ThemeStep extends ConsumerWidget {
  const _ThemeStep({this.active = false});
  final bool active;
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final look = ref.watch(appearanceProvider);
    return ListView(
      key: const ValueKey('intro-theme-step'),
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 4),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(tr('TAMPILAN · TEMA'), style: NV.monoLabel(color: NV.redInk)),
            const SizedBox(height: 10),
            NvGlassText(tr('Pilih temamu.'), key: const ValueKey('intro-theme-title'), textAlign: TextAlign.left, style: NV.display(size: 34)),
            const SizedBox(height: 10),
            Text(
              tr(look.followPc
                  ? 'Pilih warna dan mode. Kalau dilewati, HP mengikuti tema PC setelah terhubung.'
                  : 'Tema khusus HP ini dipakai, juga setelah terhubung. Ubah kapan saja di Profil → Tampilan.'),
              key: const ValueKey('intro-theme-note'),
              style: TextStyle(fontSize: 15, height: 1.4, letterSpacing: NV.tracking(15), color: NV.muted),
            ),
          ]),
        ),
        const SizedBox(height: 16),
        const AppearancePanel(showFollowPc: false, showBackground: false, margin: EdgeInsets.zero),
      ],
    );
  }
}

/// "Pilih bahasa": first intro page. Bahasa Indonesia / English, the phone's
/// language preselected; a tap switches the whole intro at once and is saved
/// as the app language (the same setting as Profil › Bahasa).
class _LanguageStep extends ConsumerWidget {
  const _LanguageStep();
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    ref.watch(appLanguageProvider);
    return ListView(
      key: const ValueKey('intro-language-step'),
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 4),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(tr('bahasa · language').toUpperCase(), style: NV.monoLabel(color: NV.redInk)),
            const SizedBox(height: 10),
            NvGlassText(tr('Pilih bahasa.'), key: const ValueKey('intro-language-title'), textAlign: TextAlign.left, style: NV.display(size: 34)),
            const SizedBox(height: 10),
            Text(
              tr('Bisa diganti kapan saja di Profil → Bahasa.'),
              style: TextStyle(fontSize: 15, height: 1.4, letterSpacing: NV.tracking(15), color: NV.muted),
            ),
          ]),
        ),
        const SizedBox(height: 16),
        const LanguagePanel(showSystem: false, margin: EdgeInsets.zero),
      ],
    );
  }
}
