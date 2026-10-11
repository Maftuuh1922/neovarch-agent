import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:neovarch_agent/remote/ui/wake_word_panel.dart';
import 'package:neovarch_agent/remote/wake_phrase.dart';
import 'package:neovarch_agent/remote/wake_word.dart';

void main() {
  group('wake phrase matcher (same rules as WakePhrase.kt)', () {
    test('greeting + name, incl. what the English model hears for "Neo"', () {
      for (final t in ['hey neo', 'Hey Neo!', 'halo neo', 'hallo neo', 'hello knee oh', 'hey neil', 'hi neon', 'okay kneel', 'so hey neil please']) {
        expect(matchesWakePhrase(t), isTrue, reason: t);
      }
    });
    test('bare name', () {
      expect(matchesWakePhrase('neo'), isTrue);
      expect(matchesWakePhrase('Neo.'), isTrue);
      expect(matchesWakePhrase('knee oh'), isTrue);
    });
    test('other speech does not match', () {
      for (final t in ['', '[unk]', 'hey', 'hello there', 'neon lights are bright', 'honey oh', 'money', null]) {
        expect(matchesWakePhrase(t), isFalse, reason: '$t');
      }
    });
  });

  testWidgets('Tes Hey Neo shows what the mic heard', (tester) async {
    var heard = <String, Object?>{};
    final calls = <String>[];
    final c = WakeWordController(
      call: (m, [a]) async {
        calls.add(m);
        if (m == 'wakeBackgroundStatus') return {'overlay': true, 'battery': true, 'xiaomi': false};
        final until = m == 'wakeTest' || heard.isNotEmpty ? DateTime.now().millisecondsSinceEpoch + 60000 : 0;
        return {'enabled': true, 'state': 'listening', 'modelReady': true, 'testUntil': until, ...heard};
      },
      permissions: () async => true,
    );
    await tester.pumpWidget(ProviderScope(
      overrides: [wakeWordProvider.overrideWith((ref) => c)],
      child: const MaterialApp(home: Scaffold(body: SingleChildScrollView(child: WakeWordPanel()))),
    ));
    await tester.pump();
    await tester.pump();
    expect(find.text('Tes Hey Neo'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('wake-test')));
    await tester.pump();
    await tester.pump();
    expect(calls, contains('wakeTest'));
    expect(find.textContaining('belum ada suara'), findsOneWidget);
    heard = {'heard': 'hey knee oh'};
    await tester.pump(const Duration(seconds: 1));
    await tester.pump();
    expect(find.textContaining('cocok, Chat akan terbuka'), findsOneWidget);
    heard = {'heard': '[unk]'};
    await tester.pump(const Duration(seconds: 1));
    await tester.pump();
    expect(find.textContaining('bukan "Hey Neo"'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });
}
