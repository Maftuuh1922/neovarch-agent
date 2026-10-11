// Cross-implementation vectors: the Dart link crypto must interoperate with
// the PC's Python implementation (test/fixtures/link_vectors.json).
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:neovarch_agent/remote/link/link_crypto.dart';

void main() {
  final v = jsonDecode(File('test/fixtures/link_vectors.json').readAsStringSync()) as Map<String, dynamic>;

  test('keys, hello, transcript and derived keys match the PC', () async {
    final dev = await LinkKeyPair.fromPrivate(b64d(v['dev_sk']));
    final pc = await LinkKeyPair.fromPrivate(b64d(v['pc_sk']));
    final ep = await LinkKeyPair.fromPrivate(b64d(v['eph_phone_sk']));
    final es = await LinkKeyPair.fromPrivate(b64d(v['eph_pc_sk']));
    expect(b64e(dev.publicBytes), v['dev_pk']);
    expect(b64e(pc.publicBytes), v['pc_pk']);
    expect(linkHello(dev, ep), v['hello']);
    final th = await linkTranscript(dev.publicBytes, pc.publicBytes, ep.publicBytes, es.publicBytes);
    expect(b64e(th), v['transcript']);
    final (up, down) = await linkDerive([...await dev.dh(pc.publicBytes), ...await ep.dh(es.publicBytes)], th);
    expect(b64e(up), v['k_up']);
    expect(b64e(down), v['k_down']);
    expect(await linkDeviceId(dev.publicBytes), v['device_id']);
  });

  test('phone session produces and reads the exact PC frames', () async {
    final dev = await LinkKeyPair.fromPrivate(b64d(v['dev_sk']));
    final ep = await LinkKeyPair.fromPrivate(b64d(v['eph_phone_sk']));
    final s = await LinkSession.phoneFinish(dev, ep, b64d(v['pc_pk']), Map<String, dynamic>.from(v['welcome']));
    expect(await s.encrypt(Map<String, dynamic>.from(v['up_message'])), v['up_frames']);
    Map<String, dynamic>? got;
    for (final f in (v['down_frames'] as List)) {
      got = await s.decrypt('$f');
    }
    expect(got, v['down_message']);
    final big = await s.encrypt({'t': 'ws', 'd': 'x' * (linkChunk + 10)});
    expect(big, v['big_up_frames_after_auth']);
  });

  test('wrong pinned PC key, replay and tampering are rejected', () async {
    final dev = await LinkKeyPair.generate();
    final pc = await LinkKeyPair.generate();
    final ep = await LinkKeyPair.generate();
    final es = await LinkKeyPair.generate();
    final (welcome, pcs) = await LinkSession.pcAccept(pc, es, linkHello(dev, ep));
    final other = await LinkKeyPair.generate();
    expect(() => LinkSession.phoneFinish(dev, ep, other.publicBytes, welcome), throwsA(isA<LinkError>()));
    final ph = await LinkSession.phoneFinish(dev, ep, pc.publicBytes, welcome);
    final f = (await ph.encrypt({'n': 1})).single;
    expect(await pcs.decrypt(f), {'n': 1});
    expect(() => pcs.decrypt(f), throwsA(isA<LinkError>()));
    final g = jsonDecode((await ph.encrypt({'n': 2})).single) as Map;
    final ct = b64d(g['c']);
    ct[0] ^= 1;
    expect(() => pcs.decrypt(jsonEncode({'t': 'd', 'c': b64e(ct)})), throwsA(isA<LinkError>()));
  });
}
