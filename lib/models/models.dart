// Domain models for Neovarch Agent.
//
// The office shapes (Task, Agent, Meeting, CronJob, ...) mirror
// the shared types of the Next.js web app one-to-one, so every backend
// (on-device, Next.js server, demo) speaks the same JSON. The chat shapes
// (ChatSessionInfo, ChatMsg, ToolActivity) mirror the desktop app's
// transcript: streaming text, reasoning, and tool rows with summaries.

String? _str(dynamic v) => v?.toString();
int _int(dynamic v, [int d = 0]) {
  if (v is int) return v;
  if (v is num) return v.toInt();
  return int.tryParse('${v ?? ''}') ?? d;
}

List<String> _strList(dynamic v) =>
    v is List ? v.map((e) => '$e').toList() : const <String>[];

// ---------------------------------------------------------------- office --

class TaskOrigin {
  final String kind; // meeting | cron | agent | manual
  final String? ref;
  final String? raw;
  const TaskOrigin({required this.kind, this.ref, this.raw});

  factory TaskOrigin.fromJson(Map<String, dynamic> j) => TaskOrigin(
      kind: '${j['kind'] ?? 'manual'}', ref: _str(j['ref']), raw: _str(j['raw']));
  Map<String, dynamic> toJson() =>
      {'kind': kind, if (ref != null) 'ref': ref, if (raw != null) 'raw': raw};

  /// Same rule as TaskPanel.originLabel: only cross-menu links are shown.
  String? get label {
    switch (kind) {
      case 'meeting':
        return ref != null ? 'rapat $ref' : 'rapat';
      case 'cron':
        return ref != null ? 'cron $ref' : 'cron';
      case 'agent':
        return ref != null ? 'agent $ref' : 'agent';
      default:
        return null;
    }
  }
}

class Task {
  final String id;
  final String title;
  final String status;
  final String? assignee;
  final int priority;
  final String? body;
  final String? createdAt;
  final String? updatedAt;
  final TaskOrigin? origin;
  final String? output;

  const Task({
    required this.id,
    required this.title,
    required this.status,
    this.assignee,
    this.priority = 0,
    this.body,
    this.createdAt,
    this.updatedAt,
    this.origin,
    this.output,
  });

  factory Task.fromJson(Map<String, dynamic> j) => Task(
        id: '${j['id']}',
        title: '${j['title'] ?? ''}',
        status: '${j['status'] ?? 'todo'}',
        assignee: _str(j['assignee']),
        priority: _int(j['priority']),
        body: _str(j['body']),
        createdAt: _str(j['createdAt']),
        updatedAt: _str(j['updatedAt']),
        origin: j['origin'] is Map
            ? TaskOrigin.fromJson(Map<String, dynamic>.from(j['origin']))
            : null,
        output: _str(j['output']),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'title': title,
        'status': status,
        'assignee': assignee,
        'priority': priority,
        if (body != null) 'body': body,
        if (createdAt != null) 'createdAt': createdAt,
        if (updatedAt != null) 'updatedAt': updatedAt,
        if (origin != null) 'origin': origin!.toJson(),
        if (output != null) 'output': output,
      };

  Task copyWith({
    String? title,
    String? status,
    String? assignee,
    int? priority,
    String? body,
    String? output,
    String? updatedAt,
  }) =>
      Task(
        id: id,
        title: title ?? this.title,
        status: status ?? this.status,
        assignee: assignee ?? this.assignee,
        priority: priority ?? this.priority,
        body: body ?? this.body,
        createdAt: createdAt,
        updatedAt: updatedAt ?? DateTime.now().toIso8601String(),
        origin: origin,
        output: output ?? this.output,
      );
}

/// The four displayed columns (board.ts `columnOf`).
const boardColumns = ['TODO', 'JALAN', 'REVIEW', 'SELESAI'];

int columnOf(String status) {
  switch (status) {
    case 'todo':
    case 'triage':
    case 'ready':
    case 'scheduled':
      return 0;
    case 'running':
      return 1;
    case 'review':
      return 2;
    case 'done':
      return 3;
    default:
      return 0; // blocked / archived ride with the backlog
  }
}

const statusLabel = <String, String>{
  'todo': 'Belum dikerjakan',
  'triage': 'Perlu dispesifikasi',
  'ready': 'Siap diambil worker',
  'scheduled': 'Terjadwal',
  'running': 'Sedang dikerjakan',
  'review': 'Menunggu review',
  'blocked': 'Terhambat',
  'done': 'Selesai',
  'archived': 'Diarsipkan',
};

class Agent {
  final String name;
  final String displayName;
  final String role;
  final int? deskIndex;
  final String status; // idle working review blocked meeting done
  final String? currentTaskId;

  const Agent({
    required this.name,
    required this.displayName,
    required this.role,
    this.deskIndex,
    this.status = 'idle',
    this.currentTaskId,
  });

  factory Agent.fromJson(Map<String, dynamic> j) => Agent(
        name: '${j['name']}',
        displayName: '${j['displayName'] ?? j['name']}',
        role: '${j['role'] ?? 'backend'}',
        deskIndex: j['deskIndex'] == null ? null : _int(j['deskIndex']),
        status: '${j['status'] ?? 'idle'}',
        currentTaskId: _str(j['currentTaskId']),
      );

  Map<String, dynamic> toJson() => {
        'name': name,
        'displayName': displayName,
        'role': role,
        'deskIndex': deskIndex,
        'status': status,
        'currentTaskId': currentTaskId,
      };
}

class RunInfo {
  final String id;
  final String status;
  final String? profile;
  final String? outcome;
  final String? summary;
  final String? error;
  const RunInfo(
      {required this.id,
      required this.status,
      this.profile,
      this.outcome,
      this.summary,
      this.error});
  factory RunInfo.fromJson(Map<String, dynamic> j) => RunInfo(
        id: '${j['id']}',
        status: '${j['status'] ?? ''}',
        profile: _str(j['profile']),
        outcome: _str(j['outcome']),
        summary: _str(j['summary']),
        error: _str(j['error']),
      );
}

class MeetingTurn {
  final int round;
  final String speaker;
  final String kind; // opening | speech | minutes
  final String text;
  final int ts;
  const MeetingTurn(
      {required this.round,
      required this.speaker,
      required this.kind,
      required this.text,
      required this.ts});
  factory MeetingTurn.fromJson(Map<String, dynamic> j) => MeetingTurn(
      round: _int(j['round']),
      speaker: '${j['speaker'] ?? ''}',
      kind: '${j['kind'] ?? 'speech'}',
      text: '${j['text'] ?? ''}',
      ts: _int(j['ts']));
  Map<String, dynamic> toJson() =>
      {'round': round, 'speaker': speaker, 'kind': kind, 'text': text, 'ts': ts};
}

class Meeting {
  final String id;
  final String topic;
  final List<String> participants;
  final String moderator;
  final String mode;
  final String state; // queued running done error idle
  final String phase;
  final String? currentSpeaker;
  final List<MeetingTurn> turns;
  final String minutes;

  const Meeting({
    required this.id,
    required this.topic,
    required this.participants,
    required this.moderator,
    required this.mode,
    required this.state,
    required this.phase,
    this.currentSpeaker,
    this.turns = const [],
    this.minutes = '',
  });

  bool get live => state == 'queued' || state == 'running';

  factory Meeting.fromJson(Map<String, dynamic> j) => Meeting(
        id: '${j['id']}',
        topic: '${j['topic'] ?? ''}',
        participants: _strList(j['participants']),
        moderator: '${j['moderator'] ?? ''}',
        mode: '${j['mode'] ?? 'auto'}',
        state: '${j['state'] ?? 'idle'}',
        phase: '${j['phase'] ?? ''}',
        currentSpeaker: _str(j['currentSpeaker']),
        turns: (j['turns'] is List ? j['turns'] as List : const [])
            .map((e) => MeetingTurn.fromJson(Map<String, dynamic>.from(e)))
            .toList(),
        minutes: '${j['minutes'] ?? ''}',
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'topic': topic,
        'participants': participants,
        'moderator': moderator,
        'mode': mode,
        'state': state,
        'phase': phase,
        'currentSpeaker': currentSpeaker,
        'turns': turns.map((t) => t.toJson()).toList(),
        'minutes': minutes,
      };
}

class ArchivedMeeting {
  final String id;
  final String topic;
  final String startedAt;
  final List<String> participants;
  final String moderator;
  final String mode;
  final int turnCount;
  final String preview;
  const ArchivedMeeting({
    required this.id,
    required this.topic,
    required this.startedAt,
    required this.participants,
    required this.moderator,
    required this.mode,
    required this.turnCount,
    required this.preview,
  });
  factory ArchivedMeeting.fromJson(Map<String, dynamic> j) => ArchivedMeeting(
        id: '${j['id']}',
        topic: '${j['topic'] ?? ''}',
        startedAt: '${j['startedAt'] ?? ''}',
        participants: _strList(j['participants']),
        moderator: '${j['moderator'] ?? ''}',
        mode: '${j['mode'] ?? 'auto'}',
        turnCount: _int(j['turnCount']),
        preview: '${j['preview'] ?? ''}',
      );
  Map<String, dynamic> toJson() => {
        'id': id,
        'topic': topic,
        'file': 'rapat-$id.md',
        'startedAt': startedAt,
        'participants': participants,
        'moderator': moderator,
        'mode': mode,
        'turnCount': turnCount,
        'preview': preview,
        'archived': true,
      };
}

/// A proposed task offered by a source panel before anything is written.
class Candidate {
  final String text;
  final String owner;
  final String? suggested;
  final String? due;
  final String? body;
  const Candidate(
      {required this.text,
      this.owner = '',
      this.suggested,
      this.due,
      this.body});
  factory Candidate.fromJson(Map<String, dynamic> j) => Candidate(
        text: '${j['text'] ?? ''}',
        owner: '${j['owner'] ?? ''}',
        suggested: _str(j['suggested']),
        due: _str(j['due']),
        body: _str(j['body']),
      );
}

class CronJob {
  final String id;
  final String name;
  final String prompt;
  final String schedule;
  final String scheduleKind;
  final bool enabled;
  final String state;
  final String? nextRunAt;
  final String? lastRunAt;
  final String? lastStatus;
  final String? lastError;
  final int failureStreak;
  final String? agent;
  final String? lastOutput;

  const CronJob({
    required this.id,
    required this.name,
    required this.prompt,
    required this.schedule,
    this.scheduleKind = 'cron',
    this.enabled = false,
    this.state = 'paused',
    this.nextRunAt,
    this.lastRunAt,
    this.lastStatus,
    this.lastError,
    this.failureStreak = 0,
    this.agent,
    this.lastOutput,
  });

  factory CronJob.fromJson(Map<String, dynamic> j) => CronJob(
        id: '${j['id']}',
        name: '${j['name'] ?? j['id']}',
        prompt: '${j['prompt'] ?? ''}',
        schedule: '${j['schedule'] ?? ''}',
        scheduleKind: '${j['scheduleKind'] ?? 'cron'}',
        enabled: j['enabled'] == true,
        state: '${j['state'] ?? ''}',
        nextRunAt: _str(j['nextRunAt']),
        lastRunAt: _str(j['lastRunAt']),
        lastStatus: _str(j['lastStatus']),
        lastError: _str(j['lastError']),
        failureStreak: _int(j['failureStreak']),
        agent: _str(j['agent']),
        lastOutput: _str(j['lastOutput']),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'prompt': prompt,
        'schedule': schedule,
        'scheduleKind': scheduleKind,
        'enabled': enabled,
        'state': state,
        'nextRunAt': nextRunAt,
        'lastRunAt': lastRunAt,
        'lastStatus': lastStatus,
        'lastError': lastError,
        'failureStreak': failureStreak,
        'agent': agent,
        'lastOutput': lastOutput,
      };
}

class CronRun {
  final String id;
  final String jobId;
  final String status;
  final String? startedAt;
  final String? finishedAt;
  const CronRun(
      {required this.id,
      required this.jobId,
      required this.status,
      this.startedAt,
      this.finishedAt});
  factory CronRun.fromJson(Map<String, dynamic> j) => CronRun(
        id: '${j['id']}',
        jobId: '${j['jobId'] ?? ''}',
        status: '${j['status'] ?? ''}',
        startedAt: _str(j['startedAt']),
        finishedAt: _str(j['finishedAt']),
      );
  Map<String, dynamic> toJson() => {
        'id': id,
        'jobId': jobId,
        'status': status,
        'startedAt': startedAt,
        'finishedAt': finishedAt
      };
}

class AgentRow {
  final String name;
  final int total;
  final bool profile;
  final bool inOffice;
  final String? reason;
  const AgentRow(
      {required this.name,
      this.total = 0,
      this.profile = true,
      this.inOffice = true,
      this.reason});
  factory AgentRow.fromJson(Map<String, dynamic> j) => AgentRow(
        name: '${j['name']}',
        total: _int(j['total']),
        profile: j['profile'] != false,
        inOffice: j['inOffice'] != false,
        reason: _str(j['reason']),
      );
}

// ---------------------------------------------------------------- agent ---

/// A profile = an agent: name, role, system prompt, model override.
class Profile {
  final String name;
  final String role;
  final String description;
  final String systemPrompt;
  final String? model;
  final int? deskIndex;
  final bool hidden;

  const Profile({
    required this.name,
    this.role = 'backend',
    this.description = '',
    this.systemPrompt = '',
    this.model,
    this.deskIndex,
    this.hidden = false,
  });

  factory Profile.fromJson(Map<String, dynamic> j) => Profile(
        name: '${j['name']}',
        role: '${j['role'] ?? 'backend'}',
        description: '${j['description'] ?? ''}',
        systemPrompt: '${j['systemPrompt'] ?? ''}',
        model: (j['model'] == null || '${j['model']}'.isEmpty)
            ? null
            : '${j['model']}',
        deskIndex: j['deskIndex'] == null ? null : _int(j['deskIndex']),
        hidden: j['hidden'] == true,
      );

  Map<String, dynamic> toJson() => {
        'name': name,
        'role': role,
        'description': description,
        'systemPrompt': systemPrompt,
        'model': model,
        'deskIndex': deskIndex,
        'hidden': hidden,
      };

  Profile copyWith({
    String? role,
    String? description,
    String? systemPrompt,
    String? model,
    bool clearModel = false,
    int? deskIndex,
    bool? hidden,
  }) =>
      Profile(
        name: name,
        role: role ?? this.role,
        description: description ?? this.description,
        systemPrompt: systemPrompt ?? this.systemPrompt,
        model: clearModel ? null : (model ?? this.model),
        deskIndex: deskIndex ?? this.deskIndex,
        hidden: hidden ?? this.hidden,
      );
}

const agentRoles = [
  'orchestrator',
  'backend',
  'frontend',
  'qa',
  'researcher',
  'devops'
];

/// Same name heuristic as the server's `roleFor(name)`.
String roleFor(String name) {
  final n = name.toLowerCase();
  if (n.contains('qa') || n.contains('test') || n.contains('review')) return 'qa';
  if (n.contains('front') || n.contains('ui') || n.contains('design')) return 'frontend';
  if (n.contains('ops') || n.contains('infra') || n.contains('deploy')) return 'devops';
  if (n.contains('riset') || n.contains('research')) return 'researcher';
  if (n == 'default' || n.contains('lead') || n.contains('orch')) return 'orchestrator';
  return 'backend';
}

class Skill {
  final String name;
  final String description;
  final String body;
  final bool enabled;
  final String updatedAt;
  const Skill(
      {required this.name,
      this.description = '',
      this.body = '',
      this.enabled = true,
      this.updatedAt = ''});
  factory Skill.fromJson(Map<String, dynamic> j) => Skill(
      name: '${j['name']}',
      description: '${j['description'] ?? ''}',
      body: '${j['body'] ?? ''}',
      enabled: j['enabled'] != false,
      updatedAt: '${j['updatedAt'] ?? ''}');
  Map<String, dynamic> toJson() => {
        'name': name,
        'description': description,
        'body': body,
        'enabled': enabled,
        'updatedAt': updatedAt
      };
}

class MemoryNote {
  final String id;
  final String scope; // profile name, or '*' for shared
  final String text;
  final String createdAt;
  const MemoryNote(
      {required this.id,
      required this.scope,
      required this.text,
      required this.createdAt});
  factory MemoryNote.fromJson(Map<String, dynamic> j) => MemoryNote(
      id: '${j['id']}',
      scope: '${j['scope'] ?? '*'}',
      text: '${j['text'] ?? ''}',
      createdAt: '${j['createdAt'] ?? ''}');
  Map<String, dynamic> toJson() =>
      {'id': id, 'scope': scope, 'text': text, 'createdAt': createdAt};
}

class Project {
  final String id;
  final String name;
  final String description;
  final String folder; // workspace folder the project owns
  const Project(
      {required this.id,
      required this.name,
      this.description = '',
      this.folder = ''});
  factory Project.fromJson(Map<String, dynamic> j) => Project(
      id: '${j['id']}',
      name: '${j['name'] ?? ''}',
      description: '${j['description'] ?? ''}',
      folder: '${j['folder'] ?? ''}');
  Map<String, dynamic> toJson() =>
      {'id': id, 'name': name, 'description': description, 'folder': folder};
}

// ----------------------------------------------------------------- chat ---

class ChatSessionInfo {
  final String id;
  final String title;
  final String profile;
  final String? projectId;
  final String updatedAt;
  final int messageCount;
  final String preview;
  const ChatSessionInfo({
    required this.id,
    required this.title,
    required this.profile,
    this.projectId,
    this.updatedAt = '',
    this.messageCount = 0,
    this.preview = '',
  });
  factory ChatSessionInfo.fromJson(Map<String, dynamic> j) => ChatSessionInfo(
        id: '${j['id']}',
        title: '${j['title'] ?? ''}',
        profile: '${j['profile'] ?? 'default'}',
        projectId: _str(j['projectId']),
        updatedAt: '${j['updatedAt'] ?? ''}',
        messageCount: _int(j['messageCount']),
        preview: '${j['preview'] ?? ''}',
      );
  Map<String, dynamic> toJson() => {
        'id': id,
        'title': title,
        'profile': profile,
        'projectId': projectId,
        'updatedAt': updatedAt,
        'messageCount': messageCount,
        'preview': preview,
      };
  ChatSessionInfo copyWith(
          {String? title,
          String? projectId,
          bool clearProject = false,
          String? updatedAt,
          int? messageCount,
          String? preview}) =>
      ChatSessionInfo(
        id: id,
        title: title ?? this.title,
        profile: profile,
        projectId: clearProject ? null : (projectId ?? this.projectId),
        updatedAt: updatedAt ?? this.updatedAt,
        messageCount: messageCount ?? this.messageCount,
        preview: preview ?? this.preview,
      );
}

/// One tool invocation as the transcript shows it.
class ToolActivity {
  final String id;
  final String name;
  String args;
  String? summary;
  String? result;
  bool running;
  bool failed;
  double? durationS;
  ToolActivity({
    required this.id,
    required this.name,
    this.args = '',
    this.summary,
    this.result,
    this.running = true,
    this.failed = false,
    this.durationS,
  });
  factory ToolActivity.fromJson(Map<String, dynamic> j) => ToolActivity(
        id: '${j['id']}',
        name: '${j['name']}',
        args: '${j['args'] ?? ''}',
        summary: _str(j['summary']),
        result: _str(j['result']),
        running: false,
        failed: j['failed'] == true,
        durationS: (j['durationS'] as num?)?.toDouble(),
      );
  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'args': args,
        'summary': summary,
        'result': result,
        'failed': failed,
        'durationS': durationS,
      };
}

class ChatMsg {
  final String id;
  final String role; // user | assistant | tool | system
  String content;
  String reasoning;
  final int ts;
  final List<String> images; // data: URLs
  final List<ToolActivity> tools;

  /// Files on a message (phone remote: PC uploads `{id, name, mime, size, kind,
  /// url, origin}`): sent by the person (user rows) or by the PC agent with
  /// send_file (assistant rows).
  final List<Map<String, dynamic>> attachments;

  /// Raw OpenAI tool_calls of an assistant message (local runtime only).
  List<Map<String, dynamic>>? toolCalls;
  final String? toolCallId;
  bool streaming;
  String? error;

  /// Structured stop/error from the PC core (v1.4.7 `error` event / `error_info`):
  /// `{code, title, message, action, action_label}`. Same wording on desktop.
  Map<String, dynamic>? errorInfo;

  ChatMsg({
    required this.id,
    required this.role,
    this.content = '',
    this.reasoning = '',
    required this.ts,
    List<String>? images,
    List<ToolActivity>? tools,
    List<Map<String, dynamic>>? attachments,
    this.toolCalls,
    this.toolCallId,
    this.streaming = false,
    this.error,
  })  : images = images ?? [],
        tools = tools ?? [],
        attachments = attachments ?? [];

  factory ChatMsg.fromJson(Map<String, dynamic> j) => ChatMsg(
        id: '${j['id'] ?? j['ts'] ?? DateTime.now().microsecondsSinceEpoch}',
        role: '${j['role'] ?? 'assistant'}',
        content: '${j['content'] ?? j['text'] ?? ''}',
        reasoning: '${j['reasoning'] ?? ''}',
        ts: _int(j['ts'], DateTime.now().millisecondsSinceEpoch),
        images: _strList(j['images']),
        tools: (j['tools'] is List ? j['tools'] as List : const [])
            .map((e) => ToolActivity.fromJson(Map<String, dynamic>.from(e)))
            .toList(),
        toolCalls: j['toolCalls'] is List
            ? (j['toolCalls'] as List)
                .map((e) => Map<String, dynamic>.from(e))
                .toList()
            : null,
        toolCallId: _str(j['toolCallId']),
        error: _str(j['error']),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'role': role,
        'content': content,
        if (reasoning.isNotEmpty) 'reasoning': reasoning,
        'ts': ts,
        if (images.isNotEmpty) 'images': images,
        if (tools.isNotEmpty) 'tools': tools.map((t) => t.toJson()).toList(),
        if (toolCalls != null) 'toolCalls': toolCalls,
        if (toolCallId != null) 'toolCallId': toolCallId,
        if (error != null) 'error': error,
      };
}

/// Events a chat engine emits while a turn streams.
sealed class ChatEvent {
  const ChatEvent();
}

class DeltaEvent extends ChatEvent {
  final String text;
  const DeltaEvent(this.text);
}

class ReasoningEvent extends ChatEvent {
  final String text;
  const ReasoningEvent(this.text);
}

class ToolStartEvent extends ChatEvent {
  final String id;
  final String name;
  final String args;
  const ToolStartEvent(this.id, this.name, this.args);
}

class ToolDoneEvent extends ChatEvent {
  final String id;
  final String name;
  final String? summary;
  final String? result;
  final bool failed;
  final double? durationS;
  const ToolDoneEvent(this.id, this.name,
      {this.summary, this.result, this.failed = false, this.durationS});
}

class NewAssistantEvent extends ChatEvent {
  /// The model started a new assistant message after tool results.
  const NewAssistantEvent();
}

class TitleEvent extends ChatEvent {
  final String title;
  const TitleEvent(this.title);
}

class UsageEvent extends ChatEvent {
  final int promptTokens;
  final int completionTokens;
  final double tokensPerSecond;
  final double? cost;
  const UsageEvent(this.promptTokens, this.completionTokens, this.tokensPerSecond, [this.cost]);
}

class ApprovalEvent extends ChatEvent {
  final String requestId;
  final String command;
  final String description;
  final List<String> choices;
  const ApprovalEvent(this.requestId, this.command, this.description, this.choices);
}

class DoneEvent extends ChatEvent {
  const DoneEvent();
}

class ErrorEvent extends ChatEvent {
  final String message;
  const ErrorEvent(this.message);
}

// ----------------------------------------------------------- providers ---

class ProviderConfig {
  final String id;
  final String label;
  final String baseUrl;
  final String model;
  final List<String> favoriteModels;
  const ProviderConfig({
    required this.id,
    required this.label,
    required this.baseUrl,
    this.model = '',
    this.favoriteModels = const [],
  });
  factory ProviderConfig.fromJson(Map<String, dynamic> j) => ProviderConfig(
        id: '${j['id']}',
        label: '${j['label'] ?? j['id']}',
        baseUrl: '${j['baseUrl'] ?? ''}',
        model: '${j['model'] ?? ''}',
        favoriteModels: _strList(j['favoriteModels']),
      );
  Map<String, dynamic> toJson() => {
        'id': id,
        'label': label,
        'baseUrl': baseUrl,
        'model': model,
        'favoriteModels': favoriteModels,
      };
  ProviderConfig copyWith(
          {String? label,
          String? baseUrl,
          String? model,
          List<String>? favoriteModels}) =>
      ProviderConfig(
        id: id,
        label: label ?? this.label,
        baseUrl: baseUrl ?? this.baseUrl,
        model: model ?? this.model,
        favoriteModels: favoriteModels ?? this.favoriteModels,
      );
}

class ProviderPreset {
  final String id;
  final String label;
  final String baseUrl;
  final String defaultModel;
  final bool needsKey;
  final String hint;
  const ProviderPreset(this.id, this.label, this.baseUrl, this.defaultModel,
      {this.needsKey = true, this.hint = ''});
}

const providerPresets = <ProviderPreset>[
  ProviderPreset('openrouter', 'OpenRouter', 'https://openrouter.ai/api/v1',
      'qwen/qwen3-coder',
      hint: 'Satu kunci untuk ratusan model. openrouter.ai/keys'),
  ProviderPreset('openai', 'OpenAI', 'https://api.openai.com/v1', 'gpt-4o-mini',
      hint: 'platform.openai.com/api-keys'),
  ProviderPreset('ollama', 'Ollama (lokal)', 'http://10.0.2.2:11434/v1',
      'llama3.1',
      needsKey: false,
      hint: 'Server Ollama di LAN. Emulator Android: 10.0.2.2'),
  ProviderPreset('lmstudio', 'LM Studio (lokal)', 'http://10.0.2.2:1234/v1',
      'local-model',
      needsKey: false, hint: 'Server LM Studio di LAN'),
  ProviderPreset('custom', 'Kustom (OpenAI-compatible)', 'https://', '',
      hint: 'Endpoint apa pun yang melayani /chat/completions'),
];

/// Connection modes. `local` is the default (on-device agent).
enum ConnectionMode { local, gateway, server, demo }

extension ConnectionModeX on ConnectionMode {
  String get label => switch (this) {
        ConnectionMode.local => 'Mandiri (di perangkat)',
        ConnectionMode.gateway => 'Gateway jarak jauh',
        ConnectionMode.server => 'Server kantor (Next.js)',
        ConnectionMode.demo => 'Demo offline',
      };
  String get short => switch (this) {
        ConnectionMode.local => 'Mandiri',
        ConnectionMode.gateway => 'Gateway',
        ConnectionMode.server => 'Server',
        ConnectionMode.demo => 'Demo',
      };
}
