// "Jalankan di latar belakang" seen from the phone: the PC's background
// service status, the setting itself, and the agent / gateway controls.
// Core: core/neovarch/background.py (GET/POST /api/remote/background).

/// What the PC reports on GET /api/remote/background.
class PcBackgroundStatus {
  const PcBackgroundStatus({
    required this.runInBackground,
    required this.startAtLogin,
    this.serviceState = 'running',
    this.mode = 'app',
    this.desktopAttached = true,
    this.pid,
    this.port,
    this.uptime = Duration.zero,
    this.sessions = 0,
    this.runningAgents = 0,
    this.relayState = 'off',
    this.relayPhones = 0,
    this.willStop = false,
  });

  final bool runInBackground;
  final bool startAtLogin;
  final String serviceState; // running | stopping | restarting
  final String mode; // app | background
  final bool desktopAttached;
  final int? pid;
  final int? port;
  final Duration uptime;
  final int sessions;
  final int runningAgents;
  final String relayState;
  final int relayPhones;
  final bool willStop;

  static int _int(Object? v) => v is num ? v.toInt() : int.tryParse('$v') ?? 0;

  factory PcBackgroundStatus.fromJson(Map<String, dynamic> j) {
    final svc = j['service'] is Map ? Map<String, dynamic>.from(j['service'] as Map) : const <String, dynamic>{};
    final agent = j['agent'] is Map ? Map<String, dynamic>.from(j['agent'] as Map) : const <String, dynamic>{};
    final relay = j['relay'] is Map ? Map<String, dynamic>.from(j['relay'] as Map) : const <String, dynamic>{};
    return PcBackgroundStatus(
      runInBackground: j['run_in_background'] == true,
      startAtLogin: j['start_at_login'] == true,
      serviceState: '${svc['state'] ?? 'running'}',
      mode: '${svc['mode'] ?? 'app'}',
      desktopAttached: svc['desktop_attached'] != false,
      pid: svc['pid'] == null ? null : _int(svc['pid']),
      port: svc['port'] == null ? null : _int(svc['port']),
      uptime: Duration(seconds: _int(svc['uptime_s'])),
      sessions: _int(agent['sessions']),
      runningAgents: _int(agent['running']),
      relayState: '${relay['state'] ?? 'off'}',
      relayPhones: _int(relay['phones']),
      willStop: j['will_stop'] == true,
    );
  }

  /// One line for the PC screen, in Indonesian.
  String get serviceLabel {
    if (willStop || serviceState == 'stopping') return 'Sedang dihentikan';
    if (serviceState == 'restarting') return 'Sedang dimulai ulang';
    if (!desktopAttached) return 'Berjalan di latar belakang (aplikasi PC tertutup)';
    return runInBackground ? 'Berjalan · tetap jalan saat jendela ditutup' : 'Berjalan · ikut jendela aplikasi';
  }

  String get uptimeLabel {
    final h = uptime.inHours;
    final m = uptime.inMinutes.remainder(60);
    if (h >= 24) return '${h ~/ 24} hari ${h % 24} jam';
    if (h > 0) return '$h jam $m menit';
    return '${uptime.inMinutes} menit';
  }
}

/// The four controls the PC exposes (POST /api/remote/background/{action}).
enum PcBackgroundAction {
  stopAgent('stop-agent', 'Hentikan agen'),
  restartAgent('restart-agent', 'Mulai ulang agen'),
  restartGateway('restart-gateway', 'Mulai ulang gateway'),
  stopGateway('stop-gateway', 'Hentikan gateway');

  const PcBackgroundAction(this.wire, this.label);
  final String wire;
  final String label;
}

/// What the panel needs; RemoteGateway implements it over LAN or the relay.
abstract class PcBackgroundApi {
  Future<PcBackgroundStatus> backgroundStatus();
  Future<PcBackgroundStatus> setBackground({bool? runInBackground, bool? startAtLogin});
  Future<String> backgroundAction(PcBackgroundAction action);
}
