// Compact Markdown renderer for transcripts, previews and minutes:
// headings, paragraphs, lists (incl. task boxes), quotes, rules, tables and
// fenced code with syntax highlighting (package:highlight). Inline: bold,
// italic, `code`, ~~strike~~, [links](url) and bare URLs. Soft newlines stay
// soft; two trailing spaces make a hard break (Markdown semantics, as
// Desktop documents).
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:highlight/highlight.dart' show highlight, Node;
import 'package:highlight/languages/all.dart' show allLanguages;

import '../../theme/app_theme.dart';
import '../../remote/ui/glass/liquid_glass.dart' show GlassCode, GlassForeground;
import 'markdown_table_normalize.dart';

typedef LinkTap = void Function(String url);

class MarkdownView extends StatelessWidget {
  const MarkdownView(this.data, {super.key, this.onLink, this.scale = 1.0, this.selectable = true});
  final String data;
  final LinkTap? onLink;
  final double scale;
  final bool selectable;

  @override
  Widget build(BuildContext context) {
    final blocks = _parse(data);
    final children = <Widget>[];
    for (var i = 0; i < blocks.length; i++) {
      children.add(_build(context, blocks[i]));
      if (i < blocks.length - 1) children.add(SizedBox(height: 8 * scale));
    }
    final col = Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: children);
    return selectable ? SelectionArea(child: col) : col;
  }

  TextStyle _base(BuildContext c) => (c.tt.bodyMedium ?? const TextStyle()).copyWith(fontSize: 14.5 * scale, height: 1.55);

  Widget _build(BuildContext context, _Block b) {
    final base = _base(context);
    switch (b.kind) {
      case _K.heading:
        final sizes = [22.0, 19.0, 17.0, 15.5, 14.5, 14.0];
        return Padding(
          padding: EdgeInsets.only(top: 4 * scale),
          child: Text.rich(
            TextSpan(children: inline(context, b.text, base.copyWith(fontSize: sizes[b.level - 1] * scale, fontWeight: FontWeight.w700, height: 1.3))),
          ),
        );
      case _K.code:
        return CodeBlock(code: b.text, language: b.lang, scale: scale);
      case _K.rule:
        return Divider(color: context.hc.strokeSoft, height: 12);
      case _K.quote:
        return Container(
          padding: EdgeInsets.only(left: 12 * scale),
          decoration: BoxDecoration(border: Border(left: BorderSide(color: context.hc.border, width: 3))),
          child: MarkdownView(b.text, onLink: onLink, scale: scale, selectable: false),
        );
      case _K.list:
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            for (var i = 0; i < b.items.length; i++)
              Padding(
                padding: EdgeInsets.only(left: 4 + b.items[i].indent * 14.0, bottom: 3 * scale),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  SizedBox(
                    width: 22 * scale,
                    child: b.items[i].task != null
                        ? Padding(
                            padding: EdgeInsets.only(top: 3 * scale),
                            child: Icon(b.items[i].task! ? Icons.check_box_outlined : Icons.check_box_outline_blank,
                                size: 16 * scale, color: context.hc.mutedForeground),
                          )
                        : Text(b.ordered ? '${b.items[i].number}.' : '•',
                            style: base.copyWith(color: context.hc.mutedForeground, fontWeight: FontWeight.w600)),
                  ),
                  Expanded(child: Text.rich(TextSpan(children: inline(context, b.items[i].text, base)))),
                ]),
              ),
          ],
        );
      case _K.table:
        return _table(context, b, base);
      case _K.para:
        return Text.rich(TextSpan(children: inline(context, b.text, base)));
    }
  }

  Widget _table(BuildContext context, _Block b, TextStyle base) {
    final rows = b.rows;
    if (rows.isEmpty) return const SizedBox.shrink();
    final cols = rows.map((r) => r.length).reduce((a, c) => a > c ? a : c);
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Container(
        decoration: BoxDecoration(border: Border.all(color: context.hc.strokeSoft), borderRadius: BorderRadius.circular(6)),
        child: Table(
          defaultColumnWidth: const IntrinsicColumnWidth(),
          border: TableBorder.symmetric(inside: BorderSide(color: context.hc.strokeSoft)),
          children: [
            for (var r = 0; r < rows.length; r++)
              TableRow(
                decoration: r == 0 ? BoxDecoration(color: context.hc.muted) : null,
                children: [
                  for (var c = 0; c < cols; c++)
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                      // Long cells wrap instead of making one very wide column;
                      // the table itself scrolls sideways.
                      child: ConstrainedBox(
                        constraints: BoxConstraints(maxWidth: 280 * scale),
                        child: Text.rich(TextSpan(
                          children: inline(context, c < rows[r].length ? rows[r][c] : '',
                              r == 0 ? base.copyWith(fontWeight: FontWeight.w600, fontSize: 13.5 * scale) : base.copyWith(fontSize: 13.5 * scale)))),
                      ),
                    ),
                ],
              ),
          ],
        ),
      ),
    );
  }

  List<InlineSpan> inline(BuildContext context, String text, TextStyle style) {
    final spans = <InlineSpan>[];
    final re = RegExp(
        r'(`[^`]+`)|(\*\*[^*]+\*\*)|(__[^_]+__)|(~~[^~]+~~)|(\*[^*\s][^*]*\*)|(\b_[^_\s][^_]*_\b)|(\[[^\]]+\]\([^)\s]+\))|(https?://[^\s<>()]+[^\s<>().,;:!?])|(  \n)');
    var last = 0;
    for (final m in re.allMatches(text)) {
      if (m.start > last) spans.add(TextSpan(text: text.substring(last, m.start).replaceAll('\n', ' '), style: style));
      final s = m.group(0)!;
      if (m.group(1) != null) {
        spans.add(WidgetSpan(
          alignment: PlaceholderAlignment.baseline,
          baseline: TextBaseline.alphabetic,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 1),
            decoration: BoxDecoration(color: context.hc.codeBg, borderRadius: BorderRadius.circular(4)),
            child: Text(s.substring(1, s.length - 1), style: monoStyle(context, size: (style.fontSize ?? 14) * 0.88)),
          ),
        ));
      } else if (m.group(2) != null || m.group(3) != null) {
        spans.addAll(inline(context, s.substring(2, s.length - 2), style.copyWith(fontWeight: FontWeight.w700)));
      } else if (m.group(4) != null) {
        spans.add(TextSpan(text: s.substring(2, s.length - 2), style: style.copyWith(decoration: TextDecoration.lineThrough)));
      } else if (m.group(5) != null || m.group(6) != null) {
        spans.addAll(inline(context, s.substring(1, s.length - 1), style.copyWith(fontStyle: FontStyle.italic)));
      } else if (m.group(7) != null) {
        final lm = RegExp(r'^\[([^\]]+)\]\(([^)\s]+)\)$').firstMatch(s)!;
        spans.add(_link(context, lm.group(1)!, lm.group(2)!, style));
      } else if (m.group(8) != null) {
        spans.add(_link(context, s, s, style));
      } else {
        spans.add(TextSpan(text: '\n', style: style));
      }
      last = m.end;
    }
    if (last < text.length) spans.add(TextSpan(text: text.substring(last).replaceAll('\n', ' '), style: style));
    return spans;
  }

  InlineSpan _link(BuildContext context, String label, String url, TextStyle style) => TextSpan(
        text: label,
        style: style.copyWith(color: context.cs.primary, decoration: TextDecoration.underline, decorationColor: context.cs.primary.withValues(alpha: 0.4)),
        recognizer: onLink == null ? null : (TapGestureRecognizer()..onTap = () => onLink!(url)),
      );
}

class CodeBlock extends StatelessWidget {
  const CodeBlock({super.key, required this.code, this.language, this.scale = 1.0});
  final String code;
  final String? language;
  final double scale;

  @override
  Widget build(BuildContext context) {
    // Inside liquid glass (phone remote): a darker glass with light text.
    final g = GlassForeground.maybeOf(context);
    if (g != null && !g.isCode) return GlassCode(child: Builder(builder: _build));
    return _build(context);
  }

  Widget _build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    final base = monoStyle(context, size: 12.5 * scale, color: context.cs.onSurface);
    List<TextSpan> spans;
    try {
      final lang = _langAlias(language);
      final res = lang == null ? highlight.parse(code, autoDetection: true) : highlight.parse(code, language: lang);
      spans = _convert(res.nodes ?? [], dark ? _darkTheme : _lightTheme);
    } catch (_) {
      spans = [TextSpan(text: code)];
    }
    return Container(
      decoration: BoxDecoration(
        color: context.hc.codeBg,
        border: Border.all(color: context.hc.strokeSoft),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Container(
          padding: const EdgeInsets.only(left: 12, right: 2),
          decoration: BoxDecoration(border: Border(bottom: BorderSide(color: context.hc.strokeSoft))),
          child: Row(children: [
            Text(language?.isNotEmpty == true ? language! : 'kode', style: monoStyle(context, size: 11, color: context.hc.mutedForeground)),
            const Spacer(),
            IconButton(
              iconSize: 15,
              visualDensity: VisualDensity.compact,
              tooltip: 'Salin kode',
              icon: const Icon(Icons.copy_rounded),
              onPressed: () {
                Clipboard.setData(ClipboardData(text: code));
                ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Kode disalin'), duration: Duration(seconds: 1)));
              },
            ),
          ]),
        ),
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          padding: const EdgeInsets.all(12),
          child: Text.rich(TextSpan(style: base, children: spans), softWrap: false),
        ),
      ]),
    );
  }

  static String? _langAlias(String? l) {
    if (l == null || l.trim().isEmpty) return null;
    final s = l.trim().toLowerCase();
    const alias = {
      'js': 'javascript', 'ts': 'typescript', 'py': 'python', 'sh': 'bash', 'shell': 'bash', 'zsh': 'bash',
      'yml': 'yaml', 'kt': 'kotlin', 'md': 'markdown', 'html': 'xml', 'jsx': 'javascript', 'tsx': 'typescript',
      'c++': 'cpp', 'rs': 'rust', 'golang': 'go', 'dockerfile': 'dockerfile', 'console': 'bash',
    };
    final v = alias[s] ?? s;
    return allLanguages.containsKey(v) ? v : null;
  }

  List<TextSpan> _convert(List<Node> nodes, Map<String, TextStyle> theme) {
    final out = <TextSpan>[];
    void walk(Node n, List<TextSpan> into) {
      if (n.value != null) {
        into.add(n.className == null ? TextSpan(text: n.value) : TextSpan(text: n.value, style: theme[n.className]));
      } else if (n.children != null) {
        final kids = <TextSpan>[];
        for (final c in n.children!) {
          walk(c, kids);
        }
        into.add(TextSpan(children: kids, style: theme[n.className]));
      }
    }

    for (final n in nodes) {
      walk(n, out);
    }
    return out;
  }
}

const _darkTheme = <String, TextStyle>{
  'keyword': TextStyle(color: Color(0xFFFF7B72)),
  'built_in': TextStyle(color: Color(0xFFFFA657)),
  'type': TextStyle(color: Color(0xFFFFA657)),
  'literal': TextStyle(color: Color(0xFF79C0FF)),
  'number': TextStyle(color: Color(0xFF79C0FF)),
  'string': TextStyle(color: Color(0xFFA5D6FF)),
  'comment': TextStyle(color: Color(0xFF8B949E), fontStyle: FontStyle.italic),
  'title': TextStyle(color: Color(0xFFD2A8FF)),
  'function': TextStyle(color: Color(0xFFD2A8FF)),
  'attr': TextStyle(color: Color(0xFF79C0FF)),
  'attribute': TextStyle(color: Color(0xFF79C0FF)),
  'meta': TextStyle(color: Color(0xFF8B949E)),
  'tag': TextStyle(color: Color(0xFF7EE787)),
  'name': TextStyle(color: Color(0xFF7EE787)),
  'variable': TextStyle(color: Color(0xFFFFA657)),
  'params': TextStyle(color: Color(0xFFC9D1D9)),
  'symbol': TextStyle(color: Color(0xFF79C0FF)),
  'section': TextStyle(color: Color(0xFF1F6FEB), fontWeight: FontWeight.bold),
  'addition': TextStyle(color: Color(0xFF7EE787)),
  'deletion': TextStyle(color: Color(0xFFFFA198)),
};

const _lightTheme = <String, TextStyle>{
  'keyword': TextStyle(color: Color(0xFFCF222E)),
  'built_in': TextStyle(color: Color(0xFF953800)),
  'type': TextStyle(color: Color(0xFF953800)),
  'literal': TextStyle(color: Color(0xFF0550AE)),
  'number': TextStyle(color: Color(0xFF0550AE)),
  'string': TextStyle(color: Color(0xFF0A3069)),
  'comment': TextStyle(color: Color(0xFF6E7781), fontStyle: FontStyle.italic),
  'title': TextStyle(color: Color(0xFF8250DF)),
  'function': TextStyle(color: Color(0xFF8250DF)),
  'attr': TextStyle(color: Color(0xFF0550AE)),
  'attribute': TextStyle(color: Color(0xFF0550AE)),
  'meta': TextStyle(color: Color(0xFF6E7781)),
  'tag': TextStyle(color: Color(0xFF116329)),
  'name': TextStyle(color: Color(0xFF116329)),
  'variable': TextStyle(color: Color(0xFF953800)),
  'symbol': TextStyle(color: Color(0xFF0550AE)),
  'section': TextStyle(color: Color(0xFF0550AE), fontWeight: FontWeight.bold),
  'addition': TextStyle(color: Color(0xFF116329)),
  'deletion': TextStyle(color: Color(0xFF82071E)),
};

// ------------------------------------------------------------------ parser --

enum _K { heading, para, code, list, quote, rule, table }

class _Item {
  final String text;
  final int indent;
  final bool? task;
  final int number;
  _Item(this.text, this.indent, this.task, this.number);
}

class _Block {
  final _K kind;
  String text;
  int level;
  String? lang;
  bool ordered;
  final List<_Item> items = [];
  final List<List<String>> rows = [];
  _Block(this.kind, {this.text = '', this.level = 1, this.lang, this.ordered = false});
}

List<_Block> _parse(String src) {
  // One-line tables (common with some models while streaming) are put back
  // on separate lines first, so they render as a scrollable table.
  final lines = normalizeMarkdownTables(src.replaceAll('\r\n', '\n')).split('\n');
  final out = <_Block>[];
  var i = 0;
  final listRe = RegExp(r'^(\s*)([-*+]|\d+[.)])\s+(\[[ xX]\]\s+)?(.*)$');
  while (i < lines.length) {
    final line = lines[i];
    final t = line.trimLeft();
    if (t.isEmpty) {
      i++;
      continue;
    }
    if (t.startsWith('```') || t.startsWith('~~~')) {
      final fence = t.substring(0, 3);
      final lang = t.substring(3).trim();
      final buf = <String>[];
      i++;
      while (i < lines.length && !lines[i].trimLeft().startsWith(fence)) {
        buf.add(lines[i]);
        i++;
      }
      i++; // closing fence (or EOF while streaming)
      out.add(_Block(_K.code, text: buf.join('\n'), lang: lang));
      continue;
    }
    final h = RegExp(r'^(#{1,6})\s+(.*)$').firstMatch(t);
    if (h != null) {
      out.add(_Block(_K.heading, text: h.group(2)!.replaceAll(RegExp(r'\s#+$'), ''), level: h.group(1)!.length));
      i++;
      continue;
    }
    if (RegExp(r'^([-*_])(\s*\1){2,}\s*$').hasMatch(t)) {
      out.add(_Block(_K.rule));
      i++;
      continue;
    }
    if (t.startsWith('>')) {
      final buf = <String>[];
      while (i < lines.length && lines[i].trimLeft().startsWith('>')) {
        buf.add(lines[i].trimLeft().replaceFirst(RegExp(r'^>\s?'), ''));
        i++;
      }
      out.add(_Block(_K.quote, text: buf.join('\n')));
      continue;
    }
    if (t.startsWith('|') && i + 1 < lines.length && RegExp(r'^\s*\|?\s*:?-{2,}').hasMatch(lines[i + 1])) {
      final b = _Block(_K.table);
      List<String> cells(String l) {
        var s = l.trim();
        if (s.startsWith('|')) s = s.substring(1);
        if (s.endsWith('|')) s = s.substring(0, s.length - 1);
        return s.split('|').map((c) => c.trim()).toList();
      }

      b.rows.add(cells(t));
      i += 2;
      while (i < lines.length && lines[i].trimLeft().startsWith('|')) {
        b.rows.add(cells(lines[i]));
        i++;
      }
      out.add(b);
      continue;
    }
    final lm = listRe.firstMatch(line);
    if (lm != null) {
      final ordered = RegExp(r'\d').hasMatch(lm.group(2)!);
      final b = _Block(_K.list, ordered: ordered);
      var n = 1;
      while (i < lines.length) {
        final m = listRe.firstMatch(lines[i]);
        if (m == null) {
          // continuation line of the previous item
          if (lines[i].trim().isNotEmpty && lines[i].startsWith('  ') && b.items.isNotEmpty) {
            final prev = b.items.removeLast();
            b.items.add(_Item('${prev.text} ${lines[i].trim()}', prev.indent, prev.task, prev.number));
            i++;
            continue;
          }
          break;
        }
        final box = m.group(3);
        final num = int.tryParse(m.group(2)!.replaceAll(RegExp(r'[.)]'), '')) ?? n;
        b.items.add(_Item(m.group(4)!, (m.group(1)!.length / 2).floor(), box?.toLowerCase().contains('x'), num));
        n++;
        i++;
      }
      out.add(b);
      continue;
    }
    final buf = <String>[];
    while (i < lines.length) {
      final l = lines[i];
      final lt = l.trimLeft();
      if (lt.isEmpty || lt.startsWith('```') || lt.startsWith('#') || lt.startsWith('>') || listRe.hasMatch(l) || (lt.startsWith('|') && buf.isEmpty)) {
        break;
      }
      buf.add(l.endsWith('  ') ? '${l.trimRight()}  ' : l.trim());
      i++;
    }
    if (buf.isEmpty) {
      buf.add(lines[i]);
      i++;
    }
    out.add(_Block(_K.para, text: buf.join('\n')));
  }
  return out;
}
