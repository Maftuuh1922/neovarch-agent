// v1.4.8: Profil › Pemakaian token reads `GET /api/usage` with one meaning for
// every provider: masuk includes cache (cache is a subset), total = masuk + keluar,
// and "Sepanjang waktu" says since when the PC counts.
import 'package:flutter_test/flutter_test.dart';

import 'package:neovarch_agent/remote/ui/token_usage_panel.dart';

void main() {
  // The numbers from the user's screenshot (1,0jt / 1,0jt / 19rb / 858rb).
  const shot = {
    'date': '2026-10-13',
    'since': '2026-10-13',
    'today': {'input': 1004000, 'output': 19000, 'cached': 858000, 'cache_write': 0, 'calls': 41, 'total': 1023000},
    'lifetime': {'input': 1004000, 'output': 19000, 'cached': 858000, 'cache_write': 0, 'calls': 41, 'total': 1023000},
    'session': {'input': 1004000, 'output': 19000, 'cached': 858000, 'calls': 41, 'total': 1023000},
    'models': [
      {'model': 'oc/mimo-v2.6-flash-free', 'input': 1004000, 'output': 19000, 'cached': 858000, 'calls': 41},
    ],
  };

  test('parses since, date, cache_write and the session', () {
    final u = TokenUsage.from(Map<String, dynamic>.from(shot))!;
    expect(u.since, '2026-10-13');
    expect(u.date, '2026-10-13');
    expect(u.today.total, 1023000);
    expect(u.session!.calls, 41);
    expect(u.models.single.$1, 'oc/mimo-v2.6-flash-free');
    expect(TokenBucket.from({'input': 10, 'cache_write': 4})!.cacheWrite, 4);
  });

  test('older core without since still parses', () {
    final u = TokenUsage.from({
      'today': {'input': 1, 'output': 1},
      'lifetime': {'input': 2, 'output': 2},
    })!;
    expect(u.since, '');
    expect(u.session, isNull);
    expect(u.lifetime.total, 4);
  });

  test('total is masuk + keluar and is not rounded onto masuk', () {
    final b = TokenUsage.from(Map<String, dynamic>.from(shot))!.today;
    expect(b.total, b.input + b.output);
    expect(usageTokens(b.total), '1,02jt');
    expect(usageTokens(b.input), '1,00jt');
    expect(usageTokens(19000), '19rb');
    expect(usageTokens(25000000), '25,0jt');
  });

  test('cache is shown as part of masuk with its share', () {
    final b = TokenUsage.from(Map<String, dynamic>.from(shot))!.today;
    expect(b.cachePct, 85);
    final line = usageDetail(b);
    expect(line, startsWith('masuk 1,00jt (cache 858rb · 85%)'));
    expect(line, contains('keluar 19rb'));
    expect(usageDetail(const TokenBucket(input: 500, output: 20)), 'masuk 500 · keluar 20');
  });

  test('negative or junk numbers never show', () {
    final b = TokenBucket.from({'input': -5, 'output': 3, 'cached': 9})!;
    expect(b.input, 0);
    expect(b.cachePct, 0);
  });

  test('since label is Indonesian', () {
    expect(usageSinceLabel('2026-10-13'), '13 Okt 2026');
    expect(usageSinceLabel('2026-05-01'), '1 Mei 2026');
    expect(usageSinceLabel('kemarin'), 'kemarin');
  });
}
