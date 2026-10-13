// Profil › Pemakaian token (v1.4.7, v1.4.8): what the PC core counted (`GET /api/usage`):
// today / this session / lifetime ("sejak <tanggal>": the PC only counts from the
// day it got the counter), input vs output, per model. Same numbers as the
// desktop monitor and the Pamerkan card tiles. Counts only, nothing private.
//
// Meaning (core ≥ 1.4.8, every provider shape): masuk = every prompt token the
// model read (uncached + cache), cache = the part of masuk served from the
// provider's cache (a SUBSET, not extra), total = masuk + keluar.
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

  /// Share of [input] read from the provider's cache, 0–100.
  int get cachePct => input > 0 ? (100 * (cached > input ? input : cached) / input).round() : 0;

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

/// `GET /api/usage` parsed for the panel.
class TokenUsage {
  const TokenUsage(
      {required this.today, required this.lifetime, this.session, this.models = const [], this.since = '', this.date = ''});
  final TokenBucket today, lifetime;
  final TokenBucket? session;

  /// First day the PC counted (`since`, core ≥ 1.4.8; empty on older cores).
  final String since;

  /// The PC's "today" (`date`).
  final String date;
  final List<(String, TokenBucket)> models;

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

      models: [
        for (final m in (j['models'] as List? ?? const []).whereType<Map>())
          ('${m['model'] ?? '?'}', TokenBucket.from(m) ?? const TokenBucket()),
      ],
    );
  }
}

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

  TextStyle get _label => TextStyle(fontFamily: NV.sans, fontSize: 12.5, color: NV.muted);
  TextStyle get _value => TextStyle(fontFamily: NV.mono, fontSize: 15, color: NV.text);

  Widget _row(String label, TokenBucket b, {String? note}) => Padding(
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

  @override
  Widget build(BuildContext context) {
    final u = _usage;
    return NvPanel(
      key: const ValueKey('token-usage-panel'),
      margin: widget.margin,
      padding: const EdgeInsets.fromLTRB(14, 10, 14, 10),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Icon(CupertinoIcons.chart_bar_alt_fill, size: 16, color: NV.muted),
          const SizedBox(width: 8),
          Expanded(child: Text('Dihitung oleh PC, semua penyedia', style: _label)),
          IconButton(
            tooltip: 'Muat ulang',
            onPressed: _loading ? null : _load,
            icon: Icon(CupertinoIcons.refresh, size: 16, color: NV.muted),
          ),
        ]),
        if (u == null)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: Text(
                _loading
                    ? 'Memuat…'
                    : (_failed ? 'Belum ada data. Sambungkan ke PC (Neovarch ≥ 1.4.7) lalu tekan muat ulang.' : ''),
                style: _label),
          )
        else ...[
          _row('Hari ini', u.today),
          if (u.session != null) _row('Sesi ini', u.session!),
          _row(u.since.isEmpty ? 'Sepanjang waktu' : 'Sepanjang waktu · sejak ${usageSinceLabel(u.since)}', u.lifetime,
              note: u.since.isNotEmpty && u.since == u.date
                  ? 'PC baru mulai menghitung hari ini, jadi masih sama dengan "Hari ini".'
                  : null),
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text('Total = masuk + keluar. Cache adalah bagian dari masuk (dibaca ulang dari cache penyedia).',
                style: _label.copyWith(fontSize: 10.5)),
          ),
          if (u.models.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text('PER MODEL', style: NV.monoLabel(size: 9, color: NV.muted)),
            for (final (name, b) in u.models.take(8)) _row(name, b),
          ],
        ],
      ]),
    );
  }
}
