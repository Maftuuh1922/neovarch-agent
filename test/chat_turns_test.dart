// One bubble per agent turn (1.4.8): the pure grouping of transcript steps
// into turns, the timeline/answer split, folding of long timelines, and the
// AssistantTurn bubble (one copy button, one time, "+N langkah").
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:neovarch_agent/models/chat_turns.dart';
import 'package:neovarch_agent/models/models.dart';
import 'package:neovarch_agent/remote/remote_transcript.dart';
import 'package:neovarch_agent/data/gateway_client.dart';
import 'package:neovarch_agent/theme/neovarch_mobile_theme.dart';
import 'package:neovarch_agent/ui/screens/chat/message_widgets.dart';

ToolActivity tool(String id, String name, {bool running = false}) =>
    ToolActivity(id: id, name: name, summary: 'HTTP 200', running: running, durationS: 0.3);

ChatMsg step(String id, {String content = '', String reasoning = '', List<ToolActivity>? tools, bool streaming = false, int ts = 1000}) =>
    ChatMsg(id: id, role: 'assistant', content: content, reasoning: reasoning, tools: tools, ts: ts, streaming: streaming);

ChatMsg user(String id, String text) => ChatMsg(id: id, role: 'user', content: text, ts: 999);

void main() {
  group('groupTurns', () {
    test('empty transcript → no rows', () {
      expect(groupTurns(const []), isEmpty);
    });

    test('all agent steps between two user messages form ONE turn', () {
      final items = groupTurns([
        user('u1', 'cari UMR'),
        step('a1', reasoning: 'pikir', tools: [tool('t1', 'read_file')], content: 'Saya baca filenya:'),
        step('a2', reasoning: 'pikir lagi', tools: [tool('t2', 'web_fetch'), tool('t3', 'web_fetch')], content: 'Coba sumber lain:'),
        step('a3', content: 'UMR Bandung 2026 adalah Rp4,4 juta.', ts: 2000),
        user('u2', 'makasih'),
        step('a4', content: 'Sama-sama!'),
      ]);
      expect(items.map((i) => i.runtimeType).toList(), [UserChatItem, AgentTurnItem, UserChatItem, AgentTurnItem]);
      final turn = items[1] as AgentTurnItem;
      expect(turn.steps.map((s) => s.id), ['a1', 'a2', 'a3']);
      expect(turn.key, 'a1');
      expect((items[3] as AgentTurnItem).steps.single.id, 'a4');
    });

    test('agent messages before any user message still group', () {
      final items = groupTurns([step('a1', content: 'halo'), step('a2', content: 'ada yang bisa dibantu?')]);
      expect(items.single, isA<AgentTurnItem>());
      expect((items.single as AgentTurnItem).steps.length, 2);
    });

    test('tool / system rows join the turn they belong to', () {
      final items = groupTurns([
        user('u1', 'x'),
        step('a1', content: 'cek'),
        ChatMsg(id: 't1', role: 'tool', content: 'ok', ts: 1),
        step('a2', content: 'selesai'),
      ]);
      expect(items.length, 2);
      expect((items[1] as AgentTurnItem).steps.map((s) => s.id), ['a1', 't1', 'a2']);
    });

    test('consecutive user messages stay separate rows', () {
      final items = groupTurns([user('u1', 'a'), user('u2', 'b'), step('a1', content: 'c')]);
      expect(items.map((i) => i.key), ['u1', 'u2', 'a1']);
    });
  });

  group('AgentTurnItem', () {
    test('timeline keeps reasoning, narration and tools in order; answer is separate', () {
      final turn = AgentTurnItem([
        step('a1', reasoning: 'pikir', tools: [tool('t1', 'read_file')], content: 'Saya baca filenya:'),
        step('a2', tools: [tool('t2', 'web_fetch')]),
        step('a3', reasoning: 'rangkum', content: 'Jawaban akhir.', ts: 3000),
      ]);
      expect(turn.answer, 'Jawaban akhir.');
      expect(turn.answerStep!.id, 'a3');
      expect(turn.timeline.map((e) => '${e.kind.name}:${e.text}'), [
        'reasoning:pikir',
        'narration:Saya baca filenya:',
        'tool:read_file',
        'tool:web_fetch',
        'reasoning:rangkum',
      ]);
      expect(turn.copyText, 'Jawaban akhir.');
      expect(turn.ts, 3000);
      expect(turn.live, isFalse);
      // keys are unique (widget state survives rebuilds)
      final keys = turn.timeline.map((e) => e.key).toList();
      expect(keys.toSet().length, keys.length);
    });

    test('while running, text of a step that called tools is narration, not the answer', () {
      final turn = AgentTurnItem([
        step('a1', content: 'Saya cek dulu:', tools: [tool('t1', 'web_fetch', running: true)], streaming: true),
      ]);
      expect(turn.live, isTrue);
      expect(turn.answerStep, isNull);
      expect(turn.timeline.map((e) => e.kind), [TurnEntryKind.narration, TurnEntryKind.tool]);
    });

    test('a streaming final step is the answer as it grows', () {
      final turn = AgentTurnItem([
        step('a1', tools: [tool('t1', 'web_fetch')]),
        step('a2', content: 'Hasilnya', streaming: true),
      ]);
      expect(turn.live, isTrue);
      expect(turn.answer, 'Hasilnya');
      expect(turn.timeline.single.kind, TurnEntryKind.tool);
    });

    test('live reasoning only while the step has no text and no tools yet', () {
      expect(AgentTurnItem([step('a1', reasoning: 'hmm', streaming: true)]).timeline.single.live, isTrue);
      expect(AgentTurnItem([step('a1', reasoning: 'hmm', content: 'Ok', streaming: true)]).timeline.single.live, isFalse);
      expect(AgentTurnItem([step('a1', reasoning: 'hmm', tools: [tool('t', 'x')], streaming: true)]).timeline.first.live, isFalse);
    });

    test('a finished turn that ended on tools: last text is the answer; copy falls back to narration', () {
      final ended = AgentTurnItem([step('a1', content: 'Sudah saya simpan.', tools: [tool('t1', 'file_write')])]);
      expect(ended.answer, 'Sudah saya simpan.');
      final toolsOnly = AgentTurnItem([
        step('a1', content: 'Langkah satu.', tools: [tool('t1', 'x')]),
        step('a2', tools: [tool('t2', 'y')])..error = 'Dihentikan.',
      ]);
      expect(toolsOnly.answer, isEmpty);
      expect(toolsOnly.copyText, 'Langkah satu.');
      expect(toolsOnly.errorStep!.id, 'a2');
    });

    test('attachments of every step, without duplicate ids', () {
      final a = step('a1')..attachments.add({'id': 'f1', 'name': 'a.txt'});
      final b = step('a2')..attachments.addAll([{'id': 'f1', 'name': 'a.txt'}, {'id': 'f2', 'name': 'b.png'}]);
      expect(AgentTurnItem([a, b]).attachments.map((x) => x['id']), ['f1', 'f2']);
    });
  });

  group('foldTimeline', () {
    final turn = AgentTurnItem([
      for (var i = 0; i < 5; i++) step('a$i', reasoning: 'r$i', tools: [tool('t$i', 'web_fetch')]),
    ]);

    test('short timelines are not folded', () {
      final short = AgentTurnItem([step('a', reasoning: 'r', tools: [tool('t', 'x')])]).timeline;
      final f = foldTimeline(short);
      expect(f.hidden, 0);
      expect(f.visible.length, 2);
    });

    test('long timelines keep the newest entries and count the rest', () {
      final f = foldTimeline(turn.timeline);
      expect(turn.timeline.length, 10);
      expect(f.hidden, 6);
      expect(f.visible.map((e) => e.key), turn.timeline.skip(6).map((e) => e.key));
      final all = foldTimeline(turn.timeline, expanded: true);
      expect(all.hidden, 0);
      expect(all.visible.length, 10);
    });
  });

  test('live gateway events of one turn end up in ONE turn', () {
    final tr = RemoteTranscript(history: [user('u1', 'cari UMR')]);
    GatewayEventFrame f(String type, Map<String, dynamic> p) => GatewayEventFrame(type, 'rt-1', p);
    tr.apply(f('message.start', {}));
    tr.apply(f('reasoning.delta', {'text': 'perlu cari'}));
    tr.apply(f('message.delta', {'text': 'Saya cari dulu:'}));
    tr.apply(f('tool.start', {'tool_id': 't1', 'name': 'web_fetch'}));
    tr.apply(f('tool.complete', {'tool_id': 't1', 'summary': 'HTTP 200'}));
    tr.apply(f('reasoning.delta', {'text': 'kurang'}));
    tr.apply(f('tool.start', {'tool_id': 't2', 'name': 'read_file'}));
    tr.apply(f('tool.complete', {'tool_id': 't2', 'summary': 'ok'}));
    tr.apply(f('message.delta', {'text': 'UMR-nya Rp4,4 juta.'}));
    tr.apply(f('message.complete', {}));
    expect(tr.messages.where((m) => m.role == 'assistant').length, greaterThan(1), reason: 'the transcript keeps steps');
    final items = groupTurns(tr.messages);
    expect(items.length, 2);
    final turn = items[1] as AgentTurnItem;
    expect(turn.answer, 'UMR-nya Rp4,4 juta.');
    expect(turn.live, isFalse);
    expect(turn.timeline.where((e) => e.kind == TurnEntryKind.tool).length, 2);
  });

  group('AssistantTurn widget', () {
    Widget host(AgentTurnItem t) => MaterialApp(
          theme: buildNeovarchMobileTheme(),
          home: Scaffold(
            body: SingleChildScrollView(
              child: AssistantTurn(turn: t, scale: 1, showReasoning: true, onLink: (_) {}, onOpenFile: (_) {}),
            ),
          ),
        );

    testWidgets('one copy button and one time for a multi-step turn; copy takes the answer', (tester) async {
      String? copied;
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, (call) async {
        if (call.method == 'Clipboard.setData') copied = (call.arguments as Map)['text'] as String?;
        return null;
      });
      addTearDown(() => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, null));
      final t = AgentTurnItem([
        step('a1', reasoning: 'pikir', tools: [tool('t1', 'read_file')], content: 'Saya baca filenya:', ts: 1000),
        step('a2', tools: [tool('t2', 'web_fetch')], content: 'Coba sumber lain:', ts: 2000),
        step('a3', content: 'UMR Bandung Rp4,4 juta.', ts: 3000),
      ]);
      await tester.pumpWidget(host(t));
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.byTooltip('Salin'), findsOneWidget);
      expect(find.byKey(const ValueKey('turn-time')), findsOneWidget);
      expect(find.byKey(const ValueKey('turn-answer')), findsOneWidget);
      expect(find.byType(ToolRow), findsNWidgets(2));
      expect(find.textContaining('Saya baca filenya', findRichText: true), findsOneWidget);
      expect(find.text('read_file'), findsOneWidget);
      await tester.tap(find.byTooltip('Salin'));
      await tester.pump(const Duration(seconds: 3));
      expect(copied, 'UMR Bandung Rp4,4 juta.');
    });

    testWidgets('a running turn: no copy/time yet, timeline grows', (tester) async {
      final t = AgentTurnItem([
        step('a1', content: 'Saya cek dulu:', tools: [tool('t1', 'web_fetch', running: true)], streaming: true),
      ]);
      await tester.pumpWidget(host(t));
      await tester.pump(const Duration(milliseconds: 100));
      expect(find.byTooltip('Salin'), findsNothing);
      expect(find.byKey(const ValueKey('turn-time')), findsNothing);
      expect(find.byKey(const ValueKey('turn-answer')), findsNothing);
      expect(find.byType(ToolRow), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
    });

    testWidgets('many steps fold behind "+N langkah" and expand on tap', (tester) async {
      final t = AgentTurnItem([
        for (var i = 0; i < 5; i++) step('a$i', tools: [tool('t$i', 'web_fetch'), tool('u$i', 'read_file')]),
        step('z', content: 'Selesai.'),
      ]);
      await tester.pumpWidget(host(t));
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.byType(ToolRow), findsNWidgets(4));
      expect(find.text('+6 langkah'), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('turn-steps-more')));
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.byType(ToolRow), findsNWidgets(10));
      expect(find.byKey(const ValueKey('turn-steps-less')), findsOneWidget);
      expect(find.byKey(const ValueKey('turn-answer')), findsOneWidget);
    });
  });
}
