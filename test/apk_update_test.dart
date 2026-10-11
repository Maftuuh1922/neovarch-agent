// In-app APK update: streamed download with progress / size / SHA-256 checks,
// cancel, the install-permission round trip, and the browser fallback.
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:neovarch_agent/remote/apk_update.dart';
import 'package:neovarch_agent/remote/remote_controller.dart';
import 'package:neovarch_agent/remote/saved_desktops.dart';
import 'package:neovarch_agent/remote/update_check.dart';
import 'package:neovarch_agent/remote/ui/update_dialog.dart';
import 'package:shared_preferences/shared_preferences.dart';

List<int> _bytes(int n) => List<int>.generate(n, (i) => i % 251);

http.Client _serve(List<int> body, {int status = 200, bool withLength = true, List<int>? chunks}) => MockClient.streaming((req, _) async {
      final parts = <List<int>>[];
      final step = chunks?.first ?? 1024;
      for (var i = 0; i < body.length; i += step) {
        parts.add(body.sublist(i, i + step > body.length ? body.length : i + step));
      }
      return http.StreamedResponse(Stream.fromIterable(parts), status, contentLength: withLength ? body.length : null);
    });

class _FakeInstaller implements ApkInstaller {
  _FakeInstaller({this.allowed = true, this.fail = false});
  bool allowed;
  bool fail;
  int settingsOpened = 0;
  final installed = <String>[];
  @override
  Future<bool> canInstall() async => allowed;
  @override
  Future<void> openInstallPermissionSettings() async => settingsOpened++;
  @override
  Future<void> install(String path) async {
    if (fail) throw const ApkUpdateException('penginstal paket Android tidak ditemukan');
    installed.add(path);
  }
}

void main() {
  late Directory tmp;
  setUp(() async => tmp = await Directory.systemTemp.createTemp('nv_apk_'));
  tearDown(() async {
    if (await tmp.exists()) await tmp.delete(recursive: true);
  });

  group('downloadApk', () {
    test('streams to the file with progress and checks size + SHA-256', () async {
      final body = _bytes(10000);
      final seen = <(int, int?)>[];
      final f = await downloadApk(
        client: _serve(body),
        url: Uri.parse('https://x/app-arm64-v8a-release.apk'),
        dest: File('${tmp.path}/updates/a.apk'),
        expectedSize: body.length,
        expectedSha256: sha256.convert(body).toString(),
        onProgress: (r, t) => seen.add((r, t)),
      );
      expect(await f.readAsBytes(), body);
      expect(seen.first, (0, 10000));
      expect(seen.last, (10000, 10000));
      expect(seen.map((e) => e.$1).toList(), orderedEquals([...seen.map((e) => e.$1)]..sort()));
      expect(File('${f.path}.part').existsSync(), isFalse);
    });

    test('size mismatch, bad checksum, HTTP error → ApkUpdateException and no file left', () async {
      final body = _bytes(4096);
      final dest = File('${tmp.path}/u/b.apk');
      await expectLater(
          downloadApk(client: _serve(body, withLength: false), url: Uri.parse('https://x/b.apk'), dest: dest, expectedSize: 5000),
          throwsA(isA<ApkUpdateException>().having((e) => e.message, 'message', contains('tidak lengkap'))));
      await expectLater(downloadApk(client: _serve(body), url: Uri.parse('https://x/b.apk'), dest: dest, expectedSize: 5000),
          throwsA(isA<ApkUpdateException>().having((e) => e.message, 'message', contains('tidak cocok'))));
      await expectLater(downloadApk(client: _serve(body), url: Uri.parse('https://x/b.apk'), dest: dest, expectedSha256: 'ab' * 32),
          throwsA(isA<ApkUpdateException>().having((e) => e.message, 'message', contains('SHA-256'))));
      await expectLater(downloadApk(client: _serve(const [], status: 404), url: Uri.parse('https://x/b.apk'), dest: dest),
          throwsA(isA<ApkUpdateException>().having((e) => e.message, 'message', contains('404'))));
      expect(dest.existsSync(), isFalse);
      expect(File('${dest.path}.part').existsSync(), isFalse);
    });

    test('cancel mid-download → DownloadCancelled, partial file removed', () async {
      final ctl = StreamController<List<int>>();
      final client = MockClient.streaming((req, _) async => http.StreamedResponse(ctl.stream, 200, contentLength: 3000));
      final token = CancelToken();
      final dest = File('${tmp.path}/c/c.apk');
      final fut = downloadApk(
        client: client,
        url: Uri.parse('https://x/c.apk'),
        dest: dest,
        cancel: token,
        onProgress: (r, _) {
          if (r >= 1000) token.cancel();
        },
      );
      ctl.add(_bytes(1000));
      await expectLater(fut, throwsA(isA<DownloadCancelled>()));
      expect(dest.existsSync(), isFalse);
      expect(File('${dest.path}.part').existsSync(), isFalse);
      await ctl.close();
    });

    test('parseSha256: single hash file and SHA256SUMS', () {
      final h = 'a' * 64, g = 'b' * 64;
      expect(parseSha256('$h  app.apk\n'), h);
      expect(parseSha256('$h  other.apk\n$g  app-arm64-v8a-release.apk\n', fileName: 'app-arm64-v8a-release.apk'), g);
      expect(parseSha256('nope'), isNull);
    });
  });

  group('ApkUpdateController', () {
    final body = _bytes(8000);
    Map<String, dynamic> upd({String url = 'https://x/app-arm64-v8a-release.apk', int? size = 8000}) => {
          'latest': '1.4.6',
          'available': true,
          'url': 'https://github.com/Maftuuh1922/neovrach_Agent/releases/tag/v1.4.6',
          'download_url': url,
          'apk_size': ?size,
        };

    ApkUpdateController make(http.Client client, _FakeInstaller inst, List<Uri> opened, {bool supported = true}) => ApkUpdateController(
          client: client,
          installer: inst,
          dir: () async => Directory('${tmp.path}/updates'),
          openUrl: (u) async {
            opened.add(u);
            return true;
          },
          supported: supported,
        );

    test('Perbarui: download with progress, then the Android installer', () async {
      final inst = _FakeInstaller();
      final opened = <Uri>[];
      final c = make(_serve(body), inst, opened);
      final progress = <double?>[];
      c.addListener(() => progress.add(c.progress));
      await c.start(upd());
      expect(c.phase, ApkUpdatePhase.done);
      expect(inst.installed.single, endsWith('/updates/neovarch-1.4.6.apk'));
      expect(File(inst.installed.single).lengthSync(), 8000);
      expect(progress.whereType<double>().last, 1.0);
      expect(opened, isEmpty);
    });

    test('install permission missing → Settings, then resume installs', () async {
      final inst = _FakeInstaller(allowed: false);
      final opened = <Uri>[];
      final c = make(_serve(body), inst, opened);
      await c.start(upd());
      expect(c.phase, ApkUpdatePhase.needsPermission);
      expect(inst.settingsOpened, 1);
      expect(inst.installed, isEmpty);
      await c.resume(); // still not allowed: stays put
      expect(c.phase, ApkUpdatePhase.needsPermission);
      inst.allowed = true;
      await c.resume();
      expect(c.phase, ApkUpdatePhase.done);
      expect(inst.installed, hasLength(1));
    });

    test('download fails → browser fallback with the APK link', () async {
      final inst = _FakeInstaller();
      final opened = <Uri>[];
      final c = make(_serve(const [], status: 503), inst, opened);
      await c.start(upd());
      expect(c.phase, ApkUpdatePhase.failed);
      expect(c.error, contains('503'));
      expect(c.openedBrowser, isTrue);
      expect(opened.single.toString(), 'https://x/app-arm64-v8a-release.apk');
      expect(inst.installed, isEmpty);
    });

    test('installer cannot open → browser fallback', () async {
      final inst = _FakeInstaller(fail: true);
      final opened = <Uri>[];
      final c = make(_serve(body), inst, opened);
      await c.start(upd());
      expect(c.phase, ApkUpdatePhase.failed);
      expect(c.error, contains('penginstal'));
      expect(opened, hasLength(1));
    });

    test('no APK asset or not Android → straight to the browser, nothing downloaded', () async {
      var requests = 0;
      final client = MockClient((_) async {
        requests++;
        return http.Response('', 200);
      });
      final opened = <Uri>[];
      final page = make(client, _FakeInstaller(), opened);
      await page.start(upd(url: 'https://github.com/Maftuuh1922/neovrach_Agent/releases/tag/v1.4.6'));
      final ios = make(client, _FakeInstaller(), opened, supported: false);
      await ios.start(upd());
      expect(requests, 0);
      expect(opened, hasLength(2));
      expect(page.phase, ApkUpdatePhase.idle);
    });

    test('Batal during the download → cancelled, no browser, no install', () async {
      final ctl = StreamController<List<int>>();
      final inst = _FakeInstaller();
      final opened = <Uri>[];
      final c = make(MockClient.streaming((req, _) async => http.StreamedResponse(ctl.stream, 200, contentLength: 8000)), inst, opened);
      final fut = c.start(upd());
      ctl.add(_bytes(2000));
      for (var i = 0; i < 100 && c.received < 2000; i++) {
        await Future<void>.delayed(const Duration(milliseconds: 10));
      }
      expect(c.phase, ApkUpdatePhase.downloading);
      expect(c.progress, closeTo(0.25, 0.001));
      c.cancel();
      await fut;
      expect(c.phase, ApkUpdatePhase.cancelled);
      expect(opened, isEmpty);
      expect(inst.installed, isEmpty);
      await ctl.close();
    });

    test('SHA-256 from the release checksum asset is enforced', () async {
      final apkUrl = 'https://x/app-arm64-v8a-release.apk';
      final good = sha256.convert(body).toString();
      final client = MockClient.streaming((req, _) async {
        if (req.url.path.endsWith('.sha256')) {
          return http.StreamedResponse(Stream.value(utf8.encode('${'0' * 64}  app-arm64-v8a-release.apk\n')), 200);
        }
        return http.StreamedResponse(Stream.value(body), 200, contentLength: body.length);
      });
      final opened = <Uri>[];
      final c = make(client, _FakeInstaller(), opened);
      await c.start({...upd(url: apkUrl), 'apk_name': 'app-arm64-v8a-release.apk', 'sha256_url': '$apkUrl.sha256'});
      expect(c.phase, ApkUpdatePhase.failed);
      expect(c.error, contains('SHA-256'));
      expect(good, isNot('0' * 64));
    });
  });

  group('update check', () {
    test('release asset size + checksum are picked up', () {
      final u = parseGithubRelease({
        'tag_name': 'v1.4.6',
        'html_url': 'https://github.com/Maftuuh1922/neovrach_Agent/releases/tag/v1.4.6',
        'assets': [
          {'name': 'app-arm64-v8a-release.apk', 'size': 31000000, 'browser_download_url': 'https://x/arm64.apk'},
          {'name': 'app-arm64-v8a-release.apk.sha256', 'browser_download_url': 'https://x/arm64.apk.sha256'},
        ],
      }, '1.4.5')!;
      expect(u['available'], isTrue);
      expect(u['download_url'], 'https://x/arm64.apk');
      expect(u['apk_size'], 31000000);
      expect(u['sha256_url'], 'https://x/arm64.apk.sha256');
    });

    test('throttled across restarts (6 h, persisted) and notified once per version', () async {
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      var calls = 0;
      http.Client gh() => MockClient((_) async {
            calls++;
            return http.Response(jsonEncode({'tag_name': 'v1.4.6'}), 200);
          });
      final first = UpdateChecker(current: '1.4.5', client: gh(), prefs: prefs);
      expect((await first.check())!['available'], isTrue);
      expect(calls, 1);
      // "app restart": new checker, same prefs → cached, no request
      final second = UpdateChecker(current: '1.4.5', client: gh(), prefs: prefs);
      expect((await second.check())!['latest'], '1.4.6');
      expect(calls, 1);
      // after updating the app the cached answer is no longer "available"
      final updated = UpdateChecker(current: '1.4.6', client: gh(), prefs: prefs);
      expect((await updated.check())!['available'], isFalse);
      expect(calls, 1);
      // older than 6 h → asks again
      await prefs.setInt(UpdateChecker.kCheckedAt, DateTime.now().subtract(const Duration(hours: 7)).millisecondsSinceEpoch);
      await UpdateChecker(current: '1.4.5', client: gh(), prefs: prefs).check();
      expect(calls, 2);
      expect(second.shouldNotify('1.4.6'), isTrue);
      expect(second.shouldNotify('1.4.6'), isFalse);
    });

    test('RemoteController.start checks for updates even before pairing', () async {
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      final notified = <String>[];
      final r = RemoteController(SavedDesktops(prefs)..load())
        ..updateChecker = UpdateChecker(
            current: '1.4.5', prefs: prefs, client: MockClient((_) async => http.Response(jsonEncode({'tag_name': 'v1.4.6'}), 200)))
        ..onNewUpdate = (u) => notified.add('${u['latest']}');
      await r.start();
      for (var i = 0; i < 20 && r.update.isEmpty; i++) {
        await Future<void>.delayed(const Duration(milliseconds: 10));
      }
      expect(r.updateAvailable, isTrue);
      expect(notified, ['1.4.6']);
      await r.checkUpdate(force: true);
      expect(notified, ['1.4.6']); // once per version
    });
  });

  testWidgets('dialog: Perbarui → progress bar + Batal → Unduh lagi; permission step', (tester) async {
    final c = _ScriptedController();
    final u = {'latest': '1.4.6', 'available': true, 'download_url': 'https://x/app-arm64-v8a-release.apk', 'apk_size': 4000};
    await tester.pumpWidget(ProviderScope(
      overrides: [apkUpdateProvider.overrideWith((ref) => c)],
      child: MaterialApp(
        home: Builder(builder: (context) => Scaffold(body: TextButton(onPressed: () => showUpdateDialog(context, u), child: const Text('buka')))),
      ),
    ));
    await tester.tap(find.text('buka'));
    await tester.pumpAndSettle();
    expect(find.text('Pembaruan v1.4.6'), findsOneWidget);
    expect(find.textContaining('diunduh di dalam aplikasi'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('nv-update-start')));
    await tester.pump();
    expect(c.started, 1);
    expect(find.byKey(const ValueKey('nv-update-progress')), findsOneWidget);
    expect(find.textContaining('25%'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('nv-update-cancel')));
    await tester.pump();
    expect(find.text('Unduhan dibatalkan.'), findsOneWidget);
    expect(find.text('Unduh lagi'), findsOneWidget);
    c.phase = ApkUpdatePhase.needsPermission;
    c.notifyListeners();
    await tester.pump();
    expect(find.text('Buka Pengaturan'), findsOneWidget);
    expect(find.textContaining('Izinkan dari sumber ini'), findsOneWidget);
  });
}

/// Phases driven by hand (no I/O inside the widget test's fake clock).
class _ScriptedController extends ApkUpdateController {
  _ScriptedController() : super(supported: true, installer: _FakeInstaller(), openUrl: (_) async => true);
  int started = 0;
  @override
  Future<void> start(Map<String, dynamic> u) async {
    started++;
    version = '${u['latest']}';
    received = 1000;
    total = 4000;
    phase = ApkUpdatePhase.downloading;
    notifyListeners();
  }

  @override
  void cancel() {
    phase = ApkUpdatePhase.cancelled;
    notifyListeners();
  }
}
