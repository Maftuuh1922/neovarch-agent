// "Hey Neo" wake word (opt-in). Android only: a microphone foreground
// service (NvWakeService.kt) listens offline with Vosk for exactly the phrase
// "hey neo" and opens Chat dictation. The ~40 MB English model is downloaded
// the first time it is switched on. After a reboot Android 11+ does not let it
// restart with the microphone, so a notification asks for one tap
// (`nv_route=wake`, handled by RemoteShell -> [WakeWordController.resume]).
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/legacy.dart';

import '../data/device_tools.dart';

class WakeWordStatus {
  const WakeWordStatus({this.enabled = false, this.state = 'off', this.modelReady = false, this.heard, this.heardAt = 0, this.testUntil = 0});
  factory WakeWordStatus.fromMap(Map<dynamic, dynamic>? m) => WakeWordStatus(
        enabled: m?['enabled'] == true,
        state: '${m?['state'] ?? 'off'}',
        modelReady: m?['modelReady'] == true,
        heard: m?['heard'] is String ? m!['heard'] as String : null,
        heardAt: m?['heardAt'] is int ? m!['heardAt'] as int : 0,
        testUntil: m?['testUntil'] is int ? m!['testUntil'] as int : 0,
      );
  /// "Tes Hey Neo": last text the recogniser heard (epoch ms), test window end.
  final String? heard;
  final int heardAt;
  final int testUntil;
  bool testing(DateTime now) => testUntil > now.millisecondsSinceEpoch;
  final bool enabled;
  /// `off`, `downloading[:done:total]`, `retrying:n:reason`, `listening`,
  /// `stopped` or `error:` + reason
  final String state;
  final bool modelReady;

  bool get downloading => state == 'downloading' || state.startsWith('downloading:') || state.startsWith('retrying:');

  /// Bytes received / expected while downloading (total 0 = unknown).
  (int, int)? get progress {
    if (!state.startsWith('downloading:')) return null;
    final p = state.split(':');
    if (p.length < 3) return null;
    return (int.tryParse(p[1]) ?? 0, int.tryParse(p[2]) ?? 0);
  }

  /// 0..1, null when unknown (indeterminate bar).
  double? get fraction {
    final p = progress;
    if (p == null || p.$2 <= 0) return null;
    return (p.$1 / p.$2).clamp(0.0, 1.0);
  }

  /// "Mengunduh model suara 12 / 40 MB (30%)" (same text as the notification).
  static String progressText(int done, int total) {
    final mb = done ~/ 1048576;
    return total > 0 ? 'Mengunduh model suara $mb / ${total ~/ 1048576} MB (${done * 100 ~/ total}%)' : 'Mengunduh model suara $mb MB';
  }

  String get label {
    if (!enabled) return 'Mati';
    if (state == 'downloading') return 'Mengunduh model suara…';
    final p = progress;
    if (p != null) return p.$1 == 0 && p.$2 == 0 ? 'Mengunduh model suara…' : progressText(p.$1, p.$2);
    if (state.startsWith('retrying:')) {
      final n = state.split(':');
      return 'Unduhan macet, mencoba lagi… (${n.length > 1 ? n[1] : '1'}/3)${n.length > 2 ? ' · ${n.sublist(2).join(':')}' : ''}';
    }
    if (state == 'listening') return 'Mendengarkan "Hey Neo"';
    if (state == 'stopped') return 'Berhenti (ketuk notifikasi atau nyalakan lagi)';
    if (state.startsWith('error:')) return 'Gagal: ${state.substring(6)}';
    return 'Menyiapkan…';
  }
}

@immutable
class BackgroundPerms {
  const BackgroundPerms({this.overlay = false, this.battery = false, this.xiaomi = false});
  final bool overlay, battery, xiaomi;
}

/// Talks to the native side over `neovarch/device` (`wakeWord`, `wakeStatus`).
class WakeWordController extends ChangeNotifier {
  WakeWordController({
    Future<Object?> Function(String method, [Map<String, dynamic>? args])? call,
    Future<bool> Function()? permissions,
  })  : _call = call ?? _deviceCall,
        _permissions = permissions ?? _askPermissions;

  final Future<Object?> Function(String method, [Map<String, dynamic>? args]) _call;
  final Future<bool> Function() _permissions;

  WakeWordStatus status = const WakeWordStatus();
  String? error;
  bool busy = false;

  static bool get supported => !kIsWeb && defaultTargetPlatform == TargetPlatform.android;

  static Future<Object?> _deviceCall(String method, [Map<String, dynamic>? args]) => deviceCall<Object?>(method, args);

  // Microphone (required) and notifications (the "ketuk untuk bicara" and
  // restart prompts; Android 13+). Only the microphone decides.
  static Future<bool> _askPermissions() async {
    final mic = await ensurePermissions(const ['android.permission.RECORD_AUDIO']);
    try {
      await ensurePermissions(const ['android.permission.POST_NOTIFICATIONS']);
    } catch (_) {}
    return mic;
  }

  /// "Tes Hey Neo": the service shows what it hears for 60 s.
  Future<void> startTest() async {
    try {
      status = WakeWordStatus.fromMap(await _call('wakeTest') as Map?);
      error = null;
    } catch (e) {
      error = '$e';
    }
    notifyListeners();
  }

  /// Granted state of the two background rows (`overlay`, `battery`) and
  /// whether this is a Xiaomi/Redmi/POCO phone (MIUI hint).
  BackgroundPerms background = const BackgroundPerms();

  Future<void> refreshBackground() async {
    try {
      final m = await _call('wakeBackgroundStatus');
      if (m is Map) {
        background = BackgroundPerms(overlay: m['overlay'] == true, battery: m['battery'] == true, xiaomi: m['xiaomi'] == true);
        notifyListeners();
      }
    } catch (_) {}
  }

  /// Opens the overlay page (or battery / autostart for background use).
  /// Returns the page that opened; null when none could be opened (the
  /// panel then shows a message instead of silently doing nothing).
  Future<String?> openBackgroundSettings({bool overlay = false}) async {
    try {
      final r = '${await _call('wakeBackground', {'kind': overlay ? 'overlay' : 'autostart'})}';
      return r == 'none' || r == 'null' ? null : r;
    } catch (e) {
      error = '$e';
      notifyListeners();
      return null;
    }
  }

  Future<void> refresh() async {
    try {
      status = WakeWordStatus.fromMap(await _call('wakeStatus') as Map?);
      error = null;
    } catch (e) {
      error = '$e';
    }
    notifyListeners();
  }

  /// Opt-in switch. Turning on asks for the microphone first.
  Future<void> setEnabled(bool on) async {
    busy = true;
    error = null;
    notifyListeners();
    try {
      if (on && !await _permissions()) {
        error = 'Izin mikrofon ditolak. Izinkan di Setelan → Aplikasi → Neovarch Agent → Izin.';
        return;
      }
      status = WakeWordStatus.fromMap(await _call('wakeWord', {'enable': on}) as Map?);
    } catch (e) {
      error = '$e';
    } finally {
      busy = false;
      notifyListeners();
    }
  }

  /// From the after-reboot notification: start again from the foreground.
  Future<void> resume() async {
    await refresh();
    if (status.enabled) await setEnabled(true);
  }
}

final wakeWordProvider = ChangeNotifierProvider<WakeWordController>((ref) => WakeWordController());
