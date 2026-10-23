// Crew on the phone: the PC's main agent puts a small team of agents together
// for one goal (core/neovarch/crew.py). The phone proposes, approves, watches
// the pixel room and answers approvals; everything goes through `crew.*` RPCs
// and the `crew.update` push.

/// What the Crew screens need from the PC connection (RemoteGateway; a fake in tests).
abstract class CrewApi {
  /// Calls `crew.<method>` with [params]; throws on an RPC error.
  Future<dynamic> crewCall(String method, [Map<String, dynamic> params = const {}]);

  /// Answers a crew member's pending approval (`approval.respond` on its session).
  Future<void> crewApproval(String sessionId, String requestId, String choice);
}

const crewTemplates = ['riset', 'konten', 'coding', 'riset_laporan'];
const crewToolGroups = ['web', 'files', 'write', 'shell'];
const crewSideEffectTools = {'write', 'shell'};

/// Indonesian labels (the phone's source language; English comes from tr()).
const crewTemplateLabel = {'riset': 'Riset', 'konten': 'Konten', 'coding': 'Coding', 'riset_laporan': 'Riset + Laporan'};
const crewToolLabel = {'web': 'Web', 'files': 'Baca file', 'write': 'Tulis file', 'shell': 'Perintah'};
const crewMemberStatusLabel = {
  'idle': 'santai',
  'working': 'bekerja',
  'reviewing': 'memeriksa',
  'waiting': 'butuh kamu',
  'done': 'selesai',
  'error': 'galat',
};
const crewStatusLabel = {
  'proposed': 'Usulan',
  'running': 'Bekerja',
  'done': 'Selesai',
  'failed': 'Gagal',
  'cancelled': 'Dihentikan',
};

Map<String, dynamic> _m(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<dynamic> _l(dynamic v) => v is List ? v : const [];
String _s(dynamic v) => v == null ? '' : '$v';
int _i(dynamic v) => v is num ? v.toInt() : int.tryParse('$v') ?? 0;

class CrewApproval {
  const CrewApproval({required this.sessionId, required this.requestId, required this.command});
  final String sessionId, requestId, command;
  static CrewApproval? fromJson(dynamic v) {
    final m = _m(v);
    if (m.isEmpty || _s(m['request_id']).isEmpty) return null;
    return CrewApproval(sessionId: _s(m['session_id']), requestId: _s(m['request_id']), command: _s(m['command']));
  }
}

class CrewMember {
  const CrewMember({
    required this.id,
    required this.name,
    required this.role,
    this.goal = '',
    this.tools = const [],
    this.model = '',
    this.avatar = 0,
    this.status = 'idle',
    this.activity = '',
    this.approval,
  });
  final String id, name, role, goal, model, status, activity;
  final List<String> tools;
  final int avatar;
  final CrewApproval? approval;

  factory CrewMember.fromJson(dynamic v) {
    final m = _m(v);
    return CrewMember(
      id: _s(m['id']),
      name: _s(m['name']),
      role: _s(m['role']),
      goal: _s(m['goal']),
      tools: [for (final t in _l(m['tools'])) _s(t)],
      model: _s(m['model']),
      avatar: _i(m['avatar']),
      status: _s(m['status']).isEmpty ? 'idle' : _s(m['status']),
      activity: _s(m['activity']),
      approval: CrewApproval.fromJson(m['approval']),
    );
  }

  CrewMember copyWith({String? name, String? role, String? goal, List<String>? tools, String? model}) => CrewMember(
        id: id,
        name: name ?? this.name,
        role: role ?? this.role,
        goal: goal ?? this.goal,
        tools: tools ?? this.tools,
        model: model ?? this.model,
        avatar: avatar,
        status: status,
        activity: activity,
        approval: approval,
      );

  Map<String, dynamic> toJson() => {'id': id, 'name': name, 'role': role, 'goal': goal, 'tools': tools, 'model': model, 'avatar': avatar};
}

class CrewTask {
  const CrewTask({required this.id, required this.title, this.description = '', this.expectedOutput = '', required this.memberId, this.status = 'todo', this.output = ''});
  final String id, title, description, expectedOutput, memberId, status, output;

  factory CrewTask.fromJson(dynamic v) {
    final m = _m(v);
    return CrewTask(
      id: _s(m['id']),
      title: _s(m['title']),
      description: _s(m['description']),
      expectedOutput: _s(m['expected_output']),
      memberId: _s(m['member_id']),
      status: _s(m['status']).isEmpty ? 'todo' : _s(m['status']),
      output: _s(m['output']),
    );
  }

  CrewTask copyWith({String? title, String? description, String? memberId}) => CrewTask(
      id: id,
      title: title ?? this.title,
      description: description ?? this.description,
      expectedOutput: expectedOutput,
      memberId: memberId ?? this.memberId,
      status: status,
      output: output);

  Map<String, dynamic> toJson() =>
      {'id': id, 'title': title, 'description': description, 'expected_output': expectedOutput, 'member_id': memberId};
}

class Crew {
  const Crew({
    required this.id,
    required this.title,
    required this.goal,
    required this.status,
    required this.process,
    this.manager,
    this.members = const [],
    this.tasks = const [],
    this.sideEffects = const [],
    this.allowSideEffects = false,
    this.designedBy = 'template',
    this.template = 'riset',
    this.finalOutput = '',
    this.error = '',
    this.createdAt = 0,
  });
  final String id, title, goal, status, process, designedBy, template, finalOutput, error;
  final String? manager;
  final List<CrewMember> members;
  final List<CrewTask> tasks;
  final List<String> sideEffects;
  final bool allowSideEffects;
  final double createdAt;

  bool get proposed => status == 'proposed';
  bool get running => status == 'running';
  bool get finished => status == 'done' || status == 'failed' || status == 'cancelled';
  int get doneCount => tasks.where((t) => t.status == 'done').length;
  CrewMember? member(String id) => members.where((m) => m.id == id).firstOrNull;

  factory Crew.fromJson(dynamic v) {
    final m = _m(v);
    return Crew(
      id: _s(m['id']),
      title: _s(m['title']),
      goal: _s(m['goal']),
      status: _s(m['status']),
      process: _s(m['process']).isEmpty ? 'sequential' : _s(m['process']),
      manager: m['manager'] == null ? null : _s(m['manager']),
      members: [for (final x in _l(m['members'])) CrewMember.fromJson(x)],
      tasks: [for (final x in _l(m['tasks'])) CrewTask.fromJson(x)],
      sideEffects: [for (final x in _l(m['side_effects'])) _s(x)],
      allowSideEffects: m['allow_side_effects'] == true,
      designedBy: _s(m['designed_by']),
      template: _s(m['template']),
      finalOutput: _s(m['final_output']),
      error: _s(m['error']),
      createdAt: (m['created_at'] is num) ? (m['created_at'] as num).toDouble() : 0,
    );
  }
}

class CrewSummary {
  const CrewSummary({required this.id, required this.title, required this.status, this.template = '', this.done = 0, this.tasks = 0});
  final String id, title, status, template;
  final int done, tasks;
  factory CrewSummary.fromJson(dynamic v) {
    final m = _m(v);
    return CrewSummary(
        id: _s(m['id']), title: _s(m['title']), status: _s(m['status']), template: _s(m['template']), done: _i(m['done']), tasks: _i(m['tasks']));
  }
}

class CrewClient {
  const CrewClient(this.api);
  final CrewApi api;

  Future<List<CrewSummary>> list() async => [for (final c in _l(_m(await api.crewCall('list'))['crews'])) CrewSummary.fromJson(c)];
  Future<Crew> get(String id) async => Crew.fromJson(await api.crewCall('get', {'id': id}));
  Future<Crew> propose(String goal, {String? template}) async =>
      Crew.fromJson(await api.crewCall('propose', {'goal': goal, 'template': ?template}));
  Future<Crew> approve(String id, {bool allowSideEffects = false}) async =>
      Crew.fromJson(await api.crewCall('approve', {'id': id, 'allow_side_effects': allowSideEffects}));
  Future<Crew> cancel(String id) async => Crew.fromJson(await api.crewCall('cancel', {'id': id}));
  Future<void> delete(String id) => api.crewCall('delete', {'id': id});
  Future<Crew> update(String id, {required String process, String? manager, required List<CrewMember> members, required List<CrewTask> tasks}) async =>
      Crew.fromJson(await api.crewCall('update', {
        'id': id,
        'patch': {
          'process': process,
          'manager': process == 'hierarchical' ? (manager ?? (members.isEmpty ? null : members.first.id)) : null,
          'members': [for (final m in members) m.toJson()],
          'tasks': [for (final t in tasks) t.toJson()],
        },
      }));
  Future<void> answer(CrewMember m, String choice) async {
    final a = m.approval;
    if (a == null) return;
    await api.crewApproval(a.sessionId, a.requestId, choice);
  }
}
