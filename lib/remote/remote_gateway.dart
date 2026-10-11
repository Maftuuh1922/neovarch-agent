// The phone's link to the desktop: the Neovarch core gateway, JSON-RPC over
// a persistent WebSocket (`/api/ws`, via GatewayClient) plus the REST routes
// the remote needs (Office, Obsidian vault, appearance, Kanban, update). Pure
// Dart so it is unit-tested against an in-process mock gateway.
//
// Gateway facts this relies on (see docs/remote-protocol.md):
//   * auth: `?token=` on the WS URL; REST takes `X-Neovarch-Session-Token`
//     or `Authorization: Bearer` with the same token;
//   * `client.capabilities {server_requests:true}` must be sent, otherwise
//     approvals are never sent to this connection;
//   * approvals arrive as a server→client JSON-RPC request `approval`
//     (string id `srq-…`), answered with `{choice}`; `request.cancel` and
//     `approval.cancelled` withdraw them; `approval.pending` / `.respond`
//     are the RPC fallbacks;
//   * realtime: everything is pushed (`office.update`, `appearance.changed`,
//     `kanban.changed`, `vault.changed`, session events); nothing is polled.
//     Events carry `seq`; after a reconnect `events.replay {since, boot_id}`
//     returns what was missed or `{resync:true}`;
//   * `ping` is the keepalive (every 15 s here, 8 s timeout) and returns
//     `boot_id` so a PC restart is noticed.
import 'dart:async';
import 'dart:convert';

import 'dart:math' as math;
import 'dart:typed_data';

import 'package:http/http.dart' as http;
import 'package:flutter/foundation.dart' show visibleForTesting;

import '../data/gateway_client.dart';
import '../models/models.dart';
import 'attachments.dart';
import 'company_models.dart';
import 'composer.dart';
import 'models_api.dart';
import 'office_models.dart';
import 'pairing.dart';
import 'vault_models.dart';
import 'remote_transcript.dart';
import 'social_models.dart';

enum RemoteStatus { disconnected, connecting, connected, reconnecting, failed }

class RemoteApproval {
  /// Server request id (`srq-…`) when it came as a server→client request.
  final String? rid;
  final String sessionId; // runtime session id
  final String requestId;
  final String command;
  final String description;
  final String? toolName;
  final List<String> choices;
  final DateTime receivedAt;
  RemoteApproval({
    this.rid,
    required this.sessionId,
    required this.requestId,
    required this.command,
    required this.description,
    this.toolName,
    required this.choices,
    DateTime? receivedAt,
  }) : receivedAt = receivedAt ?? DateTime.now();

  String get key => rid ?? '$sessionId/$requestId';

  static List<String> _choices(Object? raw) {
    final l = (raw is List ? raw : const ['once', 'session', 'deny'])
        .map((e) => e is Map ? '${e['id'] ?? e['value'] ?? e['choice'] ?? e}' : '$e')
        .where((e) => e.isNotEmpty)
        .toList();
    return l.isEmpty ? const ['once', 'deny'] : l;
  }

  factory RemoteApproval.fromParams(Map<String, dynamic> p, {String? rid, String? sessionId}) => RemoteApproval(
        rid: rid,
        sessionId: '${p['session_id'] ?? sessionId ?? ''}',
        requestId: '${p['request_id'] ?? ''}',
        command: '${p['command'] ?? ''}',
        description: '${p['description'] ?? ''}',
        toolName: p['tool_name'] as String?,
        choices: _choices(p['choices']),
      );
}

class KanbanCard {
  final String id;
  final String title;
  final String? body;
  final String status;
  final String? assignee;
  final int priority;
  final String? summary;
  final int comments;
  const KanbanCard(
      {required this.id, required this.title, this.body, required this.status, this.assignee, this.priority = 0, this.summary, this.comments = 0});
  factory KanbanCard.fromJson(Map<String, dynamic> j) => KanbanCard(
        id: '${j['id']}',
        title: '${j['title'] ?? '(tanpa judul)'}',
        body: j['body'] as String?,
        status: '${j['status'] ?? ''}',
        assignee: j['assignee'] as String?,
        priority: (j['priority'] as num?)?.toInt() ?? 0,
        summary: j['latest_summary'] as String?,
        comments: (j['comment_count'] as num?)?.toInt() ?? 0,
      );
}

class KanbanLane {
  final String name;
  final List<KanbanCard> cards;
  const KanbanLane(this.name, this.cards);
}

class KanbanSnapshot {
  final List<KanbanLane> lanes;
  final List<String> assignees;
  const KanbanSnapshot(this.lanes, this.assignees);
  factory KanbanSnapshot.fromJson(Map<String, dynamic> j) => KanbanSnapshot(
        [
          for (final c in (j['columns'] as List? ?? const []).whereType<Map>())
            KanbanLane('${c['name']}', [for (final t in (c['tasks'] as List? ?? const []).whereType<Map>()) KanbanCard.fromJson(Map<String, dynamic>.from(t))]),
        ],
        [for (final a in (j['assignees'] as List? ?? const [])) '$a'],
      );
}

/// A session opened on the phone: stored id (durable) + runtime id (live).
class OpenedSession {
  final String storedId;
  final String runtimeId;
  final String title;
  final List<ChatMsg> messages;
  final bool running;
  const OpenedSession({required this.storedId, required this.runtimeId, required this.title, required this.messages, this.running = false});
}

class ActiveSession {
  final String id; // runtime id
  final String title;
  final String status;
  final String model;
  final String preview;
  const ActiveSession({required this.id, required this.title, required this.status, required this.model, required this.preview});
}

class RemoteGateway implements VaultApi, ModelsApi, CompanyApi {
  RemoteGateway({
    required this.baseUrl,
    required this.token,
    this.alternates = const [],
    this.headers = const {},
    this.profile,
    http.Client? httpClient,
    this.heartbeat = const Duration(seconds: 15),
    this.pingTimeout = const Duration(seconds: 8),
    this.autoReconnect = true,
    this.lanTimeout = const Duration(milliseconds: 2500),
    this.wanTimeout = const Duration(seconds: 6),
    math.Random? random,
  })  : _http = httpClient ?? http.Client(),
        _rand = random ?? math.Random() {
    activeUrl = candidates.first;
    client = GatewayClient(baseUrl: activeUrl, token: token, headers: headers);
  }

  /// The paired address; [alternates] are other routes to the same PC.
  final String baseUrl;
  List<String> alternates;
  final String token;
  final Map<String, String> headers;
  final String? profile;
  final Duration heartbeat;
  final Duration pingTimeout;
  final bool autoReconnect;
  final Duration lanTimeout, wanTimeout;
  final http.Client _http;
  final math.Random _rand;
  late GatewayClient client;

  /// The address the live socket uses (REST goes there too).
  late String activeUrl;

  /// LAN first, then Tailscale MagicDNS, then tailnet IPs.
  List<String> get candidates => orderedGatewayUrls([baseUrl, ...alternates]);
  String get route => gatewayRoute(activeUrl);

  RemoteStatus status = RemoteStatus.disconnected;
  String? lastError;
  final _status = StreamController<RemoteStatus>.broadcast();
  final _events = StreamController<GatewayEventFrame>.broadcast();
  final _approvalsChanged = StreamController<RemoteApproval?>.broadcast();
  final _routes = StreamController<List<String>>.broadcast();
  final Map<String, RemoteApproval> _approvals = {};
  StreamSubscription<GatewayEventFrame>? _sub;
  Timer? _beat;
  Timer? _retry;
  int _attempt = 0;
  bool _closed = false;
  bool _everConnected = false;

  // realtime cursor (core v1.4: every event carries `seq`; ping returns boot_id)
  int lastSeq = 0;
  String? bootId;
  final _seen = <int>{}; // LinkedHashSet: oldest first
  bool _rebooted = false;

  /// Runtime session ids this phone attached to (re-attached on reconnect).
  final Set<String> attached = {};

  /// True after a reconnect whose missed events could not be replayed: the
  /// open chat must be re-read with `session.resume`.
  bool resyncNeeded = false;

  /// Round trip of the last keepalive ping.
  Duration? lastRtt;

  Stream<RemoteStatus> get statusStream => _status.stream;

  /// Gateway notifications (session-scoped events) after approval handling.
  Stream<GatewayEventFrame> get events => _events.stream;

  /// Fires with the new approval when one arrives, null when one goes away.
  Stream<RemoteApproval?> get approvalsChanged => _approvalsChanged.stream;

  /// Fallback addresses the PC reported (`network.addresses`).
  Stream<List<String>> get routesChanged => _routes.stream;
  List<RemoteApproval> get approvals => _approvals.values.toList()..sort((a, b) => a.receivedAt.compareTo(b.receivedAt));

  Map<String, dynamic> get _p => {if (profile != null && profile!.isNotEmpty) 'profile': profile};

  Map<String, String> get _restHeaders => {
        ...headers,
        if (token.isNotEmpty) 'X-Neovarch-Session-Token': token,
        if (token.isNotEmpty) 'Authorization': 'Bearer $token',
      };

  void _setStatus(RemoteStatus s) {
    status = s;
    if (!_status.isClosed) _status.add(s);
  }

  // ------------------------------------------------------------ connection --
  /// Open the socket on the first address that answers (LAN first, then
  /// Tailscale), advertise server-request support, replay what was missed,
  /// start the keepalive. Throws (and sets [lastError]) when no address works.
  Future<void> connect() async {
    _closed = false;
    _retry?.cancel();
    // Replay cursor fixed before the socket opens: live events that arrive
    // before the replay answer must not move it past the gap.
    final since = lastSeq;
    _setStatus(_attempt == 0 && !_everConnected ? RemoteStatus.connecting : RemoteStatus.reconnecting);
    try {
      Object? firstError;
      var ok = false;
      for (final url in candidates) {
        if (_closed) break;
        final c = GatewayClient(
            baseUrl: url, token: token, headers: headers, connectTimeout: gatewayRoute(url) == 'lan' ? lanTimeout : wanTimeout);
        try {
          await c.ensureConnected();
        } catch (e) {
          firstError ??= e;
          c.close();
          continue;
        }
        await _sub?.cancel();
        client.close();
        client = c;
        activeUrl = url;
        _sub = c.events.listen(_onFrame);
        ok = true;
        break;
      }
      if (!ok) throw firstError ?? const RpcError(0, 'tidak ada alamat PC yang menjawab');
      await client.call('client.capabilities', {'server_requests': true}, const Duration(seconds: 15));
      await _replayMissed(since);
      _attempt = 0;
      lastError = null;
      _everConnected = true;
      _beat?.cancel();
      _beat = Timer.periodic(heartbeat, (_) => ping());
      _setStatus(RemoteStatus.connected);
      unawaited(_refreshRoutes());
      unawaited(ping());
    } catch (e) {
      lastError = '$e';
      final retrying = autoReconnect && !_closed && (_attempt > 0 || _everConnected);
      _setStatus(retrying ? RemoteStatus.reconnecting : RemoteStatus.failed);
      if (retrying) _scheduleRetry();
      rethrow;
    }
  }

  /// After a reconnect: ask the core for the events this phone missed
  /// (`events.replay`, which also re-attaches the open sessions). Cores
  /// without it, or a gap it no longer holds, set [resyncNeeded].
  Future<void> _replayMissed(int since) async {
    resyncNeeded = false;
    if (!_everConnected) return;
    if (_rebooted) {
      _rebooted = false;
      resyncNeeded = true;
      _emit(const GatewayEventFrame('resync.required', null, {'reason': 'restart'}));
      return;
    }
    if (bootId == null || since <= 0) {
      resyncNeeded = true;
      return;
    }
    try {
      final r = await client.call('events.replay',
          {..._p, 'since': since, 'boot_id': bootId, 'session_ids': attached.toList()}, const Duration(seconds: 10));
      if (r is! Map || r['resync'] == true) {
        resyncNeeded = true;
        if (r is Map && r['boot_id'] != null) bootId = '${r['boot_id']}';
        if (r is Map && r['seq'] is num) lastSeq = (r['seq'] as num).toInt();
        _emit(const GatewayEventFrame('resync.required', null, {}));
        return;
      }
      for (final ev in (r['events'] as List? ?? const []).whereType<Map>()) {
        _onFrame(GatewayEventFrame('${ev['type']}', ev['session_id'] as String?,
            ev['payload'] is Map ? Map<String, dynamic>.from(ev['payload'] as Map) : <String, dynamic>{},
            seq: (ev['seq'] as num?)?.toInt(), replayed: true));
      }
    } catch (_) {
      resyncNeeded = true;
      _emit(const GatewayEventFrame('resync.required', null, {}));
    }
  }

  Future<void> _refreshRoutes() async {
    try {
      final r = await client.call('network.addresses', const {}, const Duration(seconds: 8));
      final urls = (r is Map ? r['urls'] : null) as List?;
      if (urls == null) return;
      final list = [for (final u in urls) normalizeGatewayUrl('$u')].whereType<String>().where((u) => u != baseUrl).toList();
      if (list.isEmpty) return;
      alternates = list;
      if (!_routes.isClosed) _routes.add(list);
    } catch (_) {
      // Older core: no network.addresses; the paired address is all we have.
    }
  }

  /// Keepalive: a dead or half-open socket is detected within [pingTimeout]
  /// and reconnected; a changed `boot_id` (PC restarted) forces a resync.
  Future<void> ping() async {
    if (status != RemoteStatus.connected) return;
    final sw = Stopwatch()..start();
    try {
      final r = await client.call('ping', const {}, pingTimeout);
      lastRtt = sw.elapsed;
      if (r is Map) {
        final b = r['boot_id'];
        if (b != null) {
          if (bootId != null && bootId != '$b') {
            lastSeq = 0;
            _seen.clear();
            resyncNeeded = true;
            bootId = '$b';
            _emit(const GatewayEventFrame('resync.required', null, {'reason': 'restart'}));
          }
          bootId = '$b';
        }
        if (r['seq'] is num && lastSeq == 0) lastSeq = (r['seq'] as num).toInt();
      }
    } catch (_) {
      client.close();
      _onDisconnected();
    }
  }

  void _onDisconnected() {
    if (status == RemoteStatus.reconnecting && _retry != null) return;
    _beat?.cancel();
    _beat = null;
    if (_closed) {
      _setStatus(RemoteStatus.disconnected);
      return;
    }
    _setStatus(RemoteStatus.reconnecting);
    if (autoReconnect) _scheduleRetry(immediate: _attempt == 0);
  }

  /// Exponential backoff with ±20 % jitter: 0.5, 1, 2, 4, 8, 16, 30 s cap.
  /// The first retry after a drop is immediate (most drops are blips).
  Duration backoff(int attempt) {
    final base = math.min(30.0, 0.5 * math.pow(2, attempt));
    final j = 0.8 + _rand.nextDouble() * 0.4;
    return Duration(milliseconds: (base * j * 1000).round());
  }

  void _scheduleRetry({bool immediate = false}) {
    _retry?.cancel();
    final wait = immediate ? Duration.zero : backoff(_attempt);
    _attempt++;
    _retry = Timer(wait, () async {
      _retry = null;
      if (_closed) return;
      try {
        await connect(); // a failure schedules the next attempt itself
      } catch (_) {}
    });
  }

  /// Test hook: drop the socket as a flaky network would and come back after
  /// [away] (used by the real-core integration test).
  @visibleForTesting
  void debugDrop({Duration away = const Duration(seconds: 1)}) {
    _beat?.cancel();
    _beat = null;
    _retry?.cancel();
    client.close();
    _setStatus(RemoteStatus.reconnecting);
    _attempt = 1;
    _retry = Timer(away, () async {
      _retry = null;
      try {
        await connect();
      } catch (_) {}
    });
  }

  /// Reconnect now (pull-to-refresh / app resumed / network changed).
  Future<void> reconnect() async {
    _retry?.cancel();
    _retry = null;
    _attempt = 1;
    client.close();
    await connect();
  }

  void _emit(GatewayEventFrame f) {
    if (!_events.isClosed) _events.add(f);
  }

  void _onFrame(GatewayEventFrame f) {
    final seq = f.seq;
    if (seq != null) {
      if (_seen.contains(seq)) return; // replayed and also received live
      _seen.add(seq);
      if (_seen.length > 1024) _seen.remove(_seen.first);
      if (seq > lastSeq) lastSeq = seq;
    }
    if (f.payload['boot_id'] != null && (f.type == 'gateway.ready' || f.type == 'hello')) {
      final nb = '${f.payload['boot_id']}';
      if (bootId != null && bootId != nb) {
        _rebooted = true; // PC restarted while we were away: nothing to replay
        lastSeq = 0;
        _seen.clear();
      }
      bootId = nb;
      if (f.payload['seq'] is num && lastSeq == 0) lastSeq = (f.payload['seq'] as num).toInt();
    }
    switch (f.type) {
      case 'gateway.disconnected':
        _onDisconnected();
        return;
      case 'server.approval':
        final rid = f.payload['_rid'];
        final a = RemoteApproval.fromParams(f.payload, rid: rid == null ? null : '$rid', sessionId: f.sessionId);
        // Same approval may already be known from approval.pending (no rid).
        _approvals.removeWhere((_, x) => x.requestId.isNotEmpty && x.requestId == a.requestId);
        _approvals[a.key] = a;
        _approvalsChanged.add(a);
      case 'approval.request':
        // A notification instead of a server request.
        final a = RemoteApproval.fromParams(f.payload, sessionId: f.sessionId);
        if (!_approvals.values.any((x) => x.requestId.isNotEmpty && x.requestId == a.requestId)) {
          _approvals[a.key] = a;
          _approvalsChanged.add(a);
        }
      case 'request.cancel':
        final id = '${f.payload['id'] ?? ''}';
        if (_approvals.remove(id) != null) _approvalsChanged.add(null);
      case 'approval.cancelled':
        final ids = ((f.payload['request_ids'] as List?) ?? const []).map((e) => '$e').toSet();
        final sid = f.sessionId ?? '${f.payload['session_id'] ?? ''}';
        final before = _approvals.length;
        _approvals.removeWhere((_, a) => ids.contains(a.requestId) || (ids.isEmpty && a.sessionId == sid));
        if (_approvals.length != before) _approvalsChanged.add(null);
    }
    _emit(f);
  }

  Future<void> close() async {
    _closed = true;
    _retry?.cancel();
    _beat?.cancel();
    await _sub?.cancel();
    _sub = null;
    client.close();
    _http.close();
    _setStatus(RemoteStatus.disconnected);
    await _status.close();
    await _events.close();
    await _approvalsChanged.close();
    await _routes.close();
  }

  // --------------------------------------------------------------- sessions --
  Future<List<ChatSessionInfo>> listSessions({int limit = 60}) async {
    final r = await client.call('session.list', {..._p, 'limit': limit});
    final rows = (r is Map ? r['sessions'] : null) as List? ?? const [];
    return rows.whereType<Map>().map((row) {
      final started = row['last_active'] ?? row['started_at'];
      final ts = started is num
          ? DateTime.fromMillisecondsSinceEpoch((started * (started > 1e12 ? 1 : 1000)).toInt()).toIso8601String()
          : '${started ?? ''}';
      final preview = '${row['preview'] ?? ''}';
      final title = '${row['title'] ?? ''}'.trim();
      return ChatSessionInfo(
        id: '${row['id']}',
        title: title.isNotEmpty ? title : (preview.isNotEmpty ? preview : '${row['id']}'),
        profile: profile ?? 'default',
        updatedAt: ts,
        messageCount: (row['message_count'] as num?)?.toInt() ?? 0,
        preview: preview,
      );
    }).toList();
  }

  Future<List<ActiveSession>> activeSessions() async {
    final r = await client.call('session.active_list', {..._p});
    final rows = (r is Map ? r['sessions'] : null) as List? ?? const [];
    return [
      for (final s in rows.whereType<Map>())
        ActiveSession(
          id: '${s['id']}',
          title: '${s['title'] ?? ''}',
          status: '${s['status'] ?? ''}',
          model: '${s['model'] ?? ''}',
          preview: '${s['preview'] ?? ''}',
        ),
    ];
  }

  /// Attach to a stored session (also re-attaches after a reconnect): its
  /// transcript, whether a turn is running, and any approval it waits on.
  Future<OpenedSession> resume(String storedId) async {
    final r = Map<String, dynamic>.from(await client.call('session.resume', {..._p, 'session_id': storedId, 'source': 'mobile'}) as Map);
    final runtime = '${r['session_id']}';
    attached.add(runtime);
    _absorbPending(r, runtime);
    final info = r['info'] is Map ? r['info'] as Map : const {};
    return OpenedSession(
      storedId: '${r['stored_session_id'] ?? info['stored_session_id'] ?? storedId}',
      runtimeId: runtime,
      title: '${info['title'] ?? ''}',
      messages: RemoteTranscript.fromGatewayMessages(r['messages'] as List? ?? const []),
      running: r['running'] == true || info['running'] == true,
    );
  }

  Future<OpenedSession> create() async {
    final r = Map<String, dynamic>.from(await client.call('session.create', {..._p, 'source': 'mobile'}) as Map);
    final runtime = '${r['session_id']}';
    attached.add(runtime);
    return OpenedSession(
      storedId: '${r['stored_session_id'] ?? runtime}',
      runtimeId: runtime,
      title: '',
      messages: RemoteTranscript.fromGatewayMessages(r['messages'] as List? ?? const []),
    );
  }

  void _absorbPending(Map<String, dynamic> r, String runtimeId) {
    var changed = false;
    final open = r['open_requests'];
    if (open is List) {
      for (final o in open.whereType<Map>()) {
        if (o['method'] != 'approval') continue;
        final a = RemoteApproval.fromParams(Map<String, dynamic>.from(o['params'] as Map? ?? const {}), rid: '${o['id']}', sessionId: runtimeId);
        _approvals[a.key] = a;
        changed = true;
      }
    }
    final pa = r['pending_approval'];
    if (!changed && pa is Map && '${pa['request_id'] ?? ''}'.isNotEmpty) {
      final a = RemoteApproval.fromParams(Map<String, dynamic>.from(pa), sessionId: runtimeId);
      if (!_approvals.values.any((x) => x.requestId == a.requestId)) {
        _approvals[a.key] = a;
        changed = true;
      }
    }
    if (changed) _approvalsChanged.add(null);
  }

  Future<dynamic> submit(String runtimeId, String text, {List<String> attachments = const [], Map<String, dynamic> extra = const {}}) =>
      client.call('prompt.submit', {
        ..._p,
        'session_id': runtimeId,
        'text': text,
        'surface': 'mobile',
        if (attachments.isNotEmpty) 'attachments': attachments,
        // Composer picks (skills, reasoning_effort); only fields the PC's
        // catalog listed, so an older PC never sees them.
        ...extra,
      });

  /// Perusahaan: `company.<method>` on the PC core (org chart, tickets, approvals, costs).
  @override
  Future<dynamic> companyCall(String method, [Map<String, dynamic> params = const {}]) =>
      client.call('company.$method', {..._p, ...params}, const Duration(seconds: 30));

  Future<void> interrupt(String runtimeId) => client.call('session.interrupt', {..._p, 'session_id': runtimeId});

  /// Pending approvals of a live session via RPC (fallback / refresh).
  Future<List<RemoteApproval>> pendingApprovals(String runtimeId) async {
    final r = await client.call('approval.pending', {..._p, 'session_id': runtimeId});
    final list = (r is Map ? r['approvals'] : null) as List? ?? const [];
    final out = [for (final a in list.whereType<Map>()) RemoteApproval.fromParams(Map<String, dynamic>.from(a), sessionId: runtimeId)];
    for (final a in out) {
      if (!_approvals.values.any((x) => x.requestId == a.requestId && x.sessionId == runtimeId)) _approvals[a.key] = a;
    }
    _approvalsChanged.add(null);
    return out;
  }

  /// Answer an approval: the server request when we got one (exactly what the
  /// desktop does), else the `approval.respond` RPC.
  Future<void> respondApproval(RemoteApproval a, String choice) async {
    _approvals.remove(a.key);
    _approvalsChanged.add(null);
    if (a.rid != null && a.rid!.isNotEmpty) {
      client.respondServerRequest(a.rid, {'choice': choice});
      return;
    }
    await client.call('approval.respond', {
      ..._p,
      'session_id': a.sessionId,
      'choice': choice,
      if (a.requestId.isNotEmpty) 'request_id': a.requestId,
    }, const Duration(seconds: 300));
  }

  // ------------------------------------------------------------------- REST --
  Uri _rest(String path, [Map<String, String>? q]) {
    final b = Uri.parse(activeUrl);
    return b.replace(path: '${b.path.replaceAll(RegExp(r'/+$'), '')}$path', queryParameters: q == null || q.isEmpty ? null : q);
  }

  Future<dynamic> _json(String method, String path, {Map<String, dynamic>? body, Map<String, String>? query}) async {
    final req = http.Request(method, _rest(path, query))..headers.addAll(_restHeaders);
    if (body != null) {
      req.headers['Content-Type'] = 'application/json';
      req.body = jsonEncode(body);
    }
    final res = await _http.send(req).timeout(const Duration(seconds: 20));
    final text = await res.stream.bytesToString();
    if (res.statusCode == 404) throw const RemoteRestError(404, 'fitur ini belum ada di Neovarch PC — perbarui aplikasi PC');
    if (res.statusCode == 401 || res.statusCode == 403) throw RemoteRestError(res.statusCode, 'token ditolak oleh PC — pasangkan ulang');
    if (res.statusCode < 200 || res.statusCode >= 300) {
      String msg = 'HTTP ${res.statusCode}';
      try {
        final j = jsonDecode(text);
        if (j is Map && j['detail'] != null) msg = '${j['detail']}';
      } catch (_) {}
      throw RemoteRestError(res.statusCode, msg);
    }
    return text.isEmpty ? null : jsonDecode(text);
  }

  /// Public `/api/status` (version, components); never throws.
  Future<Map<String, dynamic>> serverStatus() async {
    try {
      final j = await _json('GET', '/api/status');
      return j is Map ? Map<String, dynamic>.from(j) : const {};
    } catch (_) {
      return const {};
    }
  }

  /// `GET /api/update?platform=android` — the PC core checks GitHub Releases
  /// (cached there) so the phone never calls GitHub itself. Never throws.
  Future<Map<String, dynamic>> updateInfo() async {
    try {
      final j = await _json('GET', '/api/update', query: const {'platform': 'android'});
      return j is Map ? Map<String, dynamic>.from(j) : const {};
    } catch (_) {
      return const {};
    }
  }

  // ------------------------------------------------------------ composer --
  /// `GET /api/composer/catalog`: the desktop composer's controls. Null on an
  /// older PC (404, `{available:false}`, or any error) — the phone then shows
  /// the plain composer. Never throws.
  Future<ComposerCatalog?> composerCatalog() async {
    try {
      return ComposerCatalog.tryParse(await _json('GET', '/api/composer/catalog'));
    } catch (_) {
      return null;
    }
  }

  /// `GET /api/composer/complete`: "@" file/folder refs (kind=path) relative
  /// to the session folder on the PC, or "/" items (kind=slash).
  Future<List<ComposerSuggestion>> composerComplete(String kind, String query, {String? sessionId}) async {
    final j = await _json('GET', '/api/composer/complete', query: {
      'kind': kind,
      'q': query,
      if (sessionId != null && sessionId.isNotEmpty) 'session_id': sessionId,
    });
    final items = j is Map ? (j['items'] as List? ?? const []) : const [];
    return [for (final i in items) if (i is Map) ComposerSuggestion.fromJson(Map<String, dynamic>.from(i))];
  }

  /// `POST /api/model/set` (the same call as the desktop model pill).
  Future<void> setModel({required String provider, required String model}) =>
      _json('POST', '/api/model/set', body: {'provider': provider, 'model': model, 'scope': 'main'});

  // -------------------------------------------------------------- models --
  // 9Router contract v1 (/api/models, /api/models/default, /api/agents/{id}/model).
  @override
  Future<ModelsSnapshot> listModels({bool refresh = false}) async =>
      ModelsSnapshot.fromJson(Map<String, dynamic>.from(await _json('GET', '/api/models', query: refresh ? {'refresh': '1'} : null) as Map));

  @override
  Future<ModelRef> setDefaultModel(String model, {String? provider}) async =>
      ModelRef.fromJson(await _json('PUT', '/api/models/default', body: {'model': model, 'provider': ?provider}));

  @override
  Future<AgentModel> setAgentModel(String agentId, String? model, {String? provider}) async => AgentModel.fromJson(Map<String, dynamic>.from(
      await _json('PUT', '/api/agents/${Uri.encodeComponent(agentId)}/model', body: {'model': model, 'provider': ?provider}) as Map));

  /// `GET /api/office`: the agents ("pegawai") and the activity feed.
  Future<OfficeSnapshot> office() async => OfficeSnapshot.fromJson(Map<String, dynamic>.from(await _json('GET', '/api/office') as Map));

  /// `GET /api/appearance`: `{accent, base, on_accent}`; null when the core
  /// has no appearance route (older PC).
  Future<Map<String, dynamic>?> appearance() async {
    try {
      final j = await _json('GET', '/api/appearance');
      return j is Map ? Map<String, dynamic>.from(j) : null;
    } catch (_) {
      return null;
    }
  }

  // Obsidian vault (read-only on the phone).
  @override
  Future<VaultTree> vaultTree() async => VaultTree.fromJson(Map<String, dynamic>.from(await _json('GET', '/api/obsidian/tree') as Map));

  @override
  Future<VaultNote> vaultNote(String path) async =>
      VaultNote.fromJson(Map<String, dynamic>.from(await _json('GET', '/api/obsidian/note', query: {'path': path}) as Map));

  @override
  Future<VaultGraph> vaultGraph() async => VaultGraph.fromJson(Map<String, dynamic>.from(await _json('GET', '/api/obsidian/graph') as Map));

  @override
  Future<List<VaultHit>> vaultSearch(String q) async {
    final j = await _json('GET', '/api/obsidian/search', query: {'q': q});
    return [for (final h in ((j is Map ? j['results'] : null) as List? ?? const []).whereType<Map>()) VaultHit.fromJson(Map<String, dynamic>.from(h))];
  }

  static const _kanban = '/api/plugins/kanban';

  Future<KanbanSnapshot> board() async => KanbanSnapshot.fromJson(Map<String, dynamic>.from(await _json('GET', '$_kanban/board') as Map));

  Future<void> moveTask(String id, String status) => _json('PATCH', '$_kanban/tasks/${Uri.encodeComponent(id)}', body: {'status': status});

  Future<void> commentTask(String id, String text) =>
      _json('POST', '$_kanban/tasks/${Uri.encodeComponent(id)}/comments', body: {'body': text});

  Future<void> createTask({required String title, String? body, String? assignee, int? priority}) => _json('POST', '$_kanban/tasks', body: {
        'title': title,
        if (body != null && body.isNotEmpty) 'body': body,
        if (assignee != null && assignee.isNotEmpty) 'assignee': assignee,
        'priority': ?priority,
      });
}

extension RemoteGatewayExtras on RemoteGateway {
  // ------------------------------------------------------------ attachments --
  /// Headers for authenticated image loads (`Image.network(headers: …)`).
  Map<String, String> get restHeaders => _restHeaders;

  /// Absolute URL of a core path such as `/api/uploads/<id>`.
  Uri restUri(String path, [Map<String, String>? query]) => _rest(path, query);

  /// A URL a browser / download manager can open on its own (`?token=`).
  Uri downloadUri(RemoteAttachment a) =>
      _rest(a.url ?? '/api/uploads/${a.id}', {'download': '1', if (token.isNotEmpty) 'token': token});

  /// Download URL for any file the PC agent wrote (a .pptx deck, a .docx
  /// report): `GET /api/fs/download?path=…&token=…`.
  Uri fsDownloadUri(String path) => _rest('/api/fs/download', {'path': path, if (token.isNotEmpty) 'token': token});

  /// `POST /api/uploads` (multipart). [onProgress] gets 0..1 as bytes go out.
  Future<RemoteAttachment> uploadAttachment({
    required String sessionId,
    required String name,
    required String mime,
    required Uint8List bytes,
    void Function(double progress)? onProgress,
  }) async {
    if (bytes.length > kMaxAttachmentBytes) throw const RemoteRestError(413, 'File terlalu besar (maks 25 MB).');
    final req = http.MultipartRequest('POST', _rest('/api/uploads'))
      ..headers.addAll(_restHeaders)
      ..fields['session_id'] = sessionId;
    const chunk = 64 * 1024;
    var sent = 0;
    Stream<List<int>> stream() async* {
      for (var i = 0; i < bytes.length; i += chunk) {
        final end = i + chunk < bytes.length ? i + chunk : bytes.length;
        yield bytes.sublist(i, end);
        sent = end;
        onProgress?.call(bytes.isEmpty ? 1 : sent / bytes.length);
      }
    }

    // The core sniffs images and maps the file name to a MIME type itself.
    req.files.add(http.MultipartFile('file', stream(), bytes.length, filename: name));
    final res = await _http.send(req).timeout(const Duration(minutes: 5));
    final text = await res.stream.bytesToString();
    if (res.statusCode == 404) throw const RemoteRestError(404, 'PC belum mendukung lampiran — perbarui Neovarch di PC');
    if (res.statusCode == 401 || res.statusCode == 403) throw RemoteRestError(res.statusCode, 'token ditolak oleh PC — pasangkan ulang');
    if (res.statusCode == 413) throw const RemoteRestError(413, 'File terlalu besar (maks 25 MB).');
    if (res.statusCode < 200 || res.statusCode >= 300) {
      String msg = 'Unggah gagal (HTTP ${res.statusCode})';
      try {
        final j = jsonDecode(text);
        if (j is Map && j['detail'] != null) msg = '${j['detail']}';
      } catch (_) {}
      throw RemoteRestError(res.statusCode, msg);
    }
    // A PC core without the upload route answers through its quiet
    // catch-all with a 200 `{available: false, name: "uploads"}` and no id
    // (1.4.5 bug: an "uploads · 0 B" card and the agent never got the
    // image). Only a stored upload (non-empty id) counts as success.
    Object? body;
    try {
      body = jsonDecode(text);
    } catch (_) {}
    final att = body is Map ? RemoteAttachment.fromJson(Map<String, dynamic>.from(body)) : null;
    if (att == null || att.id.isEmpty || (body as Map)['available'] == false) {
      throw const RemoteRestError(404, 'PC belum mendukung lampiran — perbarui Neovarch di PC');
    }
    onProgress?.call(1);
    return att;
  }

  Future<void> deleteAttachment(String id) => _json('DELETE', '/api/uploads/${Uri.encodeComponent(id)}');

  // ----------------------------------------------------------------- social --
  /// `GET /api/social/status`: `{signed_in, login, client_id_configured, …}`.
  Future<Map<String, dynamic>> socialStatus() async => Map<String, dynamic>.from(await _json('GET', '/api/social/status') as Map);

  Future<SocialProfile> socialProfile() async => SocialProfile.fromJson(Map<String, dynamic>.from(await _json('GET', '/api/social/profile') as Map));

  Future<FriendsSnapshot> socialFriends() async => FriendsSnapshot.fromJson(Map<String, dynamic>.from(await _json('GET', '/api/social/friends') as Map));

  Future<FriendDetail> socialFriend(String login) async =>
      FriendDetail.fromJson(Map<String, dynamic>.from(await _json('GET', '/api/social/friends/${Uri.encodeComponent(login)}') as Map));
}

class RemoteRestError implements Exception {
  final int status;
  final String message;
  const RemoteRestError(this.status, this.message);
  @override
  String toString() => message;
}
