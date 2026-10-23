// Screenshots of old ```mermaid blocks in the phone chat (392 px, dark and
// light): "before" = the classic mermaid block (DiagramBlock, what main showed),
// "after" = the same fence through MarkdownView, now a visual-inline card.
//
// The diagram picture itself comes from the WebView (assets/diagram/host.html),
// which flutter test cannot run. A two-stage run fills that gap with the real
// page rendered in Chromium:
//   1. NV_SHOTS_STAGE=prepare  writes the phone theme map, the card body width
//      and the fixtures to $NV_SHOTS_DIR/_render/ (see diagram-shots tooling);
//   2. Chromium renders host.html with those exact inputs into
//      $NV_SHOTS_DIR/_render/<theme>-<name>-<kind>.png + .json;
//   3. a run with --update-goldens shows those pictures inside the real Flutter
//      widgets and writes $NV_SHOTS_DIR/hp-<theme>-<name>-<before|after>.png.
// Without NV_SHOTS_DIR / the renders it only checks that each view builds.
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:neovarch_agent/remote/appearance.dart';
import 'package:neovarch_agent/remote/ui/remote_app.dart' show PaletteScope, themeFor;
import 'package:neovarch_agent/theme/neovarch_mobile_theme.dart';
import 'package:neovarch_agent/ui/widgets/diagram_block.dart';
import 'package:neovarch_agent/ui/widgets/markdown_view.dart';
import 'package:neovarch_agent/ui/widgets/visual_block.dart';

final _shotsDir = Platform.environment['NV_SHOTS_DIR'];
final _stage = Platform.environment['NV_SHOTS_STAGE'] ?? '';

/// Old answers as the agent used to write them.
const diagramFixtures = <String, String>{
  'flowchart': '''---
title: Alur login
---
flowchart TD
  A([Buka aplikasi]) --> B[Isi email dan password]
  B --> C{Password benar?}
  C -->|Ya| D[Buat sesi + token]
  C -->|Tidak| E[Tampilkan pesan salah]
  E --> B
  D --> F([Masuk ke Beranda])
  style D fill:#2563eb''',
  'sequence': '''sequenceDiagram
  title Login dengan token
  actor U as Pengguna
  participant A as Aplikasi
  participant S as Server
  U->>A: Ketuk Login
  A->>S: POST /login
  alt password cocok
    S-->>A: 200 + token
  else salah
    S-->>A: 401
  end
  Note over A: Token disimpan di keychain
  A-->>U: Buka Beranda''',
  'timeline': '''timeline
  title Rilis Neovarch
  section 2026
  Agustus : v1.4.6 : Pairing HP
  September : v1.4.7 : Relay + Wi-Fi lokal
  Oktober : v1.4.8 : Grafik radar
  November : v1.4.9 : Visual inline + Crew''',
};

const _intro = {'flowchart': 'Ini alur login-nya:', 'sequence': 'Urutan pesan saat login:', 'timeline': 'Rencana rilisnya begini:'};

String _md(String name) => '${_intro[name]}\n\n```mermaid\n${diagramFixtures[name]}\n```\n';

void main() {
  late SharedPreferences prefs;

  setUpAll(() async {
    TestWidgetsFlutterBinding.ensureInitialized();
    final manifest = jsonDecode(await rootBundle.loadString('FontManifest.json')) as List;
    for (final f in manifest.cast<Map<String, dynamic>>()) {
      final loader = FontLoader(f['family'] as String);
      for (final a in (f['fonts'] as List).cast<Map<String, dynamic>>()) {
        loader.addFont(rootBundle.load(a['asset'] as String));
      }
      await loader.load();
    }
  });

  tearDown(() => DiagramBlock.debugPreviewBuilder = null);

  Future<AppearanceController> look(bool light) async {
    SharedPreferences.setMockInitialValues({'nv.theme.pc.base': light ? 'light' : 'dark'});
    prefs = await SharedPreferences.getInstance();
    final look = AppearanceController(prefs);
    NV.palette = look.palette;
    return look;
  }

  Widget page(AppearanceController look, Widget child, double height) => RepaintBoundary(
    key: const ValueKey('shot'),
    child: MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: themeFor(look),
      builder: (context, c) => PaletteScope(revision: look.revision, child: c!),
      home: Scaffold(
        backgroundColor: NV.bg,
        body: MediaQuery(
          data: MediaQueryData(size: Size(392, height), padding: const EdgeInsets.only(top: 47, bottom: 34)),
          // The remote chat list pads 16 px on both sides.
          child: SafeArea(
            child: SingleChildScrollView(padding: const EdgeInsets.fromLTRB(16, 16, 16, 16), child: child),
          ),
        ),
      ),
    ),
  );

  void size(WidgetTester tester, double height) {
    tester.view.physicalSize = Size(392 * 3, height * 3);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
  }

  for (final light in [false, true]) {
    final mode = light ? 'light' : 'dark';

    testWidgets('prepare: theme map + card width ($mode)', (tester) async {
      size(tester, 900);
      final l = await look(light);
      Map<String, Object?>? theme;
      Size? body;
      DiagramBlock.debugPreviewBuilder = (context, code, kind, full, onResult) {
        theme = diagramThemeFor(context);
        return LayoutBuilder(
          builder: (context, c) {
            body = Size(c.maxWidth, c.maxHeight);
            WidgetsBinding.instance.addPostFrameCallback((_) => onResult(const DiagramRenderResult.ok(200)));
            return const SizedBox.expand();
          },
        );
      };
      await tester.pumpWidget(page(l, MarkdownView(_md('flowchart')), 900));
      await tester.pumpAndSettle();
      expect(find.byType(VisualBlock), findsOneWidget);
      expect(theme, isNotNull);
      expect(body!.width, greaterThan(300));
      if (_stage == 'prepare' && _shotsDir != null) {
        final dir = Directory('$_shotsDir/_render')..createSync(recursive: true);
        File('${dir.path}/_inputs-$mode.json').writeAsStringSync(jsonEncode({'theme': theme, 'width': body!.width, 'fixtures': diagramFixtures}));
      }
    });

    for (final name in diagramFixtures.keys) {
      for (final after in [false, true]) {
        final shot = 'hp-$mode-$name-${after ? 'after' : 'before'}';
        testWidgets(shot, (tester) async {
          final kindName = after ? 'mermaidVisual' : 'mermaid';
          final png = _shotsDir == null ? null : File('$_shotsDir/_render/$mode-$name-$kindName.png');
          final meta = _shotsDir == null ? null : File('$_shotsDir/_render/$mode-$name-$kindName.json');
          final real = png != null && png.existsSync() && meta!.existsSync();
          final bytes = real ? png.readAsBytesSync() : null;
          final info = real ? jsonDecode(meta.readAsStringSync()) as Map<String, dynamic> : const <String, dynamic>{};
          DiagramKind? seen;
          DiagramBlock.debugPreviewBuilder = (context, code, kind, full, onResult) {
            seen = kind;
            WidgetsBinding.instance.addPostFrameCallback(
              (_) => onResult(
                DiagramRenderResult.ok((info['h'] as num?)?.toDouble() ?? 220, title: info['title'] as String?, caption: info['caption'] as String?),
              ),
            );
            return bytes == null
                ? const ColoredBox(color: Color(0x22888888))
                : Image.memory(bytes, fit: BoxFit.fitWidth, alignment: Alignment.topCenter, scale: 3, gaplessPlayback: true);
          };
          const height = 1000.0;
          size(tester, height);
          final l = await look(light);
          final md = _md(name);
          final child = after
              ? MarkdownView(md)
              // main (before this change) drew the fence as a classic DiagramBlock.
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    MarkdownView(_intro[name]!),
                    const SizedBox(height: 8),
                    DiagramBlock(code: diagramFixtures[name]!, kind: DiagramKind.mermaid),
                  ],
                );
          await tester.pumpWidget(page(l, child, height));
          if (bytes != null) {
            await tester.runAsync(() async {
              final el = tester.element(find.byType(Image).first);
              await precacheImage(MemoryImage(bytes, scale: 3), el);
            });
          }
          await tester.pumpAndSettle();
          expect(tester.takeException(), isNull);
          expect(seen, after ? DiagramKind.mermaidVisual : DiagramKind.mermaid);
          if (after) {
            expect(find.byKey(const ValueKey('visual-card')), findsOneWidget);
          }
          if (autoUpdateGoldenFiles && real) {
            final dir = Directory(_shotsDir!).absolute.path;
            await expectLater(find.byKey(const ValueKey('shot')), matchesGoldenFile('$dir/$shot.png'));
          }
        });
      }
    }
  }
}
