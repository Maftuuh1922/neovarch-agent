// Changelog (release notes in the update dialog, "Apa yang baru", Riwayat
// perubahan, CHANGELOG.md in step), "Tentang aplikasi", and the lag work:
// throttled streamed tokens, screen-sized background decode, "Mode ringan".
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:neovarch_agent/data/gateway_client.dart';
import 'package:neovarch_agent/remote/apk_update.dart';
import 'package:neovarch_agent/remote/appearance.dart';
import 'package:neovarch_agent/remote/changelog.dart';
import 'package:neovarch_agent/remote/lite_mode.dart';
import 'package:neovarch_agent/remote/remote_controller.dart';
import 'package:neovarch_agent/remote/saved_desktops.dart';
import 'package:neovarch_agent/remote/update_check.dart';
import 'package:neovarch_agent/remote/ui/appearance/panel_tone.dart' show NvGlassFx;
import 'package:neovarch_agent/remote/ui/changelog_screen.dart';
import 'package:neovarch_agent/remote/ui/glass/liquid_glass.dart';
import 'package:neovarch_agent/remote/ui/lite_mode_panel.dart';
import 'package:neovarch_agent/remote/ui/nv_widgets.dart';
import 'package:neovarch_agent/remote/ui/remote_about_screen.dart';
import 'package:neovarch_agent/remote/ui/remote_background.dart';
import 'package:neovarch_agent/remote/ui/update_dialog.dart';
import 'package:neovarch_agent/state/settings_controller.dart';
import 'package:neovarch_agent/theme/neovarch_mobile_theme.dart';
import 'package:shared_preferences/shared_preferences.dart';

const _body = '''## Neovarch Agent 1.4.6

Rilis kecil.

### Sorotan

- **Pembaruan di aplikasi** dengan `progres`.
- Lihat [catatan](https://example.com).

### Pasang

- Linux: `curl … | sh`

### Unduhan

- Android: `neovarch-agent-android-universal.apk`

### Yang belum ada / perlu diketahui

- Belum diuji di banyak HP.
''';

void main() {
  tearDown(() {
    NV.liteMode = false;
    NvGlassFx.reduceTransparency.value = false;
    WhatsNew.pending = null;
    liteMemoryReader = readMemoryInfo;
  });

  group('changelog data', () {
    test('newest first, valid versions, only the top entry unreleased', () {
      expect(changelog, isNotEmpty);
      for (var i = 1; i < changelog.length; i++) {
        expect(isNewerVersion(changelog[i - 1].version, changelog[i].version), isTrue, reason: '${changelog[i - 1].version} > ${changelog[i].version}');
        expect(changelog[i].released, isTrue);
        expect(changelog[i].date, matches(RegExp(r'^\d{4}-\d{2}-\d{2}$')));
      }
      for (final e in changelog) {
        expect(e.sections, isNotEmpty);
        expect(e.summary.trim(), isNotEmpty);
      }
    });

    test('CHANGELOG.md lists the same versions and dates', () {
      final md = File('CHANGELOG.md').readAsStringSync();
      final heads = RegExp(r'^## \[([\d.]+)\] — (.+)$', multiLine: true).allMatches(md).map((m) => (m.group(1)!, m.group(2)!.trim())).toList();
      expect([for (final h in heads) h.$1], [for (final e in changelog) e.version]);
      for (final (i, e) in changelog.indexed) {
        expect(heads[i].$2, e.date ?? 'belum dirilis');
      }
    });

    test('no upstream brand names in the changelog', () {
      final all = [
        File('CHANGELOG.md').readAsStringSync(),
        for (final e in changelog) ...[e.summary, for (final s in e.sections) ...[s.title, ...s.items]],
      ].join('\n').toLowerCase();
      expect(all.contains('her' 'mes'), isFalse);
    });

    test('changelogFor ignores the build number; isUpcoming', () {
      expect(changelogFor('1.4.5+146')?.version, '1.4.5');
      expect(changelogFor('v1.3.0')?.version, '1.3.0');
      expect(changelogFor('9.9.9'), isNull);
      expect(isUpcoming(changelogFor('1.4.6')!, '1.4.5'), isTrue);
      expect(isUpcoming(changelogFor('1.4.5')!, '1.4.5'), isFalse);
    });
  });

  group('release notes', () {
    test('phone notes drop the title, install and download sections', () {
      final n = phoneReleaseNotes(_body);
      expect(n, isNot(contains('Neovarch Agent 1.4.6')));
      expect(n, isNot(contains('curl')));
      expect(n, isNot(contains('universal.apk')));
      expect(n, contains('### Sorotan'));
      expect(n, contains('Belum diuji di banyak HP.'));
      expect(phoneReleaseNotes(null), '');
      final long = phoneReleaseNotes('- ${'a' * 50}\n' * 200, maxChars: 300);
      expect(long.length, lessThan(320));
      expect(long.endsWith('…'), isTrue);
    });

    test('markdown-lite lines: headings, bullets, bold/code/links reduced', () {
      final lines = parseNoteLines(phoneReleaseNotes(_body));
      expect(lines.first.kind, 'text');
      expect(lines.where((l) => l.kind == 'heading').map((l) => l.text), ['Sorotan', 'Yang belum ada / perlu diketahui']);
      final b = lines.where((l) => l.kind == 'bullet').map((l) => l.text).toList();
      expect(b[0], 'Pembaruan di aplikasi dengan progres.');
      expect(b[1], 'Lihat catatan.');
    });

    test('parseGithubRelease carries the notes', () {
      final u = parseGithubRelease({'tag_name': 'v1.4.6', 'body': _body, 'assets': []}, '1.4.5')!;
      expect(u['notes'], contains('Pembaruan di aplikasi'));
      final none = parseGithubRelease({'tag_name': 'v1.4.6', 'assets': []}, '1.4.5')!;
      expect(none.containsKey('notes'), isFalse);
    });

    testWidgets('update dialog shows the release notes', (tester) async {
      final c = ApkUpdateController(supported: true, openUrl: (_) async => true);
      final u = {'latest': '1.4.6', 'available': true, 'download_url': 'https://x/app-arm64-v8a-release.apk', 'notes': phoneReleaseNotes(_body)};
      await tester.pumpWidget(ProviderScope(
        overrides: [apkUpdateProvider.overrideWith((ref) => c)],
        child: MaterialApp(
          home: Builder(builder: (context) => Scaffold(body: TextButton(onPressed: () => showUpdateDialog(context, u), child: const Text('buka')))),
        ),
      ));
      await tester.tap(find.text('buka'));
      await tester.pumpAndSettle();
      expect(find.text('CATATAN RILIS'), findsOneWidget);
      expect(find.byKey(const ValueKey('nv-release-notes')), findsOneWidget);
      expect(find.text('Pembaruan di aplikasi dengan progres.'), findsOneWidget);
      expect(find.textContaining('curl'), findsNothing);
      expect(tester.takeException(), isNull);
    });
  });

  group('Apa yang baru', () {
    test('fresh install: recorded, nothing shown', () async {
      SharedPreferences.setMockInitialValues({});
      final p = await SharedPreferences.getInstance();
      WhatsNew.prepare(p, '1.4.6');
      expect(WhatsNew.pending, isNull);
      expect(p.getString(WhatsNew.kSeen), '1.4.6');
    });

    test('existing install without the marker (updated from an older build): shown once', () async {
      SharedPreferences.setMockInitialValues({'nv.theme.base': 'dark'});
      final p = await SharedPreferences.getInstance();
      WhatsNew.prepare(p, '1.4.5');
      expect(WhatsNew.pending, '1.4.5');
      expect(WhatsNew.take(p)?.version, '1.4.5');
      expect(p.getString(WhatsNew.kSeen), '1.4.5');
      WhatsNew.prepare(p, '1.4.5');
      expect(WhatsNew.take(p), isNull);
    });

    test('update from an older version → owed; downgrade → not', () async {
      SharedPreferences.setMockInitialValues({WhatsNew.kSeen: '1.3.0'});
      final p = await SharedPreferences.getInstance();
      WhatsNew.prepare(p, '1.4.5');
      expect(WhatsNew.pending, '1.4.5');
      SharedPreferences.setMockInitialValues({WhatsNew.kSeen: '1.4.6'});
      final q = await SharedPreferences.getInstance();
      WhatsNew.prepare(q, '1.4.5');
      expect(WhatsNew.pending, isNull);
    });

    testWidgets('sheet shows the entry and opens Riwayat perubahan', (tester) async {
      tester.view.physicalSize = const Size(390 * 3, 844 * 3);
      tester.view.devicePixelRatio = 3;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(MaterialApp(
        home: Builder(builder: (context) => Scaffold(body: TextButton(onPressed: () => showWhatsNewSheet(context, changelogFor('1.4.5')!), child: const Text('buka')))),
      ));
      await tester.tap(find.text('buka'));
      await tester.pumpAndSettle();
      expect(find.text('Apa yang baru di v1.4.5'), findsOneWidget);
      expect(find.textContaining('Tiga widget layar utama'), findsOneWidget);
      await tester.dragUntilVisible(find.byKey(const ValueKey('whats-new-history')), find.byKey(const ValueKey('whats-new-sheet')), const Offset(0, -300));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('whats-new-history')));
      await tester.pumpAndSettle();
      expect(find.text('Riwayat perubahan'), findsOneWidget);
      expect(find.byKey(const ValueKey('changelog-1.4.6')), findsOneWidget);
      expect(find.text('belum dirilis'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });

  group('Tentang aplikasi', () {
    testWidgets('versions, links, licences, check for updates', (tester) async {
      tester.view.physicalSize = const Size(390 * 3, 1500 * 3);
      tester.view.devicePixelRatio = 3;
      addTearDown(tester.view.reset);
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      final r = _CheckController(SavedDesktops(prefs)..load())..serverInfo = {'version': '1.4.5'};
      final opened = <Uri>[];
      aboutLinkOpener = (u) async {
        opened.add(u);
        return true;
      };
      addTearDown(() => aboutLinkOpener = (u) async => true);
      await tester.pumpWidget(ProviderScope(
        overrides: [
          remoteProvider.overrideWith((ref) => r),
          apkUpdateProvider.overrideWith((ref) => ApkUpdateController(supported: true, openUrl: (_) async => true)),
        ],
        child: const MaterialApp(home: RemoteAboutScreen()),
      ));
      await tester.pump();
      expect(find.text('Tentang aplikasi'), findsOneWidget);
      expect(find.byKey(const ValueKey('about-app-version')), findsOneWidget);
      expect(find.descendant(of: find.byKey(const ValueKey('about-app-version')), matching: find.text('v${SettingsController.appVersion}')), findsOneWidget);
      expect(find.descendant(of: find.byKey(const ValueKey('about-pc-version')), matching: find.text('v1.4.5')), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('about-github')));
      await tester.tap(find.byKey(const ValueKey('about-landing')));
      expect(opened.map((u) => '$u'), [repoUrl, landingUrl]);

      await tester.tap(find.byKey(const ValueKey('about-check-update')));
      await tester.pump();
      await tester.pump();
      expect(r.forced, 1);
      expect(find.text('Versi baru tersedia: v9.0.0'), findsOneWidget);
      expect(find.byKey(const ValueKey('about-update-now')), findsOneWidget);
      expect(find.text('Perbarui'), findsOneWidget); // APK + Android → in-app

      await tester.tap(find.byKey(const ValueKey('about-licenses')));
      await tester.pump();
      await tester.pump(const Duration(seconds: 1));
      expect(find.byType(LicensePage), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });

  group('lag', () {
    test('streamed deltas tick the bubble (≤ ~30 fps), not the whole controller', () async {
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      final r = RemoteController(SavedDesktops(prefs)..load())..runtimeId = 's1';
      final old = RemoteController.streamFrame;
      RemoteController.streamFrame = const Duration(milliseconds: 30);
      addTearDown(() => RemoteController.streamFrame = old);
      var notifies = 0, ticks = 0;
      r.addListener(() => notifies++);
      r.streamTick.addListener(() => ticks++);
      r.debugEvent(const GatewayEventFrame('message.start', 's1', {}));
      expect(notifies, 1);
      for (var i = 0; i < 50; i++) {
        r.debugEvent(GatewayEventFrame('message.delta', 's1', {'text': 'w$i '}));
      }
      expect(notifies, 1, reason: 'no full rebuild per token');
      expect(ticks, 1, reason: 'first delta paints at once, the rest wait for the next frame');
      await Future<void>.delayed(const Duration(milliseconds: 80));
      expect(ticks, 2);
      expect(r.transcript.messages.last.content, startsWith('w0 w1 '));
      expect(r.transcript.messages.last.content, endsWith('w49 '));
      r.debugEvent(const GatewayEventFrame('message.complete', 's1', {}));
      expect(notifies, 2);
      // a delta that opens a new bubble (after a tool) is structural
      r.debugEvent(const GatewayEventFrame('message.start', 's1', {}));
      r.debugEvent(const GatewayEventFrame('tool.complete', 's1', {'tool_id': 't', 'name': 'x'}));
      final before = notifies;
      r.debugEvent(const GatewayEventFrame('message.delta', 's1', {'text': 'baru'}));
      expect(notifies, before + 1);
      r.dispose();
    });

    test('background decodes at cover size, never upscales', () {
      expect(CoverSizedImage.targetSize(4000, 3000, 1170, 2560), (3414, 2560));
      expect(CoverSizedImage.targetSize(3000, 4000, 1170, 2560), (1920, 2560));
      expect(CoverSizedImage.targetSize(800, 600, 1170, 2560), (800, 600));
      final c = CoverSizedImage.forScreen(const AssetImage('a.png'), const Size(390, 844), 3);
      expect((c.width, c.height), (1216, 2560));
      expect(CoverSizedImageKey('a', 1, 2), CoverSizedImageKey('a', 1, 2));
    });

    testWidgets('background image is wrapped in CoverSizedImage', (tester) async {
      SharedPreferences.setMockInitialValues({'nv.bg.source': 'asset:assets/art/feat-remote.webp'});
      final prefs = await SharedPreferences.getInstance();
      final look = AppearanceController(prefs);
      await tester.pumpWidget(ProviderScope(
        overrides: [appearanceProvider.overrideWith((ref) => look)],
        child: const MaterialApp(home: NvAppBackground()),
      ));
      final img = tester.widget<Image>(find.byType(Image));
      expect(img.image, isA<CoverSizedImage>());
      expect(find.descendant(of: find.byType(IgnorePointer), matching: find.byType(RepaintBoundary)), findsWidgets);
    });

    test('Mode ringan: persisted, applied app-wide, reduces transparency', () async {
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      final look = AppearanceController(prefs);
      expect(look.liteMode, isFalse);
      final rev = look.revision;
      look.setLiteMode(true);
      expect(NV.liteMode, isTrue);
      expect(NvGlassFx.reduceTransparency.value, isTrue);
      expect(prefs.getBool(AppearanceController.kLite), isTrue);
      expect(look.revision, rev + 1);
      expect(AppearanceController(prefs).liteMode, isTrue);
      look.setLiteMode(false);
      expect(NV.liteMode, isFalse);
      expect(NvGlassFx.reduceTransparency.value, isFalse);
    });

    testWidgets('Mode ringan: NvGlass and LiquidGlass drop the backdrop blur', (tester) async {
      Future<void> show(Widget w) => tester.pumpWidget(MaterialApp(home: Scaffold(body: Center(child: SizedBox(width: 200, height: 60, child: w)))));
      await show(const NvGlass(child: Text('kaca')));
      expect(find.byType(BackdropFilter), findsOneWidget);
      NV.liteMode = true;
      await show(const NvGlass(key: ValueKey('lite'), child: Text('kaca')));
      expect(find.byType(BackdropFilter), findsNothing);
      expect(find.text('kaca'), findsOneWidget);
      await show(const LiquidGlass(child: Text('gelembung')));
      expect(find.byType(BackdropFilter), findsNothing);
      expect(find.text('gelembung'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('Mode ringan switch in Tampilan', (tester) async {
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      final look = AppearanceController(prefs);
      await tester.pumpWidget(ProviderScope(
        overrides: [appearanceProvider.overrideWith((ref) => look)],
        child: const MaterialApp(home: Scaffold(body: LiteModePanel())),
      ));
      expect(find.text('Mode ringan'), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('lite-mode')));
      await tester.pump();
      expect(look.liteMode, isTrue);
      expect(find.textContaining('Aktif: efek kaca'), findsOneWidget);
    });

    test('low-RAM detection and a one-time suggestion', () async {
      expect(isLowRam(null), isFalse);
      expect(isLowRam({'low_ram': true, 'total': 8 << 30}), isTrue);
      expect(isLowRam({'total': 3900000000}), isTrue);
      expect(isLowRam({'total': 7800000000}), isFalse);
      expect(ramLabel({'total': 3 << 30}), '3,0 GB');
      SharedPreferences.setMockInitialValues({});
      final p = await SharedPreferences.getInstance();
      Future<Map?> small() async => {'total': 3 << 30, 'low_ram': false};
      expect(await liteSuggestion(p, liteOn: true, read: small), isNull);
      expect(await liteSuggestion(p, liteOn: false, read: small), isNotNull);
      expect(await liteSuggestion(p, liteOn: false, read: small), isNull, reason: 'once per install');
    });

    testWidgets('suggestion snackbar turns Mode ringan on', (tester) async {
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      final look = AppearanceController(prefs);
      liteMemoryReader = () async => {'total': 3 << 30};
      await tester.pumpWidget(ProviderScope(
        overrides: [appearanceProvider.overrideWith((ref) => look)],
        child: MaterialApp(
          home: Scaffold(
            body: Consumer(builder: (context, ref, _) => TextButton(onPressed: () => maybeSuggestLiteMode(context, ref), child: const Text('cek'))),
          ),
        ),
      ));
      await tester.tap(find.text('cek'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));
      expect(find.textContaining('HP ini punya RAM 3,0 GB'), findsOneWidget);
      await tester.tap(find.text('Aktifkan'));
      await tester.pump();
      expect(look.liteMode, isTrue);
      await tester.pumpAndSettle(const Duration(seconds: 13));
    });
  });

}

/// checkUpdate(force) answers a newer APK release without the network.
class _CheckController extends RemoteController {
  _CheckController(super.desktops);
  int forced = 0;
  @override
  Future<void> checkUpdate({bool force = false}) async {
    if (force) forced++;
    update = {'latest': '9.0.0', 'available': true, 'download_url': 'https://x/app-arm64-v8a-release.apk', 'url': 'https://x'};
    notifyListeners();
  }
}

