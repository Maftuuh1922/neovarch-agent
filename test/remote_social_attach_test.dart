// Profil & Teman (GitHub via the PC) and chat attachments on the phone:
// models, the REST client (multipart upload with progress, social routes), the
// controller's attachment flow, and the screens (attach sheet, thumbnails with
// progress + remove, attachments in bubbles + preview, profile card, heatmap,
// friend list coding-first, friend detail). Run with --update-goldens and
// NV_SHOTS_DIR=… to write screenshots.
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:neovarch_agent/models/models.dart';
import 'package:neovarch_agent/remote/appearance.dart';
import 'package:neovarch_agent/remote/attachments.dart';
import 'package:neovarch_agent/remote/remote_controller.dart';
import 'package:neovarch_agent/remote/remote_gateway.dart';
import 'package:neovarch_agent/remote/remote_transcript.dart';
import 'package:neovarch_agent/remote/saved_desktops.dart';
import 'package:neovarch_agent/remote/social_models.dart';
import 'package:neovarch_agent/remote/ui/remote_app.dart' show neovarchMobileTheme;
import 'package:neovarch_agent/remote/ui/remote_attachments.dart';
import 'package:neovarch_agent/remote/ui/remote_chat_screen.dart';
import 'package:neovarch_agent/remote/ui/remote_social_screen.dart';
import 'package:neovarch_agent/state/app_controller.dart' show settingsProvider;
import 'package:neovarch_agent/state/settings_controller.dart';

final _shotsDir = Platform.environment['NV_SHOTS_DIR'] ?? 'build/screenshots/remote';
final _png = base64Decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==');

Map<String, dynamic> _profileJson({bool coding = true}) {
  final counts = List<int>.generate(365, (i) => (i * 7 + 3) % 11 < 4 ? 0 : (i * 13) % 9);
  return {
    'login': 'aku',
    'name': 'Aku Dev',
    'bio': 'Ngoding Flutter & Python tiap hari.',
    'avatar_url': null,
    'html_url': 'https://github.com/aku',
    'heatmap': {'start': '2025-10-10', 'end': '2026-10-09', 'days': 365, 'counts': counts, 'total': counts.fold<int>(0, (a, b) => a + b), 'active_days': counts.where((c) => c > 0).length, 'streak': 6, 'max': 8},
    'stack': {
      'languages': [
        {'name': 'Python', 'share': 0.41, 'source': 'both'},
        {'name': 'Dart', 'share': 0.27, 'source': 'agent'},
        {'name': 'TypeScript', 'share': 0.18, 'source': 'github'},
        {'name': 'Shell', 'share': 0.08},
      ],
      'tools': [
        {'name': 'shell', 'share': 0.4, 'count': 120},
        {'name': 'edit_file', 'share': 0.3, 'count': 90},
      ],
    },
    'status': {'coding': coding, 'last_active_at': DateTime.now().toUtc().toIso8601String(), 'project': coding ? 'neovarch' : null},
    'publish': {'paused': false, 'last_published_at': DateTime.now().toUtc().toIso8601String()},
  };
}

Map<String, dynamic> _friendsJson() => {
      'signed_in': true,
      'friends': [
        {'login': 'zed', 'name': 'Zed', 'coding': false, 'has_neovarch': false},
        {'login': 'sari', 'name': 'Sari Wulandari', 'coding': false, 'has_neovarch': true, 'last_active_at': DateTime.now().subtract(const Duration(hours: 3)).toUtc().toIso8601String(), 'top_stack': ['Go', 'Rust']},
        {'login': 'budi', 'name': 'Budi Santoso', 'coding': true, 'has_neovarch': true, 'project': 'toko-online', 'last_active_at': DateTime.now().toUtc().toIso8601String(), 'top_stack': ['Dart', 'Kotlin']},
        {'login': 'rina', 'name': 'Rina', 'coding': true, 'has_neovarch': true, 'last_active_at': DateTime.now().subtract(const Duration(minutes: 2)).toUtc().toIso8601String(), 'top_stack': ['TypeScript']},
      ],
      'pending': [
        {'login': 'tono'},
      ],
    };

class _Recorder {
  final requests = <http.BaseRequest>[];
  final bodies = <String>[];
}

RemoteGateway _gateway(_Recorder rec, {int uploadStatus = 200, bool oldCore = false}) => RemoteGateway(
      baseUrl: 'http://192.168.1.20:9319',
      token: 'tok-123',
      autoReconnect: false,
      httpClient: MockClient.streaming((req, body) async {
        rec.requests.add(req);
        final bytes = await body.toBytes();
        rec.bodies.add(latin1.decode(bytes));
        final path = req.url.path;
        Object out = {};
        var status = 200;
        if (path == '/api/uploads' && req.method == 'POST') {
          status = uploadStatus;
          out = oldCore
              // the quiet compat catch-all of a core without the route
              ? {'ok': false, 'available': false, 'message': 'Belum tersedia di Neovarch core.', 'detail': 'Belum tersedia di Neovarch core.', 'name': 'uploads', 'pid': 0}
              : uploadStatus == 200
              ? {'id': 'abcdef123456', 'name': 'foto.png', 'mime': 'image/png', 'size': 67, 'kind': 'image', 'url': '/api/uploads/abcdef123456'}
              : {'detail': 'File terlalu besar (maks 25 MB).'};
        } else if (path == '/api/social/status') {
          out = {'signed_in': true, 'login': 'aku'};
        } else if (path == '/api/social/profile') {
          out = _profileJson();
        } else if (path == '/api/social/friends') {
          out = _friendsJson();
        } else if (path == '/api/social/friends/budi') {
          out = {..._friendsJson()['friends'][2] as Map, 'mutual': true, 'profile': {..._profileJson(), 'login': 'budi', 'name': 'Budi Santoso'}};
        } else if (path.startsWith('/api/uploads/') && req.method == 'DELETE') {
          out = {'ok': true};
        }
        return http.StreamedResponse(Stream.value(utf8.encode(jsonEncode(out))), status, headers: {'content-type': 'application/json'});
      }),
    );

void main() {
  group('models', () {
    test('heatmap levels and Sunday-first weeks', () {
      expect([0, 1, 2, 3, 4].map((c) => SocialHeatmap.level(c, 4)), [0, 1, 2, 3, 4]);
      expect(SocialHeatmap.level(3, 0), 0);
      // 2026-10-07 is a Wednesday -> 3 padding cells
      final w = const SocialHeatmap(start: '2026-10-07', end: '2026-10-09', counts: [1, 2, 3]).weeks();
      expect(w.length, 1);
      expect(w.first, [-1, -1, -1, 1, 2, 3, -1]);
      final full = SocialHeatmap.fromJson(_profileJson()['heatmap'] as Map<String, dynamic>);
      expect(full.counts.length, 365);
      expect(full.weeks().length, inInclusiveRange(52, 54));
    });

    test('friends are sorted "lagi ngoding" first, then Neovarch users by recency', () {
      final s = FriendsSnapshot.fromJson(_friendsJson());
      expect(s.friends.map((f) => f.login), ['budi', 'rina', 'sari', 'zed']);
      expect(s.codingCount, 2);
      expect(s.pending, ['tono']);
    });

    test('profile parses stack, status and publish state', () {
      final p = SocialProfile.fromJson(_profileJson());
      expect(p.displayName, 'Aku Dev');
      expect(p.languages.first.name, 'Python');
      expect(p.tools.first.count, 120);
      expect(p.status!.coding, isTrue);
      expect(p.status!.project, 'neovarch');
    });

    test('attachment helpers', () {
      expect(sniffImageMime(_png), 'image/png');
      expect(sniffImageMime([0xFF, 0xD8, 0xFF, 0]), 'image/jpeg');
      expect(mimeForName('laporan.PDF'), 'application/pdf');
      expect(humanSize(2 * 1024 * 1024 + 1), '2.0 MB');
      final a = RemoteAttachment.fromJson({'id': 'x', 'name': 'a.png', 'mime': 'image/png', 'kind': 'image', 'size': 3});
      expect(a.isImage, isTrue);
      expect(RemoteAttachment.fromJson(a.toJson()).name, 'a.png');
    });

    test('history messages keep their attachments', () {
      final msgs = RemoteTranscript.fromGatewayMessages([
        {'role': 'user', 'text': 'lihat ini', 'attachments': [{'id': 'u1', 'name': 'layar.png', 'kind': 'image', 'url': '/api/uploads/u1'}]},
        {'role': 'assistant', 'text': 'ok'},
      ]);
      expect(msgs.first.attachments.single['id'], 'u1');
    });
  });

  group('REST client', () {
    test('multipart upload with session id, token headers and progress', () async {
      final rec = _Recorder();
      final g = _gateway(rec);
      final progress = <double>[];
      final bytes = Uint8List.fromList(List<int>.generate(200 * 1024, (i) => i % 251));
      final a = await g.uploadAttachment(sessionId: 's-1', name: 'foto.png', mime: 'image/png', bytes: bytes, onProgress: progress.add);
      expect(a.id, 'abcdef123456');
      expect(a.isImage, isTrue);
      final req = rec.requests.single;
      expect(req.url.toString(), 'http://192.168.1.20:9319/api/uploads');
      expect(req.headers['Authorization'], 'Bearer tok-123');
      expect(req.headers['X-Neovarch-Session-Token'], 'tok-123');
      expect(req.headers['content-type'], startsWith('multipart/form-data'));
      expect(rec.bodies.single, contains('name="session_id"'));
      expect(rec.bodies.single, contains('filename="foto.png"'));
      expect(progress.length, greaterThan(2));
      expect(progress.last, 1.0);
      expect(g.downloadUri(a).toString(), 'http://192.168.1.20:9319/api/uploads/abcdef123456?download=1&token=tok-123');
      await g.close();
    });

    test('upload refuses > 25 MB locally and maps 413 from the PC', () async {
      final g = _gateway(_Recorder(), uploadStatus: 413);
      await expectLater(
        g.uploadAttachment(sessionId: 's', name: 'big.bin', mime: 'x/y', bytes: Uint8List(kMaxAttachmentBytes + 1)),
        throwsA(isA<RemoteRestError>().having((e) => e.status, 'status', 413)),
      );
      await expectLater(
        g.uploadAttachment(sessionId: 's', name: 'a.bin', mime: 'x/y', bytes: Uint8List(10)),
        throwsA(isA<RemoteRestError>().having((e) => e.message, 'message', contains('25 MB'))),
      );
      await g.close();
    });

    test('a core without the upload route (fake 200 {name: uploads}) is an error, not a 0 B attachment', () async {
      final g = _gateway(_Recorder(), oldCore: true);
      await expectLater(
        g.uploadAttachment(sessionId: 's', name: 'scaled_1000.jpg', mime: 'image/jpeg', bytes: Uint8List.fromList(_png)),
        throwsA(isA<RemoteRestError>().having((e) => e.message, 'message', contains('PC belum mendukung lampiran'))),
      );
      await g.close();
    });

    test('social routes through the PC', () async {
      final rec = _Recorder();
      final g = _gateway(rec);
      expect((await g.socialStatus())['signed_in'], isTrue);
      expect((await g.socialProfile()).login, 'aku');
      expect((await g.socialFriends()).friends.first.login, 'budi');
      final d = await g.socialFriend('budi');
      expect(d.mutual, isTrue);
      expect(d.profile!.name, 'Budi Santoso');
      expect(rec.requests.map((r) => r.url.path), ['/api/social/status', '/api/social/profile', '/api/social/friends', '/api/social/friends/budi']);
      await g.close();
    });
  });

  group('controller', () {
    late SharedPreferences prefs;
    setUp(() async {
      SharedPreferences.setMockInitialValues({});
      prefs = await SharedPreferences.getInstance();
    });

    test('addAttachment uploads with progress, removeAttachment deletes it on the PC', () async {
      final rec = _Recorder();
      final r = RemoteController(SavedDesktops(prefs)..load())
        ..gateway = _gateway(rec)
        ..status = RemoteStatus.connected
        ..runtimeId = 'rt-1';
      final err = await r.addAttachment('foto.png', Uint8List.fromList(_png));
      expect(err, isNull);
      final p = r.pendingAttachments.single;
      expect(p.state, AttachState.done);
      expect(p.mime, 'image/png');
      expect(p.remote!.id, 'abcdef123456');
      r.removeAttachment(p.localId);
      expect(r.pendingAttachments, isEmpty);
      await Future<void>.delayed(const Duration(milliseconds: 10));
      expect(rec.requests.last.method, 'DELETE');
      expect(await r.addAttachment('besar.bin', Uint8List(kMaxAttachmentBytes + 1)), contains('25 MB'));
    });

    test('old core: the photo is marked failed and nothing "uploads · 0 B" is sent', () async {
      final rec = _Recorder();
      final r = RemoteController(SavedDesktops(prefs)..load())
        ..gateway = _gateway(rec, oldCore: true)
        ..status = RemoteStatus.connected
        ..runtimeId = 'rt-1';
      final err = await r.addAttachment('scaled_1000.jpg', Uint8List.fromList(_png), mime: 'image/jpeg');
      expect(err, contains('PC belum mendukung lampiran'));
      final p = r.pendingAttachments.single;
      expect(p.state, AttachState.failed);
      expect(p.remote, isNull);
    });

    test('refreshSocial fills profile + friends; social.changed refreshes', () async {
      final rec = _Recorder();
      final r = RemoteController(SavedDesktops(prefs)..load())
        ..gateway = _gateway(rec)
        ..status = RemoteStatus.connected;
      await r.refreshSocial();
      expect(r.socialSignedIn, isTrue);
      expect(r.socialProfile!.login, 'aku');
      expect(r.socialFriends!.codingCount, 2);
      expect(r.socialError, isNull);
    });
  });

  group('screens', () {
    late SharedPreferences prefs;
    late SettingsController settings;

    setUpAll(() async {
      TestWidgetsFlutterBinding.ensureInitialized();
      final manifest = jsonDecode(await rootBundle.loadString('FontManifest.json')) as List;
      for (final f in manifest.cast<Map<String, dynamic>>()) {
        final loader = FontLoader(f['family'] as String);
        for (final a in (f['fonts'] as List).cast<Map<String, dynamic>>()) {
          loader.addFont(rootBundle.load(a['asset'] as String));
        }
        await loader.load();
      }
    });

    setUp(() async {
      SharedPreferences.setMockInitialValues({
        'remote.desktops': jsonEncode([
          {'id': 'pc1', 'name': 'PC Kantor', 'url': 'http://192.168.1.20:9319', 'addedAt': DateTime.now().toIso8601String()},
        ]),
        'remote.active': 'pc1',
      });
      prefs = await SharedPreferences.getInstance();
      settings = SettingsController(prefs);
      await settings.load();
      remoteImageProvider = (url, headers) => const AssetImage('assets/art/feat-remote.webp');
      socialAvatarProvider = (url) => null;
    });

    RemoteController controller({_Recorder? rec}) {
      final desktops = SavedDesktops(prefs)..load();
      final r = RemoteController(desktops)
        ..desktop = desktops.items.first
        ..status = RemoteStatus.connected
        ..gateway = _gateway(rec ?? _Recorder())
        ..runtimeId = 'rt-1'
        ..storedId = 's-1'
        ..title = 'Cek tampilan login';
      return r;
    }

    Widget host(RemoteController r, Widget home) => ProviderScope(
          overrides: [
            settingsProvider.overrideWith((ref) => settings),
            remoteProvider.overrideWith((ref) => r),
            appearanceProvider.overrideWith((ref) => AppearanceController(prefs)),
          ],
          child: RepaintBoundary(
            key: const ValueKey('shot'),
            child: MaterialApp(debugShowCheckedModeBanner: false, theme: neovarchMobileTheme, darkTheme: neovarchMobileTheme, themeMode: ThemeMode.dark, home: home),
          ),
        );

    Future<void> phone(WidgetTester tester) async {
      tester.view.physicalSize = const Size(1170, 2532);
      tester.view.devicePixelRatio = 3;
      tester.view.padding = const FakeViewPadding(top: 141, bottom: 102);
      tester.view.viewPadding = const FakeViewPadding(top: 141, bottom: 102);
      addTearDown(tester.view.reset);
    }

    Future<void> settle(WidgetTester tester) async {
      for (var i = 0; i < 8; i++) {
        await tester.pump(const Duration(milliseconds: 120));
      }
    }

    Future<void> shot(WidgetTester tester, String name) async {
      if (!autoUpdateGoldenFiles) return;
      final dir = Directory(_shotsDir).absolute.path;
      Directory(dir).createSync(recursive: true);
      await expectLater(find.byKey(const ValueKey('shot')), matchesGoldenFile('$dir/$name.png'));
    }

    Future<void> precache(WidgetTester tester) async {
      final ctx = tester.element(find.byType(MaterialApp));
      await tester.runAsync(() => precacheImage(const AssetImage('assets/art/feat-remote.webp'), ctx));
    }

    testWidgets('composer: attach sheet, upload progress, thumbnails, remove', (tester) async {
      await phone(tester);
      final rec = _Recorder();
      final r = controller(rec: rec);
      final photo = (await tester.runAsync(() => rootBundle.load('assets/art/feat-remote.webp')))!.buffer.asUint8List();
      attachPicker = (src) async => src == AttachSource.file
          ? (name: 'catatan-rapat.md', bytes: Uint8List.fromList(utf8.encode('# Rapat\n')), mime: 'text/markdown')
          : (name: 'layar.webp', bytes: photo, mime: 'image/webp');
      await tester.pumpWidget(host(r, RemoteChatScreen(onOpenApprovals: () {})));
      await settle(tester);
      await tester.tap(find.byKey(const ValueKey('attach-button')));
      await settle(tester);
      expect(find.text('Foto / Galeri'), findsOneWidget);
      expect(find.text('Kamera'), findsOneWidget);
      expect(find.text('File'), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('attach-gallery')));
      await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 50)));
      await settle(tester);
      await tester.tap(find.byKey(const ValueKey('attach-button')));
      await settle(tester);
      await tester.tap(find.byKey(const ValueKey('attach-file')));
      await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 50)));
      await settle(tester);
      expect(r.pendingAttachments.length, 2);
      expect(find.byKey(const ValueKey('attach-strip')), findsOneWidget);
      expect(find.text('catatan-rapat.md'), findsOneWidget);
      expect(rec.requests.where((q) => q.url.path == '/api/uploads').length, 2);
      // a third one "still uploading" for the progress bar
      r.pendingAttachments.add(PendingAttachment(localId: 'up', name: 'video-demo.png', mime: 'image/png', bytes: photo)..progress = 0.42);
      r.attachNotice = null;
      r.notifyListeners();
      await settle(tester);
      expect(find.byKey(const ValueKey('attach-progress-up')), findsOneWidget);
      await tester.runAsync(() => precacheImage(MemoryImage(photo), tester.element(find.byType(MaterialApp))));
      await settle(tester);
      await shot(tester, 'social_01_composer_attachments');
      await tester.tap(find.byKey(ValueKey('attach-remove-${r.pendingAttachments.first.localId}')));
      await settle(tester);
      expect(r.pendingAttachments.length, 2);
      await tester.pumpWidget(const SizedBox());
    });

    testWidgets('bubbles: image (tap to preview) and file attachments', (tester) async {
      await phone(tester);
      final r = controller();
      final ts = DateTime.now().millisecondsSinceEpoch;
      r.transcript = RemoteTranscript(history: [
        ChatMsg(id: 'u1', role: 'user', content: 'Kenapa tombol login ini kepotong di HP?', ts: ts - 90000, attachments: [
          {'id': 'img1', 'name': 'layar-login.png', 'mime': 'image/png', 'kind': 'image', 'size': 182000, 'url': '/api/uploads/img1'},
          {'id': 'f1', 'name': 'login_page.dart', 'mime': 'text/x-dart', 'kind': 'file', 'size': 4200, 'url': '/api/uploads/f1'},
        ]),
        ChatMsg(id: 'a1', role: 'assistant', ts: ts - 60000, content: 'Tombolnya pakai lebar tetap 420 px. Saya ganti jadi `double.infinity` di dalam `Padding` supaya ikut lebar layar.'),
      ]);
      r.attachNotice = null;
      await tester.pumpWidget(host(r, RemoteChatScreen(onOpenApprovals: () {})));
      await precache(tester);
      await settle(tester);
      expect(find.byKey(const ValueKey('msg-att-img1')), findsOneWidget);
      expect(find.text('login_page.dart'), findsOneWidget);
      await shot(tester, 'social_02_chat_bubble_attachments');
      await tester.tap(find.byKey(const ValueKey('msg-att-img1')));
      await settle(tester);
      expect(find.byKey(const ValueKey('image-preview')), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
    });

    testWidgets('profile & friends: heatmap, stack, coding-first list, detail', (tester) async {
      await phone(tester);
      final r = controller()
        ..socialSignedIn = true
        ..socialProfile = SocialProfile.fromJson(_profileJson())
        ..socialFriends = FriendsSnapshot.fromJson(_friendsJson());
      await tester.pumpWidget(host(r, const RemoteSocialScreen(autoLoad: false)));
      await settle(tester);
      expect(find.byKey(const ValueKey('social-profile')), findsOneWidget);
      expect(find.byKey(const ValueKey('social-heatmap')), findsOneWidget);
      expect(find.text('Lagi ngoding · neovarch'), findsOneWidget);
      expect(find.text('Python'), findsOneWidget);
      final budi = tester.getTopLeft(find.byKey(const ValueKey('friend-budi'))).dy;
      final zed = tester.getTopLeft(find.byKey(const ValueKey('friend-zed'))).dy;
      expect(budi, lessThan(zed));
      await shot(tester, 'social_03_profile');
      await tester.drag(find.byType(ListView).first, const Offset(0, -700));
      await settle(tester);
      expect(find.text('Belum pakai Neovarch'), findsOneWidget);
      await shot(tester, 'social_04_friends');
      await tester.tap(find.byKey(const ValueKey('friend-budi')));
      await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 50)));
      await settle(tester);
      expect(find.text('Budi Santoso'), findsWidgets);
      expect(find.text('Lagi ngoding · neovarch'), findsOneWidget);
      await shot(tester, 'social_05_friend_detail');
      await tester.pumpWidget(const SizedBox());
    });

    testWidgets('signed out on the PC: explains where to sign in', (tester) async {
      await phone(tester);
      final r = controller()..socialSignedIn = false;
      await tester.pumpWidget(host(r, const RemoteSocialScreen(autoLoad: false)));
      await settle(tester);
      expect(find.text('Masuk di PC dulu'), findsOneWidget);
      expect(find.byKey(const ValueKey('pc-github-login')), findsOneWidget);
      expect(find.byType(TextField), findsNothing); // no username on the phone
      await tester.pumpWidget(const SizedBox());
    });
  });
}
