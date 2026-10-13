// Profil › Pemakaian token (v1.4.7, v1.4.8): what the PC core counted (`GET /api/usage`):
// today / this session / lifetime ("sejak <tanggal>": the PC only counts from the
// day it got the counter), input vs output, per model. Same numbers as the
// desktop monitor and the Pamerkan card tiles. Counts only, nothing private.
//
// Meaning (core ≥ 1.4.8, every provider shape): masuk = every prompt token the
// model read (uncached + cache), cache = the part of masuk served from the
// provider's cache (a SUBSET, not extra), total = masuk + keluar.
//
// v1.4.8 chart view (the text list was too hard to read): a Hari ini | Sesi |
// Semua toggle over one big total, a bar that splits it into masuk baru /
// masuk dari cache / keluar (the three add up to the total, so cache is never
// counted twice), a 14-day stacked bar trend (tap a day for its numbers) and
// per-model horizontal bars. "Angka lengkap" still opens the exact numbers.
// Older cores degrade: trend without the per-day split (core 1.4.7/early 1.4.8)
// draws single-colour bars, no trend hides the chart, no today_models hides the
// per-model bars for Hari ini.
import 'dart:math' as math;

import 'package:flutter/cupertino.dart' show CupertinoIcons;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../theme/neovarch_mobile_theme.dart';
import '../remote_controller.dart';
import 'brag_card.dart' show compactTokens;
import 'nv_widgets.dart';

/// One bucket of `/api/usage` (`{input, output, cached, cache_write, calls, total}`).
class TokenBucket {
  const TokenBucket({this.input = 0, this.output = 0, this.cached = 0, this.cacheWrite = 0, this.calls = 0});
  final int input, output, cached, cacheWrite, calls;
  int get total => input + output;

  /// Cache-read part of [input], never more than [input].
  int get cachedPart => cached > input ? input : cached;

  /// [input] the model read fresh (not from the provider's cache).
  int get freshInput => input - cachedPart;

  /// Share of [input] read from the provider's cache, 0–100.
  int get cachePct => input > 0 ? (100 * cachedPart / input).round() : 0;

  static TokenBucket? from(Object? j) {
    if (j is! Map) return null;
    int n(String k) {
      final v = (j[k] as num?)?.toInt() ?? 0;
      return v < 0 ? 0 : v;
    }

    return TokenBucket(
        input: n('input'), output: n('output'), cached: n('cached'), cacheWrite: n('cache_write'), calls: n('calls'));
  }
}

const _bulan = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];

/// `2026-10-12` → `12 Okt 2026`; anything else comes back as given.
String usageSinceLabel(String iso) {
  final m = RegExp(r'^(\d{4})-(\d{2})-(\d{2})$').firstMatch(iso.trim());
  if (m == null) return iso.trim();
  final mo = int.parse(m.group(2)!);
  if (mo < 1 || mo > 12) return iso.trim();
  return '${int.parse(m.group(3)!)} ${_bulan[mo - 1]} ${m.group(1)}';
}

/// Token count for the panel: like [compactTokens] but two decimals between
/// 1 and 10 juta, so 1.020.000 reads `1,02jt` and is not mistaken for `masuk 1,0jt`.
String usageTokens(int n) {
  if (n >= 1000000 && n < 10000000) return '${(n / 1000000).toStringAsFixed(2).replaceAll('.', ',')}jt';
  return compactTokens(n);
}

/// The detail line under a bucket: cache is shown as part of masuk, never next to it.
String usageDetail(TokenBucket b) {
  final cache = b.cached > 0 ? ' (cache ${usageTokens(b.cached)} · ${b.cachePct}%)' : '';
  final calls = b.calls > 0 ? ' · ${b.calls}× panggil' : '';
  return 'masuk ${usageTokens(b.input)}$cache · keluar ${usageTokens(b.output)}$calls';
}

/// One day of `trend` (`{date, total}`; core ≥ 1.4.8 also sends the split).
class DayUsage {
  const DayUsage(this.date, this.bucket, {this.totalOnly = 0, this.hasSplit = true});
  final String date;
  final TokenBucket bucket;

  /// Older cores send only `total`: kept here, drawn as one colour.
  final int totalOnly;
  final bool hasSplit;
  int get total => hasSplit ? bucket.total : totalOnly;

  static DayUsage? from(Object? j) {
    if (j is! Map) return null;
    final date = '${j['date'] ?? ''}';
    if (date.isEmpty) return null;
    final split = j.containsKey('input') || j.containsKey('output');
    final t = (j['total'] as num?)?.toInt() ?? 0;
    return DayUsage(date, split ? TokenBucket.from(j)! : const TokenBucket(), totalOnly: t < 0 ? 0 : t, hasSplit: split);
  }
}

/// `2026-10-13` → DateTime (local midnight), or null.
DateTime? _day(String iso) {
  final m = RegExp(r'^(\d{4})-(\d{2})-(\d{2})$').firstMatch(iso.trim());
  if (m == null) return null;
  return DateTime(int.parse(m.group(1)!), int.parse(m.group(2)!), int.parse(m.group(3)!));
}

String _iso(DateTime d) =>
    '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

/// The last [days] calendar days ending on [end] (the PC's today), days the PC
/// did not count filled with zeros so the bars keep a steady time axis.
List<DayUsage> usageLastDays(List<DayUsage> trend, String end, {int days = 14}) {
  final last = _day(end) ?? (trend.isEmpty ? null : _day(trend.last.date));
  if (last == null) return const [];
  final byDate = {for (final d in trend) d.date: d};
  final split = trend.isEmpty || trend.any((d) => d.hasSplit);
  return [
    for (var i = days - 1; i >= 0; i--)
      () {
        // DateTime(y, m, d - i) handles month ends and DST without Duration maths.
        final iso = _iso(DateTime(last.year, last.month, last.day - i));
        return byDate[iso] ?? DayUsage(iso, const TokenBucket(), hasSplit: split);
      }(),
  ];
}

/// `2026-10-13` → `13 Okt`.
String usageDayLabel(String iso) {
  final d = _day(iso);
  return d == null ? iso : '${d.day} ${_bulan[d.month - 1]}';
}

/// `GET /api/usage` parsed for the panel.
class TokenUsage {
  const TokenUsage(
      {required this.today,
      required this.lifetime,
      this.session,
      this.models = const [],
      this.todayModels,
      this.trend = const [],
      this.since = '',
      this.date = ''});
  final TokenBucket today, lifetime;
  final TokenBucket? session;

  /// First day the PC counted (`since`, core ≥ 1.4.8; empty on older cores).
  final String since;

  /// The PC's "today" (`date`).
  final String date;

  /// Lifetime per model, biggest first.
  final List<(String, TokenBucket)> models;

  /// Today per model (`today_models`); null when the core does not send it.
  final List<(String, TokenBucket)>? todayModels;

  /// Kept days, oldest first (`trend`, up to 30).
  final List<DayUsage> trend;

  static List<(String, TokenBucket)> _models(Object? j) => [
        for (final m in (j as List? ?? const []).whereType<Map>())
          ('${m['model'] ?? '?'}', TokenBucket.from(m) ?? const TokenBucket()),
      ];

  static TokenUsage? from(Map<String, dynamic>? j) {
    if (j == null) return null;
    final today = TokenBucket.from(j['today']);
    final life = TokenBucket.from(j['lifetime']);
    if (today == null || life == null) return null;
    return TokenUsage(
      today: today,
      lifetime: life,
      session: TokenBucket.from(j['session']),
      since: '${j['since'] ?? ''}',
      date: '${j['date'] ?? ''}',
      models: _models(j['models']),
      todayModels: j['today_models'] is List ? _models(j['today_models']) : null,
      trend: (j['trend'] as List? ?? const []).map(DayUsage.from).whereType<DayUsage>().toList(),
    );
  }
}

/// Which bucket the headline shows.
enum UsageScope { today, session, all }

/// The three parts of a total, in drawing order. They add up to the total.
class _Part {
  const _Part(this.label, this.short, this.value, this.color);
  final String label, short;
  final int value;
  final Color color;
}

Color get _cFresh => NV.red;
Color get _cCache => NV.red.withValues(alpha: NV.palette.dark ? 0.38 : 0.30);
Color get _cOut => NV.text.withValues(alpha: NV.palette.dark ? 0.62 : 0.55);
Color get _cTrack => NV.text.withValues(alpha: NV.palette.dark ? 0.08 : 0.07);

List<_Part> _parts(TokenBucket b) => [
      _Part('Masuk baru', 'baru', b.freshInput, _cFresh),
      _Part('Masuk dari cache', 'cache', b.cachedPart, _cCache),
      _Part('Keluar (jawaban)', 'keluar', b.output, _cOut),
    ];

class TokenUsagePanel extends ConsumerStatefulWidget {
  const TokenUsagePanel({super.key, this.margin = const EdgeInsets.symmetric(horizontal: 16)});
  final EdgeInsets margin;
  @override
  ConsumerState<TokenUsagePanel> createState() => _TokenUsagePanelState();
}

class _TokenUsagePanelState extends ConsumerState<TokenUsagePanel> {
  TokenUsage? _usage;
  bool _loading = false;
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    final r = ref.read(remoteProvider);
    final g = r.gateway;
    if (g == null || !r.connected) {
      setState(() => _failed = true);
      return;
    }
    setState(() => _loading = true);
    final j = await g.usageStats(session: r.storedId);
    if (!mounted) return;
    setState(() {
      _loading = false;
      _usage = TokenUsage.from(j);
      _failed = _usage == null;
    });
  }

  @override
  Widget build(BuildContext context) => TokenUsageView(
        usage: _usage,
        loading: _loading,
        failed: _failed,
        onRefresh: _loading ? null : _load,
        margin: widget.margin,
      );
}

/// The panel body for a parsed [usage] (null: loading / not connected).
class TokenUsageView extends StatefulWidget {
  const TokenUsageView(
      {super.key,
      required this.usage,
      this.loading = false,
      this.failed = false,
      this.onRefresh,
      this.margin = const EdgeInsets.symmetric(horizontal: 16)});
  final TokenUsage? usage;
  final bool loading, failed;
  final VoidCallback? onRefresh;
  final EdgeInsets margin;

  @override
  State<TokenUsageView> createState() => _TokenUsageViewState();
}

class _TokenUsageViewState extends State<TokenUsageView> {
  UsageScope _scope = UsageScope.today;
  bool _details = false;

  TextStyle get _label => TextStyle(fontFamily: NV.sans, fontSize: 12.5, color: NV.muted);
  TextStyle get _value => TextStyle(fontFamily: NV.mono, fontSize: 15, color: NV.text);

  List<UsageScope> _scopes(TokenUsage u) =>
      [UsageScope.today, if (u.session != null) UsageScope.session, UsageScope.all];

  static String _scopeLabel(UsageScope s) => switch (s) {
        UsageScope.today => 'Hari ini',
        UsageScope.session => 'Sesi',
        UsageScope.all => 'Semua',
      };

  TokenBucket _bucket(TokenUsage u, UsageScope s) => switch (s) {
        UsageScope.today => u.today,
        UsageScope.session => u.session ?? u.today,
        UsageScope.all => u.lifetime,
      };

  String _caption(TokenUsage u, UsageScope s, TokenBucket b) {
    final when = switch (s) {
      UsageScope.today => 'token hari ini',
      UsageScope.session => 'token di sesi chat ini',
      UsageScope.all => u.since.isEmpty ? 'token sepanjang waktu' : 'token sejak ${usageSinceLabel(u.since)}',
    };
    return b.calls > 0 ? '$when · ${b.calls}× panggil model' : when;
  }

  Widget _rawRow(String label, TokenBucket b, {String? note}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 5),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [
            Expanded(child: Text(label, style: _label, maxLines: 1, overflow: TextOverflow.ellipsis)),
            Text(usageTokens(b.total), style: _value),
          ]),
          Text(usageDetail(b), style: _label.copyWith(fontSize: 11)),
          if (note != null) Text(note, style: _label.copyWith(fontSize: 10.5, fontStyle: FontStyle.italic)),
        ]),
      );

  Widget _section(String text) => Padding(
        padding: const EdgeInsets.only(top: 14, bottom: 6),
        child: Text(text.toUpperCase(), style: NV.monoLabel(size: 9, color: NV.muted)),
      );

  @override
  Widget build(BuildContext context) {
    final u = widget.usage;
    return NvPanel(
      key: const ValueKey('token-usage-panel'),
      margin: widget.margin,
      padding: const EdgeInsets.fromLTRB(14, 10, 14, 12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Icon(CupertinoIcons.chart_bar_alt_fill, size: 16, color: NV.muted),
          const SizedBox(width: 8),
          Expanded(child: Text('Dihitung oleh PC, semua penyedia', style: _label)),
          IconButton(
            tooltip: 'Muat ulang',
            onPressed: widget.onRefresh,
            icon: Icon(CupertinoIcons.refresh, size: 16, color: NV.muted),
          ),
        ]),
        if (u == null)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: Text(
                widget.loading
                    ? 'Memuat…'
                    : (widget.failed ? 'Belum ada data. Sambungkan ke PC (Neovarch ≥ 1.4.7) lalu tekan muat ulang.' : ''),
                style: _label),
          )
        else
          ..._body(u),
      ]),
    );
  }

  List<Widget> _body(TokenUsage u) {
    final scopes = _scopes(u);
    final scope = scopes.contains(_scope) ? _scope : UsageScope.today;
    final b = _bucket(u, scope);
    final models = switch (scope) {
      UsageScope.today => u.todayModels,
      UsageScope.session => null,
      UsageScope.all => u.models,
    };
    final days = usageLastDays(u.trend, u.date);
    return [
      NvGlassSegmented(
        key: const ValueKey('token-scope'),
        labels: [for (final s in scopes) _scopeLabel(s)],
        index: scopes.indexOf(scope),
        onChanged: (i) => setState(() => _scope = scopes[i]),
        height: 36,
      ),
      const SizedBox(height: 14),
      // Headline: the one number that matters.
      Semantics(
        label: '${usageTokens(b.total)} ${_caption(u, scope, b)}',
        excludeSemantics: true,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(usageTokens(b.total), key: const ValueKey('token-headline'), style: NV.display(size: 36)),
          const SizedBox(height: 2),
          Text(_caption(u, scope, b), style: _label),
        ]),
      ),
      const SizedBox(height: 12),
      UsageSplitBar(bucket: b),
      const SizedBox(height: 8),
      for (final p in _parts(b)) _legendRow(p, b.total),
      if (scope == UsageScope.all && u.since.isNotEmpty && u.since == u.date)
        Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Text('PC baru mulai menghitung hari ini, jadi masih sama dengan "Hari ini".',
              style: _label.copyWith(fontSize: 10.5, fontStyle: FontStyle.italic)),
        ),
      if (days.isNotEmpty && days.any((d) => d.total > 0)) ...[
        _section('14 hari terakhir'),
        UsageTrendChart(days: days),
      ],
      if (models != null && models.isNotEmpty) ...[
        _section(scope == UsageScope.today ? 'Per model · hari ini' : 'Per model · semua'),
        UsageModelBars(models: models),
      ],
      const SizedBox(height: 6),
      _detailsToggle(),
      if (_details) ..._raw(u),
    ];
  }

  Widget _legendRow(_Part p, int total) {
    final pct = total > 0 ? (100 * p.value / total).round() : 0;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2.5),
      child: Row(children: [
        Container(width: 10, height: 10, decoration: BoxDecoration(color: p.color, borderRadius: BorderRadius.circular(3))),
        const SizedBox(width: 8),
        Expanded(child: Text(p.label, style: _label.copyWith(color: NV.text, fontSize: 13))),
        Text(usageTokens(p.value), style: _value.copyWith(fontSize: 13)),
        SizedBox(
          width: 44,
          child: Text('$pct%', textAlign: TextAlign.right, style: _label.copyWith(fontSize: 12)),
        ),
      ]),
    );
  }

  Widget _detailsToggle() => Semantics(
        button: true,
        expanded: _details,
        child: InkWell(
          key: const ValueKey('token-details-toggle'),
          borderRadius: BorderRadius.circular(10),
          onTap: () => setState(() => _details = !_details),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: Row(children: [
              Text(_details ? 'Sembunyikan angka lengkap' : 'Angka lengkap',
                  style: _label.copyWith(color: NV.text, fontWeight: FontWeight.w600)),
              const SizedBox(width: 4),
              Icon(_details ? CupertinoIcons.chevron_up : CupertinoIcons.chevron_down, size: 13, color: NV.muted),
            ]),
          ),
        ),
      );

  List<Widget> _raw(TokenUsage u) => [
        _rawRow('Hari ini', u.today),
        if (u.session != null) _rawRow('Sesi ini', u.session!),
        _rawRow(u.since.isEmpty ? 'Sepanjang waktu' : 'Sepanjang waktu · sejak ${usageSinceLabel(u.since)}', u.lifetime),
        Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Text('Total = masuk + keluar. Cache adalah bagian dari masuk (dibaca ulang dari cache penyedia).',
              style: _label.copyWith(fontSize: 10.5)),
        ),
        if (u.models.isNotEmpty) ...[
          _section('Per model · semua'),
          for (final (name, b) in u.models.take(8)) _rawRow(name, b),
        ],
      ];
}

/// One capsule split into masuk baru | masuk dari cache | keluar.
class UsageSplitBar extends StatelessWidget {
  const UsageSplitBar({super.key, required this.bucket, this.height = 14});
  final TokenBucket bucket;
  final double height;

  @override
  Widget build(BuildContext context) {
    final parts = _parts(bucket);
    final total = bucket.total;
    return ClipRRect(
      key: const ValueKey('token-split-bar'),
      borderRadius: BorderRadius.circular(height / 2),
      child: SizedBox(
        height: height,
        child: total <= 0
            ? SizedBox.expand(child: ColoredBox(color: _cTrack))
            : Row(children: [
                for (final p in parts)
                  if (p.value > 0)
                    // flex is int: scale to 1/1000ths so a 1% slice still shows.
                    Expanded(flex: math.max(1, (1000 * p.value / total).round()), child: SizedBox.expand(child: ColoredBox(color: p.color))),
              ]),
      ),
    );
  }
}

/// Stacked daily bars (cache / baru / keluar), today highlighted; tap a bar
/// to read that day. Total-only days (older cores) are one colour.
class UsageTrendChart extends StatefulWidget {
  const UsageTrendChart({super.key, required this.days, this.height = 120});
  final List<DayUsage> days;
  final double height;
  @override
  State<UsageTrendChart> createState() => _UsageTrendChartState();
}

class _UsageTrendChartState extends State<UsageTrendChart> {
  int? _sel;

  int get _selected => (_sel ?? widget.days.length - 1).clamp(0, widget.days.length - 1);

  void _pick(Offset local, double width) {
    if (widget.days.isEmpty) return;
    final i = (local.dx / width * widget.days.length).floor().clamp(0, widget.days.length - 1);
    if (i != _sel) setState(() => _sel = i);
  }

  @override
  Widget build(BuildContext context) {
    final days = widget.days;
    final d = days[_selected];
    final label = TextStyle(fontFamily: NV.sans, fontSize: 11, color: NV.muted);
    final readout = d.hasSplit
        ? '${usageDayLabel(d.date)} · ${usageTokens(d.total)} (baru ${usageTokens(d.bucket.freshInput)} · '
            'cache ${usageTokens(d.bucket.cachedPart)} · keluar ${usageTokens(d.bucket.output)})'
        : '${usageDayLabel(d.date)} · ${usageTokens(d.total)}';
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Text(readout, key: const ValueKey('token-trend-readout'), style: label.copyWith(color: NV.text, fontSize: 12)),
      const SizedBox(height: 8),
      LayoutBuilder(builder: (context, c) {
        final w = c.maxWidth;
        return Semantics(
          label: 'Grafik token per hari, ${days.length} hari. Dipilih: $readout',
          child: GestureDetector(
            key: const ValueKey('token-trend-chart'),
            behavior: HitTestBehavior.opaque,
            onTapDown: (e) => _pick(e.localPosition, w),
            onHorizontalDragUpdate: (e) => _pick(e.localPosition, w),
            child: CustomPaint(
              size: Size(w, widget.height),
              painter: UsageTrendPainter(
                days: days,
                selected: _selected,
                fresh: _cFresh,
                cache: _cCache,
                out: _cOut,
                track: _cTrack,
              ),
            ),
          ),
        );
      }),
      const SizedBox(height: 4),
      Row(children: [
        Text(usageDayLabel(days.first.date), style: label),
        const Spacer(),
        Text('Hari ini', style: label),
      ]),
    ]);
  }
}

class UsageTrendPainter extends CustomPainter {
  UsageTrendPainter(
      {required this.days,
      required this.selected,
      required this.fresh,
      required this.cache,
      required this.out,
      required this.track});
  final List<DayUsage> days;
  final int selected;
  final Color fresh, cache, out, track;

  @override
  void paint(Canvas canvas, Size size) {
    if (days.isEmpty) return;
    final maxT = days.fold<int>(0, (m, d) => math.max(m, d.total));
    final slot = size.width / days.length;
    final barW = math.min(18.0, slot * 0.62);
    final r = Radius.circular(math.min(4, barW / 2));
    final paint = Paint();
    for (var i = 0; i < days.length; i++) {
      final d = days[i];
      final x = slot * i + (slot - barW) / 2;
      final dim = i != selected;
      // empty track so zero days still read as days
      paint.color = track;
      canvas.drawRRect(RRect.fromRectAndRadius(Rect.fromLTWH(x, 0, barW, size.height), r), paint);
      if (maxT <= 0 || d.total <= 0) continue;
      final h = size.height * d.total / maxT;
      final rect = Rect.fromLTWH(x, size.height - h, barW, h);
      canvas.save();
      canvas.clipRRect(RRect.fromRectAndRadius(rect, r));
      final segs = d.hasSplit
          ? [(d.bucket.cachedPart, cache), (d.bucket.freshInput, fresh), (d.bucket.output, out)]
          : [(d.total, fresh)];
      var y = size.height;
      for (final (v, c) in segs) {
        if (v <= 0) continue;
        final sh = h * v / d.total;
        paint.color = dim ? c.withValues(alpha: c.a * 0.55) : c;
        canvas.drawRect(Rect.fromLTWH(x, y - sh, barW, sh), paint);
        y -= sh;
      }
      canvas.restore();
    }
  }

  @override
  bool shouldRepaint(UsageTrendPainter old) =>
      old.days != days || old.selected != selected || old.fresh != fresh || old.cache != cache || old.out != out;
}

/// Horizontal bars per model, scaled to the biggest; split like the headline bar.
class UsageModelBars extends StatelessWidget {
  const UsageModelBars({super.key, required this.models, this.max = 6});
  final List<(String, TokenBucket)> models;
  final int max;

  @override
  Widget build(BuildContext context) {
    final shown = models.where((m) => m.$2.total > 0).take(max).toList();
    final rest = models.where((m) => m.$2.total > 0).length - shown.length;
    final top = shown.fold<int>(0, (m, e) => math.max(m, e.$2.total));
    final label = TextStyle(fontFamily: NV.sans, fontSize: 12.5, color: NV.text);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      for (final (name, b) in shown)
        Padding(
          key: ValueKey('token-model-$name'),
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Row(children: [
              Expanded(child: Text(name, style: label, maxLines: 1, overflow: TextOverflow.ellipsis)),
              const SizedBox(width: 8),
              Text(usageTokens(b.total), style: TextStyle(fontFamily: NV.mono, fontSize: 12.5, color: NV.text)),
            ]),
            const SizedBox(height: 4),
            LayoutBuilder(
              builder: (context, c) => Align(
                alignment: Alignment.centerLeft,
                child: SizedBox(
                  width: math.max(6.0, c.maxWidth * (top > 0 ? b.total / top : 0)),
                  child: UsageSplitBar(bucket: b, height: 8),
                ),
              ),
            ),
          ]),
        ),
      if (rest > 0)
        Padding(
          padding: const EdgeInsets.only(top: 2),
          child: Text('+$rest model lain', style: label.copyWith(color: NV.muted, fontSize: 11.5)),
        ),
    ]);
  }
}
