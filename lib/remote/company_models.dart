// Perusahaan (company) on the PC, controlled from the phone: org chart, tickets,
// approvals and costs over the core's `company.*` JSON-RPC methods (the same
// ones the desktop Kantor uses). The PC pushes `company.changed`; the phone
// re-reads. See docs/company-flow-design.md in the core branch.

import '../data/gateway_client.dart' show RpcError, jsonRpcMethodNotFound;

/// What the company screens need from the PC. [RemoteGateway] implements it;
/// widget tests pass a fake through `RemoteController.debugCompanyApi`.
abstract class CompanyApi {
  /// Calls `company.<method>` with [params]; throws on an RPC error.
  Future<dynamic> companyCall(String method, [Map<String, dynamic> params = const {}]);
}

/// True when [e] says the paired core has no `company.*` RPCs at all (an
/// older Neovarch on the PC): JSON-RPC -32601 / "not implemented".
bool isCompanyUnsupported(Object e) {
  if (e is RpcError && e.code == jsonRpcMethodNotFound) return true;
  final s = '$e';
  return s.contains('-32601') || s.contains('not implemented');
}

/// Indonesian text for an error from a `company.*` call.
String companyErrorText(Object e) {
  if (isCompanyUnsupported(e)) return 'Core di PC belum punya fitur Perusahaan. Perbarui Neovarch di PC.';
  final s = '$e';
  if (s.contains('metode tidak dikenal')) return 'Fitur ini belum ada di core PC. Perbarui Neovarch di PC.';
  if (s.contains('TimeoutException') || s.contains('timed out')) return 'PC tidak menjawab. Cek koneksi lalu coba lagi.';
  if (s.contains('SocketException') || s.contains('not connected') || s.contains('closed')) return 'Koneksi ke PC terputus.';
  return s.replaceFirst(RegExp(r'^(Exception|RpcError|GatewayError|StateError)[^:]*:\s*'), '');
}

int _i(Object? v) => v is int ? v : (v is num ? v.toInt() : int.tryParse('${v ?? ''}') ?? 0);
int? _iq(Object? v) => v == null ? null : _i(v);
double _d(Object? v) => v is num ? v.toDouble() : double.tryParse('${v ?? ''}') ?? 0;
String _s(Object? v) => v == null ? '' : '$v';
Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : const {};
List<Map<String, dynamic>> _l(Object? v) => v is List ? [for (final e in v) if (e is Map) Map<String, dynamic>.from(e)] : const [];

const ticketStatusLabel = {
  'backlog': 'Backlog',
  'todo': 'Akan dikerjakan',
  'in_progress': 'Dikerjakan',
  'review': 'Ditinjau',
  'blocked': 'Terhambat',
  'done': 'Selesai',
  'cancelled': 'Dibatalkan',
};

/// Board order on the phone (cancelled tickets are not listed).
const ticketStatusOrder = ['in_progress', 'review', 'blocked', 'todo', 'backlog', 'done'];

/// Mirrors core/neovarch/company.py TRANSITIONS; the core re-checks every move.
const ticketTransitions = {
  'backlog': ['todo', 'cancelled'],
  'todo': ['in_progress', 'blocked', 'backlog', 'cancelled'],
  'in_progress': ['review', 'blocked', 'done', 'todo', 'cancelled'],
  'review': ['in_progress', 'done', 'cancelled'],
  'blocked': ['todo', 'in_progress', 'cancelled'],
  'done': ['todo'],
  'cancelled': ['todo'],
};

const agentStatusLabel = {
  'idle': 'siaga',
  'running': 'bekerja',
  'paused': 'dijeda',
  'error': 'galat',
  'pending_approval': 'menunggu persetujuan',
  'terminated': 'diberhentikan',
};

class BudgetState {
  const BudgetState({this.cents = 0, this.tokens = 0, this.pct, this.level = 'ok'});
  final double cents;
  final int tokens;
  final double? pct;
  final String level;
  factory BudgetState.fromJson(Map<String, dynamic> j) =>
      BudgetState(cents: _d(j['cents']), tokens: _i(j['tokens']), pct: j['pct'] == null ? null : _d(j['pct']), level: _s(j['level']).isEmpty ? 'ok' : _s(j['level']));
}

class CompanyAgent {
  const CompanyAgent({
    required this.id,
    required this.name,
    this.title = '',
    this.status = 'idle',
    this.reportsTo,
    this.pauseReason,
    this.ticketKey,
    this.ticketTitle,
    this.ticketStatus,
    this.budget = const BudgetState(),
    this.sessionId,
    this.role = 'pegawai',
    this.jobDescription = '',
    this.model = '',
    this.budgetMonthlyCents = 0,
    this.budgetMonthlyTokens = 0,
  });
  final int id;
  final String name;
  final String title;
  final String role;
  final String jobDescription;
  final String model;
  /// Monthly limits on the PC (0 = no limit).
  final int budgetMonthlyCents;
  final int budgetMonthlyTokens;
  final String status;
  final int? reportsTo;
  final String? pauseReason;
  final String? ticketKey;
  final String? ticketTitle;
  final String? ticketStatus;
  final BudgetState budget;
  final String? sessionId;

  factory CompanyAgent.fromJson(Map<String, dynamic> j) {
    final cur = _m(j['current_ticket']);
    return CompanyAgent(
      id: _i(j['id']),
      name: _s(j['name']),
      title: _s(j['title']).isNotEmpty ? _s(j['title']) : _s(j['role']),
      status: _s(j['status']).isEmpty ? 'idle' : _s(j['status']),
      reportsTo: _iq(j['reports_to']),
      pauseReason: j['pause_reason'] == null ? null : _s(j['pause_reason']),
      ticketKey: cur.isEmpty ? null : _s(cur['key']),
      ticketTitle: cur.isEmpty ? null : _s(cur['title']),
      ticketStatus: cur.isEmpty ? null : _s(cur['status']),
      budget: BudgetState.fromJson(_m(j['budget'])),
      sessionId: j['session_id'] == null ? null : _s(j['session_id']),
      role: _s(j['role']).isEmpty ? 'pegawai' : _s(j['role']),
      jobDescription: _s(j['job_description']),
      model: _s(j['model']),
      budgetMonthlyCents: _i(j['budget_monthly_cents']),
      budgetMonthlyTokens: _i(j['budget_monthly_tokens']),
    );
  }

  String get statusLabel => agentStatusLabel[status] ?? status;
  bool get paused => status == 'paused' || status == 'error';
}

class CompanySnapshot {
  const CompanySnapshot({
    required this.exists,
    this.name = '',
    this.mission = '',
    this.autorun = false,
    this.pendingApprovals = 0,
    this.agents = const [],
    this.ticketCounts = const {},
    this.budget = const BudgetState(),
    this.active = const {},
    this.goals = const [],
    this.projects = const [],
    this.routines = const [],
    this.requireHireApproval = false,
    this.budgetMonthlyCents = 0,
    this.budgetMonthlyTokens = 0,
  });
  final bool exists;
  final List<CompanyGoal> goals;
  final List<CompanyProject> projects;
  final List<CompanyRoutine> routines;
  final bool requireHireApproval;
  final int budgetMonthlyCents;
  final int budgetMonthlyTokens;
  final String name;
  final String mission;
  final bool autorun;
  final int pendingApprovals;
  final List<CompanyAgent> agents;
  final Map<String, int> ticketCounts;
  final BudgetState budget;
  final Set<int> active;

  factory CompanySnapshot.fromJson(Map<String, dynamic> j) {
    if (j['exists'] != true) return const CompanySnapshot(exists: false);
    final c = _m(j['company']);
    return CompanySnapshot(
      exists: true,
      name: _s(c['name']),
      mission: _s(c['mission']),
      autorun: c['autorun'] == true,
      pendingApprovals: _i(j['pending_approvals']),
      agents: [for (final a in _l(j['agents'])) CompanyAgent.fromJson(a)],
      ticketCounts: {for (final e in _m(j['ticket_counts']).entries) e.key: _i(e.value)},
      budget: BudgetState.fromJson(_m(j['budget'])),
      active: {for (final a in (j['active_agents'] is List ? j['active_agents'] as List : const [])) _i(a)},
      goals: [for (final g in _l(j['goals'])) CompanyGoal.fromJson(g)],
      projects: [for (final p in _l(j['projects'])) CompanyProject.fromJson(p)],
      routines: [for (final r in _l(j['routines'])) CompanyRoutine.fromJson(r)],
      requireHireApproval: c['require_hire_approval'] == true || c['require_hire_approval'] == 1,
      budgetMonthlyCents: _i(c['budget_monthly_cents']),
      budgetMonthlyTokens: _i(c['budget_monthly_tokens']),
    );
  }

  /// Goals as a tree under the mission: parents before children, with depth.
  List<(CompanyGoal, int)> get goalTree {
    final ids = {for (final g in goals) g.id};
    final out = <(CompanyGoal, int)>[];
    final seen = <int>{};
    void walk(int? parent, int depth) {
      for (final g in goals) {
        final key = g.parentId != null && ids.contains(g.parentId) ? g.parentId : null;
        if (key != parent || seen.contains(g.id)) continue;
        seen.add(g.id);
        out.add((g, depth));
        walk(g.id, depth + 1);
      }
    }

    walk(null, 0);
    return out;
  }

  String agentName(int? id) => id == null ? '' : agents.where((a) => a.id == id).map((a) => a.name).firstOrNull ?? '';
  String projectName(int? id) => id == null ? '' : projects.where((p) => p.id == id).map((p) => p.name).firstOrNull ?? '';

  /// Managers before their reports, with depth (strict tree in the core).
  List<(CompanyAgent, int)> get orgTree {
    final ids = {for (final a in agents) a.id};
    final out = <(CompanyAgent, int)>[];
    final seen = <int>{};
    void walk(int? manager, int depth) {
      for (final a in agents) {
        final key = a.reportsTo != null && ids.contains(a.reportsTo) ? a.reportsTo : null;
        if (key != manager || seen.contains(a.id)) continue;
        seen.add(a.id);
        out.add((a, depth));
        walk(a.id, depth + 1);
      }
    }

    walk(null, 0);
    return out;
  }

  bool isRunning(CompanyAgent a) => a.status == 'running' || active.contains(a.id);
}

class CompanyGoal {
  const CompanyGoal({required this.id, required this.title, this.parentId, this.description = '', this.status = 'active'});
  final int id;
  final int? parentId;
  final String title;
  final String description;
  final String status;
  factory CompanyGoal.fromJson(Map<String, dynamic> j) => CompanyGoal(
        id: _i(j['id']),
        parentId: _s(j['parent_id']).isEmpty || _i(j['parent_id']) == 0 ? null : _i(j['parent_id']),
        title: _s(j['title']),
        description: _s(j['description']),
        status: _s(j['status']).isEmpty ? 'active' : _s(j['status']),
      );
  bool get done => status == 'done' || status == 'achieved';
}

class CompanyProject {
  const CompanyProject({required this.id, required this.name, this.goalId, this.description = '', this.status = 'active', this.budgetMonthlyCents = 0});
  final int id;
  final int? goalId;
  final String name;
  final String description;
  final String status;
  final int budgetMonthlyCents;
  factory CompanyProject.fromJson(Map<String, dynamic> j) => CompanyProject(
        id: _i(j['id']),
        goalId: _s(j['goal_id']).isEmpty || _i(j['goal_id']) == 0 ? null : _i(j['goal_id']),
        name: _s(j['name']),
        description: _s(j['description']),
        status: _s(j['status']).isEmpty ? 'active' : _s(j['status']),
        budgetMonthlyCents: _i(j['budget_monthly_cents']),
      );
}

class CompanyRoutine {
  const CompanyRoutine({
    required this.id,
    required this.name,
    required this.schedule,
    this.title = '',
    this.description = '',
    this.agentId,
    this.projectId,
    this.enabled = true,
    this.nextRunAt,
  });
  final int id;
  final String name;
  final String schedule;
  final String title;
  final String description;
  final int? agentId;
  final int? projectId;
  final bool enabled;
  /// Unix seconds (PC clock), null when it will not run again.
  final double? nextRunAt;
  factory CompanyRoutine.fromJson(Map<String, dynamic> j) => CompanyRoutine(
        id: _i(j['id']),
        name: _s(j['name']),
        schedule: _s(j['schedule']),
        title: _s(j['title']),
        description: _s(j['description']),
        agentId: _s(j['agent_id']).isEmpty || _i(j['agent_id']) == 0 ? null : _i(j['agent_id']),
        projectId: _s(j['project_id']).isEmpty || _i(j['project_id']) == 0 ? null : _i(j['project_id']),
        enabled: !(j['enabled'] == false || j['enabled'] == 0),
        nextRunAt: j['next_run_at'] is num ? (j['next_run_at'] as num).toDouble() : null,
      );

  /// "Jalan berikutnya 12 Okt 08:00" in the phone's local time.
  String get nextLabel {
    final t = nextRunAt;
    if (!enabled) return 'nonaktif';
    if (t == null) return 'tidak dijadwalkan lagi';
    final d = DateTime.fromMillisecondsSinceEpoch((t * 1000).round());
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];
    String two(int n) => n.toString().padLeft(2, '0');
    return 'berikutnya ${d.day} ${months[d.month - 1]} ${two(d.hour)}:${two(d.minute)}';
  }
}

/// Dollars typed on the phone ("2.5", "2,50", "") → whole cents (0 = no limit).
int dollarsToCents(String text) {
  final v = double.tryParse(text.trim().replaceAll(',', '.').replaceAll(r'$', ''));
  return v == null || v <= 0 ? 0 : (v * 100).round();
}

/// Whole cents → the editable dollars text ("" for no limit).
String centsToDollars(int cents) => cents <= 0 ? '' : (cents % 100 == 0 ? '${cents ~/ 100}' : (cents / 100).toStringAsFixed(2));

class CompanyTicket {
  const CompanyTicket({
    required this.id,
    required this.key,
    required this.title,
    required this.status,
    this.description = '',
    this.assigneeId,
    this.assigneeName,
    this.locked = false,
    this.blockedBy = 0,
  });
  final int id;
  final String key;
  final String title;
  final String status;
  final String description;
  final int? assigneeId;
  final String? assigneeName;
  final bool locked;
  final int blockedBy;

  factory CompanyTicket.fromJson(Map<String, dynamic> j) => CompanyTicket(
        id: _i(j['id']),
        key: _s(j['key']),
        title: _s(j['title']),
        status: _s(j['status']),
        description: _s(j['description']),
        assigneeId: _iq(j['assignee_id']),
        assigneeName: j['assignee_name'] == null ? null : _s(j['assignee_name']),
        locked: j['locked'] == true,
        blockedBy: _i(j['blocked_by']),
      );
}

class TicketComment {
  const TicketComment({required this.author, required this.body, this.fromUser = false});
  final String author;
  final String body;
  final bool fromUser;
}

/// One line of a ticket's thread: a comment, an audit event (move, assign,
/// approval) or a heartbeat run. Core `ticket_timeline`, oldest first.
class TimelineEntry {
  const TimelineEntry({required this.type, required this.actor, required this.text, this.fromUser = false});
  final String type; // comment | event | run
  final String actor;
  final String text;
  final bool fromUser;
  bool get isComment => type == 'comment';

  factory TimelineEntry.fromJson(Map<String, dynamic> j) => TimelineEntry(
        type: _s(j['type']),
        actor: _s(j['actor_name']),
        text: _s(j['type'] == 'comment' ? j['body'] : j['summary']),
        fromUser: j['actor_type'] == 'user',
      );
}

/// A row of the Kantor activity log (pushed live as `company.activity`).
class CompanyActivity {
  const CompanyActivity({required this.id, required this.actor, required this.summary, this.action = '', this.ts = 0, this.actorType = '', this.actorId, this.entity = '', this.entityId});
  final int id;
  final String actor;
  final String actorType;
  final int? actorId;
  final String action;
  final String summary;
  final String entity;
  final int? entityId;
  final double ts;

  factory CompanyActivity.fromJson(Map<String, dynamic> j) => CompanyActivity(
        id: _i(j['id']),
        actor: _s(j['actor_name']),
        actorType: _s(j['actor_type']),
        actorId: j['actor_id'] == null ? null : _i(j['actor_id']),
        action: _s(j['action']),
        summary: _s(j['summary']),
        entity: _s(j['entity']),
        entityId: j['entity_id'] == null ? null : _i(j['entity_id']),
        ts: _d(j['ts']),
      );

  /// This employee did it, or it was done to them.
  bool involves(int? agentId) =>
      agentId == null || (actorType == 'agent' && actorId == agentId) || (entity == 'agent' && entityId == agentId);
}

/// Newest first, de-duplicated by id, capped.
List<CompanyActivity> mergeFeed(List<CompanyActivity> items, List<CompanyActivity> incoming, {int cap = 300}) {
  final seen = <int>{};
  final all = [...incoming, ...items]..sort((a, b) => b.id.compareTo(a.id));
  final out = <CompanyActivity>[];
  for (final a in all) {
    if (!seen.add(a.id)) continue;
    out.add(a);
    if (out.length >= cap) break;
  }
  return out;
}

class TicketDetail {
  const TicketDetail({required this.ticket, this.ancestry = const [], this.comments = const [], this.timeline = const []});
  final CompanyTicket ticket;
  final List<String> ancestry;
  final List<TicketComment> comments;
  final List<TimelineEntry> timeline;

  factory TicketDetail.fromJson(Map<String, dynamic> j) => TicketDetail(
        ticket: CompanyTicket.fromJson(j),
        ancestry: [
          for (final a in _l(j['ancestry'])) a['key'] != null ? '${a['key']} ${a['title']}' : _s(a['title']),
        ],
        comments: [
          for (final c in _l(j['comments']))
            TicketComment(
              author: c['author_name'] != null ? _s(c['author_name']) : (c['author_type'] == 'user' ? 'Kamu' : 'Sistem'),
              body: _s(c['body']),
              fromUser: c['author_type'] == 'user',
            ),
        ],
        timeline: [for (final t in _l(j['timeline'])) TimelineEntry.fromJson(t)],
      );
}

class CompanyApproval {
  const CompanyApproval({required this.id, required this.kind, required this.title, this.status = 'pending', this.detail = '', this.agentName, this.tickets = const [], this.extraTokens = 0, this.extraCents = 0});
  final int id;
  final String kind;
  final String title;
  final String status;
  final String detail;
  final String? agentName;
  /// Strategy approvals: "title → assignee" for each ticket the CEO proposed.
  final List<String> tickets;
  /// Budget approvals: how much the board adds when it approves.
  final int extraTokens;
  final double extraCents;
  bool get canRevise => const {'hire', 'plan', 'strategy'}.contains(kind);

  factory CompanyApproval.fromJson(Map<String, dynamic> j) {
    final p = _m(j['payload']);
    return CompanyApproval(
      id: _i(j['id']),
      kind: _s(j['kind']),
      title: _s(j['title']),
      status: _s(j['status']),
      detail: _s(p['plan'] ?? p['summary'] ?? ''),
      agentName: j['agent_name'] == null ? null : _s(j['agent_name']),
      tickets: [
        for (final t in _l(p['tickets']))
          if (_s(t['title']).isNotEmpty) '${_s(t['title'])} → ${t['assignee'] == null ? 'belum ada penanggung jawab' : _s(t['assignee'])}',
      ],
      extraTokens: _i(p['extra_tokens']),
      extraCents: _d(p['extra_cents']),
    );
  }

  String get kindLabel =>
      const {'hire': 'rekrut', 'plan': 'rencana', 'review': 'tinjau hasil', 'budget': 'anggaran', 'strategy': 'strategi CEO'}[kind] ?? kind;
}

class CostRow {
  const CostRow({required this.name, this.cents = 0, this.tokens = 0, this.pct});
  final String name;
  final double cents;
  final int tokens;
  final double? pct;
  factory CostRow.fromJson(Map<String, dynamic> j) =>
      CostRow(name: _s(j['name']), cents: _d(j['cents']), tokens: _i(j['tokens']), pct: j['pct'] == null ? null : _d(j['pct']));
}

class CompanyCosts {
  const CompanyCosts({this.month = '', this.total = const BudgetState(), this.byAgent = const []});
  final String month;
  final BudgetState total;
  final List<CostRow> byAgent;
  factory CompanyCosts.fromJson(Map<String, dynamic> j) => CompanyCosts(
        month: _s(j['month']),
        total: BudgetState.fromJson(_m(j['total'])),
        byAgent: [for (final r in _l(j['by_agent'])) CostRow.fromJson(r)],
      );
}

String formatCents(double cents) => '\$${(cents / 100).toStringAsFixed(cents > 0 && cents < 1 ? 4 : 2)}';

String formatTokens(int t) => t >= 1000000
    ? '${(t / 1000000).toStringAsFixed(1)} jt token'
    : t >= 1000
        ? '${(t / 1000).toStringAsFixed(1)} rb token'
        : '$t token';

/// Thin typed layer over [CompanyApi] used by the screens.
class CompanyClient {
  const CompanyClient(this.api);
  final CompanyApi api;

  Future<CompanySnapshot> snapshot() async => CompanySnapshot.fromJson(_m(await api.companyCall('snapshot')));
  Future<List<CompanyTicket>> tickets() async =>
      [for (final t in _l(_m(await api.companyCall('ticket.list'))['tickets'])) CompanyTicket.fromJson(t)];
  Future<TicketDetail> ticket(int id) async => TicketDetail.fromJson(_m(await api.companyCall('ticket.get', {'id': id})));
  Future<List<CompanyApproval>> approvals() async =>
      [for (final a in _l(_m(await api.companyCall('approval.list', {'status': 'pending'}))['approvals'])) CompanyApproval.fromJson(a)];
  Future<CompanyCosts> costs() async => CompanyCosts.fromJson(_m(await api.companyCall('costs')));

  Future<void> seedDemo() => api.companyCall('seed_demo');
  Future<void> setAutorun(bool on) => api.companyCall('update', {'autorun': on});
  /// Heartbeat on/off (the pause switch); the core logs who paused it.
  Future<void> setHeartbeat(bool on) => api.companyCall('heartbeat', {'on': on});
  Future<List<CompanyActivity>> activity({int? agentId, int limit = 100}) async => [
        for (final a in _l(_m(await api.companyCall('activity', {'limit': limit, 'agent_id': ?agentId}))['items'])) CompanyActivity.fromJson(a)
      ];
  Future<void> revise(int id, {String note = ''}) =>
      api.companyCall('approval.decide', {'id': id, 'decision': 'revise', 'note': note});
  Future<void> wake(int id) => api.companyCall('agent.wake', {'id': id});
  Future<void> pause(int id) => api.companyCall('agent.pause', {'id': id});
  Future<void> resume(int id) => api.companyCall('agent.resume', {'id': id});
  Future<void> stop(int id) => api.companyCall('agent.stop', {'id': id});
  Future<void> move(int id, String status) => api.companyCall('ticket.move', {'id': id, 'status': status});
  Future<void> assign(int id, int? agentId) => api.companyCall('ticket.assign', {'id': id, 'agent_id': agentId});
  Future<void> comment(int id, String body) => api.companyCall('ticket.comment', {'id': id, 'body': body});
  Future<void> createTicket(String title, int? assigneeId) =>
      api.companyCall('ticket.save', {'title': title, 'assignee_id': ?assigneeId});
  /// New agent (a hire approval when the company requires it) or edits one.
  /// Returns the agent as the PC saved it (status `pending_approval` when
  /// the hire waits for approval).
  Future<CompanyAgent> saveAgent(Map<String, dynamic> body) async => CompanyAgent.fromJson(_m(await api.companyCall('agent.save', body)));
  Future<void> terminate(int id) => api.companyCall('agent.terminate', {'id': id});
  Future<void> updateCompany(Map<String, dynamic> fields) => api.companyCall('update', fields);
  Future<void> saveGoal(Map<String, dynamic> body) => api.companyCall('goal.save', body);
  Future<void> deleteGoal(int id) => api.companyCall('goal.delete', {'id': id});
  Future<void> saveProject(Map<String, dynamic> body) => api.companyCall('project.save', body);
  Future<void> deleteProject(int id) => api.companyCall('project.delete', {'id': id});
  Future<void> saveRoutine(Map<String, dynamic> body) => api.companyCall('routine.save', body);
  Future<void> deleteRoutine(int id) => api.companyCall('routine.delete', {'id': id});
  Future<void> triggerRoutine(int id) => api.companyCall('routine.trigger', {'id': id});
  Future<void> decide(int id, bool approve, {String note = ''}) =>
      api.companyCall('approval.decide', {'id': id, 'decision': approve ? 'approve' : 'reject', 'note': note});
}
