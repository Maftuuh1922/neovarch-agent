// PowerPoint from the phone: "buatin PPT dari …" goes to the PC agent as a
// normal chat turn (the PC runs ppt_setup / ppt-master / ppt_export), and the
// .pptx it reports is offered as a download from the PC, like Word reports.
// No real PC, model or network.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:neovarch_agent/models/models.dart';
import 'package:neovarch_agent/remote/attachments.dart';
import 'package:neovarch_agent/remote/remote_controller.dart';
import 'package:neovarch_agent/remote/remote_gateway.dart';
import 'package:neovarch_agent/remote/saved_desktops.dart';
import 'package:neovarch_agent/remote/ui/remote_attachments.dart';
import 'package:neovarch_agent/theme/neovarch_mobile_theme.dart';
import 'package:neovarch_agent/ui/screens/chat/message_widgets.dart';

class _Gw extends RemoteGateway {
  _Gw() : super(baseUrl: 'http://192.168.1.20:9319', token: 'tok-123', autoReconnect: false);
  final submits = <Map<String, dynamic>>[];
  @override
  Future<dynamic> submit(String runtimeId, String text, {List<String> attachments = const [], Map<String, dynamic> extra = const {}}) async {
    submits.add({'session_id': runtimeId, 'text': text, ...extra});
    return {'ok': true};
  }
}

ToolActivity _export(String name, String result, {bool failed = false}) =>
    ToolActivity(id: 't1', name: name, args: '{}', result: result, running: false, failed: failed);

void main() {
  test('pptx/docx are downloadable documents with the right mime', () {
    expect(isDownloadableDoc('/home/u/.neovarch/presentations/deck/exports/deck.pptx'), isTrue);
    expect(isDownloadableDoc(r'C:\Users\u\.neovarch\reports\a\report.docx'), isTrue);
    expect(isDownloadableDoc('/home/u/proyek/main.dart'), isFalse);
    expect(mimeForName('deck.pptx'), 'application/vnd.openxmlformats-officedocument.presentationml.presentation');
  });

  test('the PC download URL carries the path and the pairing token', () {
    final u = _Gw().fsDownloadUri('/home/u/.neovarch/presentations/deck/exports/deck.pptx');
    expect(u.path, '/api/fs/download');
    expect(u.queryParameters, {'path': '/home/u/.neovarch/presentations/deck/exports/deck.pptx', 'token': 'tok-123'});
  });

  test('producedFiles reads ppt_export / report_export output only', () {
    expect(producedFiles(_export('ppt_export', 'exported\npptx: /h/p/deck/exports/deck.pptx')), ['/h/p/deck/exports/deck.pptx']);
    expect(producedFiles(_export('report_export', 'exported\ndocx: /h/r/report.docx\npdf: /h/r/report.pdf')),
        ['/h/r/report.docx', '/h/r/report.pdf']);
    expect(producedFiles(_export('ppt_export', 'error: Python 3.10 …', failed: true)), isEmpty);
    expect(producedFiles(_export('shell', 'pptx: /x.pptx')), isEmpty);
  });

  test('"buatin PPT dari …" on the phone is sent to the PC agent unchanged', () async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    final g = _Gw();
    final r = RemoteController(SavedDesktops(prefs)..load())
      ..gateway = g
      ..status = RemoteStatus.connected
      ..runtimeId = 'rt-1';
    expect(await r.send('buatin PPT dari catatan rapat kemarin, 8 slide'), isNull);
    expect(g.submits.single, {'session_id': 'rt-1', 'text': 'buatin PPT dari catatan rapat kemarin, 8 slide'});
  });

  testWidgets('the tool row offers "Unduh deck.pptx" and the phone downloads it from the PC', (tester) async {
    final opened = <String>[];
    final launched = <Uri>[];
    launchDownload = (u) async {
      launched.add(u);
      return true;
    };
    final g = _Gw();
    await tester.pumpWidget(MaterialApp(
      theme: buildNeovarchMobileTheme(),
      home: Scaffold(
        body: Builder(
          builder: (context) => ToolRow(
            tool: _export('ppt_export', 'exported\npptx: /h/p/deck/exports/deck.pptx'),
            onOpenFile: (p) {
              opened.add(p);
              openPcFile(context, g, p);
            },
            onLink: (_) {},
          ),
        ),
      ),
    ));
    expect(find.text('Unduh deck.pptx'), findsOneWidget);
    await tester.tap(find.text('Unduh deck.pptx'));
    await tester.pump();
    expect(opened, ['/h/p/deck/exports/deck.pptx']);
    expect(launched.single.queryParameters['path'], '/h/p/deck/exports/deck.pptx');
    await tester.pump(const Duration(seconds: 4));
  });
}
