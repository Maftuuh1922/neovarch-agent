// "Update tersedia" for the phone app: GitHub Releases API
// (`releases/latest`), with the PC core's cached check (`/api/update`) as the
// fallback when GitHub is unreachable (rate limit, no internet but LAN).
// Compares against THIS app's version, not the PC's. Pure Dart.
import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import '../state/settings_controller.dart';

const githubRepo = 'Maftuuh1922/neovrach_Agent';
const releasesPage = 'https://github.com/$githubRepo/releases/latest';

List<int> parseVersion(String v) {
  final m = RegExp(r'(\d+)(?:\.(\d+))?(?:\.(\d+))?').firstMatch(v.trim().replaceFirst(RegExp(r'^[vV]'), ''));
  if (m == null) return const [0, 0, 0];
  return [for (var i = 1; i <= 3; i++) int.tryParse(m.group(i) ?? '0') ?? 0];
}

bool isNewerVersion(String latest, String current) {
  final a = parseVersion(latest), b = parseVersion(current);
  for (var i = 0; i < 3; i++) {
    if (a[i] != b[i]) return a[i] > b[i];
  }
  return false;
}

/// Android asset: an arm64 split APK first, then any non-x86 APK, then any
/// APK. `{url, name, size}` or null when the release ships no APK.
Map<String, dynamic>? pickApkAsset(List assets) {
  final apks = [
    for (final a in assets.whereType<Map>())
      if ('${a['name'] ?? ''}'.toLowerCase().endsWith('.apk')) a,
  ];
  final arm = apks.where((a) => '${a['name']}'.toLowerCase().contains('arm64')).firstOrNull;
  final pick = arm ?? apks.where((a) => !'${a['name']}'.toLowerCase().contains('x86')).firstOrNull ?? apks.firstOrNull;
  final url = pick?['browser_download_url'];
  if (pick == null || url is! String || url.isEmpty) return null;
  final size = pick['size'];
  return {'url': url, 'name': '${pick['name']}', 'size': size is int && size > 0 ? size : null};
}

String? pickApk(List assets) => pickApkAsset(assets)?['url'] as String?;

/// Optional checksum asset for [apkName]: `<apk>.sha256` first, then a
/// combined `SHA256SUMS` / `checksums.txt` / `sha256sums.txt`.
String? pickSha256Asset(List assets, String apkName) {
  final named = <String, String>{
    for (final a in assets.whereType<Map>())
      if (a['browser_download_url'] is String) '${a['name'] ?? ''}'.toLowerCase(): a['browser_download_url'] as String,
  };
  final n = apkName.toLowerCase();
  return named['$n.sha256'] ?? named['$n.sha256sum'] ?? named['sha256sums'] ?? named['sha256sums.txt'] ?? named['checksums.txt'];
}

/// A GitHub `releases/latest` body → the update map ([UpdateChecker.check]).
Map<String, dynamic>? parseGithubRelease(Map j, String current) {
  final latest = '${j['tag_name'] ?? ''}'.replaceFirst(RegExp(r'^[vV]'), '');
  if (latest.isEmpty) return null;
  final url = '${j['html_url'] ?? releasesPage}';
  final assets = j['assets'] as List? ?? const [];
  final apk = pickApkAsset(assets);
  return {
    'current': current,
    'latest': latest,
    'available': isNewerVersion(latest, current),
    'url': url,
    'download_url': apk?['url'] ?? url,
    if (apk != null) 'apk_name': apk['name'],
    if (apk?['size'] != null) 'apk_size': apk!['size'],
    if (apk != null && pickSha256Asset(assets, apk['name'] as String) != null)
      'sha256_url': pickSha256Asset(assets, apk['name'] as String),
    'source': 'github',
  };
}

class UpdateChecker {
  UpdateChecker({http.Client? client, this.current = SettingsController.appVersion, this.minInterval = const Duration(hours: 6), this.prefs})
      : _client = client ?? http.Client();
  final http.Client _client;
  final String current;
  final Duration minInterval;

  /// When set, the last answer and its time survive restarts, so the check
  /// on app start hits GitHub at most once per [minInterval].
  final SharedPreferences? prefs;
  static const kCheckedAt = 'nv.update.checkedAt', kLast = 'nv.update.last', kNotified = 'nv.update.notified';
  DateTime? _lastAt;
  Map<String, dynamic>? _last;

  void _loadCache() {
    final p = prefs;
    if (p == null || _last != null) return;
    final at = p.getInt(kCheckedAt);
    final raw = p.getString(kLast);
    if (at == null || raw == null) return;
    try {
      final m = Map<String, dynamic>.from(jsonDecode(raw) as Map);
      final latest = '${m['latest'] ?? ''}';
      if (latest.isEmpty) return;
      // The app may have been updated since: compare against THIS build.
      m['current'] = current;
      m['available'] = isNewerVersion(latest, current);
      _last = m;
      _lastAt = DateTime.fromMillisecondsSinceEpoch(at);
    } catch (_) {}
  }

  /// True once per released version (the system notification).
  bool shouldNotify(String latest) {
    final p = prefs;
    if (p == null) return false;
    if (p.getString(kNotified) == latest) return false;
    unawaited(p.setString(kNotified, latest));
    return true;
  }

  /// `{current, latest, available, url, download_url, source}` (plus
  /// `apk_name`, `apk_size`, `sha256_url` when GitHub lists them) or null when
  /// neither GitHub nor the PC answered.
  Future<Map<String, dynamic>?> check({Future<Map<String, dynamic>> Function()? fallback, bool force = false}) async {
    _loadCache();
    if (!force && _last != null && _lastAt != null && DateTime.now().difference(_lastAt!) < minInterval) return _last;
    Map<String, dynamic>? r;
    try {
      final res = await _client.get(Uri.parse('https://api.github.com/repos/$githubRepo/releases/latest'),
          headers: const {'Accept': 'application/vnd.github+json', 'User-Agent': 'neovarch-remote'}).timeout(const Duration(seconds: 10));
      if (res.statusCode == 200) {
        r = parseGithubRelease(jsonDecode(res.body) as Map, current);
      }
    } catch (_) {}
    if (r == null && fallback != null) {
      try {
        final u = await fallback();
        final latest = '${u['latest'] ?? ''}';
        if (latest.isNotEmpty && latest != 'null') {
          r = {
            'current': current,
            'latest': latest,
            'available': isNewerVersion(latest, current),
            'url': '${u['url'] ?? releasesPage}',
            'download_url': '${u['download_url'] ?? u['url'] ?? releasesPage}',
            'source': 'pc',
          };
        }
      } catch (_) {}
    }
    if (r != null) {
      _last = r;
      _lastAt = DateTime.now();
      final p = prefs;
      if (p != null) {
        unawaited(p.setInt(kCheckedAt, _lastAt!.millisecondsSinceEpoch));
        unawaited(p.setString(kLast, jsonEncode(r)));
      }
    }
    return r ?? _last;
  }
}
