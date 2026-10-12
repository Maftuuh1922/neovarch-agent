// v1.4.7: the agent's default avatar is the Neovarch mascot — animated only
// while the turn runs, static when idle / done / failed or under reduced motion.
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:neovarch_agent/remote/ui/nv_mascot_avatar.dart';
import 'package:neovarch_agent/remote/ui/nv_widgets.dart' show NvAgentLabel;
import 'package:neovarch_agent/remote/ui/remote_app.dart' show neovarchMobileTheme;

String? _asset(WidgetTester tester) {
  final img = tester.widget<Image>(find.descendant(of: find.byType(NvMascotAvatar), matching: find.byType(Image)));
  var p = img.image;
  if (p is ResizeImage) p = p.imageProvider;
  return (p as AssetImage).assetName;
}

Widget _app(Widget child, {bool disableAnimations = false}) => MaterialApp(
      theme: neovarchMobileTheme,
      home: MediaQuery(
        data: MediaQueryData(disableAnimations: disableAnimations),
        child: Scaffold(body: Center(child: child)),
      ),
    );

void main() {
  test('both mascot assets are bundled', () async {
    TestWidgetsFlutterBinding.ensureInitialized();
    final anim = await rootBundle.load(NvMascotAvatar.animatedAsset);
    final still = await rootBundle.load(NvMascotAvatar.staticAsset);
    expect(anim.lengthInBytes, greaterThan(1000));
    expect(still.lengthInBytes, greaterThan(1000));
    // RIFF....WEBP header and PNG signature.
    expect(String.fromCharCodes(anim.buffer.asUint8List(0, 4)), 'RIFF');
    expect(String.fromCharCodes(anim.buffer.asUint8List(8, 4)), 'WEBP');
    expect(still.buffer.asUint8List(1, 3), [0x50, 0x4E, 0x47]);
  });

  testWidgets('running → animated WebP; idle/done → static PNG', (tester) async {
    await tester.pumpWidget(_app(const NvMascotAvatar(animated: true)));
    expect(_asset(tester), NvMascotAvatar.animatedAsset);
    await tester.pumpWidget(_app(const NvMascotAvatar()));
    expect(_asset(tester), NvMascotAvatar.staticAsset);
    expect(tester.getSize(find.byType(NvMascotAvatar)), const Size(18, 18));
  });

  testWidgets('reduced motion keeps the mascot still even while running', (tester) async {
    await tester.pumpWidget(_app(const NvMascotAvatar(animated: true), disableAnimations: true));
    expect(_asset(tester), NvMascotAvatar.staticAsset);
  });

  testWidgets('agent label shows the mascot instead of the "N" mark, animated only while live', (tester) async {
    await tester.pumpWidget(_app(const NvAgentLabel('neovarch · PC', live: true)));
    expect(find.text('N'), findsNothing);
    expect(_asset(tester), NvMascotAvatar.animatedAsset);
    await tester.pumpWidget(_app(const NvAgentLabel('neovarch · PC')));
    expect(_asset(tester), NvMascotAvatar.staticAsset);
  });
}
