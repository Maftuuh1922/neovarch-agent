// Chat "mode fokus" (1.4.8): scrolling down through a conversation shrinks
// the big glass header into a compact bar and tucks the composer chips and
// the nav pill away; scrolling back up, or reaching the top, restores them.
//
// Also the header status line: built from short segments that never break
// inside a segment, and a step counter that never reads "9/3".
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/legacy.dart';

/// True while the Chat tab is in focus mode AND its bottom chrome may shrink
/// (not while the keyboard is up or the composer has focus). The shell hides
/// the nav pill from this.
final chatFocusProvider = StateProvider<bool>((ref) => false);

/// Room the shell reserves at the bottom for its floating nav pill. The chat
/// reads it to let the composer slide down into that room when the pill
/// hides. Absent (tests, other hosts) = 0, so nothing moves.
class NavReserveScope extends InheritedWidget {
  const NavReserveScope({super.key, required this.reserve, required super.child});
  final double reserve;

  static double of(BuildContext context) => context.dependOnInheritedWidgetOfExactType<NavReserveScope>()?.reserve ?? 0;

  @override
  bool updateShouldNotify(NavReserveScope oldWidget) => oldWidget.reserve != reserve;
}

/// Decides focus mode from scroll movement, with hysteresis so a jittery
/// finger does not flap the header.
class ChatFocusTracker {
  ChatFocusTracker({this.threshold = 28, this.topSlop = 8});
  final double threshold;
  final double topSlop;
  bool focused = false;
  double _acc = 0;
  double? _last;
  double? _lastMax;

  /// Feed the list's offset after every scroll. [user] is false for
  /// programmatic scrolls (auto-follow of a streaming reply, jump to latest):
  /// those never change the mode. Returns true when [focused] changed.
  bool update({required double pixels, required double maxExtent, required bool user}) {
    final last = _last ?? pixels;
    _last = pixels;
    // the content changed size (a reply streamed in, the composer folded):
    // a jump that comes from that is not the user's scrolling
    final resized = _lastMax != null && (maxExtent - _lastMax!).abs() > 0.5;
    _lastMax = maxExtent;
    final delta = resized ? 0.0 : pixels - last;
    var next = focused;
    if (maxExtent < 1 || pixels <= topSlop) {
      // nothing to scroll, or back at the top: full header
      next = false;
      _acc = 0;
    } else if (user && delta != 0) {
      if ((delta > 0) != (_acc > 0)) _acc = 0; // direction flipped
      _acc += delta;
      if (_acc >= threshold) next = true; // reading down: focus
      if (_acc <= -threshold) next = false; // going back up: restore
    }
    if (next == focused) return false;
    focused = next;
    _acc = 0;
    return true;
  }

  void reset() {
    focused = false;
    _acc = 0;
    _last = null;
    _lastMax = null;
  }
}

/// Status segments for the chat header, in order.
List<String> chatStatusSegments({
  required String status,
  bool running = false,
  String? step,
  String? context,
  double? tokensPerSecond,
}) =>
    [
      if (status.isNotEmpty) status,
      if (running) 'agen bekerja',
      ?step,
      if (context != null) context else if (tokensPerSecond != null) '${tokensPerSecond.toStringAsFixed(0)} tok/s',
    ];

/// Joins segments with " · ", keeping each segment on one line (spaces
/// inside a segment become non-breaking), so a wrap only ever falls between
/// segments.
String joinStatus(List<String> segments) => segments.map((s) => s.replaceAll(' ', '\u00A0')).join('\u00A0· ');
