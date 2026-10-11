// "Hey Neo" wake word: controller over the device channel and the Profil switch.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:neovarch_agent/remote/ui/wake_word_panel.dart';
import 'package:neovarch_agent/remote/wake_word.dart';

class FakeNative {
  bool enabled = false;
  String state = 'off';
  bool model = false;
  final calls = <String>[];
  Future<Object?> call(String method, [Map<String, dynamic>? args]) async {
    calls.add(args == null ? method : '$method $args');
    if (method == 'wakeWord') {
      enabled = args?['enable'] == true;
      state = enabled ? (model ? 'listening' : 'downloading') : 'off';
    }
    return {'enabled': enabled, 'state': state, 'modelReady': model};
  }
}

void main() {
  test('status labels', () {
    expect(const WakeWordStatus().label, 'Mati');
    expect(const WakeWordStatus(enabled: true, state: 'downloading').label, contains('Mengunduh'));
    expect(const WakeWordStatus(enabled: true, state: 'listening').label, 'Mendengarkan "Hey Neo"');
    expect(const WakeWordStatus(enabled: true, state: 'error:mikrofon dipakai').label, 'Gagal: mikrofon dipakai');
    expect(WakeWordStatus.fromMap({'enabled': true, 'state': 'stopped', 'modelReady': true}).modelReady, isTrue);
  });

  test('opt-in: asks for the microphone first; denied keeps it off', () async {
    final n = FakeNative();
    var granted = false;
    final c = WakeWordController(call: n.call, permissions: () async => granted);
    await c.setEnabled(true);
    expect(n.calls, isEmpty);
    expect(c.status.enabled, isFalse);
    expect(c.error, contains('Izin mikrofon'));
    granted = true;
    await c.setEnabled(true);
    expect(n.calls, ['wakeWord {enable: true}']);
    expect(c.status.enabled, isTrue);
    expect(c.status.state, 'downloading'); // first time: model download
    await c.setEnabled(false);
    expect(c.status.enabled, isFalse);
    expect(n.calls.last, 'wakeWord {enable: false}');
  });

  test('resume after reboot restarts only when it was switched on', () async {
    final n = FakeNative()..model = true;
    final c = WakeWordController(call: n.call, permissions: () async => true);
    await c.resume();
    expect(n.calls, ['wakeStatus']);
    n.enabled = true;
    n.state = 'stopped';
    await c.resume();
    expect(n.calls.last, 'wakeWord {enable: true}');
    expect(c.status.state, 'listening');
  });

  testWidgets('Profil switch turns it on and shows the state', (tester) async {
    final n = FakeNative();
    final c = WakeWordController(call: n.call, permissions: () async => true);
    await tester.pumpWidget(ProviderScope(
      overrides: [wakeWordProvider.overrideWith((ref) => c)],
      child: const MaterialApp(home: Scaffold(body: Padding(padding: EdgeInsets.all(16), child: WakeWordPanel()))),
    ));
    await tester.pump();
    expect(find.text('Mati'), findsOneWidget);
    expect(n.calls, ['wakeStatus', 'wakeBackgroundStatus']);
    await tester.tap(find.byKey(const ValueKey('wake-switch')));
    await tester.pump();
    await tester.pump();
    expect(find.text('Mengunduh model suara…'), findsOneWidget);
    expect(n.enabled, isTrue);
  });
}
