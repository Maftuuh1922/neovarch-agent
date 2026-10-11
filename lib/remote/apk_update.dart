// In-app APK update for the Android phone app: download the release APK
// inside the app (progress + cancel), check its size (and SHA-256 when the
// release ships a checksum), then hand it to the Android package installer
// through the "neovarch/device" channel (FileProvider + ACTION_VIEW in
// MainActivity.kt). Any failure falls back to opening the download in the
// browser, as before.
import 'dart:async';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../data/device_tools.dart' show deviceCall;
import 'update_check.dart' show releasesPage;

/// A problem worth showing to the user (Indonesian message).
class ApkUpdateException implements Exception {
  const ApkUpdateException(this.message);
  final String message;
  @override
  String toString() => message;
}

/// The user pressed "Batal" during the download.
class DownloadCancelled implements Exception {
  const DownloadCancelled();
  @override
  String toString() => 'Unduhan dibatalkan';
}

class CancelToken {
  bool _cancelled = false;
  final _listeners = <void Function()>[];
  bool get isCancelled => _cancelled;
  void cancel() {
    if (_cancelled) return;
    _cancelled = true;
    for (final l in List.of(_listeners)) {
      l();
    }
  }

  void _onCancel(void Function() l) => _listeners.add(l);
}

class _DigestSink implements Sink<Digest> {
  Digest? value;
  @override
  void add(Digest data) => value = data;
  @override
  void close() {}
}

/// First 64-hex token of a `.sha256` / `SHA256SUMS` body; with several lines
/// the one naming [fileName] wins.
String? parseSha256(String body, {String? fileName}) {
  final hex = RegExp(r'\b([a-fA-F0-9]{64})\b');
  final lines = body.split('\n');
  if (fileName != null) {
    for (final l in lines) {
      if (l.contains(fileName)) {
        final m = hex.firstMatch(l);
        if (m != null) return m.group(1)!.toLowerCase();
      }
    }
  }
  return hex.firstMatch(body)?.group(1)?.toLowerCase();
}

/// Streams [url] into [dest] (through `<dest>.part`, renamed when complete).
/// [onProgress] gets (received, total) where total is the server's
/// Content-Length or [expectedSize]. Throws [DownloadCancelled] or
/// [ApkUpdateException]; a partial file never stays behind.
Future<File> downloadApk({
  required http.Client client,
  required Uri url,
  required File dest,
  int? expectedSize,
  String? expectedSha256,
  void Function(int received, int? total)? onProgress,
  CancelToken? cancel,
  Duration connectTimeout = const Duration(seconds: 30),
  Duration idleTimeout = const Duration(seconds: 60),
}) async {
  if (cancel?.isCancelled ?? false) throw const DownloadCancelled();
  final part = File('${dest.path}.part');
  await dest.parent.create(recursive: true);
  if (await part.exists()) await part.delete();
  IOSink? out;
  StreamSubscription<List<int>>? sub;
  try {
    final req = http.Request('GET', url)..headers['User-Agent'] = 'neovarch-remote';
    final res = await client.send(req).timeout(connectTimeout, onTimeout: () => throw const ApkUpdateException('Server tidak menjawab'));
    if (cancel?.isCancelled ?? false) throw const DownloadCancelled();
    if (res.statusCode != 200) throw ApkUpdateException('Server membalas HTTP ${res.statusCode}');
    final total = (res.contentLength != null && res.contentLength! > 0) ? res.contentLength : expectedSize;
    if (expectedSize != null && res.contentLength != null && res.contentLength! > 0 && res.contentLength != expectedSize) {
      throw const ApkUpdateException('Ukuran berkas di server tidak cocok dengan rilis');
    }
    final sink = _DigestSink();
    final hasher = expectedSha256 != null ? sha256.startChunkedConversion(sink) : null;
    out = part.openWrite();
    var received = 0;
    onProgress?.call(0, total);
    final done = Completer<void>();
    Timer? idle;
    void resetIdle() {
      idle?.cancel();
      idle = Timer(idleTimeout, () {
        if (!done.isCompleted) done.completeError(const ApkUpdateException('Unduhan macet — koneksi terputus'));
      });
    }

    resetIdle();
    sub = res.stream.listen(
      (chunk) {
        out!.add(chunk);
        hasher?.add(chunk);
        received += chunk.length;
        resetIdle();
        onProgress?.call(received, total);
      },
      onError: (Object e) {
        if (!done.isCompleted) done.completeError(ApkUpdateException('Unduhan terputus: $e'));
      },
      onDone: () {
        if (!done.isCompleted) done.complete();
      },
      cancelOnError: true,
    );
    cancel?._onCancel(() {
      if (!done.isCompleted) done.completeError(const DownloadCancelled());
    });
    try {
      await done.future;
    } finally {
      idle?.cancel();
    }
    await out.flush();
    await out.close();
    out = null;
    hasher?.close();
    if (total != null && received != total) {
      throw ApkUpdateException('Unduhan tidak lengkap ($received dari $total byte)');
    }
    if (received == 0) throw const ApkUpdateException('Berkas kosong');
    if (expectedSha256 != null && sink.value.toString() != expectedSha256.toLowerCase()) {
      throw const ApkUpdateException('Checksum SHA-256 tidak cocok — berkas rusak');
    }
    if (await dest.exists()) await dest.delete();
    return await part.rename(dest.path);
  } catch (e) {
    await sub?.cancel();
    try {
      await out?.close();
    } catch (_) {}
    try {
      if (await part.exists()) await part.delete();
    } catch (_) {}
    if (e is DownloadCancelled || e is ApkUpdateException) rethrow;
    throw ApkUpdateException('Gagal mengunduh: $e');
  }
}

/// The Android side of an install (MainActivity.kt, "neovarch/device").
abstract class ApkInstaller {
  /// "Instal aplikasi tidak dikenal" allowed for this app (always true < Android 8).
  Future<bool> canInstall();

  /// Opens Settings → Instal aplikasi tidak dikenal for this app.
  Future<void> openInstallPermissionSettings();

  /// Launches the system package installer for [path] (inside cache/updates).
  Future<void> install(String path);
}

class ChannelApkInstaller implements ApkInstaller {
  const ChannelApkInstaller();
  @override
  Future<bool> canInstall() async => await deviceCall<bool>('canInstallApks') ?? false;
  @override
  Future<void> openInstallPermissionSettings() => deviceCall<bool>('openInstallSourcesSettings');
  @override
  Future<void> install(String path) async {
    final r = await deviceCall<String>('installApk', {'path': path});
    if (r != null && r != 'dibuka') throw ApkUpdateException(r);
  }
}

enum ApkUpdatePhase { idle, downloading, needsPermission, installing, done, failed, cancelled }

bool get _isAndroid => !kIsWeb && defaultTargetPlatform == TargetPlatform.android;

Future<Directory> _defaultDir() async => Directory('${(await getTemporaryDirectory()).path}/updates');

Future<bool> _openBrowser(Uri u) => launchUrl(u, mode: LaunchMode.externalApplication);

/// One update at a time; outlives the dialog so closing it does not stop
/// the download.
class ApkUpdateController extends ChangeNotifier {
  ApkUpdateController({
    http.Client? client,
    ApkInstaller? installer,
    Future<Directory> Function()? dir,
    Future<bool> Function(Uri url)? openUrl,
    bool? supported,
  })  : _supported = supported, // ignore: prefer_initializing_formals
        _client = client ?? http.Client(),
        _installer = installer ?? const ChannelApkInstaller(),
        _dir = dir ?? _defaultDir,
        _openUrl = openUrl ?? _openBrowser;

  final http.Client _client;
  final ApkInstaller _installer;
  final Future<Directory> Function() _dir;
  final Future<bool> Function(Uri url) _openUrl;
  final bool? _supported;
  bool get supported => _supported ?? _isAndroid;

  ApkUpdatePhase phase = ApkUpdatePhase.idle;
  int received = 0;
  int? total;
  String? error;
  String? version;
  File? file;

  /// True when the failure path opened the browser.
  bool openedBrowser = false;
  CancelToken? _cancel;
  Map<String, dynamic>? _update;

  bool get busy => phase == ApkUpdatePhase.downloading || phase == ApkUpdatePhase.installing;
  double? get progress => (total == null || total == 0) ? null : (received / total!).clamp(0.0, 1.0);

  void _set(ApkUpdatePhase p, {String? err}) {
    phase = p;
    error = err;
    notifyListeners();
  }

  static bool isApkUrl(String url) => Uri.tryParse(url)?.path.toLowerCase().endsWith('.apk') ?? false;

  /// Release page for the browser fallback.
  static Uri fallbackUri(Map<String, dynamic> u) {
    final dl = '${u['download_url'] ?? ''}';
    final page = '${u['url'] ?? ''}';
    return Uri.parse(dl.isNotEmpty && dl != 'null' ? dl : (page.isNotEmpty && page != 'null' ? page : releasesPage));
  }

  Future<void> _fallback(Map<String, dynamic> u) async {
    try {
      openedBrowser = await _openUrl(fallbackUri(u));
    } catch (_) {
      openedBrowser = false;
    }
  }

  /// "Perbarui": download, verify, install. Without an APK asset or off
  /// Android it just opens the browser (old behaviour).
  Future<void> start(Map<String, dynamic> u) async {
    if (busy) return;
    _update = u;
    version = '${u['latest'] ?? ''}';
    openedBrowser = false;
    received = 0;
    total = null;
    final url = '${u['download_url'] ?? ''}';
    if (!supported || !isApkUrl(url)) {
      await _fallback(u);
      _set(ApkUpdatePhase.idle);
      return;
    }
    final size = u['apk_size'] is int ? u['apk_size'] as int : null;
    try {
      final dir = await _dir();
      final name = 'neovarch-${version!.replaceAll(RegExp(r'[^0-9A-Za-z.\-]'), '_')}.apk';
      final dest = File('${dir.path}/$name');
      // Already downloaded (e.g. the user left for Settings and came back).
      if (size != null && await dest.exists() && await dest.length() == size && u['sha256_url'] == null) {
        file = dest;
        received = size;
        total = size;
      } else {
        _cancel = CancelToken();
        _set(ApkUpdatePhase.downloading);
        String? sha;
        final shaUrl = u['sha256_url'];
        if (shaUrl is String && shaUrl.isNotEmpty) {
          try {
            final r = await _client.get(Uri.parse(shaUrl)).timeout(const Duration(seconds: 15));
            if (r.statusCode == 200) sha = parseSha256(r.body, fileName: '${u['apk_name'] ?? ''}'.isEmpty ? null : '${u['apk_name']}');
          } catch (_) {}
        }
        file = await downloadApk(
          client: _client,
          url: Uri.parse(url),
          dest: dest,
          expectedSize: size,
          expectedSha256: sha,
          cancel: _cancel,
          onProgress: (r, t) {
            received = r;
            total = t;
            notifyListeners();
          },
        );
      }
    } on DownloadCancelled {
      _set(ApkUpdatePhase.cancelled);
      return;
    } catch (e) {
      await _fallback(u);
      _set(ApkUpdatePhase.failed, err: e is ApkUpdateException ? e.message : '$e');
      return;
    } finally {
      _cancel = null;
    }
    await _install();
  }

  Future<void> _install() async {
    final f = file;
    final u = _update ?? const {};
    if (f == null) return;
    try {
      if (!await _installer.canInstall()) {
        _set(ApkUpdatePhase.needsPermission);
        await _installer.openInstallPermissionSettings();
        return;
      }
      _set(ApkUpdatePhase.installing);
      await _installer.install(f.path);
      _set(ApkUpdatePhase.done);
    } catch (e) {
      await _fallback(u);
      _set(ApkUpdatePhase.failed, err: e is ApkUpdateException ? e.message : 'Penginstal tidak bisa dibuka: $e');
    }
  }

  /// Back from Settings: install when the permission is now granted.
  Future<void> resume() async {
    if (phase != ApkUpdatePhase.needsPermission) return;
    try {
      if (await _installer.canInstall()) await _install();
    } catch (_) {}
  }

  /// "Buka Pengaturan" again from the permission step.
  Future<void> openPermissionSettings() async {
    try {
      await _installer.openInstallPermissionSettings();
    } catch (_) {}
  }

  void cancel() => _cancel?.cancel();

  /// Back to the start state (dialog closed after a final phase).
  void reset() {
    if (busy || phase == ApkUpdatePhase.needsPermission) return;
    phase = ApkUpdatePhase.idle;
    error = null;
    notifyListeners();
  }
}

/// System notification for a new version (Android, existing "notify"
/// bridge; silently skipped without POST_NOTIFICATIONS). Tapping it opens
/// the app on the "update" route → the update dialog.
void notifyUpdateAvailable(Map<String, dynamic> u) {
  if (!_isAndroid) return;
  unawaited(deviceCall<String>('notify', {
    'title': 'Pembaruan Neovarch Agent',
    'body': 'Versi v${u['latest']} tersedia. Ketuk untuk memperbarui langsung di aplikasi.',
    'route': 'update',
  }).catchError((_) => null));
}

String formatMb(int bytes) => (bytes / (1024 * 1024)).toStringAsFixed(1).replaceAll('.', ',');
