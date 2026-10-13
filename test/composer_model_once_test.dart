// Backlog: "Composer menampilkan nama model dua kali". The phone composer
// showed the PC model twice: the chips-row model chip (cube, from the composer
// catalog) and a separate ModelChip (sparkle, from /api/models) right below
// it. The composer must show the model once: the chip on the reasoning row
// when the PC sends a composer catalog, the fallback chip only for an older PC
// without one. A model switch from elsewhere must also update that one chip.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:neovarch_agent/data/gateway_client.dart';
import 'package:neovarch_agent/remote/appearance.dart';
import 'package:neovarch_agent/remote/composer.dart';
import 'package:neovarch_agent/remote/models_api.dart';
import 'package:neovarch_agent/remote/remote_controller.dart';
import 'package:neovarch_agent/remote/remote_gateway.dart';
import 'package:neovarch_agent/remote/saved_desktops.dart';
import 'package:neovarch_agent/remote/ui/remote_chat_screen.dart';
import 'package:neovarch_agent/remote/ui/remote_composer.dart';
import 'package:neovarch_agent/state/app_controller.dart' show settingsProvider;
import 'package:neovarch_agent/state/settings_controller.dart';
import 'package:neovarch_agent/theme/neovarch_mobile_theme.dart';

/// The PC's composer catalog; [model] is what the PC reports right now.
Map<String, dynamic> catalogJson(String model) => {
      'version': 1,
      'skills': [],
      'commands': [],
      'snippets': [],
      'mentions': [],
      'models': {
        'model': model,
        'provider': '9router',
        'providers': [
          {'slug': '9router', 'name': '9router', 'models': ['oc/mimo-2.6', 'kr/claude-sonnet-4.5'], 'is_current': true},
        ],
      },
      'reasoning': {
        'supported': true,
        'levels': ['low', 'medium', 'high'],
        'labels': {'low': 'Rendah', 'medium': 'Sedang', 'high': 'Tinggi'},
        'default': 'default',
      },
      'features': {'prompt_fields': ['reasoning_effort']},
    };

/// The PC whose catalog follows [model] (a switch on the PC changes it).
class _Pc {
  String model = 'oc/mimo-2.6';
  bool failCatalog = false;
  int catalogReads = 0;
  http.Client client() => MockClient((req) async {
        if (req.url.path == '/api/composer/catalog') {
          catalogReads++;
          if (failCatalog) return http.Response('boom', 500);
          return http.Response(jsonEncode(catalogJson(model)), 200, headers: {'content-type': 'application/json'});
        }
        return http.Response(jsonEncode({'detail': 'nope'}), 404, headers: {'content-type': 'application/json'});
      });
}

class _Models implements ModelsApi {
  _Models(this.pc);
  final _Pc pc;
  @override
  Future<ModelsSnapshot> listModels({bool refresh = false}) async => ModelsSnapshot.fromJson({
        'models': [
          {'id': 'oc/mimo-2.6', 'label': 'MiMo 2.6', 'provider': '9router', 'group': 'OpenCode'},
          {'id': 'kr/claude-sonnet-4.5', 'label': 'Claude Sonnet 4.5', 'provider': '9router', 'group': 'Kiro'},
        ],
        'default': {'model': pc.model, 'provider': '9router'},
        'router': {'setup': {'ready': true}},
      });
  @override
  Future<ModelRef> setDefaultModel(String model, {String? provider}) async {
    pc.model = model;
    return ModelRef(model, provider ?? '9router');
  }
  @override
  Future<AgentModel> setAgentModel(String agentId, String? model, {String? provider}) async =>
      AgentModel(agentId: agentId, model: model ?? pc.model, provider: '9router');
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

  Future<RemoteController> controller(_Pc pc, {bool withCatalog = true}) async {
    final desktops = SavedDesktops(prefs)..load();
    final r = RemoteController(desktops)
      ..desktop = desktops.items.first
      ..status = RemoteStatus.connected
      ..debugApprovals = []
      ..debugModelsApi = _Models(pc)
      ..gateway = RemoteGateway(baseUrl: 'http://192.168.1.20:9319', token: 'tok', autoReconnect: false, httpClient: pc.client())
      ..runtimeId = 'rt-1';
    if (withCatalog) r.composer = ComposerCatalog.tryParse(catalogJson(pc.model));
    await r.refreshModels();
    return r;
  }

  Future<void> pump(WidgetTester tester, RemoteController r) async {
    tester.view.physicalSize = const Size(390 * 3, 844 * 3);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    final look = AppearanceController(prefs);
    await tester.pumpWidget(ProviderScope(
      overrides: [
        settingsProvider.overrideWith((ref) => settings),
        remoteProvider.overrideWith((ref) => r),
        appearanceProvider.overrideWith((ref) => look),
      ],
      child: MaterialApp(theme: buildNeovarchMobileTheme(), home: RemoteChatScreen(onOpenApprovals: () {})),
    ));
    for (var i = 0; i < 4; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
  }

  Finder inComposer(Finder f) => find.descendant(of: find.byKey(const ValueKey('chat-composer')), matching: f);

  testWidgets('PC with a composer catalog: the model shows once, on the reasoning row', (tester) async {
    final r = await controller(_Pc());
    await pump(tester, r);
    expect(composerShowsModel(r), isTrue);
    expect(inComposer(find.byKey(const ValueKey('chip-model'))), findsOneWidget);
    expect(inComposer(find.byKey(const ValueKey('chip-reasoning'))), findsOneWidget);
    // the old second chip (sparkle, from /api/models) is gone
    expect(find.byKey(const ValueKey('model-chip')), findsNothing);
    expect(inComposer(find.text('mimo-2.6')), findsOneWidget);
    // both live in the same chips row
    final row = find.byKey(const ValueKey('composer-chips'));
    expect(find.descendant(of: row, matching: find.byKey(const ValueKey('chip-model'))), findsOneWidget);
    expect(find.descendant(of: row, matching: find.byKey(const ValueKey('chip-reasoning'))), findsOneWidget);
  });

  testWidgets('older PC without a composer catalog: the fallback chip is the only model control', (tester) async {
    final r = await controller(_Pc(), withCatalog: false);
    await pump(tester, r);
    expect(composerShowsModel(r), isFalse);
    expect(find.byKey(const ValueKey('chip-model')), findsNothing);
    expect(inComposer(find.byKey(const ValueKey('model-chip'))), findsOneWidget);
    expect(inComposer(find.text('mimo-2.6')), findsOneWidget);
  });

  testWidgets('model switched elsewhere (top-bar pill / desktop): the composer chip follows', (tester) async {
    final pc = _Pc();
    final r = await controller(pc);
    await pump(tester, r);
    expect(inComposer(find.text('mimo-2.6')), findsOneWidget);
    // the PC switches its default and broadcasts it
    pc.model = 'kr/claude-sonnet-4.5';
    r.debugEvent(const GatewayEventFrame('model.default.changed', null, {'model': 'kr/claude-sonnet-4.5', 'provider': '9router'}));
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 50)));
    for (var i = 0; i < 4; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    expect(r.composer!.model, 'kr/claude-sonnet-4.5');
    expect(inComposer(find.text('claude-sonnet-4.5')), findsOneWidget);
    expect(inComposer(find.text('mimo-2.6')), findsNothing);
    expect(find.byKey(const ValueKey('model-chip')), findsNothing);
  });

  test('a failed catalog re-read after a model change keeps the chips (no fold on a flaky link)', () async {
    final pc = _Pc();
    final r = await controller(pc);
    pc.failCatalog = true;
    final before = pc.catalogReads;
    r.debugEvent(const GatewayEventFrame('model.default.changed', null, {'model': 'kr/claude-sonnet-4.5', 'provider': '9router'}));
    await Future<void>.delayed(const Duration(milliseconds: 50));
    expect(pc.catalogReads, before + 1);
    expect(r.composer, isNotNull);
    expect(composerShowsModel(r), isTrue);
  });
}
