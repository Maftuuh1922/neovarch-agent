// v1.4.8: Profil › Pemakaian token as a chart (the text list was too confusing):
// Hari ini | Sesi | Semua toggle over one big total, a split bar (masuk baru /
// cache / keluar add up to the total), a 14-day stacked trend, per-model bars,
// and the exact numbers behind "Angka lengkap". Older cores fall back.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:neovarch_agent/remote/ui/remote_app.dart' show neovarchMobileTheme;
import 'package:neovarch_agent/remote/ui/token_usage_panel.dart';
import 'package:neovarch_agent/theme/neovarch_mobile_theme.dart';

Map<String, dynamic> _full() => {
      'date': '2026-10-13',
      'since': '2026-10-01',
      'today': {'input': 1004000, 'output': 19000, 'cached': 858000, 'cache_write': 0, 'calls': 41},
      'session': {'input': 200000, 'output': 4000, 'cached': 150000, 'calls': 9},
      'lifetime': {'input': 5000000, 'output': 100000, 'cached': 4000000, 'calls': 300},
      'models': [
        {'model': 'oc/mimo-v2.6-flash-free', 'input': 4000000, 'output': 80000, 'cached': 3500000, 'calls': 250},
        {'model': 'gpt-5-mini', 'input': 1000000, 'output': 20000, 'cached': 500000, 'calls': 50},
      ],
      'today_models': [
        {'model': 'oc/mimo-v2.6-flash-free', 'input': 1004000, 'output': 19000, 'cached': 858000, 'calls': 41},
      ],
      'trend': [
        {'date': '2026-10-01', 'total': 50000, 'input': 45000, 'output': 5000, 'cached': 20000, 'cache_write': 0, 'calls': 3},
        {'date': '2026-10-12', 'total': 300000, 'input': 280000, 'output': 20000, 'cached': 200000, 'cache_write': 0, 'calls': 12},
        {'date': '2026-10-13', 'total': 1023000, 'input': 1004000, 'output': 19000, 'cached': 858000, 'cache_write': 0, 'calls': 41},
      ],
    };

Future<void> _pump(WidgetTester t, TokenUsage? u, {bool failed = false}) async {
  t.view.physicalSize = const Size(1170, 4000);
  t.view.devicePixelRatio = 3;
  addTearDown(t.view.reset);
  await t.pumpWidget(MaterialApp(
    theme: neovarchMobileTheme,
    home: Scaffold(body: SingleChildScrollView(child: TokenUsageView(usage: u, failed: failed))),
  ));
  await t.pumpAndSettle();
}

String _headline(WidgetTester t) => t.widget<Text>(find.byKey(const ValueKey('token-headline'))).data!;

void main() {
  group('parsing', () {
    test('trend days with the split, today_models, and total-only days', () {
      final u = TokenUsage.from(_full())!;
      expect(u.trend, hasLength(3));
      expect(u.trend.last.hasSplit, isTrue);
      expect(u.trend.last.bucket.freshInput, 1004000 - 858000);
      expect(u.todayModels!.single.$1, 'oc/mimo-v2.6-flash-free');
      final old = DayUsage.from({'date': '2026-10-13', 'total': 77})!;
      expect(old.hasSplit, isFalse);
      expect(old.total, 77);
      expect(DayUsage.from({'total': 5}), isNull);
    });

    test('older core: no trend / today_models', () {
      final u = TokenUsage.from({
        'today': {'input': 1, 'output': 1},
        'lifetime': {'input': 2, 'output': 2},
      })!;
      expect(u.trend, isEmpty);
      expect(u.todayModels, isNull);
    });

    test('last 14 days fill gaps with zeros and end on the PC today', () {
      final days = usageLastDays(TokenUsage.from(_full())!.trend, '2026-10-13');
      expect(days, hasLength(14));
      expect(days.first.date, '2026-09-30');
      expect(days.last.date, '2026-10-13');
      expect(days.last.total, 1023000);
      expect(days[days.length - 2].total, 300000);
      expect(days[5].total, 0);
      // month boundary
      expect(usageLastDays(const [], '2026-03-02', days: 3).map((d) => d.date), ['2026-02-28', '2026-03-01', '2026-03-02']);
      expect(usageLastDays(const [], ''), isEmpty);
      expect(usageDayLabel('2026-10-13'), '13 Okt');
    });

    test('split parts add up to the total (cache never counted twice)', () {
      const b = TokenBucket(input: 1000, output: 50, cached: 1200);
      expect(b.cachedPart, 1000);
      expect(b.freshInput + b.cachedPart + b.output, b.total);
    });
  });

  group('chart view', () {
    testWidgets('headline, split legend, trend and per-model bars; toggle switches scope', (t) async {
      await _pump(t, TokenUsage.from(_full()));
      expect(_headline(t), '1,02jt');
      expect(find.text('token hari ini · 41× panggil model'), findsOneWidget);
      expect(find.text('Masuk baru'), findsOneWidget);
      expect(find.text('Masuk dari cache'), findsOneWidget);
      expect(find.text('Keluar (jawaban)'), findsOneWidget);
      expect(find.text('858rb'), findsOneWidget); // cache part
      expect(find.text('84%'), findsOneWidget); // 858k of 1,023k
      expect(find.byKey(const ValueKey('token-trend-chart')), findsOneWidget);
      expect(find.text('14 HARI TERAKHIR'), findsOneWidget);
      expect(find.text('PER MODEL · HARI INI'), findsOneWidget);
      expect(find.byKey(const ValueKey('token-model-oc/mimo-v2.6-flash-free')), findsOneWidget);
      expect(find.byKey(const ValueKey('token-model-gpt-5-mini')), findsNothing);

      await t.tap(find.byKey(const ValueKey('segment-Sesi')));
      await t.pumpAndSettle();
      expect(_headline(t), '204rb');
      expect(find.textContaining('sesi chat ini'), findsOneWidget);
      expect(find.textContaining('PER MODEL'), findsNothing);

      await t.tap(find.byKey(const ValueKey('segment-Semua')));
      await t.pumpAndSettle();
      expect(_headline(t), '5,10jt');
      expect(find.text('token sejak 1 Okt 2026 · 300× panggil model'), findsOneWidget);
      expect(find.text('PER MODEL · SEMUA'), findsOneWidget);
      expect(find.byKey(const ValueKey('token-model-gpt-5-mini')), findsOneWidget);
    });

    testWidgets('tapping a day reads that day; today is selected first', (t) async {
      await _pump(t, TokenUsage.from(_full()));
      final readout = find.byKey(const ValueKey('token-trend-readout'));
      expect(t.widget<Text>(readout).data, startsWith('13 Okt · 1,02jt (baru 146rb · cache 858rb · keluar 19rb)'));
      final chart = find.byKey(const ValueKey('token-trend-chart'));
      final box = t.getRect(chart);
      // 14 slots; 2026-10-12 is slot 12
      await t.tapAt(Offset(box.left + box.width * (12.5 / 14), box.center.dy));
      await t.pumpAndSettle();
      expect(t.widget<Text>(readout).data, startsWith('12 Okt · 300rb'));
    });

    testWidgets('raw numbers stay one tap away', (t) async {
      await _pump(t, TokenUsage.from(_full()));
      expect(find.textContaining('masuk 1,00jt (cache 858rb'), findsNothing);
      await t.tap(find.byKey(const ValueKey('token-details-toggle')));
      await t.pumpAndSettle();
      expect(find.textContaining('masuk 1,00jt (cache 858rb · 85%)'), findsOneWidget);
      expect(find.text('Sesi ini'), findsOneWidget);
      expect(find.text('Sepanjang waktu · sejak 1 Okt 2026'), findsOneWidget);
      expect(find.text('Sembunyikan angka lengkap'), findsOneWidget);
    });

    testWidgets('older core: no session, no trend, no today_models → totals still show', (t) async {
      await _pump(
          t,
          TokenUsage.from({
            'today': {'input': 1200, 'output': 300},
            'lifetime': {'input': 5000, 'output': 1000},
            'models': [
              {'model': 'm1', 'input': 5000, 'output': 1000},
            ],
          }));
      expect(_headline(t), '1,5rb');
      expect(find.byKey(const ValueKey('segment-Sesi')), findsNothing);
      expect(find.byKey(const ValueKey('token-trend-chart')), findsNothing);
      expect(find.textContaining('PER MODEL'), findsNothing); // today has no per-model data on this core
      await t.tap(find.byKey(const ValueKey('segment-Semua')));
      await t.pumpAndSettle();
      expect(_headline(t), '6,0rb');
      expect(find.text('token sepanjang waktu'), findsOneWidget);
      expect(find.byKey(const ValueKey('token-model-m1')), findsOneWidget);
      expect(t.takeException(), isNull);
    });

    testWidgets('trend with totals only (older core) draws one-colour bars', (t) async {
      final j = _full()
        ..['trend'] = [
          {'date': '2026-10-12', 'total': 300000},
          {'date': '2026-10-13', 'total': 1023000},
        ];
      await _pump(t, TokenUsage.from(j));
      expect(find.byKey(const ValueKey('token-trend-chart')), findsOneWidget);
      expect(t.widget<Text>(find.byKey(const ValueKey('token-trend-readout'))).data, '13 Okt · 1,02jt');
    });

    testWidgets('nothing counted yet: no empty chart', (t) async {
      await _pump(
          t,
          TokenUsage.from({
            'date': '2026-10-13',
            'today': {'input': 0, 'output': 0},
            'lifetime': {'input': 0, 'output': 0},
            'trend': <Object>[],
          }));
      expect(_headline(t), '0');
      expect(find.byKey(const ValueKey('token-trend-chart')), findsNothing);
      expect(find.byKey(const ValueKey('token-split-bar')), findsOneWidget);
    });

    testWidgets('not connected shows the fallback message', (t) async {
      await _pump(t, null, failed: true);
      expect(find.textContaining('Belum ada data'), findsOneWidget);
      expect(find.byKey(const ValueKey('token-scope')), findsNothing);
    });

    testWidgets('light mode renders without errors', (t) async {
      final prev = NV.palette;
      NV.palette = NvPalette.from(NvPalette.defaultAccent, Brightness.light);
      addTearDown(() => NV.palette = prev);
      await _pump(t, TokenUsage.from(_full()));
      expect(_headline(t), '1,02jt');
      expect(t.takeException(), isNull);
    });
  });
}
