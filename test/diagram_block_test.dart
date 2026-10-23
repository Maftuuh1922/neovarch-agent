import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:neovarch_agent/theme/app_theme.dart';
import 'package:neovarch_agent/ui/widgets/diagram_block.dart';
import 'package:neovarch_agent/ui/widgets/markdown_view.dart';

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

// A diagram type without a ```visual equivalent keeps the classic block
// (flowcharts, sequences, timelines … now draw as visual cards, see
// visual_block_test.dart).
const _mermaid = '''Struktur:

```mermaid
classDiagram
  Pemilik <|-- Agent
```

selesai''';

void main() {
  tearDown(() => DiagramBlock.debugPreviewBuilder = null);

  test('diagramKindFor picks mermaid, svg and inline svg', () {
    expect(diagramKindFor('mermaid', 'graph TD; A-->B'), DiagramKind.mermaid);
    expect(diagramKindFor('svg', '<svg></svg>'), DiagramKind.svg);
    expect(diagramKindFor('', '<svg viewBox="0 0 1 1"><rect/></svg>'), DiagramKind.svg);
    expect(diagramKindFor('xml', '<?xml version="1.0"?>\n<svg><g/></svg>'), DiagramKind.svg);
    expect(diagramKindFor('', 'Pemilik\n  ↓\nAgent'), isNull);
    expect(diagramKindFor('dart', 'void main() {}'), isNull);
  });

  test('diagramKindFor previews whole html documents only', () {
    const page = '<!doctype html>\n<html><head><style>:root{--bg:#fff}</style></head><body>Hai</body></html>\n';
    expect(diagramKindFor('html', page), DiagramKind.html);
    expect(diagramKindFor('html', '<!-- artifact -->\n<html lang="id"><body></body></html>'), DiagramKind.html);
    expect(diagramKindFor('html', '<div class="card">Hai</div>'), isNull);
    expect(diagramKindFor('', page), isNull);
    expect(looksLikeHtmlDocument('<!DOCTYPE html><html></html>'), isTrue);
    expect(looksLikeHtmlDocument('<html><body>'), isFalse);
  });

  testWidgets('mermaid block defaults to Pratinjau and toggles to Kode', (t) async {
    DiagramBlock.debugPreviewBuilder = (ctx, code, kind, full, onResult) {
      WidgetsBinding.instance.addPostFrameCallback((_) => onResult(const DiagramRenderResult.ok(160)));
      return Text('RENDERED ${kind.name}', key: const ValueKey('fake-preview'));
    };
    await t.pumpWidget(_host(_mermaid));
    await t.pumpAndSettle();

    expect(find.text('Pratinjau'), findsOneWidget);
    expect(find.text('Kode'), findsOneWidget);
    expect(find.text('RENDERED mermaid'), findsOneWidget);
    expect(find.textContaining('classDiagram'), findsNothing);
    expect(find.byKey(const ValueKey('diagram-failed')), findsNothing);

    await t.tap(find.text('Kode'));
    await t.pumpAndSettle();
    expect(find.textContaining('classDiagram'), findsOneWidget);
    expect(find.byTooltip('Salin kode'), findsOneWidget);

    await t.tap(find.text('Pratinjau'));
    await t.pumpAndSettle();
    expect(find.textContaining('classDiagram'), findsNothing);
  });

  testWidgets('render error falls back to Kode with a note', (t) async {
    DiagramBlock.debugPreviewBuilder = (ctx, code, kind, full, onResult) {
      WidgetsBinding.instance.addPostFrameCallback((_) => onResult(const DiagramRenderResult.failed('Parse error on line 2')));
      return const SizedBox();
    };
    await t.pumpWidget(_host(_mermaid));
    await t.pumpAndSettle();
    expect(find.byKey(const ValueKey('diagram-failed')), findsOneWidget);
    expect(find.text('gagal dirender — menampilkan kode'), findsOneWidget);
    expect(find.textContaining('classDiagram'), findsOneWidget);
  });

  testWidgets('without a WebView (desktop/test host) it shows the code with the note', (t) async {
    await t.pumpWidget(_host(_mermaid));
    await t.pumpAndSettle();
    expect(find.text('gagal dirender — menampilkan kode'), findsOneWidget);
    expect(find.textContaining('classDiagram'), findsOneWidget);
  });

  testWidgets('while streaming it shows Kode, then flips to Pratinjau when the fence closes', (t) async {
    var renders = 0;
    DiagramBlock.debugPreviewBuilder = (ctx, code, kind, full, onResult) {
      renders++;
      WidgetsBinding.instance.addPostFrameCallback((_) => onResult(const DiagramRenderResult.ok(120)));
      return const Text('RENDERED');
    };
    await t.pumpWidget(_host('Lihat:\n\n```mermaid\nclassDiagram'));
    await t.pumpAndSettle();
    expect(find.text('Pratinjau'), findsOneWidget);
    expect(find.byKey(const ValueKey('diagram-streaming')), findsOneWidget);
    expect(find.text('RENDERED'), findsNothing);
    expect(find.textContaining('classDiagram'), findsOneWidget);
    // Pratinjau is disabled until the block is complete.
    await t.tap(find.text('Pratinjau'));
    await t.pumpAndSettle();
    expect(find.text('RENDERED'), findsNothing);

    await t.pumpWidget(_host('Lihat:\n\n```mermaid\nclassDiagram\n  A <|-- B'));
    await t.pumpAndSettle();
    expect(find.textContaining('A <|-- B'), findsOneWidget);
    expect(renders, 0);

    await t.pumpWidget(_host('Lihat:\n\n```mermaid\nclassDiagram\n  A <|-- B\n```\n\nSelesai'));
    await t.pumpAndSettle();
    expect(find.byKey(const ValueKey('diagram-streaming')), findsNothing);
    expect(find.text('RENDERED'), findsOneWidget);
    expect(find.textContaining('A <|-- B'), findsNothing);
    expect(renders, greaterThan(0));
  });

  testWidgets('fullscreen opens from the preview and has copy', (t) async {
    DiagramBlock.debugPreviewBuilder = (ctx, code, kind, full, onResult) {
      WidgetsBinding.instance.addPostFrameCallback((_) => onResult(const DiagramRenderResult.ok(120)));
      return Text(full ? 'FULL' : 'INLINE');
    };
    await t.pumpWidget(_host(_mermaid));
    await t.pumpAndSettle();
    await t.tap(find.byTooltip('Layar penuh'));
    await t.pumpAndSettle();
    expect(find.text('FULL'), findsOneWidget);
    expect(find.byTooltip('Salin kode'), findsWidgets);
  });

  testWidgets('```svg and raw inline <svg> render as diagrams', (t) async {
    final kinds = <DiagramKind>[];
    DiagramBlock.debugPreviewBuilder = (ctx, code, kind, full, onResult) {
      kinds.add(kind);
      WidgetsBinding.instance.addPostFrameCallback((_) => onResult(const DiagramRenderResult.ok(120)));
      return const Text('RENDERED');
    };
    await t.pumpWidget(_host('A\n\n```svg\n<svg viewBox="0 0 10 10"><rect width="5" height="5"/></svg>\n```\n\n'
        'B\n\n<svg viewBox="0 0 4 4">\n  <circle r="2"/>\n</svg>\n\nC'));
    await t.pumpAndSettle();
    expect(find.text('Pratinjau'), findsNWidgets(2));
    expect(kinds.toSet(), {DiagramKind.svg});
    expect(find.text('C'), findsOneWidget);
  });

  testWidgets('ordinary code blocks are untouched', (t) async {
    await t.pumpWidget(_host('```\nPemilik Kantor (kamu)\n   ↓\nNeovarch Agent\n```'));
    await t.pumpAndSettle();
    expect(find.text('Pratinjau'), findsNothing);
    expect(find.text('kode'), findsOneWidget);
  });
}
