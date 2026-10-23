// Pixel art for Crew members on the phone: the same 12×12 bust, ten palettes
// and desk scene as the desktop (desktop/.../components/neovarch/crew-pixel.tsx),
// painted cell by cell. `working` types (two frames), `reviewing` holds a
// clipboard, `waiting` shows a "!" bubble, `done` a check.
import 'dart:async';

import 'package:flutter/material.dart';

import '../../ui/widgets/common.dart' show reduceMotion;

const crewSprite = [
  '....hhhh....',
  '...hhhhhh...',
  '..hhhhhhhh..',
  '..hssssssh..',
  '..sesssses..',
  '..ssssssss..',
  '...ssssss...',
  '....ssss....',
  '..cccccccc..',
  '.cccccccccc.',
  '.cdccccccdc.',
  '.cdccccccdc.',
];
const crewHands = ['..ss....ss..', '...ss..ss...'];
const _blinkRow = '..ssssssss..';

/// hair, skin, shirt, shirt shade — identical to the desktop palettes.
const crewPalettes = <List<int>>[
  [0xFF2B1A12, 0xFFF1C7A1, 0xFFEE1C1C, 0xFF8F0A0A],
  [0xFF111111, 0xFFE0AC85, 0xFF3D5A80, 0xFF293D57],
  [0xFF6B3A1E, 0xFFF6D2B4, 0xFFF2B134, 0xFFB67F12],
  [0xFF1B1B2F, 0xFFC68863, 0xFF2F9E74, 0xFF1D6B4E],
  [0xFF3A2418, 0xFFD79B72, 0xFF8E6CD8, 0xFF5C43A0],
  [0xFFC7C2B8, 0xFFF0C9A6, 0xFF262626, 0xFF111111],
  [0xFF4B1D0F, 0xFFA86B4C, 0xFFE8E4DC, 0xFFB5AFA5],
  [0xFFE05D2B, 0xFFF4D0B2, 0xFF1F7A8C, 0xFF14525E],
  [0xFF0D0D0D, 0xFF8D5A3C, 0xFFD94F70, 0xFF9E2F4B],
  [0xFF5A4636, 0xFFE9B994, 0xFF6A8F2A, 0xFF47611B],
];
const _eye = 0xFF1A1010;

/// Global switch for widget tests that settle frames (the typing animation repeats forever).
bool crewPixelAnimate = true;

/// The sprite rows for one frame (pure; mirrors spritePixels() on the desktop).
List<String> crewSpriteRows(String status, int frame) {
  final rows = [...crewSprite];
  if (status == 'idle' && frame.isOdd) rows[4] = _blinkRow;
  rows.add(status == 'working' || status == 'reviewing' ? crewHands[frame % 2] : crewHands[0]);
  return rows;
}

class CrewStationPainter extends CustomPainter {
  CrewStationPainter({required this.avatar, required this.status, required this.frame, required this.chair, required this.accent});
  final int avatar;
  final String status;
  final int frame;
  final Color chair;
  final Color accent;

  @override
  void paint(Canvas canvas, Size size) {
    final px = size.width / 22;
    final p = Paint()..isAntiAlias = false;
    void cell(double x, double y, double w, double h, Color c) {
      p.color = c;
      canvas.drawRect(Rect.fromLTWH(x * px, y * px, w * px, h * px), p);
    }

    final pal = crewPalettes[((avatar % 10) + 10) % 10];
    final colors = {'h': Color(pal[0]), 's': Color(pal[1]), 'c': Color(pal[2]), 'd': Color(pal[3]), 'e': const Color(_eye)};
    cell(6, 7, 10, 6, chair);
    final rows = crewSpriteRows(status, frame);
    for (var y = 0; y < rows.length; y++) {
      for (var x = 0; x < rows[y].length; x++) {
        final c = colors[rows[y][x]];
        if (c != null) cell(x + 5.0, y + 2.0, 1, 1, c);
      }
    }
    if (status == 'reviewing') {
      cell(15, 11, 3, 4, const Color(0xFFB67F12));
      cell(15.5, 12, 2, 2, const Color(0xFFF4F2ED));
    }
    cell(0, 15, 22, 2, const Color(0xFF8A5A3B));
    cell(1, 17, 2, 2, const Color(0xFF5E3C27));
    cell(19, 17, 2, 2, const Color(0xFF5E3C27));
    final lit = status == 'working' || status == 'reviewing';
    cell(7.5, 11, 7, 4, lit ? accent : const Color(0xFF6F6A66));
    cell(10.5, 12.5, 1, 1, const Color(0xFFF4F2ED));
    if (status == 'waiting' || status == 'done' || status == 'error') {
      final b = status == 'done' ? const Color(0xFF2F9E74) : status == 'waiting' ? const Color(0xFFF2B134) : const Color(0xFFEE1C1C);
      cell(15, 0, 6, 5, b);
      cell(16, 5, 1, 1, b);
      if (status == 'done') {
        for (final (x, y) in const [(16.0, 2.0), (17.0, 3.0), (18.0, 2.0), (19.0, 1.0)]) {
          cell(x, y, 1, 1, Colors.white);
        }
      } else {
        cell(18, 1, 1, 2, const Color(0xFF1A1010));
        cell(18, 3, 1, 1, const Color(0xFF1A1010));
      }
    }
  }

  @override
  bool shouldRepaint(CrewStationPainter old) =>
      old.avatar != avatar || old.status != status || old.frame != frame || old.chair != chair || old.accent != accent;
}

/// One member at their desk, [width] logical px wide (22×19 cells).
class CrewStation extends StatefulWidget {
  const CrewStation({super.key, required this.avatar, required this.status, this.width = 110, required this.chair, required this.accent, this.animate = true});
  final int avatar;
  final String status;
  final double width;
  final Color chair;
  final Color accent;
  /// Typing frames while working; off for static art (onboarding).
  final bool animate;

  @override
  State<CrewStation> createState() => _CrewStationState();
}

class _CrewStationState extends State<CrewStation> {
  int frame = 0;
  Timer? _timer;

  void _sync() {
    final busy = widget.status == 'working' || widget.status == 'reviewing';
    _timer?.cancel();
    _timer = null;
    // only working members animate (typing); no timer runs for an idle room
    if (!crewPixelAnimate || !widget.animate || !busy) return;
    _timer = Timer.periodic(const Duration(milliseconds: 500), (_) {
      if (mounted && !reduceMotion(context)) setState(() => frame++);
    });
  }

  @override
  void initState() {
    super.initState();
    _sync();
  }

  @override
  void didUpdateWidget(CrewStation old) {
    super.didUpdateWidget(old);
    if (old.status != widget.status) _sync();
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => SizedBox(
        width: widget.width,
        height: widget.width * 19 / 22,
        child: CustomPaint(
          key: ValueKey('crew-station-${widget.status}'),
          painter: CrewStationPainter(avatar: widget.avatar, status: widget.status, frame: frame, chair: widget.chair, accent: widget.accent),
        ),
      );
}
