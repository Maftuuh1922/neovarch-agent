// v1.4.7: one-line Markdown tables (header, delimiter and rows on a single
// line, as streamed by some models) render as a sideways-scrollable table.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:neovarch_agent/remote/ui/remote_app.dart' show neovarchMobileTheme;
import 'package:neovarch_agent/ui/widgets/markdown_table_normalize.dart';
import 'package:neovarch_agent/ui/widgets/markdown_view.dart';

const _oneLine =
    '2. Soal "mimo 2.5" — ketiga rute mati di hulunya: | Rute | Error | Perbaikan | |---|---|---| | `mimo/mimo-v2.5` | 401 Invalid API Key | isi API key | | `op-p/mimo-v2.5` | 402 saldo \$0 | top up | | `mimo/mimo-v2.6-flash` | 403 membership habis | berlangganan |';

void main() {
  test('one-line table → header, delimiter, rows; prose kept apart', () {
    expect(normalizeMarkdownTables(_oneLine).split('\n'), [
      '2. Soal "mimo 2.5" — ketiga rute mati di hulunya:',
      '',
      '| Rute | Error | Perbaikan |',
      '| --- | --- | --- |',
      '| `mimo/mimo-v2.5` | 401 Invalid API Key | isi API key |',
      '| `op-p/mimo-v2.5` | 402 saldo \$0 | top up |',
      '| `mimo/mimo-v2.6-flash` | 403 membership habis | berlangganan |',
    ]);
  });

  test('text after the table, code-span pipes, escaped pipes', () {
    expect(normalizeMarkdownTables('| a | b | |:--|--:| | 1 | 2 | Jadi begitu.').split('\n'),
        ['| a | b |', '| :-- | --: |', '| 1 | 2 |', '', 'Jadi begitu.']);
    expect(normalizeMarkdownTables(r'| cmd | arti | |---|---| | `a | b` | pipa \| literal |').split('\n'),
        ['| cmd | arti |', '| --- | --- |', '| `a | b` | pipa \\| literal |']);
  });

  test('streaming: untouched before the delimiter is complete; a half row is kept', () {
    expect(normalizeMarkdownTables('Tabel: | a | b | |-'), 'Tabel: | a | b | |-');
    expect(normalizeMarkdownTables('| a | b | |---|---| | 1 | 2 | | 3').split('\n'),
        ['| a | b |', '| --- | --- |', '| 1 | 2 |', '| 3 |  |']);
  });

  test('prose on the header line, delimiter on the next', () {
    expect(normalizeMarkdownTables('Ringkasan: | a | b |\n|---|---|\n| 1 | 2 |').split('\n'),
        ['Ringkasan:', '', '| a | b |', '|---|---|', '| 1 | 2 |']);
  });

  test('proper tables, fences and plain pipes are left alone', () {
    const proper = '| a | b |\n|---|---|\n| 1 | 2 |';
    expect(normalizeMarkdownTables(proper), proper);
    const fenced = '```\n| a | b | |---|---| | 1 | 2 |\n```';
    expect(normalizeMarkdownTables(fenced), fenced);
    expect(normalizeMarkdownTables('pilih a | b saja'), 'pilih a | b saja');
  });

  Future<void> pumpMd(WidgetTester tester, String md) => tester.pumpWidget(MaterialApp(
        theme: neovarchMobileTheme,
        home: Scaffold(body: SizedBox(width: 360, child: SingleChildScrollView(child: MarkdownView(md)))),
      ));

  testWidgets('MarkdownView renders the one-line table as a horizontally scrollable Table', (tester) async {
    await pumpMd(tester, _oneLine);
    final table = find.byType(Table);
    expect(table, findsOneWidget);
    expect(tester.widget<Table>(table).children.length, 4); // header + 3 rows
    final scroller = find.ancestor(of: table, matching: find.byType(SingleChildScrollView)).first;
    expect(tester.widget<SingleChildScrollView>(scroller).scrollDirection, Axis.horizontal);
    expect(find.textContaining('|---|'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('streaming: each partial frame renders without errors', (tester) async {
    for (var n = 10; n <= _oneLine.length; n += 23) {
      await pumpMd(tester, _oneLine.substring(0, n));
      expect(tester.takeException(), isNull, reason: 'prefix $n');
    }
    await pumpMd(tester, _oneLine);
    expect(find.byType(Table), findsOneWidget);
  });
}
