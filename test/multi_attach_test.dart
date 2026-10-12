// Multi-lampiran (v1.4.7): several images/files in one message from the phone.
// The controller makes one chat session, gives every file its own chip that
// uploads in parallel, and stops at kMaxAttachmentsPerMessage with one plain
// Indonesian message (the PC core enforces the same limit).
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:neovarch_agent/remote/attachments.dart';
import 'package:neovarch_agent/remote/remote_controller.dart';
import 'package:neovarch_agent/remote/remote_gateway.dart';
import 'package:neovarch_agent/remote/saved_desktops.dart';

final _png = base64Decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==');

RemoteGateway _gateway(List<String> uploaded) {
  var n = 0;
  return RemoteGateway(
    baseUrl: 'http://192.168.1.20:9319',
    token: 'tok-123',
    autoReconnect: false,
    httpClient: MockClient.streaming((req, body) async {
      await body.toBytes();
      Object out = {};
      if (req.url.path == '/api/uploads' && req.method == 'POST') {
        final id = (n++).toRadixString(16).padLeft(12, '0');
        uploaded.add(id);
        out = {'id': id, 'name': 'f$id', 'mime': 'image/png', 'size': 67, 'kind': 'image', 'url': '/api/uploads/$id'};
      } else if (req.method == 'DELETE') {
        out = {'ok': true};
      }
      return http.StreamedResponse(Stream.value(utf8.encode(jsonEncode(out))), 200, headers: {'content-type': 'application/json'});
    }),
  );
}

List<({String name, Uint8List bytes, String? mime})> _files(int count) => [
      for (var i = 0; i < count; i++)
        i.isEven
            ? (name: 'foto-$i.png', bytes: Uint8List.fromList(_png), mime: 'image/png')
            : (name: 'catatan-$i.md', bytes: Uint8List.fromList(utf8.encode('# catatan $i\n')), mime: 'text/markdown'),
    ];

void main() {
  late SharedPreferences prefs;
  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    prefs = await SharedPreferences.getInstance();
  });

  RemoteController controller(List<String> uploaded) => RemoteController(SavedDesktops(prefs)..load())
    ..gateway = _gateway(uploaded)
    ..status = RemoteStatus.connected
    ..runtimeId = 'rt-1';

  test('several picked files become one chip each, all uploaded', () async {
    final uploaded = <String>[];
    final r = controller(uploaded);
    final err = await r.addAttachments(_files(4));
    expect(err, isNull);
    expect(r.pendingAttachments.length, 4);
    expect(r.pendingAttachments.every((a) => a.state == AttachState.done), isTrue);
    expect(r.pendingAttachments.map((a) => a.name), ['foto-0.png', 'catatan-1.md', 'foto-2.png', 'catatan-3.md']);
    expect(r.pendingAttachments.map((a) => a.remote!.id).toSet().length, 4);
    expect(uploaded.length, 4);
    // one chip can still be removed on its own
    r.removeAttachment(r.pendingAttachments[1].localId);
    expect(r.pendingAttachments.length, 3);
  });

  test('past the limit: extra files are skipped with one clear message', () async {
    final uploaded = <String>[];
    final r = controller(uploaded);
    final err = await r.addAttachments(_files(kMaxAttachmentsPerMessage + 2));
    expect(r.pendingAttachments.length, kMaxAttachmentsPerMessage);
    expect(uploaded.length, kMaxAttachmentsPerMessage);
    expect(err, contains('Maksimal $kMaxAttachmentsPerMessage lampiran per pesan.'));
    expect(err, contains('2 file dilewati'));
    // a single add on a full composer says the same thing
    expect(await r.addAttachment('lagi.png', Uint8List.fromList(_png)), kTooManyAttachments);
    expect(r.pendingAttachments.length, kMaxAttachmentsPerMessage);
  });

  test('not connected: nothing is added', () async {
    final r = controller(<String>[])..status = RemoteStatus.disconnected;
    expect(await r.addAttachments(_files(2)), 'Belum terhubung ke PC.');
    expect(r.pendingAttachments, isEmpty);
  });
}
