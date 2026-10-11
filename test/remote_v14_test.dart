// v1.4 phone features as widget/unit tests: Kantor (office), Obsidian vault
// viewer (tree, note with wikilinks + backlinks, graph), theme following the
// PC with a local override, liquid glass surfaces (blur, no gradient/shadow),
// minimal greeting start screen, update strip, pairing fallback addresses.
import 'dart:convert';
import 'dart:ui' show ImageFilter;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:neovarch_agent/main.dart' as app;
import 'package:neovarch_agent/remote/appearance.dart';
import 'package:neovarch_agent/remote/office_models.dart';
import 'package:neovarch_agent/remote/pairing.dart';
import 'package:neovarch_agent/remote/remote_controller.dart';
import 'package:neovarch_agent/remote/remote_gateway.dart';
import 'package:neovarch_agent/remote/remote_transcript.dart';
import 'package:neovarch_agent/remote/saved_desktops.dart';
import 'package:neovarch_agent/remote/update_check.dart';
import 'package:neovarch_agent/remote/vault_models.dart';
import 'package:neovarch_agent/remote/ui/nv_widgets.dart';
import 'package:neovarch_agent/remote/ui/remote_app.dart' show PaletteScope, themeFor;
import 'package:neovarch_agent/remote/ui/remote_chat_screen.dart' show greetingFor;
import 'package:neovarch_agent/remote/ui/remote_office_screen.dart';
import 'package:neovarch_agent/remote/ui/remote_shell.dart';
import 'package:neovarch_agent/remote/ui/remote_vault_screen.dart';
import 'package:neovarch_agent/state/app_controller.dart' show settingsProvider;
import 'package:neovarch_agent/state/settings_controller.dart';
import 'package:neovarch_agent/theme/neovarch_mobile_theme.dart';

class FakeVault implements VaultApi {
  final opened = <String>[];
  @override
  Future<VaultTree> vaultTree() async => VaultTree.fromJson({
        'configured': true,
        'vault': 'Kuliah',
        'tree': {
          'name': 'Kuliah',
          'path': '',
          'type': 'folder',
          'children': [
            {
              'name': 'Bab',
              'path': 'Bab',
              'type': 'folder',
              'children': [
                {'name': 'Pendahuluan', 'path': 'Bab/Pendahuluan.md', 'type': 'note'}
              ]
            },
            {'name': 'Metode', 'path': 'Metode.md', 'type': 'note'},
            {'name': 'Skripsi', 'path': 'Skripsi.md', 'type': 'note'},
          ]
        }
      });

  @override
  Future<VaultNote> vaultNote(String path) async {
    opened.add(path);
    if (path == 'Bab/Pendahuluan.md') {
      return VaultNote.fromJson({
        'path': path,
        'title': 'Pendahuluan',
        'content': '# Pendahuluan\n\nLatar belakang penelitian.',
        'backlinks': [
          {'path': 'Skripsi.md', 'title': 'Skripsi', 'snippet': 'lihat [[Bab/Pendahuluan]]'}
        ],
        'outgoing': [],
        'open_uri': 'obsidian://open?vault=Kuliah&file=Bab/Pendahuluan',
      });
    }
    return VaultNote.fromJson({
      'path': 'Skripsi.md',
      'title': 'Skripsi',
      'tags': ['ta'],
      'content': '---\ntags: [ta]\n---\n# Skripsi\n\nMulai dari [[Bab/Pendahuluan|pendahuluan]] lalu [[Metode]]. Belum: [[Belum Ada]].',
      'backlinks': [
        {'path': 'Metode.md', 'title': 'Metode', 'snippet': 'dasar: [[Skripsi]]'}
      ],
      'outgoing': [
        {'target': 'Bab/Pendahuluan', 'path': 'Bab/Pendahuluan.md'},
        {'target': 'Metode', 'path': 'Metode.md'},
        {'target': 'Belum Ada', 'path': null},
      ],
      'open_uri': 'obsidian://open?vault=Kuliah&file=Skripsi',
    });
  }

  @override
  Future<VaultGraph> vaultGraph() async => VaultGraph.fromJson({
        'configured': true,
        'nodes': [
          {'id': 'Skripsi.md', 'title': 'Skripsi', 'exists': true, 'degree': 4},
          {'id': 'Bab/Pendahuluan.md', 'title': 'Pendahuluan', 'exists': true, 'degree': 1},
          {'id': 'Metode.md', 'title': 'Metode', 'exists': true, 'degree': 2},
          {'id': '?Belum Ada', 'title': 'Belum Ada', 'exists': false, 'degree': 1},
        ],
        'edges': [
          {'source': 'Skripsi.md', 'target': 'Bab/Pendahuluan.md'},
          {'source': 'Skripsi.md', 'target': 'Metode.md'},
          {'source': 'Metode.md', 'target': 'Skripsi.md'},
          {'source': 'Skripsi.md', 'target': '?Belum Ada'},
        ],
      });

  @override
  Future<List<VaultHit>> vaultSearch(String q) async => [const VaultHit(path: 'Metode.md', title: 'Metode', snippet: 'metode penelitian')];
}

OfficeSnapshot demoOffice({String status = 'working', int feedId = 2}) {
  final sec = DateTime.now().millisecondsSinceEpoch / 1000;
  return OfficeSnapshot.fromJson({
    'agents': [
      {
        'id': 'session:s1', 'kind': 'session', 'session_id': 's1', 'name': 'Raka', 'role': 'Agen remote · HP', 'status': status,
        'current_task': 'Rapikan folder Unduhan', 'current_tool': status == 'working' ? 'move_files: ~/Downloads' : null,
        'last_activity': sec - 30,
      },
      {'id': 'kanban:writer', 'kind': 'kanban', 'name': 'writer', 'role': 'Pelaksana tugas Kanban', 'status': 'idle', 'current_task': 'Draf laporan'},
    ],
    'counts': {'working': status == 'working' ? 1 : 0, 'waiting-approval': 0, 'idle': status == 'working' ? 1 : 2},
    'kanban': {'running': 1},
    'feed': [
      {'id': feedId, 'ts': sec - 10, 'kind': 'tool', 'agent': 'Raka', 'session_id': 's1', 'text': 'menjalankan move_files: ~/Downloads'},
      {'id': 1, 'ts': sec - 300, 'kind': 'message.user', 'agent': 'Raka', 'session_id': 's1', 'text': 'mendapat tugas: Rapikan folder Unduhan'},
    ],
    'vault': {'configured': true, 'note_count': 3},
  });
}

void main() {
  late SharedPreferences prefs;
  late SettingsController settings;

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
    NV.palette = NvPalette.red;
  });

  RemoteController controller({bool connected = true}) {
    final desktops = SavedDesktops(prefs)..load();
    final r = RemoteController(desktops)
      ..desktop = desktops.items.first
      ..status = connected ? RemoteStatus.connected : RemoteStatus.reconnecting
      ..debugApprovals = [];
    return r;
  }

  Future<AppearanceController> pump(WidgetTester tester, RemoteController r, Widget home, {AppearanceController? look}) async {
    tester.view.physicalSize = const Size(1170, 2532);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    final l = look ?? AppearanceController(prefs);
    await tester.pumpWidget(ProviderScope(
      overrides: [
        settingsProvider.overrideWith((ref) => settings),
        remoteProvider.overrideWith((ref) => r),
        appearanceProvider.overrideWith((ref) => l),
      ],
      child: Consumer(builder: (context, ref, _) {
        final look = ref.watch(appearanceProvider);
        return MaterialApp(
          theme: themeFor(look),
          builder: (context, child) => PaletteScope(revision: look.revision, child: child!),
          home: home,
        );
      }),
    ));
    await tester.pump(const Duration(milliseconds: 50));
    return l;
  }

  group('Kantor', () {
    testWidgets('lists pegawai with status, task and the activity feed', (tester) async {
      final r = controller()..office = demoOffice();
      await pump(tester, r, RemoteOfficeScreen(onOpenChat: () {}, onOpenApprovals: () {}));
      expect(find.text('Raka'), findsWidgets);
      expect(find.text('bekerja'), findsWidgets);
      expect(find.text('Rapikan folder Unduhan'), findsOneWidget);
      expect(find.textContaining('move_files'), findsWidgets);
      await tester.scrollUntilVisible(find.byKey(const ValueKey('office-feed')), 300);
      expect(find.textContaining('mendapat tugas'), findsOneWidget);
    });

    testWidgets('an office.update push re-renders without polling', (tester) async {
      final r = controller()..office = demoOffice();
      await pump(tester, r, RemoteOfficeScreen(onOpenChat: () {}, onOpenApprovals: () {}));
      expect(find.text('Selesai, 3 berkas'), findsNothing);
      // what RemoteController does on the `office.update` WebSocket event
      r.office = OfficeSnapshot.fromJson({
        'agents': [
          {'id': 'session:s1', 'session_id': 's1', 'name': 'Raka', 'role': 'Agen', 'status': 'idle', 'current_task': 'Selesai, 3 berkas'}
        ],
        'feed': [],
      });
      r.notifyListeners();
      await tester.pump();
      expect(find.text('Selesai, 3 berkas'), findsOneWidget);
      expect(find.text('santai'), findsWidgets);
    });

    testWidgets('empty office says so', (tester) async {
      final r = controller()..office = const OfficeSnapshot();
      await pump(tester, r, RemoteOfficeScreen(onOpenChat: () {}, onOpenApprovals: () {}));
      expect(find.text('Kantor masih sepi'), findsOneWidget);
    });

    test('snapshot parsing', () {
      final o = demoOffice();
      expect(o.agents.first.statusLabel, 'bekerja');
      expect(o.working, 1);
      expect(o.vaultConfigured, isTrue);
      expect(o.feed.first.kind, 'tool');
      expect(OfficeAgent.fromJson({'status': 'waiting-approval'}).statusLabel, 'menunggu persetujuan');
    });
  });

  group('Vault', () {
    testWidgets('tree opens folders and notes', (tester) async {
      final fake = FakeVault();
      final r = controller()..debugVault = fake;
      await pump(tester, r, const RemoteVaultScreen());
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('vault-tree')), findsOneWidget);
      expect(find.text('Skripsi'), findsOneWidget);
      expect(find.text('Pendahuluan'), findsNothing);
      await tester.tap(find.text('Bab'));
      await tester.pumpAndSettle();
      expect(find.text('Pendahuluan'), findsOneWidget);
      await tester.tap(find.text('Skripsi'));
      await tester.pumpAndSettle();
      expect(fake.opened, ['Skripsi.md']);
      expect(find.byKey(const ValueKey('open-obsidian')), findsOneWidget);
      expect(find.text('Buka di Obsidian'), findsOneWidget);
    });

    testWidgets('note: wikilinks are clickable, backlinks listed', (tester) async {
      final fake = FakeVault();
      final r = controller()..debugVault = fake;
      await pump(tester, r, const VaultNoteScreen(path: 'Skripsi.md'));
      await tester.pumpAndSettle();
      expect(find.text('Metode'), findsWidgets); // backlink row
      expect(find.textContaining('#ta'), findsOneWidget);
      // the front matter is not rendered
      expect(find.textContaining('tags: [ta]'), findsNothing);
      // tap the [[Bab/Pendahuluan|pendahuluan]] link inside the rich text
      final rich = find.byWidgetPredicate((w) => w is RichText && w.text.toPlainText().contains('pendahuluan'));
      expect(rich, findsWidgets);
      final link = _findSpan(tester.widget<RichText>(rich.first).text, 'pendahuluan');
      expect(link, isNotNull);
      (link!.recognizer as dynamic).onTap();
      await tester.pumpAndSettle();
      expect(fake.opened.last, 'Bab/Pendahuluan.md');
      expect(find.text('Latar belakang penelitian.'), findsOneWidget);
    });

    testWidgets('graph paints nodes and selects on tap', (tester) async {
      final r = controller()..debugVault = FakeVault();
      await pump(tester, r, const VaultGraphScreen());
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('vault-graph')), findsOneWidget);
      expect(find.textContaining('4 CATATAN'), findsOneWidget);
    });

    testWidgets('not configured shows how to pick a vault', (tester) async {
      final r = controller()..debugVault = _EmptyVault();
      await pump(tester, r, const RemoteVaultScreen());
      await tester.pumpAndSettle();
      expect(find.text('Pilih vault di PC'), findsOneWidget);
    });

    test('wikilinks → markdown links, resolution, front matter', () {
      expect(wikilinksToMarkdown('a [[Bab/Pendahuluan|pendahuluan]] b'), 'a [pendahuluan](nvwiki:Bab%2FPendahuluan) b');
      expect(wikilinksToMarkdown('[[Metode#Desain]]'), '[Metode#Desain](nvwiki:Metode)');
      final n = VaultNote.fromJson({
        'content': '---\ntitle: x\n---\nisi',
        'outgoing': [
          {'target': 'Bab/Pendahuluan', 'path': 'Bab/Pendahuluan.md'},
          {'target': 'Kosong', 'path': null},
        ],
      });
      expect(n.body, 'isi');
      expect(n.resolve('Bab/Pendahuluan'), 'Bab/Pendahuluan.md');
      expect(n.resolve('pendahuluan'), 'Bab/Pendahuluan.md');
      expect(n.resolve('Kosong'), isNull);
    });

    test('graph layout is deterministic and inside the canvas', () async {
      final g = await FakeVault().vaultGraph();
      final a = layoutGraph(g), b = layoutGraph(g);
      expect(a.length, 4);
      for (final id in a.keys) {
        expect(a[id], b[id]);
        expect(a[id]!.dx, inInclusiveRange(0.0, 1.0));
        expect(a[id]!.dy, inInclusiveRange(0.0, 1.0));
      }
    });
  });

  group('Theme', () {
    test('palette: default red is the v1.3 set; other accents tint flat colours', () {
      expect(NvPalette.from(const Color(0xFFEE1C1C), Brightness.dark), same(NvPalette.red));
      final blue = NvPalette.from(const Color(0xFF2563EB), Brightness.light);
      expect(blue.dark, isFalse);
      expect(blue.accent, const Color(0xFF2563EB));
      expect(blue.onAccent, const Color(0xFFFFFFFF));
      expect(NvPalette.from(const Color(0xFFA3A3A3), Brightness.dark).onAccent, const Color(0xFF000000));
    });

    testWidgets('follows the PC appearance, then a local override wins', (tester) async {
      final r = controller()..office = demoOffice();
      final look = await pump(tester, r, RemoteOfficeScreen(onOpenChat: () {}, onOpenApprovals: () {}));
      r.onAppearance = look.applyPc;
      expect(NV.red, const Color(0xFFEE1C1C));
      // `appearance.changed` from the PC
      r.onAppearance!({'accent': '#2563EB', 'base': 'light', 'on_accent': '#FFFFFF'});
      await tester.pumpAndSettle();
      expect(NV.red, const Color(0xFF2563EB));
      expect(NV.palette.dark, isFalse);
      expect(Theme.of(tester.element(find.byType(RemoteOfficeScreen))).colorScheme.primary, const Color(0xFF2563EB));
      // local override on the phone
      look.setLocal(accent: const Color(0xFF16A34A), dark: true);
      await tester.pumpAndSettle();
      expect(NV.red, const Color(0xFF16A34A));
      expect(NV.palette.dark, isTrue);
      // the PC changes again: the override keeps winning
      look.applyPc({'accent': '#7C3AED', 'base': 'dark'});
      expect(NV.red, const Color(0xFF16A34A));
      look.setFollowPc(true);
      expect(NV.red, const Color(0xFF7C3AED));
      // persisted
      final again = AppearanceController(prefs);
      expect(again.followPc, isTrue);
      expect(again.pcAccent, const Color(0xFF7C3AED));
      NV.palette = NvPalette.red;
    });

    test('hex parsing', () {
      expect(parseHexColor('#f06'), const Color(0xFFFF0066));
      expect(parseHexColor('EE1C1C'), const Color(0xFFEE1C1C));
      expect(parseHexColor('nope'), isNull);
      expect(hexOf(const Color(0xFF2563EB)), '#2563EB');
    });
  });

  group('Liquid glass + minimal start', () {
    testWidgets('nav bar and composer are blurred glass; no gradients or shadows', (tester) async {
      app.previewTab = 0;
      final r = controller()..transcript = RemoteTranscript();
      await pump(tester, r, const RemoteShell());
      await tester.pump(const Duration(milliseconds: 400));
      final glass = find.byType(NvGlass);
      expect(glass, findsWidgets);
      final blur = find.descendant(of: glass.first, matching: find.byType(BackdropFilter));
      expect(blur, findsOneWidget);
      expect(tester.widget<BackdropFilter>(blur).filter, isA<ImageFilter>());
      for (final d in tester.widgetList<DecoratedBox>(find.byType(DecoratedBox))) {
        final dec = d.decoration;
        if (dec is BoxDecoration) {
          expect(dec.gradient, isNull);
          expect(dec.boxShadow == null || dec.boxShadow!.isEmpty, isTrue);
        }
      }
      for (final c in tester.widgetList<Container>(find.byType(Container))) {
        final dec = c.decoration;
        if (dec is BoxDecoration) {
          expect(dec.gradient, isNull);
          expect(dec.boxShadow == null || dec.boxShadow!.isEmpty, isTrue);
        }
      }
      // four tabs, Indonesian (1.4.2: Tugas in Kantor, Setujui in Chat)
      for (final t in ['CHAT', 'KANTOR', 'PROFIL', 'PC']) {
        expect(find.text(t), findsOneWidget);
      }
    });

    testWidgets('empty chat = greeting + composer only', (tester) async {
      app.previewTab = 0;
      final r = controller()..transcript = RemoteTranscript();
      await pump(tester, r, const RemoteShell());
      await tester.pump(const Duration(milliseconds: 400));
      expect(find.byKey(const ValueKey('chat-greeting')), findsOneWidget);
      expect(find.text(greetingFor(DateTime.now())), findsOneWidget);
      expect(find.byKey(const ValueKey('chat-composer')), findsOneWidget);
      expect(find.text('Perintahkan agen di PC'), findsNothing);
      expect(find.text('coba perintah'.toUpperCase()), findsNothing);
      expect(find.byTooltip('Sesi baru'), findsOneWidget);
    });

    test('greeting by hour', () {
      expect(greetingFor(DateTime(2026, 1, 1, 6)), 'Selamat pagi');
      expect(greetingFor(DateTime(2026, 1, 1, 12)), 'Selamat siang');
      expect(greetingFor(DateTime(2026, 1, 1, 16)), 'Selamat sore');
      expect(greetingFor(DateTime(2026, 1, 1, 21)), 'Selamat malam');
      expect(greetingFor(DateTime(2026, 1, 1, 2)), 'Selamat malam');
    });
  });

  group('Update tersedia', () {
    test('GitHub releases/latest newer than the app → available with the arm64 APK', () async {
      final c = UpdateChecker(
        current: '1.3.0',
        client: MockClient((req) async {
          expect(req.url.toString(), 'https://api.github.com/repos/Maftuuh1922/neovrach_Agent/releases/latest');
          return http.Response(
              jsonEncode({
                'tag_name': 'v1.4.0',
                'html_url': 'https://github.com/Maftuuh1922/neovrach_Agent/releases/tag/v1.4.0',
                'assets': [
                  {'name': 'neovarch-agent-1.4.0-linux-x64.tar.gz', 'browser_download_url': 'https://x/linux.tar.gz'},
                  {'name': 'app-armeabi-v7a-release.apk', 'browser_download_url': 'https://x/v7.apk'},
                  {'name': 'app-arm64-v8a-release.apk', 'browser_download_url': 'https://x/arm64.apk'},
                ]
              }),
              200);
        }),
      );
      final u = (await c.check())!;
      expect(u['available'], isTrue);
      expect(u['latest'], '1.4.0');
      expect(u['download_url'], 'https://x/arm64.apk');
      expect(u['source'], 'github');
    });

    test('same version → not available; GitHub down → PC fallback', () async {
      final same = UpdateChecker(current: '1.4.0', client: MockClient((_) async => http.Response('{"tag_name":"v1.4.0"}', 200)));
      expect((await same.check())!['available'], isFalse);
      final down = UpdateChecker(current: '1.3.0', client: MockClient((_) async => http.Response('rate limited', 403)));
      final u = (await down.check(fallback: () async => {'latest': '1.4.1', 'url': 'https://r'}))!;
      expect(u['available'], isTrue);
      expect(u['source'], 'pc');
      expect(isNewerVersion('1.10.0', '1.9.9'), isTrue);
      expect(isNewerVersion('v1.4.0', '1.4.0'), isFalse);
    });

    testWidgets('strip shows on the shell and can be dismissed', (tester) async {
      app.previewTab = 0;
      final r = controller()
        ..transcript = RemoteTranscript()
        ..update = const {'available': true, 'latest': '1.4.0', 'download_url': 'https://x/arm64.apk'};
      await pump(tester, r, const RemoteShell());
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.text('Update tersedia v1.4.0'), findsOneWidget);
      expect(find.text('Perbarui'), findsOneWidget);
      await tester.tap(find.byTooltip('Tutup'));
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.text('Update tersedia v1.4.0'), findsNothing);
    });
  });

  group('Pairing routes', () {
    test('QR with fallback addresses: LAN first, then MagicDNS, then tailnet IP', () {
      final p = GatewayPairing.parse(jsonEncode({
        'url': 'http://100.101.2.3:9319',
        'token': 't',
        'urls': ['http://100.101.2.3:9319', 'pc.tail1234.ts.net', 'http://192.168.1.20:9319'],
      }))!;
      expect(p.allUrls, ['http://192.168.1.20:9319', 'http://pc.tail1234.ts.net:9319', 'http://100.101.2.3:9319']);
      final u = GatewayPairing.parse('neovarch://pair?v=1&url=http%3A%2F%2F192.168.1.20%3A9319&token=t&alt=http%3A%2F%2F100.64.0.7%3A9319')!;
      expect(u.alternates, ['http://100.64.0.7:9319']);
      expect(GatewayPairing.parse(u.toUri())!.alternates, ['http://100.64.0.7:9319']);
      expect(gatewayRoute('http://100.64.0.7:9319'), 'tailscale');
      expect(gatewayRoute('http://10.0.0.2:9319'), 'lan');
      expect(gatewayRoute('https://gw.example.com'), 'other');
    });

    test('backoff grows exponentially with jitter and caps at 30 s', () {
      final g = RemoteGateway(baseUrl: 'http://127.0.0.1:9', token: '');
      final d = [for (var i = 0; i < 9; i++) g.backoff(i).inMilliseconds];
      expect(d[0], inInclusiveRange(400, 600));
      expect(d[3], inInclusiveRange(3200, 4800));
      expect(d.last, inInclusiveRange(24000, 36000));
      g.close();
    });
  });
}

class _EmptyVault extends FakeVault {
  @override
  Future<VaultTree> vaultTree() async => VaultTree.fromJson({'configured': false, 'tree': null, 'detail': 'no vault'});
}

TextSpan? _findSpan(InlineSpan root, String text) {
  TextSpan? hit;
  root.visitChildren((s) {
    if (s is TextSpan && s.text == text && s.recognizer != null) {
      hit = s;
      return false;
    }
    return true;
  });
  return hit;
}
