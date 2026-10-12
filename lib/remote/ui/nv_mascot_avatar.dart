// The Neovarch mascot as the agent's default avatar (v1.4.7), replacing the
// orange "N" circle. Animated (thinking loop, animated WebP) only while the
// agent's turn is running; static when idle, done or failed — and static when
// the system asks for reduced motion. Office agents keep their own avatar.
import 'package:flutter/material.dart';

import '../../ui/widgets/motion.dart' show reduceMotion;

class NvMascotAvatar extends StatelessWidget {
  const NvMascotAvatar({super.key, this.size = 18, this.animated = false});

  static const animatedAsset = 'assets/brand/neovarch_avatar_128.webp';
  static const staticAsset = 'assets/brand/neovarch_avatar_128_static.png';

  final double size;

  /// True while the agent is thinking / running this turn.
  final bool animated;

  @override
  Widget build(BuildContext context) {
    final anim = animated && !reduceMotion(context);
    final px = (size * MediaQuery.devicePixelRatioOf(context)).ceil();
    return SizedBox(
      width: size,
      height: size,
      child: ClipOval(
        child: Image.asset(
          anim ? animatedAsset : staticAsset,
          key: ValueKey(anim ? 'nv-mascot-animated' : 'nv-mascot-static'),
          width: size,
          height: size,
          fit: BoxFit.cover,
          // Decode at display size: an 18 dp avatar never needs 128 px frames.
          cacheWidth: px,
          cacheHeight: px,
          filterQuality: FilterQuality.medium,
          gaplessPlayback: true,
          excludeFromSemantics: true,
        ),
      ),
    );
  }
}
