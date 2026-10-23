// Screenshots of the Crew tab on a 392 px phone, dark and light: usulan
// (proposal), crew sedang bekerja, Lanjutan and the short onboarding.
// Run with --update-goldens and NV_SHOTS_DIR=… to write PNGs; a plain run only
// checks each view renders without errors.
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:neovarch_agent/remote/appearance.dart';
import 'package:neovarch_agent/remote/remote_controller.dart';
import 'package:neovarch_agent/remote/remote_gateway.dart' show RemoteStatus;
import 'package:neovarch_agent/remote/saved_desktops.dart';
import 'package:neovarch_agent/remote/ui/crew_pixel.dart';
import 'package:neovarch_agent/remote/ui/remote_app.dart' show PaletteScope;
import 'package:neovarch_agent/remote/ui/remote_crew_screen.dart';
import 'package:neovarch_agent/remote/ui/remote_kantor_tab.dart';
import 'package:neovarch_agent/state/app_controller.dart' show settingsProvider;
import 'package:neovarch_agent/state/settings_controller.dart';
import 'package:neovarch_agent/theme/neovarch_mobile_theme.dart';

import 'remote_crew_test.dart' show FakeCrew, crewJson, member;

final _shotsDir = Platform.environment['NV_SHOTS_DIR'] ?? 'build/screenshots/crew';

List<Map<String, dynamic>> _team({bool running = false}) => [
      member('m1', 'Arga', 'Manajer teknis', ['files'], status: running ? 'reviewing' : 'idle'),
      member('m2', 'Nadia', 'Perancang', ['files'], status: running ? 'done' : 'idle'),
      member('m3', 'Fajar', 'Programmer', ['files', 'write', 'shell'],
          status: running ? 'waiting' : 'idle',
          approval: running ? {'session_id': 's9', 'request_id': 'apr-1', 'command': 'npm test -- login'} : null),
      member('m4', 'Wulan', 'Penguji', ['files', 'shell'], status: running ? 'working' : 'idle'),
    ];

List<Map<String, dynamic>> _tasks({bool running = false}) => [
      {'id': 't1', 'title': 'Rencana', 'description': 'Baca kode login dan tulis rencana perubahan', 'member_id': 'm2', 'status': running ? 'done' : 'todo', 'output': running ? 'Ubah validasi token di auth.ts' : ''},
      {'id': 't2', 'title': 'Implementasi', 'description': 'Terapkan rencana, ubah sesedikit mungkin', 'member_id': 'm3', 'status': running ? 'running' : 'todo', 'output': ''},
      {'id': 't3', 'title': 'Uji', 'description': 'Jalankan tes login dan laporkan hasilnya', 'member_id': 'm4', 'status': 'todo', 'output': ''},
    ];

class _ShotCrew extends FakeCrew {
  @override
  Future<dynamic> crewCall(String method, [Map<String, dynamic> params = const {}]) async {
    if (method == 'propose') return crewJson(members: _team(), tasks: _tasks());
    return super.crewCall(method, params);
  }
}

void main() {
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

  Future<void> setUpPrefs({required bool light}) async {
    SharedPreferences.setMockInitialValues({
      crewIntroKey: true,
      'nv.theme.pc.base': light ? 'light' : 'dark',
      'remote.desktops': jsonEncode([
        {'id': 'pc1', 'name': 'PC Rumah', 'url': 'http://192.168.1.20:9319', 'addedAt': DateTime.now().toIso8601String()},
      ]),
      'remote.active': 'pc1',
    });
    prefs = await SharedPreferences.getInstance();
    settings = SettingsController(prefs);
    await settings.load();
    crewPixelAnimate = false;
  }

  Future<void> shot(WidgetTester tester, String name,
      {bool introSeen = true, double height = 1000, int segment = kantorSegCrew, Future<void> Function(RemoteController r)? act}) async {
    if (!introSeen) await prefs.remove(crewIntroKey);
    tester.view.physicalSize = Size(392 * 3, height * 3);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    final desktops = SavedDesktops(prefs)..load();
    final r = RemoteController(desktops)
      ..desktop = desktops.items.first
      ..status = RemoteStatus.connected
      ..debugApprovals = []
      ..debugCrewApi = _ShotCrew();
    final look = AppearanceController(prefs);
    NV.palette = look.palette;
    var seg = segment;
    await tester.pumpWidget(ProviderScope(
      overrides: [
        settingsProvider.overrideWith((ref) => settings),
        remoteProvider.overrideWith((ref) => r),
        appearanceProvider.overrideWith((ref) => look),
      ],
      child: RepaintBoundary(
        key: const ValueKey('shot'),
        child: MaterialApp(
          debugShowCheckedModeBanner: false,
          // built fresh: themeFor() caches by look.revision, which is 0 in both modes here
          theme: buildNeovarchMobileTheme(),
          builder: (context, child) => PaletteScope(revision: look.revision, child: child!),
          home: Scaffold(
            backgroundColor: NV.bg,
            body: MediaQuery(
              data: MediaQueryData(size: Size(392, height), padding: const EdgeInsets.only(top: 47, bottom: 34)),
              child: SafeArea(
                child: StatefulBuilder(
                  builder: (context, set) =>
                      RemoteKantorTab(segment: seg, onSegment: (i) => set(() => seg = i), onOpenChat: () {}, onOpenApprovals: () {}),
                ),
              ),
            ),
          ),
        ),
      ),
    ));
    await tester.pumpAndSettle();
    if (act != null) {
      await act(r);
      await tester.pumpAndSettle();
    }
    expect(tester.takeException(), isNull);
    if (autoUpdateGoldenFiles) {
      final dir = Directory(_shotsDir).absolute.path;
      Directory(dir).createSync(recursive: true);
      await expectLater(find.byKey(const ValueKey('shot')), matchesGoldenFile('$dir/$name.png'));
    }
  }

  Future<void> propose(WidgetTester tester) async {
    await tester.enterText(find.byKey(const ValueKey('crew-goal')), 'Perbaiki bug login di aplikasi');
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('crew-propose')));
    await tester.pumpAndSettle();
  }

  Future<void> working(WidgetTester tester, RemoteController r) async {
    await propose(tester);
    r.crewPush = crewJson(status: 'running', members: _team(running: true), tasks: _tasks(running: true));
    r.crewRevision++;
    r.notifyListeners(); // ignore: invalid_use_of_protected_member, invalid_use_of_visible_for_testing_member
    await tester.pumpAndSettle();
  }

  for (final light in [false, true]) {
    final mode = light ? 'light' : 'dark';
    group(mode, () {
      setUp(() => setUpPrefs(light: light));
      testWidgets('usulan', (tester) => shot(tester, 'phone-392-$mode-1-usulan', height: 1560, act: (_) => propose(tester)));
      testWidgets('bekerja', (tester) => shot(tester, 'phone-392-$mode-2-bekerja', height: 1400, act: (r) => working(tester, r)));
      testWidgets('lanjutan', (tester) => shot(tester, 'phone-392-$mode-3-lanjutan', act: (_) async {
            await propose(tester);
            await tester.tap(find.byKey(const ValueKey('segment-Lanjutan')));
          }));
      testWidgets('onboarding', (tester) => shot(tester, 'phone-392-$mode-4-onboarding', introSeen: false));
    });
  }
}
