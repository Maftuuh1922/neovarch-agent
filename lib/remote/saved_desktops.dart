// Desktops this phone has paired with. Addresses live in shared_preferences;
// each gateway token lives in flutter_secure_storage (never in prefs, except
// the web preview build which has no keystore).
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'link/link_crypto.dart';
import 'link/link_info.dart';
import 'pairing.dart';

class SavedDesktop {
  final String id;
  final String name;
  final String url;
  final String? profile;
  final Map<String, String> headers;
  final DateTime addedAt;
  DateTime? lastConnected;

  /// Fallback addresses of this PC (Tailscale / other LAN interfaces), kept
  /// fresh from `network.addresses` after each connect.
  List<String> alternates;

  /// The address that answered last (tried first next time).
  String? lastUrl;

  /// Relay / Bluetooth identity of this PC (Remote dari mana saja).
  LinkInfo? link;

  /// Phone-side setting: also try Bluetooth when the LAN is not reachable.
  bool bluetooth;
  SavedDesktop(
      {required this.id,
      required this.name,
      required this.url,
      this.profile,
      this.headers = const {},
      required this.addedAt,
      this.lastConnected,
      this.alternates = const [],
      this.lastUrl,
      this.link,
      this.bluetooth = false});

  /// Candidate addresses in connect order: LAN first, then Tailscale.
  List<String> get candidates => orderedGatewayUrls([url, ...alternates]);

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'url': url,
        'profile': profile,
        'headers': headers,
        'addedAt': addedAt.toIso8601String(),
        'lastConnected': lastConnected?.toIso8601String(),
        'alternates': alternates,
        'lastUrl': lastUrl,
        if (link != null) 'link': link!.toJson(),
        'bluetooth': bluetooth,
      };
  factory SavedDesktop.fromJson(Map<String, dynamic> j) => SavedDesktop(
        id: '${j['id']}',
        name: '${j['name'] ?? ''}',
        url: '${j['url'] ?? ''}',
        profile: j['profile'] as String?,
        headers: j['headers'] is Map ? (j['headers'] as Map).map((k, v) => MapEntry('$k', '$v')) : const {},
        addedAt: DateTime.tryParse('${j['addedAt'] ?? ''}') ?? DateTime.now(),
        lastConnected: DateTime.tryParse('${j['lastConnected'] ?? ''}'),
        alternates: [for (final a in (j['alternates'] as List? ?? const [])) '$a'],
        lastUrl: j['lastUrl'] as String?,
        link: LinkInfo.tryParse(j['link']),
        bluetooth: j['bluetooth'] == true,
      );
}

class SavedDesktops {
  SavedDesktops(this._prefs);
  final SharedPreferences _prefs;
  final FlutterSecureStorage _secure = const FlutterSecureStorage();
  static const _key = 'remote.desktops';
  static const _activeKey = 'remote.active';

  final List<SavedDesktop> items = [];
  String? activeId;

  void load() {
    items.clear();
    try {
      final raw = jsonDecode(_prefs.getString(_key) ?? '[]') as List;
      items.addAll(raw.whereType<Map>().map((e) => SavedDesktop.fromJson(Map<String, dynamic>.from(e))));
    } catch (_) {}
    activeId = _prefs.getString(_activeKey);
  }

  void _save() {
    _prefs.setString(_key, jsonEncode(items.map((e) => e.toJson()).toList()));
    if (activeId == null) {
      _prefs.remove(_activeKey);
    } else {
      _prefs.setString(_activeKey, activeId!);
    }
  }

  SavedDesktop? get active => items.where((d) => d.id == activeId).firstOrNull ?? items.firstOrNull;

  /// Add or update (same URL = same desktop) and make it active.
  /// The id [upsert] will use for [p] (so a device key can be made first).
  String idFor(GatewayPairing p) =>
      items.where((d) => d.url == p.url || (p.link != null && d.link?.pcId == p.link!.pcId)).firstOrNull?.id ??
      'pc_${DateTime.now().microsecondsSinceEpoch}';

  Future<SavedDesktop> upsert(GatewayPairing p, {String? id}) async {
    final existing = items.where((d) => d.id == id || d.url == p.url || (p.link != null && d.link?.pcId == p.link!.pcId)).firstOrNull;
    final d = SavedDesktop(
      id: existing?.id ?? id ?? 'pc_${DateTime.now().microsecondsSinceEpoch}',
      name: p.displayName,
      url: p.url,
      profile: p.profile,
      headers: p.headers,
      addedAt: existing?.addedAt ?? DateTime.now(),
      lastConnected: DateTime.now(),
      alternates: p.alternates.isNotEmpty ? p.alternates : (existing?.alternates ?? const []),
      // A fresh QR replaces the link (new pairing code); an old QR keeps what we had.
      link: p.link != null && existing?.link?.pcPk == p.link!.pcPk && existing?.link?.enrolled == true
          ? p.link!.copyWith(enrolled: true, clearPairCode: true, deviceId: existing!.link!.deviceId)
          : (p.link ?? existing?.link),
      bluetooth: existing?.bluetooth ?? false,
    );
    items
      ..removeWhere((x) => x.id == d.id)
      ..insert(0, d);
    activeId = d.id;
    await _writeToken(d.id, p.token);
    _save();
    return d;
  }

  void touch(SavedDesktop d) {
    d.lastConnected = DateTime.now();
    activeId = d.id;
    _save();
  }

  /// Remember the addresses the PC reported and which one answered.
  void updateRoutes(SavedDesktop d, {List<String>? alternates, String? lastUrl}) {
    if (alternates != null) d.alternates = [for (final a in alternates) if (a != d.url) a];
    if (lastUrl != null) d.lastUrl = lastUrl;
    _save();
  }

  /// Save a changed link (enrolled, new relay URL) or the Bluetooth setting.
  void updateLink(SavedDesktop d, {LinkInfo? link, bool? bluetooth}) {
    if (link != null) d.link = link;
    if (bluetooth != null) d.bluetooth = bluetooth;
    _save();
  }

  /// This phone's X25519 device key for desktop [id] (created on first use,
  /// kept in secure storage, one per PC so a revoke on one PC affects only it).
  Future<LinkKeyPair> linkKey(String id) async {
    final k = 'remote.linkkey.$id';
    String? raw;
    try {
      raw = kIsWeb ? _prefs.getString(k) : await _secure.read(key: k);
    } catch (_) {
      raw = _prefs.getString('$k.fallback');
    }
    if (raw != null && raw.isNotEmpty) {
      try {
        return await LinkKeyPair.fromPrivate(b64d(raw));
      } catch (_) {}
    }
    final kp = await LinkKeyPair.generate();
    final enc = b64e(kp.privateBytes);
    try {
      if (kIsWeb) {
        await _prefs.setString(k, enc);
      } else {
        await _secure.write(key: k, value: enc);
      }
    } catch (_) {
      await _prefs.setString('$k.fallback', enc);
    }
    return kp;
  }

  Future<void> remove(String id) async {
    items.removeWhere((d) => d.id == id);
    if (activeId == id) activeId = items.firstOrNull?.id;
    try {
      await _secure.delete(key: 'remote.token.$id');
      await _secure.delete(key: 'remote.linkkey.$id');
    } catch (_) {}
    await _prefs.remove('remote.linkkey.$id');
    await _prefs.remove('remote.linkkey.$id.fallback');
    await _prefs.remove('remote.tokenfallback.$id');
    _save();
  }

  Future<String> token(String id) async {
    if (kIsWeb) return _prefs.getString('remote.tokenfallback.$id') ?? '';
    try {
      return await _secure.read(key: 'remote.token.$id') ?? _prefs.getString('remote.tokenfallback.$id') ?? '';
    } catch (_) {
      return _prefs.getString('remote.tokenfallback.$id') ?? '';
    }
  }

  Future<void> _writeToken(String id, String token) async {
    if (kIsWeb) {
      await _prefs.setString('remote.tokenfallback.$id', token);
      return;
    }
    try {
      await _secure.write(key: 'remote.token.$id', value: token);
    } catch (_) {
      // Keystore unavailable (rare emulator images): keep the remote usable.
      await _prefs.setString('remote.tokenfallback.$id', token);
    }
  }
}
