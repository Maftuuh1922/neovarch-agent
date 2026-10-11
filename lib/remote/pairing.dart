// What a phone needs to reach the desktop's Neovarch core gateway: the
// gateway base URL (the HTTP origin that serves `/api/ws`), its auth token,
// and optional fallback addresses (LAN first, then Tailscale MagicDNS / 100.x). The Neovarch desktop shows this as a
// pairing QR; it can also be typed by hand. Pure Dart.
//
// Accepted forms (see docs/remote-protocol.md):
//   neovarch://pair?v=1&url=http%3A%2F%2F192.168.1.5%3A9319&token=…&name=…&profile=…
//        [&alt=http%3A%2F%2Fpc.tailnet.ts.net%3A9319&alt=…]   (or urls=a,b,c)
//   {"url":"http://192.168.1.5:9319","token":"…","name":"PC Kantor",
//    "urls":["http://192.168.1.5:9319","http://pc.tailnet.ts.net:9319","http://100.101.1.2:9319"]}
//   http://192.168.1.5:9319/?token=…        (a dashboard URL with ?token=)
//   ws://192.168.1.5:9319/api/ws?token=…    (the WebSocket URL itself)
//   192.168.1.5:9319                        (manual: token typed separately)
//
// Remote dari mana saja (v1.5): the same QR also carries the relay room id,
// the PC's public key, the relay URL and a short-lived pairing code
//   …&pc=<pcId>&pk=<pcPublicKey>&relay=wss%3A%2F%2F…&pair=<code>[&bt=AA:BB:…&btch=3]
// Old QRs without them still work (LAN only until the first LAN connect
// enrolls this phone).
import 'dart:convert';

import 'link/link_info.dart';

const int defaultGatewayPort = 9319;

class GatewayPairing {
  final String url; // normalized http(s)://host:port[/base]
  final String token;
  final String name;
  final String? profile;
  final Map<String, String> headers;

  /// Other addresses of the same PC, tried after [url] (see [orderedGatewayUrls]).
  final List<String> alternates;

  /// Relay / Bluetooth identity of the PC (null for an old QR).
  final LinkInfo? link;

  const GatewayPairing({required this.url, this.token = '', this.name = '', this.profile, this.headers = const {}, this.alternates = const [], this.link});

  /// [url] first, then the alternates, LAN before Tailscale, no duplicates.
  List<String> get allUrls => orderedGatewayUrls([url, ...alternates]);

  String get displayName => name.trim().isNotEmpty ? name.trim() : (Uri.tryParse(url)?.host ?? url);

  GatewayPairing copyWith({String? token, String? name}) => GatewayPairing(
      url: url, token: token ?? this.token, name: name ?? this.name, profile: profile, headers: headers, alternates: alternates, link: link);

  String toUri() => Uri(scheme: 'neovarch', host: 'pair', queryParameters: {
        'v': '1',
        'url': url,
        if (token.isNotEmpty) 'token': token,
        if (name.isNotEmpty) 'name': name,
        if (profile != null && profile!.isNotEmpty) 'profile': profile!,
        if (alternates.isNotEmpty) 'alt': alternates,
        if (link != null) 'pc': link!.pcId,
        if (link != null) 'pk': link!.pcPk,
        if (link?.relayUrl != null) 'relay': link!.relayUrl!,
        if (link?.pairCode != null) 'pair': link!.pairCode!,
        if (link?.bluetooth != null) 'bt': link!.bluetooth!.address,
        if (link?.bluetooth?.channel != null) 'btch': '${link!.bluetooth!.channel}',
      }).toString();

  /// Never throws; null when [raw] carries no usable gateway address.
  static GatewayPairing? parse(String raw) {
    final s = raw.trim();
    if (s.isEmpty) return null;
    if (s.startsWith('{')) {
      try {
        final j = Map<String, dynamic>.from(jsonDecode(s) as Map);
        final url = normalizeGatewayUrl('${j['url'] ?? j['gateway'] ?? j['host'] ?? ''}');
        if (url == null) return null;
        final h = j['headers'];
        return GatewayPairing(
          url: url,
          token: '${j['token'] ?? ''}',
          name: '${j['name'] ?? ''}',
          profile: (j['profile'] as String?)?.trim().isEmpty == true ? null : j['profile'] as String?,
          headers: h is Map ? h.map((k, v) => MapEntry('$k', '$v')) : const {},
          alternates: _alts(url, [
            for (final k in const ['urls', 'alt', 'alternates', 'addresses'])
              if (j[k] is List) ...(j[k] as List).map((e) => '$e') else if (j[k] is String) ...'${j[k]}'.split(','),
            if (j['tailscale'] is Map) ...[
              if ((j['tailscale'] as Map)['magic_dns'] != null) '${(j['tailscale'] as Map)['magic_dns']}',
              for (final ip in ((j['tailscale'] as Map)['ips'] as List? ?? const [])) '$ip',
            ],
          ], Uri.tryParse(url)?.port),
          link: LinkInfo.tryParse(j['link'] is Map ? j['link'] : {
            'pc_id': j['pc'] ?? j['pc_id'],
            'pc_pk': j['pk'] ?? j['pc_pk'],
            'relay_url': j['relay'] ?? j['relay_url'],
            'pair_code': j['pair'] ?? j['pair_code'],
            'bluetooth': j['bluetooth'] ?? (j['bt'] != null ? {'address': j['bt'], 'channel': j['btch']} : null),
          }),
        );
      } catch (_) {
        return null;
      }
    }
    final u = Uri.tryParse(s);
    if (u != null && u.scheme == 'neovarch') {
      final q = u.queryParameters;
      final url = normalizeGatewayUrl(q['url'] ?? q['u'] ?? '');
      if (url == null) return null;
      final all = u.queryParametersAll;
      return GatewayPairing(
          url: url,
          token: q['token'] ?? q['t'] ?? '',
          name: q['name'] ?? q['n'] ?? '',
          profile: (q['profile'] ?? '').isEmpty ? null : q['profile'],
          alternates: _alts(url, [
            ...?all['alt'],
            for (final v in [...?all['urls'], ...?all['ts']]) ...v.split(','),
          ], Uri.tryParse(url)?.port),
          link: LinkInfo.tryParse({
            'pc_id': q['pc'],
            'pc_pk': q['pk'],
            'relay_url': q['relay'],
            'pair_code': q['pair'],
            if (q['bt'] != null) 'bluetooth': {'address': q['bt'], 'channel': int.tryParse(q['btch'] ?? ''), 'uuid': q['btuuid']},
          }));
    }
    final url = normalizeGatewayUrl(s);
    if (url == null) return null;
    final token = Uri.tryParse(s.contains('://') ? s : 'http://$s')?.queryParameters['token'] ?? '';
    return GatewayPairing(url: url, token: token);
  }
}

/// `192.168.1.5` → `http://192.168.1.5:9319`; `ws(s)://…/api/ws?token=x` →
/// `http(s)://…`; keeps a base path (reverse proxies), drops query/fragment.
String? normalizeGatewayUrl(String input) {
  var s = input.trim();
  if (s.isEmpty) return null;
  if (!s.contains('://')) s = 'http://$s';
  final u = Uri.tryParse(s);
  if (u == null || u.host.isEmpty) return null;
  final scheme = switch (u.scheme) {
    'https' || 'wss' => 'https',
    'http' || 'ws' => 'http',
    _ => null,
  };
  if (scheme == null) return null;
  var path = u.path.replaceAll(RegExp(r'/+$'), '');
  if (path.endsWith('/api/ws')) path = path.substring(0, path.length - '/api/ws'.length);
  final port = u.hasPort ? u.port : (scheme == 'https' ? null : defaultGatewayPort);
  return Uri(scheme: scheme, host: u.host, port: port, path: path).toString();
}

/// Normalise alternate addresses (bare hosts get the primary's port), drop
/// the primary and duplicates.
List<String> _alts(String primary, Iterable<String> raw, int? port) {
  final out = <String>[];
  for (final r in raw) {
    var v = r.trim();
    if (v.isEmpty) continue;
    if (!v.contains('://') && !RegExp(r':\d+$').hasMatch(v) && port != null) v = '$v:$port';
    final n = normalizeGatewayUrl(v);
    if (n != null && n != primary && !out.contains(n)) out.add(n);
  }
  return out;
}

/// Kind of network an address is on: `lan` (private IPv4, `.local`,
/// localhost), `tailscale` (100.64.0.0/10 or `*.ts.net`), else `other`.
String gatewayRoute(String url) {
  final h = Uri.tryParse(url)?.host.toLowerCase() ?? '';
  if (h.endsWith('.ts.net')) return 'tailscale';
  final p = h.split('.').map(int.tryParse).toList();
  if (p.length == 4 && !p.contains(null)) {
    final a = p[0]!, b = p[1]!;
    if (a == 100 && b >= 64 && b <= 127) return 'tailscale';
    if (a == 10 || (a == 192 && b == 168) || (a == 172 && b >= 16 && b <= 31) || a == 127) return 'lan';
    return 'other';
  }
  if (h == 'localhost' || h.endsWith('.local') || h.endsWith('.lan')) return 'lan';
  return 'other';
}

/// LAN first (fastest), then Tailscale MagicDNS, then tailnet IPs, then the
/// rest; the order within a group is kept and duplicates are dropped.
List<String> orderedGatewayUrls(Iterable<String> urls) {
  int rank(String u) {
    final r = gatewayRoute(u);
    if (r == 'lan') return 0;
    if (r == 'tailscale') return (Uri.tryParse(u)?.host ?? '').endsWith('.ts.net') ? 1 : 2;
    return 3;
  }
  final seen = <String>{};
  final list = [for (final u in urls) if (seen.add(u)) u];
  final idx = {for (final (i, u) in list.indexed) u: i};
  list.sort((a, b) {
    final c = rank(a).compareTo(rank(b));
    return c != 0 ? c : idx[a]!.compareTo(idx[b]!);
  });
  return list;
}
