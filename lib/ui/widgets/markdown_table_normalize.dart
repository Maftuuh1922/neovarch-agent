// Repair GFM tables that a model streamed onto a single line, e.g.
//
//   Rute ada 3: | Rute | Error | |---|---| | `a` | 401 | | `b` | 402 |
//
// A table is only a table when header, delimiter and rows sit on their own
// lines, so that used to render as a paragraph full of pipes. This finds an
// inline delimiter row (`|---|:--:|`), takes the header cells right before it
// and the body rows after it (split every N cells, N = delimiter columns) and
// puts them back on separate lines, with prose before/after kept apart.
// Also: "prose: | a | b |" on one line with the delimiter on the next.
//
// Streaming-safe: nothing changes until a complete delimiter row (≥ 2 columns)
// arrived; a half-received last row stays a row. Pipes inside `code` or
// escaped (`\|`) are not separators; fenced code is skipped.
//
// Same algorithm as desktop/apps/desktop/src/lib/markdown-table-normalize.ts —
// keep the two in step.

final _inlineDelim = RegExp(r'\|[ \t]*:?-{2,}:?[ \t]*(?:\|[ \t]*:?-{2,}:?[ \t]*)+\|');
final _delimLine = RegExp(r'^[ \t]*\|?[ \t]*:?-{2,}:?[ \t]*(?:\|[ \t]*:?-{2,}:?[ \t]*)+\|?[ \t]*$');
final _fence = RegExp(r'^[ \t]*(```|~~~)');

List<int> _pipePositions(String s) {
  final out = <int>[];
  var inCode = false;
  for (var i = 0; i < s.length; i++) {
    final ch = s[i];
    if (ch == r'\') {
      i++;
      continue;
    }
    if (ch == '`') {
      inCode = !inCode;
      continue;
    }
    if (ch == '|' && !inCode) out.add(i);
  }
  return out;
}

List<String> _splitCells(String s) {
  final out = <String>[];
  var last = 0;
  for (final p in _pipePositions(s)) {
    out.add(s.substring(last, p));
    last = p + 1;
  }
  out.add(s.substring(last));
  return out;
}

String _row(List<String> cells) => '| ${cells.map((c) => c.trim()).join(' | ')} |';

List<String> _delimCells(String d) {
  var s = d.trim();
  if (s.startsWith('|')) s = s.substring(1);
  if (s.endsWith('|')) s = s.substring(0, s.length - 1);
  return s.split('|').map((c) => c.trim()).toList();
}

({String prose, List<String> header})? _splitHeader(String pre, int n) {
  final t = pre.replaceFirst(RegExp(r'[ \t]+$'), '');
  final pos = _pipePositions(t);
  if (pos.length < n + 1) return null;
  if (pos.last != t.length - 1) return null;
  final start = pos[pos.length - 1 - n];
  final header = _splitCells(t.substring(start + 1, t.length - 1));
  if (header.length != n) return null;
  return (prose: t.substring(0, start).trim(), header: header);
}

({List<List<String>> rows, String tail}) _splitBody(String post, int n) {
  final tokens = _splitCells(post);
  final rows = <List<String>>[];
  if (tokens.isNotEmpty && tokens[0].trim().isNotEmpty) return (rows: rows, tail: post.trim());
  var i = 1;
  while (i < tokens.length) {
    if (tokens.length - i == 1) {
      // Right after a row gap ("| |"): the next row, still streaming in.
      if (tokens[i].trim().isNotEmpty) rows.add([tokens[i]]);
      return (rows: rows, tail: '');
    }
    final end = i + n < tokens.length ? i + n : tokens.length;
    rows.add(tokens.sublist(i, end));
    i += n;
    if (i >= tokens.length) break;
    if (tokens[i].trim().isNotEmpty) return (rows: rows, tail: tokens.sublist(i).join('|').trim());
    i++;
  }
  return (rows: rows, tail: '');
}

List<String>? _normalizeLine(String line, String? next) {
  final m = _inlineDelim.firstMatch(line);
  if (m != null && !_delimLine.hasMatch(line)) {
    final delim = m.group(0)!;
    final n = _delimCells(delim).length;
    final head = _splitHeader(line.substring(0, m.start), n);
    if (head == null) return null;
    final body = _splitBody(line.substring(m.end), n);
    final out = <String>[];
    if (head.prose.isNotEmpty) out.addAll([head.prose, '']);
    out.addAll([_row(head.header), _row(_delimCells(delim))]);
    for (final r in body.rows) {
      final cells = [...r];
      while (cells.length < n) {
        cells.add('');
      }
      out.add(_row(cells));
    }
    if (body.tail.isNotEmpty) {
      out.addAll(['', body.tail]);
    } else {
      out.add('');
    }
    return out;
  }
  if (next != null && _delimLine.hasMatch(next) && !line.trimLeft().startsWith('|')) {
    final head = _splitHeader(line, _delimCells(next).length);
    if (head == null || head.prose.isEmpty) return null;
    return [head.prose, '', _row(head.header)];
  }
  return null;
}

/// Puts one-line markdown tables back on separate lines (see file comment).
String normalizeMarkdownTables(String text) {
  if (!text.contains('|')) return text;
  final lines = text.split('\n');
  final out = <String>[];
  String? fence;
  var changed = false;
  for (var i = 0; i < lines.length; i++) {
    final line = lines[i];
    final f = _fence.firstMatch(line);
    if (f != null) {
      if (fence == null) {
        fence = f.group(1);
      } else if (f.group(1) == fence) {
        fence = null;
      }
      out.add(line);
      continue;
    }
    if (fence != null || !line.contains('|')) {
      out.add(line);
      continue;
    }
    final r = _normalizeLine(line, i + 1 < lines.length ? lines[i + 1] : null);
    if (r == null) {
      out.add(line);
      continue;
    }
    changed = true;
    if (out.isNotEmpty && out.last.trim().isNotEmpty && r.first.startsWith('|')) out.add('');
    out.addAll(r);
  }
  if (!changed) return text;
  if (out.isNotEmpty && out.last.isEmpty && lines.last.isNotEmpty) out.removeLast();
  return out.join('\n');
}
