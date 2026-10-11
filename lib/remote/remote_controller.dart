// Phone remote state: which desktop, the live gateway link, the open chat,
// approvals, the Office, the Kanban board and the desktop's status. One
// ChangeNotifier the remote screens watch. Everything after the first load is
// pushed by the PC over the WebSocket (no polling); a reconnect re-reads the
// snapshots and replays or resumes what was missed.
import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/legacy.dart';

import '../data/device_tools.dart';
import '../data/gateway_client.dart';
import '../models/models.dart';
import 'attachments.dart';
import 'company_models.dart';
import 'link/frame_link.dart';
import 'link/link_info.dart';
import 'models_api.dart';
import 'office_models.dart';
import 'pairing.dart';
import 'remote_errors.dart';
import 'remote_gateway.dart';
import 'update_check.dart';
import 'vault_models.dart';
import 'composer.dart';
import 'remote_transcript.dart';
import 'saved_desktops.dart';
import 'social_models.dart';

class RemoteController extends ChangeNotifier {
  RemoteController(this.desktops);
  final SavedDesktops desktops;

  RemoteGateway? gateway;
  SavedDesktop? desktop;
  RemoteStatus status = RemoteStatus.disconnected;
  String? error;
  StreamSubscription? _statusSub, _eventSub, _approvalSub, _routeSub;

  /// Opens a Bluetooth link to the PC (Android platform channel; null = no Bluetooth).
  Future<FrameLink> Function(BluetoothTarget target)? bluetoothConnector;

  /// The PC's appearance (`/api/appearance`, `appearance.changed`).
  void Function(Map<String, dynamic> appearance)? onAppearance;

  /// Checks GitHub Releases for a newer phone app (injectable for tests).
  UpdateChecker updateChecker = UpdateChecker();

  // office (pushed via `office.update`)
  OfficeSnapshot? office;
  String? officeError;
  DateTime? officeAt;

  /// Bumped on `vault.changed` so an open vault screen re-reads its note.
  int vaultRevision = 0;

  /// Bumped on `company.changed` so the Perusahaan screen re-reads.
  int companyRevision = 0;

  /// Widget-test harness only: Perusahaan data without a gateway.
  CompanyApi? debugCompanyApi;
  CompanyApi? get companyApi => debugCompanyApi ?? gateway;

  /// Whether the paired core answers `company.*`: null until checked (or
  /// unknown after a network error), false on an older core (-32601), where
  /// the Kantor tab hides its Perusahaan segment.
  bool? companySupported;

  /// Asks the PC once per connection whether it has the Perusahaan RPCs.
  Future<void> probeCompany() async {
    final api = companyApi;
    if (api == null || (debugCompanyApi == null && !connected)) return;
    try {
      await api.companyCall('snapshot');
      if (companyApi != api) return;
      companySupported = true;
    } catch (e) {
      if (companyApi != api) return;
      if (isCompanyUnsupported(e)) companySupported = false;
    }
    notifyListeners();
  }

  // social: GitHub friends & profile, read through the PC (no phone login)
  SocialProfile? socialProfile;
  FriendsSnapshot? socialFriends;
  bool socialSignedIn = false;
  bool socialLoading = false;
  String? socialError;

  // composer attachments (uploaded to the PC as soon as they are picked)
  final List<PendingAttachment> pendingAttachments = [];

  /// Last notice about attachments (e.g. the model cannot see images).
  String? attachNotice;
  int _attachSeq = 0;

  // composer controls mirrored from the desktop (skills, model, reasoning,
  // "/" and "@"); null = the PC has no catalog (older version) → plain composer
  ComposerCatalog? composer;
  /// Skills picked for the next prompt (cleared after sending, like the
  /// desktop's `/skill` references that live in the message text).
  final List<String> selectedSkills = [];
  /// Reasoning effort for the following prompts; null = the PC's default.
  String? reasoningEffort;
  bool modelSwitching = false;

  /// Widget-test harness only: vault data without a gateway.
  @visibleForTesting
  VaultApi? debugVault;
  VaultApi? get vault => debugVault ?? gateway;

  // chat
  List<ChatSessionInfo> sessions = [];
  bool sessionsLoading = false;
  String? storedId;
  String? runtimeId;
  String title = '';
  RemoteTranscript transcript = RemoteTranscript();
  bool opening = false;
  bool notifyApprovals = true;
  void setNotifyApprovals(bool v) {
    notifyApprovals = v;
    notifyListeners();
  }

  // models (9Router contract v1; null on cores without /api/models)
  ModelsSnapshot? models;
  String? modelsError;
  bool modelsUnsupported = false;
  @visibleForTesting
  ModelsApi? debugModelsApi;
  ModelsApi? get _modelsApi => debugModelsApi ?? gateway;

  // board / status
  KanbanSnapshot? board;
  String? boardError;
  bool boardLoading = false;
  List<ActiveSession> active = [];
  Map<String, dynamic> serverInfo = const {};

  /// Newest release for this phone app: GitHub Releases API directly, the
  /// PC core's `/api/update` (cached GitHub check) as the fallback.
  Map<String, dynamic> update = const {};
  String? dismissedUpdate;
  bool get updateAvailable =>
      update['available'] == true && update['latest'] != null && update['latest'] != dismissedUpdate;

  /// Called once per newly released version (system notification on
  /// Android; set by `runRemoteApp`).
  void Function(Map<String, dynamic> update)? onNewUpdate;

  /// Throttled by [UpdateChecker.minInterval] (persisted when the checker has
  /// prefs), so calling it on every start / status refresh is cheap.
  Future<void> checkUpdate({bool force = false}) async {
    Map<String, dynamic>? u;
    try {
      u = await updateChecker.check(fallback: gateway?.updateInfo, force: force);
    } catch (_) {}
    if (u != null) {
      update = u;
      notifyListeners();
      final latest = '${u['latest'] ?? ''}';
      if (u['available'] == true && latest.isNotEmpty && latest != dismissedUpdate && updateChecker.shouldNotify(latest)) {
        onNewUpdate?.call(u);
      }
    }
  }
  void dismissUpdate() {
    dismissedUpdate = update['latest'] as String?;
    notifyListeners();
  }

  bool get connected => status == RemoteStatus.connected;
  List<RemoteApproval> get approvals => debugApprovals ?? gateway?.approvals ?? const [];

  /// Screenshot / widget-test harness only: approvals to show without a gateway.
  @visibleForTesting
  List<RemoteApproval>? debugApprovals;
  bool get running => transcript.running;

  String get statusLabel => switch (status) {
        RemoteStatus.connected => 'terhubung',
        RemoteStatus.connecting => 'menghubungkan…',
        RemoteStatus.reconnecting => 'menyambung ulang…',
        RemoteStatus.failed => 'gagal terhubung',
        RemoteStatus.disconnected => 'terputus',
      };

  /// Called once at start: reconnect to the last desktop.
  Future<void> start() async {
    // Update notice without opening About or pairing first (throttled).
    unawaited(checkUpdate());
    final d = desktops.active;
    if (d != null) await connectTo(d);
  }

  /// Validate a scanned/typed pairing against the gateway, then save it.
  /// Returns an error message, or null on success.
  Future<String?> pair(GatewayPairing p) async {
    // A new QR also carries the relay identity: pairing then works from
    // anywhere (LAN first, else Bluetooth/relay with the QR's pairing code).
    final id = desktops.idFor(p);
    LinkInfo? link = p.link;
    final g = RemoteGateway(
        baseUrl: p.url,
        alternates: p.alternates,
        token: p.token,
        headers: p.headers,
        profile: p.profile,
        autoReconnect: false,
        link: link,
        deviceKey: () => desktops.linkKey(id),
        deviceName: deviceName,
        onLinkChanged: (l) => link = l);
    try {
      await g.connect();
      await g.listSessions(limit: 1);
    } catch (e) {
      await g.close();
      return _friendly('$e', relay: p.link?.canRelay == true);
    }
    await g.close();
    final d = await desktops.upsert(p, id: id);
    if (link != null) desktops.updateLink(d, link: link);
    await connectTo(d);
    return null;
  }

  /// Name this phone shows in PC Settings → Remote (paired devices).
  String deviceName = 'HP Neovarch';

  /// Never the raw exception text: network failures become one Indonesian
  /// sentence ("PC tidak terjangkau…"), see remote_errors.dart.
  String _friendly(String e, {bool? relay}) {
    final s = e.replaceFirst('Exception: ', '');
    final viaRelay = relay ?? (gateway?.relayAvailable ?? false);
    if (s.contains('401') || s.contains('403') || s.contains('not upgraded')) {
      return 'PC menolak token. Buat ulang QR pemasangan di PC lalu pindai lagi.';
    }
    if (s.startsWith('PC tidak terjangkau') || s.startsWith('HP ini sudah dicabut') || s.startsWith('PC belum mengenal') || s.startsWith('Kode pemasangan')) {
      return s;
    }
    if (isNetworkError(s) || s.contains('timed out') || s.contains('waktu habis') || s.contains('tidak ada alamat PC')) {
      return RemoteUnreachable(relayAvailable: viaRelay).toString();
    }
    return s;
  }

  /// Phone setting: also try Bluetooth for the active PC (off by default).
  Future<void> setBluetooth(bool on) async {
    final d = desktop;
    if (d == null) return;
    desktops.updateLink(d, bluetooth: on);
    gateway?.bluetoothEnabled = on;
    notifyListeners();
  }

  /// How the live connection runs: 'lan' (direct, incl. other direct
  /// addresses), 'relay' or 'bluetooth'.
  String get transport => gateway?.transport ?? 'lan';

  Future<void> connectTo(SavedDesktop d) async {
    await _teardown();
    desktop = d;
    desktops.touch(d);
    final token = await desktops.token(d.id);
    final g = gateway = RemoteGateway(
        baseUrl: d.url,
        alternates: d.alternates,
        token: token,
        headers: d.headers,
        profile: d.profile,
        link: d.link,
        deviceKey: () => desktops.linkKey(d.id),
        deviceName: deviceName,
        bluetoothEnabled: d.bluetooth,
        bluetoothConnector: bluetoothConnector,
        onLinkChanged: (l) => desktops.updateLink(d, link: l));
    _statusSub = g.statusStream.listen(_onStatus);
    _eventSub = g.events.listen(_onEvent);
    _approvalSub = g.approvalsChanged.listen(_onApproval);
    _routeSub = g.routesChanged.listen((urls) => desktops.updateRoutes(d, alternates: urls));
    error = null;
    notifyListeners();
    try {
      await g.connect();
      if (status != g.status) _onStatus(g.status); // the stream event lands a tick later
    } catch (e) {
      error = _friendly('$e');
      // keep retrying in the background
      unawaited(Future<void>.delayed(const Duration(seconds: 2), () {
        if (gateway == g && !connected) unawaited(g.reconnect().catchError((_) {}));
      }));
      notifyListeners();
    }
  }

  Future<void> _teardown() async {
    await _statusSub?.cancel();
    await _eventSub?.cancel();
    await _approvalSub?.cancel();
    await _routeSub?.cancel();
    final g = gateway;
    gateway = null;
    await g?.close();
    sessions = [];
    storedId = runtimeId = null;
    title = '';
    transcript = RemoteTranscript();
    board = null;
    boardError = null;
    active = [];
    serverInfo = const {};
    office = null;
    officeError = null;
    models = null;
    modelsError = null;
    modelsUnsupported = false;
    companySupported = null;
    composer = null;
    selectedSkills.clear();
    reasoningEffort = null;
    status = RemoteStatus.disconnected;
  }

  Future<void> disconnect() async {
    await _teardown();
    desktop = null;
    notifyListeners();
  }

  Future<void> forget(SavedDesktop d) async {
    if (desktop?.id == d.id) await disconnect();
    await desktops.remove(d.id);
    notifyListeners();
  }

  Future<void> reconnect() async {
    final g = gateway;
    if (g == null) {
      final d = desktop ?? desktops.active;
      if (d != null) await connectTo(d);
      return;
    }
    try {
      await g.reconnect();
    } catch (e) {
      error = _friendly('$e');
      notifyListeners();
    }
  }

  void _onStatus(RemoteStatus s) {
    if (s == status) return;
    final was = status;
    status = s;
    if (s == RemoteStatus.connected) {
      error = null;
      final d = desktop, g = gateway;
      if (d != null && g != null) desktops.updateRoutes(d, lastUrl: g.activeUrl);
      unawaited(refreshAll());
      // Re-attach to the open chat when the missed events could not be
      // replayed (older core, PC restarted, gap too old).
      if (was != RemoteStatus.connected && storedId != null && (g == null || g.resyncNeeded || runtimeId == null)) {
        unawaited(openSession(storedId!, quiet: true));
      }
    } else if (s == RemoteStatus.reconnecting || s == RemoteStatus.failed) {
      transcript.interrupted();
      if (s == RemoteStatus.failed) error ??= _friendly(gateway?.lastError ?? 'gagal terhubung');
    }
    notifyListeners();
  }

  /// Tests: feed a gateway event exactly as the WebSocket subscription does.
  @visibleForTesting
  void debugEvent(GatewayEventFrame f) => _onEvent(f);

  /// Back in the foreground: phones may have slept through pushes, so take
  /// fresh snapshots (office, board, live sessions) once; from there the PC
  /// pushes again. A dropped socket reconnects (and resyncs on connect).
  Future<void> resyncOnResume() async {
    if (!connected) return reconnect();
    await Future.wait([refreshOffice(), refreshBoard(), refreshStatus()]);
  }

  void _onEvent(GatewayEventFrame f) {
    switch (f.type) {
      case 'office.update':
        _applyOffice(f.payload);
      case 'appearance.changed':
        onAppearance?.call(f.payload);
      case 'kanban.changed':
        unawaited(refreshBoard());
      case 'vault.changed':
        vaultRevision++;
        notifyListeners();
      case 'company.changed':
        companyRevision++;
        companySupported = true;
        notifyListeners();
      case 'social.changed':
        if (socialProfile != null || socialFriends != null || socialError != null) unawaited(refreshSocial());
      case 'attachment.notice':
        if (f.sessionId == null || f.sessionId == runtimeId) {
          attachNotice = '${f.payload['message'] ?? ''}';
          notifyListeners();
        }
      case 'models.changed':
        unawaited(refreshModels());
      case 'model.default.changed':
        final m = models;
        if (m != null) {
          models = m.withDefault(ModelRef.fromJson(f.payload));
          notifyListeners();
        } else {
          unawaited(refreshModels());
        }
      case 'agent.model.changed':
        notifyListeners(); // office.update follows with the new effective model
      case 'resync.required':
        unawaited(refreshAll());
        if (storedId != null) unawaited(openSession(storedId!, quiet: true));
    }
    if (f.type == 'sessions.changed' || f.type == 'session.title') unawaited(loadSessions());
    if (f.sessionId != null && f.sessionId == runtimeId) {
      if (transcript.apply(f)) {
        if (f.type == 'session.title') title = transcript.title ?? title;
        notifyListeners();
      }
    }
  }

  void _onApproval(RemoteApproval? a) {
    notifyListeners();
    if (a != null && notifyApprovals) unawaited(_notify(a));
  }

  Future<void> _notify(RemoteApproval a) async {
    if (kIsWeb || defaultTargetPlatform != TargetPlatform.android) return;
    try {
      await ensurePermissions(['android.permission.POST_NOTIFICATIONS']);
      await deviceCall<String>('notify', {
        'title': 'Neovarch · perlu persetujuan',
        'body': '${a.toolName ?? 'Agen'} di ${desktop?.name ?? 'PC'}: ${a.description.isNotEmpty ? a.description : a.command}',
        'route': 'approvals', // tap → Chat + approvals sheet
      });
    } catch (_) {
      // No notification bridge: the in-app badge still shows it.
    }
  }

  /// Snapshots after (re)connecting; from here on the PC pushes changes.
  Future<void> refreshAll() async {
    await Future.wait([loadSessions(), refreshStatus(), refreshBoard(), refreshOffice(), _loadAppearance(), refreshComposer(), refreshModels(), probeCompany()]);
  }

  // ------------------------------------------------------------- composer --
  Future<void> refreshComposer() async {
    final g = gateway;
    if (g == null) return;
    final c = await g.composerCatalog();
    if (gateway != g) return;
    composer = c;
    if (c != null) {
      selectedSkills.removeWhere((s) => !c.skills.any((k) => k.name == s));
      if (reasoningEffort != null && !c.reasoningLevels.contains(reasoningEffort)) reasoningEffort = null;
    } else {
      selectedSkills.clear();
      reasoningEffort = null;
    }
    notifyListeners();
  }

  void toggleSkill(String name) {
    if (!selectedSkills.remove(name)) selectedSkills.add(name);
    notifyListeners();
  }

  void setSkills(Iterable<String> names) {
    selectedSkills
      ..clear()
      ..addAll(names);
    notifyListeners();
  }

  void setReasoningEffort(String? level) {
    reasoningEffort = (level == null || level == 'default') ? null : level;
    notifyListeners();
  }

  /// Switch the PC's model (global, like the desktop model pill). Returns an
  /// error to show, or null.
  Future<String?> selectModel(String provider, String model) async {
    final g = gateway, c = composer;
    if (g == null || c == null) return 'Belum terhubung ke PC.';
    modelSwitching = true;
    notifyListeners();
    try {
      await g.setModel(provider: provider, model: model);
      composer = c.withModel(provider, model);
      return null;
    } catch (e) {
      return _friendly('$e');
    } finally {
      modelSwitching = false;
      notifyListeners();
    }
  }

  /// "@" / "/" suggestions from the PC (empty when it has no catalog).
  Future<List<ComposerSuggestion>> completeMentions(String query) async {
    final g = gateway, c = composer;
    if (g == null || c == null) return const [];
    final q = query.toLowerCase();
    final starters = [for (final m in c.mentions) if (q.isEmpty || m.text.toLowerCase().contains(q)) m];
    // `@url:` / `@git:` values are typed, not looked up.
    if (q.startsWith('url:') || q.startsWith('git:')) return starters;
    try {
      final files = await g.composerComplete('path', query, sessionId: runtimeId);
      return [...files, ...starters];
    } catch (_) {
      return starters;
    }
  }

  Future<void> _loadAppearance() async {
    final a = await gateway?.appearance();
    if (a != null) onAppearance?.call(a);
  }

  // --------------------------------------------------------------- office --
  Future<void> refreshOffice() async {
    final g = gateway;
    if (g == null || !connected) return;
    try {
      office = await g.office();
      officeAt = DateTime.now();
      officeError = null;
    } catch (e) {
      officeError = _friendly('$e');
    }
    notifyListeners();
  }

  void _applyOffice(Map<String, dynamic> payload) {
    final before = office;
    office = OfficeSnapshot.fromJson(payload);
    officeAt = DateTime.now();
    officeError = null;
    // The Kanban counts changed or a task moved: re-read the board (event
    // driven; cores without `kanban.changed`).
    final k = office!.kanban, kb = before?.kanban ?? const {};
    final moved = office!.feed.isNotEmpty && office!.feed.first.kind == 'task' && office!.feed.first.id != (before?.feed.firstOrNull?.id);
    if (before != null && (moved || k.entries.any((e) => kb[e.key] != e.value))) unawaited(refreshBoard());
    notifyListeners();
  }

  // --------------------------------------------------------------- models --
  Future<void> refreshModels({bool refresh = false}) async {
    final api = _modelsApi;
    if (api == null || (debugModelsApi == null && !connected)) return;
    try {
      models = await api.listModels(refresh: refresh);
      modelsError = null;
      modelsUnsupported = false;
    } on RemoteRestError catch (e) {
      if (e.status == 404) {
        modelsUnsupported = true; // older core: the composer "+" menu still has model.options
      } else {
        modelsError = e.message;
      }
    } catch (e) {
      modelsError = _friendly('$e');
    }
    notifyListeners();
  }

  /// The PC's default model (every agent without its own model).
  Future<String?> setDefaultModel(ModelEntry m) async {
    final api = _modelsApi;
    if (api == null) return 'Belum terhubung ke PC.';
    try {
      final d = await api.setDefaultModel(m.id, provider: m.provider);
      models = models?.withDefault(d.model.isEmpty ? ModelRef(m.id, m.provider) : d);
      notifyListeners();
      return null;
    } catch (e) {
      return _friendly('$e');
    }
  }

  /// One agent's own model; [m] null = follow the PC default again.
  Future<String?> setAgentModel(String agentId, ModelEntry? m) async {
    final api = _modelsApi;
    if (api == null) return 'Belum terhubung ke PC.';
    try {
      await api.setAgentModel(agentId, m?.id, provider: m?.provider);
      return null;
    } catch (e) {
      return _friendly('$e');
    }
  }

  // ----------------------------------------------------------------- chat --
  Future<void> loadSessions() async {
    final g = gateway;
    if (g == null || !connected) return;
    sessionsLoading = true;
    notifyListeners();
    try {
      sessions = await g.listSessions();
    } catch (_) {}
    sessionsLoading = false;
    notifyListeners();
  }

  Future<void> openSession(String stored, {bool quiet = false}) async {
    final g = gateway;
    if (g == null) return;
    if (!quiet) {
      opening = true;
      storedId = stored;
      transcript = RemoteTranscript();
      notifyListeners();
    }
    try {
      final s = await g.resume(stored);
      storedId = s.storedId;
      runtimeId = s.runtimeId;
      title = s.title.isNotEmpty ? s.title : (sessions.where((x) => x.id == stored).firstOrNull?.title ?? '');
      transcript = RemoteTranscript(history: s.messages)..running = s.running;
    } catch (e) {
      error = _friendly('$e');
    }
    opening = false;
    notifyListeners();
  }

  /// Open a live session from `session.active_list`: resume accepts a stored
  /// id or an exact title.
  Future<void> openActive(ActiveSession a) async {
    final stored = sessions.where((s) => s.title == a.title).firstOrNull?.id ?? (a.title.isNotEmpty ? a.title : a.id);
    await openSession(stored);
  }

  /// Start a new chat (a new gateway session).
  Future<void> newChat() async {
    final g = gateway;
    if (g == null) return;
    opening = true;
    notifyListeners();
    try {
      final s = await g.create();
      storedId = s.storedId;
      runtimeId = s.runtimeId;
      title = '';
      transcript = RemoteTranscript(history: s.messages);
    } catch (e) {
      error = _friendly('$e');
    }
    opening = false;
    notifyListeners();
  }

  Future<String?> send(String text) async {
    final t = text.trim();
    final g = gateway;
    final ready = pendingAttachments.where((a) => a.state == AttachState.done && (a.remote?.id ?? '').isNotEmpty).toList();
    if ((t.isEmpty && ready.isEmpty) || g == null) return null;
    if (!connected) return 'Belum terhubung ke PC.';
    if (pendingAttachments.any((a) => a.state == AttachState.uploading)) return 'Tunggu lampiran selesai diunggah.';
    if (runtimeId == null) await newChat();
    final rid = runtimeId;
    if (rid == null) return error ?? 'Gagal membuat sesi di PC.';
    final extra = composerSubmitFields(composer, skills: List.of(selectedSkills), reasoningEffort: reasoningEffort);
    selectedSkills.clear();
    // The PC prefixes picked skills as `/name` (the desktop's text form); show
    // the turn the same way right away.
    final skills = [for (final s in (extra['skills'] as List? ?? const [])) '/$s'].where((s) => !t.split(RegExp(r'\s+')).contains(s));
    transcript.addUser(skills.isEmpty ? t : '${skills.join(' ')} $t', attachments: [for (final a in ready) a.remote!.toJson()]);
    pendingAttachments.clear();
    attachNotice = null;
    notifyListeners();
    try {
      final res = await g.submit(rid, t, attachments: [for (final a in ready) a.remote!.id], extra: extra);
      if (res is Map && res['notice'] != null) {
        attachNotice = '${res['notice']}';
        notifyListeners();
      }
      return null;
    } catch (e) {
      transcript.interrupted();
      transcript.error = _friendly('$e');
      notifyListeners();
      return transcript.error;
    }
  }

  // ------------------------------------------------------------ attachments --
  /// Add a picked / pasted / shot file to the composer and upload it to the PC
  /// right away (progress on the chip). Returns an error to show, or null.
  Future<String?> addAttachment(String name, Uint8List bytes, {String? mime}) async {
    final g = gateway;
    if (g == null || !connected) return 'Belum terhubung ke PC.';
    if (bytes.isEmpty) return 'File kosong.';
    if (bytes.length > kMaxAttachmentBytes) return '$name terlalu besar (maks 25 MB).';
    if (runtimeId == null) await newChat();
    final rid = runtimeId;
    if (rid == null) return error ?? 'Gagal membuat sesi di PC.';
    final type = sniffImageMime(bytes) ?? mime ?? mimeForName(name);
    final p = PendingAttachment(localId: 'att${_attachSeq++}', name: name, mime: type, bytes: bytes);
    pendingAttachments.add(p);
    notifyListeners();
    var lastTick = 0.0;
    try {
      p.remote = await g.uploadAttachment(
        sessionId: rid,
        name: name,
        mime: type,
        bytes: bytes,
        onProgress: (v) {
          p.progress = v;
          if (v - lastTick >= 0.05 || v >= 1) {
            lastTick = v;
            notifyListeners();
          }
        },
      );
      p.state = AttachState.done;
      p.progress = 1;
      notifyListeners();
      return null;
    } catch (e) {
      p.state = AttachState.failed;
      p.error = _friendly('$e');
      notifyListeners();
      return p.error;
    }
  }

  void removeAttachment(String localId) {
    final p = pendingAttachments.where((a) => a.localId == localId).firstOrNull;
    if (p == null) return;
    pendingAttachments.remove(p);
    final id = p.remote?.id;
    if (id != null) unawaited(gateway?.deleteAttachment(id).catchError((_) {}));
    notifyListeners();
  }

  // ----------------------------------------------------------------- social --
  /// Profile + friends from the PC (`/api/social/*`); the PC signs in to GitHub.
  Future<void> refreshSocial() async {
    final g = gateway;
    if (g == null || !connected) return;
    socialLoading = true;
    notifyListeners();
    try {
      final st = await g.socialStatus();
      socialSignedIn = st['signed_in'] == true;
      if (socialSignedIn) {
        final res = await Future.wait([g.socialProfile(), g.socialFriends()]);
        socialProfile = res[0] as SocialProfile;
        socialFriends = res[1] as FriendsSnapshot;
      } else {
        socialProfile = null;
        socialFriends = const FriendsSnapshot();
      }
      socialError = null;
    } catch (e) {
      socialError = _friendly('$e');
    }
    socialLoading = false;
    notifyListeners();
  }

  Future<FriendDetail> friendDetail(String login) async {
    final g = gateway;
    if (g == null) throw StateError('Belum terhubung ke PC.');
    return g.socialFriend(login);
  }

  Future<void> stop() async {
    final rid = runtimeId;
    if (rid == null) return;
    try {
      await gateway?.interrupt(rid);
    } catch (_) {}
  }

  Future<String?> respond(RemoteApproval a, String choice) async {
    try {
      await gateway?.respondApproval(a, choice);
      notifyListeners();
      return null;
    } catch (e) {
      return _friendly('$e');
    }
  }

  String sessionTitle(String runtimeOrStored) {
    final s = sessions.where((x) => x.id == runtimeOrStored).firstOrNull;
    if (s != null) return s.title;
    final a = active.where((x) => x.id == runtimeOrStored).firstOrNull;
    if (a != null && a.title.isNotEmpty) return a.title;
    if (runtimeOrStored == runtimeId && title.isNotEmpty) return title;
    return 'sesi ${runtimeOrStored.length > 8 ? runtimeOrStored.substring(0, 8) : runtimeOrStored}';
  }

  // ---------------------------------------------------------------- board --
  Future<void> refreshBoard() async {
    final g = gateway;
    if (g == null || !connected) return;
    boardLoading = true;
    notifyListeners();
    try {
      board = await g.board();
      boardError = null;
    } catch (e) {
      boardError = _friendly('$e');
    }
    boardLoading = false;
    notifyListeners();
  }

  Future<String?> moveTask(String id, String status) => _boardAction(() => gateway!.moveTask(id, status));
  Future<String?> commentTask(String id, String text) => _boardAction(() => gateway!.commentTask(id, text));
  Future<String?> createTask({required String title, String? body, String? assignee}) =>
      _boardAction(() => gateway!.createTask(title: title, body: body, assignee: assignee));

  Future<String?> _boardAction(Future<void> Function() f) async {
    if (gateway == null || !connected) return 'Belum terhubung ke PC.';
    try {
      await f();
      unawaited(refreshBoard());
      return null;
    } catch (e) {
      return _friendly('$e');
    }
  }

  // --------------------------------------------------------------- status --
  Future<void> refreshStatus() async {
    final g = gateway;
    if (g == null || !connected) return;
    try {
      active = await g.activeSessions();
      // Approvals of sessions this phone has not opened (desktop chats,
      // background work): ask each live session.
      for (final a in active) {
        try {
          await g.pendingApprovals(a.id);
        } catch (_) {}
      }
    } catch (_) {}
    serverInfo = await g.serverStatus();
    notifyListeners();
    unawaited(checkUpdate());
  }

  @override
  void dispose() {
    unawaited(_teardown());
    super.dispose();
  }
}

final remoteProvider = ChangeNotifierProvider<RemoteController>((ref) => throw UnimplementedError());
