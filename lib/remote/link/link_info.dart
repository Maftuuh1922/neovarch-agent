// What the phone remembers to reach a PC without the LAN: the PC's relay room
// id and public key (pinned at pairing), the relay URL, and the Bluetooth
// target. The device's private key lives in flutter_secure_storage
// (SavedDesktops.linkKey), never here.

/// Bluetooth RFCOMM target of the PC (only when the PC enabled Bluetooth).
class BluetoothTarget {
  const BluetoothTarget({required this.address, this.channel, this.uuid});
  final String address; // AA:BB:CC:DD:EE:FF
  final int? channel;
  final String? uuid;

  static final _mac = RegExp(r'^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$');

  static BluetoothTarget? tryParse(Object? j) {
    if (j is! Map) return null;
    final a = '${j['address'] ?? ''}'.trim();
    if (!_mac.hasMatch(a)) return null;
    return BluetoothTarget(address: a.toUpperCase(), channel: (j['channel'] as num?)?.toInt(), uuid: j['uuid'] as String?);
  }

  Map<String, dynamic> toJson() => {'address': address, 'channel': channel, 'uuid': uuid};
}

class LinkInfo {
  const LinkInfo({required this.pcId, required this.pcPk, this.relayUrl, this.pairCode, this.enrolled = false, this.bluetooth, this.deviceId});

  /// Relay room id (22 chars) and the PC's X25519 public key (base64url).
  final String pcId, pcPk;
  final String? relayUrl;

  /// One-time pairing code from the QR, used until this device is enrolled.
  final String? pairCode;
  final bool enrolled;
  final BluetoothTarget? bluetooth;
  final String? deviceId;

  static final _pcId = RegExp(r'^[A-Za-z0-9_-]{22}$');
  static final _pk = RegExp(r'^[A-Za-z0-9_-]{43}$');

  bool get valid => _pcId.hasMatch(pcId) && _pk.hasMatch(pcPk);
  bool get canRelay => valid && (relayUrl ?? '').isNotEmpty;

  static LinkInfo? tryParse(Object? j) {
    if (j is! Map) return null;
    final l = LinkInfo(
      pcId: '${j['pc_id'] ?? j['pcId'] ?? ''}',
      pcPk: '${j['pc_pk'] ?? j['pcPk'] ?? ''}',
      relayUrl: (j['relay_url'] ?? j['relayUrl']) as String?,
      pairCode: (j['pair_code'] ?? j['pairCode']) as String?,
      enrolled: j['enrolled'] == true,
      bluetooth: BluetoothTarget.tryParse(j['bluetooth']),
      deviceId: (j['device'] ?? j['deviceId']) as String?,
    );
    return l.valid ? l : null;
  }

  Map<String, dynamic> toJson() => {
        'pcId': pcId,
        'pcPk': pcPk,
        'relayUrl': relayUrl,
        'pairCode': pairCode,
        'enrolled': enrolled,
        'bluetooth': bluetooth?.toJson(),
        'deviceId': deviceId,
      };

  LinkInfo copyWith({String? relayUrl, bool clearRelay = false, String? pairCode, bool clearPairCode = false, bool? enrolled, BluetoothTarget? bluetooth, bool clearBluetooth = false, String? deviceId, String? pcId, String? pcPk}) =>
      LinkInfo(
        pcId: pcId ?? this.pcId,
        pcPk: pcPk ?? this.pcPk,
        relayUrl: clearRelay ? null : (relayUrl ?? this.relayUrl),
        pairCode: clearPairCode ? null : (pairCode ?? this.pairCode),
        enrolled: enrolled ?? this.enrolled,
        bluetooth: clearBluetooth ? null : (bluetooth ?? this.bluetooth),
        deviceId: deviceId ?? this.deviceId,
      );
}
