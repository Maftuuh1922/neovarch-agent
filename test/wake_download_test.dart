import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:neovarch_agent/remote/ui/wake_word_panel.dart';
import 'package:neovarch_agent/remote/wake_word.dart';

void main() {
  test('download progress / retry / error states', () {
    const mb = 1048576;
    final s = WakeWordStatus.fromMap({'enabled': true, 'state': 'downloading:${12 * mb}:${40 * mb}'});
    expect(s.downloading, isTrue);
    expect(s.label, 'Mengunduh model suara 12 / 40 MB (30%)');
    expect(s.fraction, closeTo(0.3, 1e-9));
    final u = WakeWordStatus.fromMap({'enabled': true, 'state': 'downloading:${5 * mb}:0'});
    expect(u.fraction, isNull);
    expect(u.label, 'Mengunduh model suara 5 MB');
    expect(WakeWordStatus.fromMap({'enabled': true, 'state': 'downloading:0:0'}).label, 'Mengunduh model suara…');
    final r = WakeWordStatus.fromMap({'enabled': true, 'state': 'retrying:2:Unduhan macet (tidak ada data 20 detik)'});
    expect(r.downloading, isTrue);
    expect(r.label, startsWith('Unduhan macet, mencoba lagi… (2/3)'));
    expect(r.label, contains('tidak ada data 20 detik'));
    final e = WakeWordStatus.fromMap({'enabled': true, 'state': 'error:Unduhan model gagal setelah 3 percobaan: HTTP 403 dari alphacephei.com'});
    expect(e.label, 'Gagal: Unduhan model gagal setelah 3 percobaan: HTTP 403 dari alphacephei.com');
    expect(e.downloading, isFalse);
  });

  testWidgets('panel shows the live progress bar, real error text and background rows inside the card', (tester) async {
    var state = 'downloading:${20 * 1048576}:${40 * 1048576}';
    final calls = <String>[];
    final c = WakeWordController(
      call: (m, [a]) async {
        calls.add(m);
        return {'enabled': true, 'state': state, 'modelReady': false};
      },
      permissions: () async => true,
    );
    await tester.pumpWidget(ProviderScope(
      overrides: [wakeWordProvider.overrideWith((ref) => c)],
      child: const MaterialApp(home: Scaffold(body: SingleChildScrollView(child: WakeWordPanel()))),
    ));
    await tester.pump();
    await tester.pump();
    expect(find.text('Mengunduh model suara 20 / 40 MB (50%)'), findsOneWidget);
    final bar = tester.widget<LinearProgressIndicator>(find.byKey(const ValueKey('wake-progress')));
    expect(bar.value, closeTo(0.5, 1e-9));
    expect(find.descendant(of: find.byKey(const ValueKey('wake-panel')), matching: find.byKey(const ValueKey('wake-switch'))), findsOneWidget);
    state = 'error:HTTP 403 dari alphacephei.com';
    await tester.pump(const Duration(seconds: 1));
    await tester.pump();
    expect(find.text('Gagal: HTTP 403 dari alphacephei.com'), findsOneWidget);
    expect(find.byKey(const ValueKey('wake-progress')), findsNothing);
    await tester.tap(find.byKey(const ValueKey('wake-background')));
    await tester.pump();
    expect(calls, contains('wakeBackground'));
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('background rows: granted state, no MIUI text off Xiaomi, message when no Settings page opens', (tester) async {
    var bg = {'overlay': false, 'battery': false, 'xiaomi': false};
    var opened = 'none';
    final kinds = <String>[];
    final c = WakeWordController(
      call: (m, [a]) async {
        if (m == 'wakeBackgroundStatus') return bg;
        if (m == 'wakeBackground') {
          kinds.add('${a?['kind']}');
          return opened;
        }
        return {'enabled': false, 'state': 'off'};
      },
      permissions: () async => true,
    );
    await tester.pumpWidget(ProviderScope(
      overrides: [wakeWordProvider.overrideWith((ref) => c)],
      child: const MaterialApp(home: Scaffold(body: SingleChildScrollView(child: WakeWordPanel()))),
    ));
    await tester.pump();
    await tester.pump();
    expect(find.textContaining('Xiaomi'), findsNothing);
    expect(find.text('Matikan pengoptimalan baterai untuk Neovarch Agent.'), findsOneWidget);
    // every page missing → a visible message, not a silent no-op
    await tester.tap(find.byKey(const ValueKey('wake-overlay')));
    await tester.pump();
    await tester.pump();
    expect(kinds, ['overlay']);
    expect(find.textContaining('Tidak bisa membuka Pengaturan'), findsOneWidget);
    // granted in Settings, back in the app → row shows it
    opened = 'overlay';
    bg = {'overlay': true, 'battery': false, 'xiaomi': true};
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();
    await tester.pump();
    expect(find.text('Sudah diizinkan.'), findsOneWidget);
    expect(find.textContaining('Xiaomi/MIUI'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });
}
