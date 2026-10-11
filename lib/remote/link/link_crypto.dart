// End-to-end encryption for the phone ↔ PC link (relay and Bluetooth).
// Same protocol as core/neovarch/remote_link/crypto.py (docs/relay.md):
// X25519 static-static + ephemeral-ephemeral, HKDF-SHA256, ChaCha20-Poly1305
// with implicit per-direction counters as nonces (replay/reorder = failure).
import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

const int linkProtocol = 1;
const int linkChunk = 48 * 1024;
const int linkMaxMessage = 24 * 1024 * 1024;
final List<int> _label = utf8.encode('neovarch-link/1');
final List<int> _info = utf8.encode('neovarch-link/1 keys');

class LinkError implements Exception {
  final String message;
  const LinkError(this.message);
  @override
  String toString() => message;
}

String b64e(List<int> b) => base64Url.encode(b).replaceAll('=', '');

Uint8List b64d(String s) {
  try {
    return base64Url.decode(s + '=' * ((4 - s.length % 4) % 4));
  } catch (_) {
    throw const LinkError('bad base64');
  }
}

final _x25519 = X25519();
final _aead = Chacha20.poly1305Aead();

/// An X25519 key pair kept as raw bytes (private bytes go to secure storage).
class LinkKeyPair {
  LinkKeyPair._(this.privateBytes, this.publicBytes, this._kp);
  final Uint8List privateBytes;
  final Uint8List publicBytes;
  final SimpleKeyPair _kp;

  static Future<LinkKeyPair> fromPrivate(List<int> raw) async {
    if (raw.length != 32) throw const LinkError('bad private key');
    final kp = await _x25519.newKeyPairFromSeed(raw);
    final pub = await kp.extractPublicKey();
    return LinkKeyPair._(Uint8List.fromList(raw), Uint8List.fromList(pub.bytes), kp);
  }

  static Future<LinkKeyPair> generate() async {
    final kp = await _x25519.newKeyPair();
    return fromPrivate(await kp.extractPrivateKeyBytes());
  }

  Future<Uint8List> dh(List<int> peer) async {
    if (peer.length != 32) throw const LinkError('bad public key');
    final s = await _x25519.sharedSecretKey(keyPair: _kp, remotePublicKey: SimplePublicKey(peer, type: KeyPairType.x25519));
    final b = Uint8List.fromList(await s.extractBytes());
    if (b.every((x) => x == 0)) throw const LinkError('low-order public key');
    return b;
  }
}

Future<String> linkDeviceId(List<int> pkDev) async => b64e((await Sha256().hash(pkDev)).bytes).substring(0, 16);

Future<Uint8List> linkTranscript(List<int> pkDev, List<int> pkPc, List<int> ePhone, List<int> ePc) async =>
    Uint8List.fromList((await Sha256().hash([..._label, ...pkDev, ...pkPc, ...ePhone, ...ePc])).bytes);

Future<(Uint8List, Uint8List)> linkDerive(List<int> ikm, List<int> th) async {
  final okm = await Hkdf(hmac: Hmac.sha256(), outputLength: 64).deriveKey(secretKey: SecretKey(ikm), nonce: th, info: _info);
  final b = await okm.extractBytes();
  return (Uint8List.fromList(b.sublist(0, 32)), Uint8List.fromList(b.sublist(32)));
}

List<int> _nonce(int counter) {
  final n = Uint8List(12);
  final bd = ByteData.sublistView(n);
  bd.setUint32(4, counter >> 32);
  bd.setUint32(8, counter & 0xffffffff);
  return n;
}

Map<String, dynamic> linkHello(LinkKeyPair dev, LinkKeyPair eph) =>
    {'t': 'hello', 'v': linkProtocol, 'dev': b64e(dev.publicBytes), 'eph': b64e(eph.publicBytes)};

/// One direction pair of an established link.
class LinkSession {
  LinkSession._(this._kSend, this._kRecv, this.transcript);
  final SecretKey _kSend, _kRecv;
  final Uint8List transcript;
  int sendCounter = 0, recvCounter = 0;
  final List<int> _parts = [];

  /// Phone side: finish the handshake against the PC key pinned at pairing.
  static Future<LinkSession> phoneFinish(LinkKeyPair dev, LinkKeyPair eph, List<int> pinnedPc, Map<String, dynamic> welcome) async {
    if (welcome['t'] != 'welcome' || welcome['v'] != linkProtocol) throw const LinkError('unsupported welcome');
    final pkPc = b64d('${welcome['pc'] ?? ''}'), ePc = b64d('${welcome['eph'] ?? ''}');
    if (pkPc.length != 32 || ePc.length != 32) throw const LinkError('bad key length');
    var same = pinnedPc.length == pkPc.length;
    for (var i = 0; same && i < pkPc.length; i++) {
      same = pinnedPc[i] == pkPc[i];
    }
    if (!same) throw const LinkError('PC key does not match the pairing');
    final th = await linkTranscript(dev.publicBytes, pkPc, eph.publicBytes, ePc);
    final (up, down) = await linkDerive([...await dev.dh(pkPc), ...await eph.dh(ePc)], th);
    return LinkSession._(SecretKey(up), SecretKey(down), th);
  }

  /// PC side (tests and tooling; the PC does this in Python).
  static Future<(Map<String, dynamic>, LinkSession)> pcAccept(LinkKeyPair pc, LinkKeyPair eph, Map<String, dynamic> hello) async {
    final pkDev = b64d('${hello['dev']}'), ePhone = b64d('${hello['eph']}');
    final th = await linkTranscript(pkDev, pc.publicBytes, ePhone, eph.publicBytes);
    final (up, down) = await linkDerive([...await pc.dh(pkDev), ...await eph.dh(ePhone)], th);
    return (
      {'t': 'welcome', 'v': linkProtocol, 'pc': b64e(pc.publicBytes), 'eph': b64e(eph.publicBytes)},
      LinkSession._(SecretKey(down), SecretKey(up), th)
    );
  }

  Future<String> _seal(List<int> plaintext) async {
    final box = await _aead.encrypt(plaintext, secretKey: _kSend, nonce: _nonce(sendCounter), aad: transcript);
    sendCounter++;
    return jsonEncode({'t': 'd', 'c': b64e([...box.cipherText, ...box.mac.bytes])});
  }

  /// Wire frames for one inner message (split into parts above [linkChunk]).
  Future<List<String>> encrypt(Map<String, dynamic> message) async {
    final data = utf8.encode(jsonEncode(message));
    if (data.length > linkMaxMessage) throw const LinkError('message too large');
    final out = <String>[];
    if (data.isEmpty) return [await _seal([0])];
    for (var i = 0; i < data.length; i += linkChunk) {
      final end = i + linkChunk < data.length ? i + linkChunk : data.length;
      out.add(await _seal([end < data.length ? 1 : 0, ...data.sublist(i, end)]));
    }
    return out;
  }

  /// Feed one wire frame; the inner message once complete, else null. Throws [LinkError].
  Future<Map<String, dynamic>?> decrypt(String frame) async {
    Map f;
    try {
      f = jsonDecode(frame) as Map;
    } catch (_) {
      throw const LinkError('bad frame');
    }
    if (f['t'] != 'd') throw const LinkError('expected a data frame');
    final raw = b64d('${f['c'] ?? ''}');
    if (raw.length < 16) throw const LinkError('short frame');
    List<int> pt;
    try {
      pt = await _aead.decrypt(SecretBox(raw.sublist(0, raw.length - 16), nonce: _nonce(recvCounter), mac: Mac(raw.sublist(raw.length - 16))),
          secretKey: _kRecv, aad: transcript);
    } catch (_) {
      throw const LinkError('authentication failed');
    }
    recvCounter++;
    if (pt.isEmpty) throw const LinkError('empty frame');
    _parts.addAll(pt.sublist(1));
    if (_parts.length > linkMaxMessage) throw const LinkError('message too large');
    if (pt[0] == 1) return null;
    if (pt[0] != 0) throw const LinkError('bad flag');
    final text = utf8.decode(_parts);
    _parts.clear();
    final m = jsonDecode(text);
    if (m is! Map) throw const LinkError('expected an object');
    return Map<String, dynamic>.from(m);
  }
}
