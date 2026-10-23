import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:neovarch_agent/theme/app_theme.dart';
import 'package:neovarch_agent/ui/widgets/diagram_block.dart';
import 'package:neovarch_agent/ui/widgets/markdown_view.dart';
import 'package:neovarch_agent/ui/widgets/visual_block.dart';

const _c = Color(0xFF140808);

ThemeData _theme() => ThemeData(
      brightness: Brightness.dark,
      colorScheme: const ColorScheme.dark(primary: Color(0xFFEE1C1C), onSurface: Color(0xFFF4F2ED)),
      extensions: const [
        NvColors(
          card: _c, muted: _c, mutedForeground: Color(0xFFB8ADA6), popover: _c, border: Color(0xFF2A1212),
          strokeSoft: Color(0xFF2A1212), midground: _c, destructive: Color(0xFFEE1C1C), success: _c, warning: _c,
          info: _c, sidebar: _c, sidebarBorder: _c, userBubble: _c, userBubbleBorder: _c, codeBg: Color(0xFF0D0606),
          monoFamily: 'JetBrains Mono',
        ),
      ],
    );

Widget _host(String md) => MaterialApp(
      theme: _theme(),
      home: Scaffold(body: SingleChildScrollView(child: MarkdownView(md))),
    );

const _done = '''Lihat:

```visual
{"type": "graph", "title": "Star vs graf kamu", "nodes": ["A", "B"], "edges": [["A", "B"]]}
```
''';

const _open = '''Lihat:

```visual
{"type": "graph", "title": "Star vs graf kamu", "nodes": [''';

void main() {
  tearDown(() => DiagramBlock.debugPreviewBuilder = null);

  test('diagramKindFor knows ```visual', () {
    expect(diagramKindFor('visual', '{}'), DiagramKind.visual);
    expect(diagramKindFor('Visual', '<svg></svg>'), DiagramKind.visual);
  });

  test('visualPartialTitle reads JSON and header titles', () {
    expect(visualPartialTitle('{"type":"bar","title":"Ukuran \\"bundel\\"", "data": ['), 'Ukuran "bundel"');
    expect(visualPartialTitle('judul: Alur login\n<svg'), 'Alur login');
    expect(visualPartialTitle('{"type":"bar","tit'), isNull);
  });

  testWidgets('streaming fence shows the drawing placeholder with the title', (t) async {
    DiagramBlock.debugPreviewBuilder = (c, code, kind, full, onResult) => const SizedBox();
    await t.pumpWidget(_host(_open));
    expect(find.byType(VisualBlock), findsOneWidget);
    expect(find.byKey(const ValueKey('visual-drawing')), findsOneWidget);
    expect(find.text('Star vs graf kamu'), findsOneWidget);
    expect(find.text('Menggambar…'), findsOneWidget);
  });

  testWidgets('finished card shows title and caption from the renderer', (t) async {
    DiagramKind? seen;
    DiagramBlock.debugPreviewBuilder = (c, code, kind, full, onResult) {
      seen = kind;
      WidgetsBinding.instance.addPostFrameCallback(
          (_) => onResult(const DiagramRenderResult.ok(220, title: 'Star vs graf kamu', caption: '✓ Star: satu pusat')));
      return const SizedBox(key: ValueKey('fake-preview'));
    };
    await t.pumpWidget(_host(_done));
    await t.pumpAndSettle();
    expect(seen, DiagramKind.visual);
    expect(find.byKey(const ValueKey('fake-preview')), findsOneWidget);
    expect(find.text('Star vs graf kamu'), findsOneWidget);
    expect(find.text('✓ Star: satu pusat'), findsOneWidget);
    expect(find.byKey(const ValueKey('visual-drawing')), findsNothing);
  });

  testWidgets('menu toggles to the code view', (t) async {
    DiagramBlock.debugPreviewBuilder = (c, code, kind, full, onResult) {
      WidgetsBinding.instance.addPostFrameCallback((_) => onResult(const DiagramRenderResult.ok(200, title: 'T')));
      return const SizedBox();
    };
    await t.pumpWidget(_host(_done));
    await t.pumpAndSettle();
    await t.tap(find.byKey(const ValueKey('visual-menu')));
    await t.pumpAndSettle();
    expect(find.text('Simpan PNG'), findsOneWidget);
    expect(find.text('Bagikan SVG'), findsOneWidget);
    await t.tap(find.text('Lihat kode'));
    await t.pumpAndSettle();
    expect(find.byType(CodeBlock), findsOneWidget);
  });

  testWidgets('render failure falls back to the code', (t) async {
    DiagramBlock.debugPreviewBuilder = (c, code, kind, full, onResult) {
      WidgetsBinding.instance.addPostFrameCallback((_) => onResult(const DiagramRenderResult.failed('unknown type')));
      return const SizedBox();
    };
    await t.pumpWidget(_host(_done));
    await t.pumpAndSettle();
    expect(find.byKey(const ValueKey('visual-failed')), findsOneWidget);
    expect(find.byType(CodeBlock), findsOneWidget);
  });

  group('old ```mermaid / ```diagram blocks in the visual style', () {
    const flow = '''Alur:

```mermaid
---
title: Alur login
---
flowchart TD
  A([Mulai]) --> B{Benar?}
  B -->|Ya| C[Masuk]
```
''';

    test('which fences convert', () {
      expect(mermaidDrawsAsVisual('flowchart TD\n A-->B'), isTrue);
      expect(mermaidDrawsAsVisual('%%{init: {}}%%\nsequenceDiagram\n A->>B: x'), isTrue);
      expect(mermaidDrawsAsVisual('---\ntitle: x\n---\ntimeline\n 2026 : a'), isTrue);
      expect(mermaidDrawsAsVisual('classDiagram\n A <|-- B'), isFalse);
      expect(mermaidDrawsAsVisual('erDiagram\n A ||--o{ B : x'), isFalse);
      expect(diagramKindFor('diagram', 'flowchart TD\n A-->B'), DiagramKind.mermaid);
      expect(diagramKindFor('diagram', '{"type": "bar"}'), DiagramKind.visual);
      expect(diagramKindFor('diagram', 'title: x\n---\n<svg viewBox="0 0 1 1"></svg>'), DiagramKind.visual);
      expect(mermaidPartialTitle('---\ntitle: Alur login\n---\nflowchart TD'), 'Alur login');
      expect(mermaidPartialTitle('sequenceDiagram\n  title Login\n A->>B: x'), 'Login');
      expect(mermaidPartialTitle('pie title "Bahasa"\n "a" : 1'), 'Bahasa');
      expect(mermaidPartialTitle('flowchart TD\n A-->B'), isNull);
    });

    testWidgets('a convertible mermaid fence becomes a visual card (mermaidVisual)', (t) async {
      DiagramKind? seen;
      DiagramBlock.debugPreviewBuilder = (c, code, kind, full, onResult) {
        seen = kind;
        WidgetsBinding.instance.addPostFrameCallback((_) => onResult(const DiagramRenderResult.ok(200, title: 'Alur login')));
        return const SizedBox(key: ValueKey('fake-preview'));
      };
      await t.pumpWidget(_host(flow));
      await t.pumpAndSettle();
      expect(find.byType(VisualBlock), findsOneWidget);
      expect(seen, DiagramKind.mermaidVisual);
      expect(find.byKey(const ValueKey('visual-card')), findsOneWidget);
      expect(find.text('Alur login'), findsOneWidget);
      expect(find.text('Pratinjau'), findsNothing);
    });

    testWidgets('streaming mermaid shows the drawing placeholder with its title', (t) async {
      DiagramBlock.debugPreviewBuilder = (c, code, kind, full, onResult) => const SizedBox();
      await t.pumpWidget(_host('Alur:\n\n```mermaid\n---\ntitle: Alur login\n---\nflowchart TD\n  A --> '));
      await t.pump();
      expect(find.byKey(const ValueKey('visual-drawing')), findsOneWidget);
      expect(find.text('Alur login'), findsOneWidget);
    });

    testWidgets('untitled mermaid gets the "Diagram" heading', (t) async {
      DiagramBlock.debugPreviewBuilder = (c, code, kind, full, onResult) {
        WidgetsBinding.instance.addPostFrameCallback((_) => onResult(const DiagramRenderResult.ok(120)));
        return const SizedBox();
      };
      await t.pumpWidget(_host('```mermaid\nflowchart LR\n  A --> B\n```\n'));
      await t.pumpAndSettle();
      expect(find.text('Diagram'), findsOneWidget);
    });

    testWidgets('syntax the converter rejects falls back to the classic mermaid block', (t) async {
      final kinds = <DiagramKind>[];
      DiagramBlock.debugPreviewBuilder = (c, code, kind, full, onResult) {
        kinds.add(kind);
        WidgetsBinding.instance.addPostFrameCallback((_) => onResult(kind == DiagramKind.mermaidVisual
            ? const DiagramRenderResult.failed('unsupported mermaid')
            : const DiagramRenderResult.ok(140)));
        return Text('RENDERED ${kind.name}');
      };
      await t.pumpWidget(_host('```mermaid\nflowchart TD\n  subgraph X\n  A --> B\n  end\n```\n'));
      await t.pumpAndSettle();
      expect(kinds.first, DiagramKind.mermaidVisual);
      expect(find.text('RENDERED mermaid'), findsOneWidget);
      expect(find.text('Pratinjau'), findsOneWidget);
      expect(find.byKey(const ValueKey('visual-card')), findsNothing);
    });

    testWidgets('without a WebView it shows the classic block with its code', (t) async {
      await t.pumpWidget(_host(flow));
      await t.pumpAndSettle();
      expect(find.byType(DiagramBlock), findsOneWidget);
      expect(find.text('gagal dirender — menampilkan kode'), findsOneWidget);
    });

    testWidgets('the menu switches to the original mermaid style and back', (t) async {
      DiagramBlock.debugPreviewBuilder = (c, code, kind, full, onResult) {
        WidgetsBinding.instance.addPostFrameCallback((_) => onResult(const DiagramRenderResult.ok(140)));
        return Text('RENDERED ${kind.name}');
      };
      await t.pumpWidget(_host(flow));
      await t.pumpAndSettle();
      await t.tap(find.byKey(const ValueKey('visual-menu')));
      await t.pumpAndSettle();
      await t.tap(find.text('Gaya Mermaid asli'));
      await t.pumpAndSettle();
      expect(find.byKey(const ValueKey('visual-classic')), findsOneWidget);
      expect(find.text('RENDERED mermaid'), findsOneWidget);
      await t.tap(find.byKey(const ValueKey('visual-new-style')));
      await t.pumpAndSettle();
      expect(find.byKey(const ValueKey('visual-card')), findsOneWidget);
      expect(find.text('RENDERED mermaidVisual'), findsOneWidget);
    });
  });
}
