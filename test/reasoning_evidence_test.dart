// Phone parity with the desktop "Penalaran": the PC's levels (Mati / Rendah /
// Sedang / Tinggi / Ultra) next to the model pill, saved per chat on the PC
// (PATCH /api/sessions/{id}) and following the desktop through session.info;
// plus the folded "Bukti" section under an agent report.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:neovarch_agent/data/gateway_client.dart';
import 'package:neovarch_agent/models/models.dart';
import 'package:neovarch_agent/remote/appearance.dart';
import 'package:neovarch_agent/remote/composer.dart';
import 'package:neovarch_agent/remote/evidence.dart';
import 'package:neovarch_agent/remote/remote_controller.dart';
import 'package:neovarch_agent/remote/remote_gateway.dart';
import 'package:neovarch_agent/remote/remote_transcript.dart';
import 'package:neovarch_agent/remote/saved_desktops.dart';
import 'package:neovarch_agent/remote/ui/remote_chat_screen.dart';
import 'package:neovarch_agent/state/app_controller.dart' show settingsProvider;
import 'package:neovarch_agent/state/settings_controller.dart';
import 'package:neovarch_agent/theme/neovarch_mobile_theme.dart';
import 'package:neovarch_agent/ui/screens/chat/message_widgets.dart';

/// The catalog the Neovarch core serves (core/neovarch/server.py composer_catalog).
Map<String, dynamic> coreCatalog({bool reasoning = true}) => {
      'version': 1,
      'skills': [
        {'name': 'neovarch-diri', 'description': 'Perbaikan diri'},
      ],
      'commands': [
        {'name': 'new', 'description': 'Mulai percakapan baru'},
        {'name': 'perbaiki', 'description': 'Diagnosis & perbaikan diri'},
        {'name': 'undo', 'description': 'Pulihkan versi sebelumnya'},
      ],
      'snippets': [],
      'mentions': [],
      'models': {
        'model': 'mimo-v2.6',
        'provider': '9router',
        'providers': [
          {'slug': '9router', 'name': '9router', 'models': ['mimo-v2.6', 'kimi-k2'], 'is_current': true},
        ],
      },
      'reasoning': {
        'supported': reasoning,
        'levels': reasoning ? ['none', 'low', 'medium', 'high', 'ultra'] : [],
        'labels': {'none': 'Mati', 'low': 'Rendah', 'medium': 'Sedang', 'high': 'Tinggi', 'ultra': 'Ultra'},
        'default': 'default',
      },
      'features': {
        'prompt_fields': ['reasoning_effort'],
      },
    };

class _Rec {
  final requests = <http.BaseRequest>[];
  final bodies = <String>[];
}

http.Client _http(_Rec rec, {bool reasoning = true}) => MockClient.streaming((req, body) async {
      rec.requests.add(req);
      rec.bodies.add(utf8.decode(await body.toBytes(), allowMalformed: true));
      final path = req.url.path;
      Object out = {'ok': true};
      if (path == '/api/composer/catalog') out = coreCatalog(reasoning: reasoning);
      return http.StreamedResponse(Stream.value(utf8.encode(jsonEncode(out))), 200, headers: {'content-type': 'application/json'});
    });

class _Gw extends RemoteGateway {
  _Gw(_Rec rec, {bool reasoning = true})
      : super(baseUrl: 'http://192.168.1.20:9319', token: 'tok', autoReconnect: false, httpClient: _http(rec, reasoning: reasoning));
  final submits = <Map<String, dynamic>>[];
  @override
  Future<dynamic> submit(String runtimeId, String text, {List<String> attachments = const [], Map<String, dynamic> extra = const {}}) async {
    submits.add({'session_id': runtimeId, 'text': text, ...extra});
    return {'ok': true};
  }
}

const report = '**Temuan**\nLogin gagal karena token kedaluwarsa.\n\n**Bukti**\n- `lib/auth.dart:42` tidak memperbarui token\n'
    '- `flutter test` → 12 lulus\n\n**Batasan**\n- Belum dites di iOS.\n\n**Langkah berikutnya**\n- Tambah tes refresh.';

void main() {
  group('pure helpers', () {
    test('splitEvidence folds Bukti and everything after it', () {
      final p = splitEvidence(report);
      expect(p.main, '**Temuan**\nLogin gagal karena token kedaluwarsa.');
      expect(p.evidence, startsWith('- `lib/auth.dart:42`'));
      expect(p.evidence, contains('Batasan'));
      expect(splitEvidence('Halo, ada yang bisa dibantu?').evidence, isNull);
      expect(splitEvidence('## Bukti\n- a.dart').evidence, isNull); // nothing before it: keep as is
      expect(splitEvidence('Hasil\n\n### Evidence\n- x.py:1').evidence, '- x.py:1');
    });

    test('sessionEffort maps the PC value onto the picker', () {
      final c = ComposerCatalog.tryParse(coreCatalog())!;
      expect(sessionEffort('ultra', c), 'ultra');
      expect(sessionEffort('', c), isNull);
      expect(sessionEffort('default', c), isNull);
      expect(sessionEffort('xhigh', c), isNull); // not offered for this model → Bawaan
      expect(c.effortLabel('ultra'), 'Ultra');
      expect(ComposerCatalog.tryParse(coreCatalog(reasoning: false))!.canSendEffort, isFalse);
    });
  });

  group('controller sync', () {
    late SharedPreferences prefs;
    setUp(() async {
      SharedPreferences.setMockInitialValues({});
      prefs = await SharedPreferences.getInstance();
    });

    test('picking a level saves it on the chat; the desktop changing it updates the phone', () async {
      final rec = _Rec();
      final g = _Gw(rec);
      final r = RemoteController(SavedDesktops(prefs)..load())
        ..gateway = g
        ..status = RemoteStatus.connected
        ..runtimeId = 'rt-1';
      await r.refreshComposer();
      expect(rec.requests.first.url.queryParameters['session_id'], 'rt-1');
      r.setReasoningEffort('ultra');
      await Future<void>.delayed(Duration.zero);
      final patch = rec.requests.lastWhere((q) => q.method == 'PATCH');
      expect(patch.url.path, '/api/sessions/rt-1');
      expect(jsonDecode(rec.bodies[rec.requests.indexOf(patch)]), {'reasoning_effort': 'ultra'});
      await r.send('cek login');
      expect(g.submits.single['reasoning_effort'], 'ultra');
      // desktop sets "Sedang" on the same chat
      r.debugEvent(const GatewayEventFrame('session.info', 'rt-1', {'reasoning_effort': 'medium', 'model': 'mimo-v2.6'}));
      expect(r.reasoningEffort, 'medium');
      // another chat's info does not touch this one
      r.debugEvent(const GatewayEventFrame('session.info', 'rt-2', {'reasoning_effort': 'high'}));
      expect(r.reasoningEffort, 'medium');
      r.setReasoningEffort('default');
      await Future<void>.delayed(Duration.zero);
      expect(jsonDecode(rec.bodies.last), {'reasoning_effort': 'default'});
    });
  });

  group('widgets', () {
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
    });

    Widget host(RemoteController r, Widget home) => ProviderScope(
          overrides: [
            settingsProvider.overrideWith((ref) => settings),
            remoteProvider.overrideWith((ref) => r),
            appearanceProvider.overrideWith((ref) => AppearanceController(prefs)),
          ],
          child: MaterialApp(theme: buildNeovarchMobileTheme(), darkTheme: buildNeovarchMobileTheme(), home: home),
        );

    Future<void> settle(WidgetTester tester) async {
      for (var i = 0; i < 8; i++) {
        await tester.pump(const Duration(milliseconds: 120));
      }
    }

    Future<RemoteController> controller(_Gw g, {bool reasoning = true}) async {
      final desktops = SavedDesktops(prefs)..load();
      return RemoteController(desktops)
        ..desktop = desktops.items.first
        ..status = RemoteStatus.connected
        ..gateway = g
        ..runtimeId = 'rt-1'
        ..storedId = 'rt-1'
        ..title = 'Login'
        ..transcript = RemoteTranscript(history: [ChatMsg(id: 'm0', role: 'user', content: 'halo', ts: 1000)])
        ..composer = ComposerCatalog.tryParse(coreCatalog(reasoning: reasoning));
    }

    testWidgets('reasoning chip next to the model pill: levels, save per chat, follow desktop', (tester) async {
      tester.view.physicalSize = const Size(1170, 2532);
      tester.view.devicePixelRatio = 3;
      addTearDown(tester.view.reset);
      final rec = _Rec();
      final g = _Gw(rec);
      final r = await controller(g);
      await tester.pumpWidget(host(r, RemoteChatScreen(onOpenApprovals: () {})));
      await settle(tester);
      expect(find.byKey(const ValueKey('chip-model')), findsOneWidget);
      expect(find.byKey(const ValueKey('chip-reasoning')), findsOneWidget);
      expect(find.text('Penalaran: Bawaan'), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('chip-reasoning')));
      await settle(tester);
      for (final l in ['none', 'low', 'medium', 'high', 'ultra']) {
        expect(find.byKey(ValueKey('reasoning-$l')), findsOneWidget, reason: l);
      }
      for (final t in ['Mati', 'Rendah', 'Sedang', 'Tinggi', 'Ultra']) {
        expect(find.text(t), findsOneWidget, reason: t);
      }
      await tester.tap(find.byKey(const ValueKey('reasoning-ultra')));
      await settle(tester);
      expect(find.text('Penalaran: Ultra'), findsOneWidget);
      expect(rec.requests.where((q) => q.method == 'PATCH' && q.url.path == '/api/sessions/rt-1'), hasLength(1));
      r.debugEvent(const GatewayEventFrame('session.info', 'rt-1', {'reasoning_effort': 'low'}));
      await settle(tester);
      expect(find.text('Penalaran: Rendah'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
    });

    testWidgets('a model without reasoning hides the chip', (tester) async {
      tester.view.physicalSize = const Size(1170, 2532);
      tester.view.devicePixelRatio = 3;
      addTearDown(tester.view.reset);
      final r = await controller(_Gw(_Rec(), reasoning: false), reasoning: false);
      await tester.pumpWidget(host(r, RemoteChatScreen(onOpenApprovals: () {})));
      await settle(tester);
      expect(find.byKey(const ValueKey('chip-model')), findsOneWidget);
      expect(find.byKey(const ValueKey('chip-reasoning')), findsNothing);
      await tester.pumpWidget(const SizedBox());
    });

    testWidgets('agent report shows a folded Bukti section', (tester) async {
      await tester.pumpWidget(MaterialApp(
        theme: buildNeovarchMobileTheme(),
        home: Scaffold(
          body: SingleChildScrollView(
            child: AssistantMessage(
              msg: ChatMsg(id: 'a1', role: 'assistant', content: report, ts: 1001),
              scale: 1,
              showReasoning: true,
              onLink: (_) {},
              onOpenFile: (_) {},
            ),
          ),
        ),
      ));
      await tester.pump();
      expect(find.byKey(const ValueKey('evidence-toggle')), findsOneWidget);
      expect(find.byKey(const ValueKey('evidence-body')), findsNothing);
      await tester.tap(find.byKey(const ValueKey('evidence-toggle')));
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('evidence-body')), findsOneWidget);
    });
  });
}
