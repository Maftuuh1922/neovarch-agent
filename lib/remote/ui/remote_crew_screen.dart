// Crew on the phone (Crew tab, first segment): write a goal, the PC's main
// agent proposes a team, approve it, watch the pixel room work and answer
// approvals. "Lanjutan" (third segment) edits the open crew by hand and keeps
// the old Kantor and Perusahaan views one tap away.
import 'dart:async';

import 'package:flutter/cupertino.dart' show CupertinoIcons;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/legacy.dart' show StateProvider;
import 'package:shared_preferences/shared_preferences.dart';

import '../../theme/neovarch_mobile_theme.dart';
import '../../ui/widgets/common.dart' show toast;
import '../crew_models.dart';
import '../home_widget.dart' show remoteLaunchAction;
import '../l10n/strings.dart';
import '../remote_controller.dart';
import 'crew_pixel.dart';
import 'nv_widgets.dart';
import 'remote_company_screen.dart';
import 'remote_office_screen.dart';

const crewIntroKey = 'nv.crew.intro.seen';

/// The crew both segments (Crew and Lanjutan) work on; survives switching segments.
final crewOpenProvider = StateProvider<Crew?>((ref) => null);

String crewErrorText(Object e) {
  final s = '$e';
  if (s.contains('-32601') || s.contains('not implemented')) return tr('PC belum mendukung Crew. Perbarui Neovarch di PC.');
  return s.replaceFirst(RegExp(r'^(RpcError|Exception)[^:]*:\s*'), '');
}

/// The pixel building (every member in a desk bay acting out their status) and a roster under it.
class CrewRoomGrid extends StatelessWidget {
  const CrewRoomGrid({super.key, required this.crew});
  final Crew crew;

  String? _bubble(CrewMember m) {
    if (crew.status == 'proposed') return m.role;
    if (m.status == 'working') {
      if (m.activity.isNotEmpty) return m.activity;
      for (final t in crew.tasks) {
        if (t.status == 'running' && t.memberId == m.id) return t.title;
      }
      return null;
    }
    if (m.status == 'waiting') return m.approval?.command ?? tr(crewMemberStatusLabel['waiting'] ?? 'waiting');
    if (m.status == 'done' || m.status == 'error') return tr(crewMemberStatusLabel[m.status] ?? m.status);
    return null;
  }

  @override
  Widget build(BuildContext context) => Container(
    key: const ValueKey('crew-room'),
    padding: const EdgeInsets.all(8),
    decoration: BoxDecoration(
      color: NV.raised,
      borderRadius: NV.card,
      border: Border.all(color: NV.border),
    ),
    child: LayoutBuilder(
      builder: (context, c) {
        final w = (c.maxWidth - 8) / 2;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            ClipRRect(
              borderRadius: BorderRadius.circular(10),
              child: Center(
                child: CrewScene(
                  crewStatus: crew.status,
                  accent: NV.red,
                  label: tr('Gedung crew: tiap anggota di mejanya'),
                  members: [
                    for (final m in crew.members)
                      CrewSceneMember(id: m.id, name: m.name, avatar: m.avatar, status: m.status, bubble: _bubble(m), manager: crew.manager == m.id),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final m in crew.members)
                  Container(
                    key: ValueKey('crew-seat-${m.id}'),
                    width: w,
                    padding: const EdgeInsets.fromLTRB(8, 6, 8, 6),
                    decoration: BoxDecoration(
                      color: NV.surface,
                      borderRadius: BorderRadius.circular(10),
                      border: Border.all(
                        color: m.status == 'working'
                            ? NV.red
                            : m.status == 'waiting'
                            ? const Color(0xFFF2B134)
                            : NV.border,
                      ),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Flexible(
                              child: Text(
                                m.name,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: TextStyle(color: NV.text, fontWeight: FontWeight.w600, fontSize: 13.5),
                              ),
                            ),
                            if (crew.manager == m.id)
                              Padding(
                                padding: const EdgeInsets.only(left: 4),
                                child: NvPill(tr('Manajer'), color: NV.red),
                              ),
                          ],
                        ),
                        Text(
                          m.role,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(color: NV.muted, fontSize: 12),
                        ),
                        Text(
                          tr(crewMemberStatusLabel[m.status] ?? m.status) + (m.activity.isEmpty ? '' : ' · ${m.activity}'),
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(color: m.status == 'working' ? NV.redInk : NV.muted, fontSize: 11.5),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
          ],
        );
      },
    ),
  );
}

class RemoteCrewScreen extends ConsumerStatefulWidget {
  const RemoteCrewScreen({super.key, this.onOpenAdvanced});
  final VoidCallback? onOpenAdvanced;
  @override
  ConsumerState<RemoteCrewScreen> createState() => _RemoteCrewScreenState();
}

class _RemoteCrewScreenState extends ConsumerState<RemoteCrewScreen> {
  final goal = TextEditingController();
  List<CrewSummary> history = const [];
  bool busy = false;
  bool consent = false;
  bool? introSeen;
  String? error;
  int _rev = -1;

  CrewClient? get _client {
    final api = ref.read(remoteProvider).crewApi;
    return api == null ? null : CrewClient(api);
  }

  @override
  void initState() {
    super.initState();
    SharedPreferences.getInstance().then((p) {
      if (mounted) setState(() => introSeen = p.getBool(crewIntroKey) ?? false);
    });
    WidgetsBinding.instance.addPostFrameCallback((_) => unawaited(load()));
  }

  @override
  void dispose() {
    goal.dispose();
    super.dispose();
  }

  Future<void> load() async {
    final c = _client;
    if (c == null) return;
    try {
      final list = await c.list();
      if (!mounted) return;
      setState(() {
        history = list;
        error = null;
      });
      final open = ref.read(crewOpenProvider);
      final running = list.where((x) => x.status == 'running').firstOrNull;
      if (open == null && running != null) await _open(running.id);
    } catch (e) {
      if (mounted) setState(() => error = crewErrorText(e));
    }
  }

  Future<void> _run(Future<Crew?> Function(CrewClient c) fn) async {
    final c = _client;
    if (c == null) return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final crew = await fn(c);
      if (!mounted) return;
      ref.read(crewOpenProvider.notifier).state = crew;
      consent = false;
      unawaited(load());
    } catch (e) {
      if (mounted) {
        setState(() => error = crewErrorText(e));
        toast(context, crewErrorText(e));
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> _open(String id) => _run((c) => c.get(id));

  void _applyPush(Map<String, dynamic>? p) {
    if (p == null) return;
    final open = ref.read(crewOpenProvider);
    if (p['deleted'] == true) {
      if (open?.id == p['id']) ref.read(crewOpenProvider.notifier).state = null;
      unawaited(load());
      return;
    }
    final crew = Crew.fromJson(p);
    if (open?.id == crew.id) ref.read(crewOpenProvider.notifier).state = crew;
    if (crew.finished || !history.any((h) => h.id == crew.id)) unawaited(load());
  }

  Future<void> _finishIntro() async {
    setState(() => introSeen = true);
    (await SharedPreferences.getInstance()).setBool(crewIntroKey, true);
  }

  @override
  Widget build(BuildContext context) {
    final rev = ref.watch(remoteProvider.select((r) => r.crewRevision));
    if (rev != _rev) {
      final first = _rev == -1;
      _rev = rev;
      if (!first) WidgetsBinding.instance.addPostFrameCallback((_) => _applyPush(ref.read(remoteProvider).crewPush));
    }
    final crew = ref.watch(crewOpenProvider);
    final pad = MediaQuery.paddingOf(context).bottom + 110;
    return ListView(
      key: const ValueKey('crew-screen'),
      padding: EdgeInsets.fromLTRB(16, 4, 16, pad),
      children: [
        const NvHeader(kicker: 'crew · tim agen', title: 'Crew', inset: 4),
        if (introSeen == false) _intro(),
        if (error != null) Padding(padding: const EdgeInsets.only(bottom: 10), child: NvNotice(error!)),
        if (crew == null) ..._form() else ..._crew(crew),
      ],
    );
  }

  Widget _intro() => NvPanel(
    key: const ValueKey('crew-intro'),
    margin: const EdgeInsets.only(bottom: 12),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            for (final (a, s) in const [(1, 'idle'), (4, 'working'), (9, 'done')])
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 3),
                child: CrewStation(avatar: a, status: s, width: 78, chair: NV.border, accent: NV.red, animate: false),
              ),
          ],
        ),
        const SizedBox(height: 10),
        Text(tr('Kenalan dengan Crew'), style: NV.display(size: 22)),
        const SizedBox(height: 8),
        for (final (i, s) in [
          (1, 'Tulis tujuan, mis. “bandingkan 3 laptop di bawah 15 juta”.'),
          (2, 'Agen utama mengusulkan anggota, tugas dan alurnya.'),
          (3, 'Kamu setujui, lalu lihat crew bekerja.'),
        ])
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                NvPill('$i'),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(tr(s), style: TextStyle(color: NV.text, fontSize: 14)),
                ),
              ],
            ),
          ),
        const SizedBox(height: 4),
        Row(
          children: [
            FilledButton(key: const ValueKey('crew-intro-ok'), onPressed: _finishIntro, child: Text(tr('Mengerti'))),
            const SizedBox(width: 8),
            TextButton(onPressed: _finishIntro, child: Text(tr('Lewati'))),
          ],
        ),
      ],
    ),
  );

  List<Widget> _form() => [
    NvPanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          TextField(
            key: const ValueKey('crew-goal'),
            controller: goal,
            minLines: 2,
            maxLines: 4,
            onChanged: (_) => setState(() {}),
            decoration: InputDecoration(labelText: tr('Tujuan'), hintText: tr('Apa yang harus diselesaikan crew?')),
          ),
          const SizedBox(height: 10),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              key: const ValueKey('crew-propose'),
              onPressed: busy || goal.text.trim().isEmpty ? null : () => _run((c) => c.propose(goal.text.trim())),
              child: Text(tr(busy ? 'Menyusun crew…' : 'Susun crew')),
            ),
          ),
          const SizedBox(height: 12),
          Text(tr('Atau mulai dari template'), style: NV.monoLabel()),
          const SizedBox(height: 6),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              for (final t in crewTemplates)
                ActionChip(
                  key: ValueKey('crew-template-$t'),
                  label: Text(tr(crewTemplateLabel[t]!)),
                  onPressed: busy || goal.text.trim().isEmpty ? null : () => _run((c) => c.propose(goal.text.trim(), template: t)),
                ),
            ],
          ),
          const SizedBox(height: 8),
          Text(tr('Hanya model gratis'), style: NV.monoLabel(size: 9.5)),
        ],
      ),
    ),
    if (history.isNotEmpty) ...[
      const NvSection('Riwayat', padding: EdgeInsets.fromLTRB(4, 20, 4, 8)),
      NvList(
        margin: EdgeInsets.zero,
        children: [
          for (final h in history.take(6))
            NvRow(
              key: ValueKey('crew-history-${h.id}'),
              icon: CupertinoIcons.person_3_fill,
              title: h.title,
              subtitle: '${tr(crewTemplateLabel[h.template] ?? h.template)} · ${tr('{done}/{total} tugas', {'done': h.done, 'total': h.tasks})}',
              trailing: NvPill(tr(crewStatusLabel[h.status] ?? h.status), color: h.status == 'running' ? NV.red : null),
              onTap: () => _open(h.id),
            ),
        ],
      ),
    ],
  ];

  List<Widget> _crew(Crew crew) {
    final needsConsent = crew.sideEffects.isNotEmpty && !(crew.finished && crew.allowSideEffects);
    final canStart = !busy && (crew.sideEffects.isEmpty || consent || (crew.finished && crew.allowSideEffects));
    return [
      Text(crew.goal, style: TextStyle(color: NV.muted, fontSize: 12.5)),
      const SizedBox(height: 2),
      Text(crew.title, key: const ValueKey('crew-title'), style: NV.display(size: 22)),
      const SizedBox(height: 6),
      Wrap(
        spacing: 6,
        runSpacing: 6,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          NvPill(tr(crewStatusLabel[crew.status] ?? crew.status), color: crew.running ? NV.red : null),
          NvPill(tr(crew.designedBy == 'agent' ? 'Disusun agen utama' : 'Dari template')),
          NvPill(tr(crew.process == 'hierarchical' ? 'Dipimpin manajer' : 'Berurutan')),
          if (!crew.proposed) NvPill(tr('{done}/{total} tugas', {'done': crew.doneCount, 'total': crew.tasks.length})),
        ],
      ),
      const SizedBox(height: 12),
      CrewRoomGrid(crew: crew),
      for (final m in crew.members.where((m) => m.status == 'waiting' && m.approval != null))
        NvApprovalCard(
          key: ValueKey('crew-approval-${m.id}'),
          margin: const EdgeInsets.only(top: 10),
          origin: m.name,
          command: m.approval!.command,
          description: tr('{name} minta izin', {'name': m.name}),
          choices: const ['once', 'deny'],
          onChoice: (choice) async {
            final c = _client;
            if (c == null) return;
            try {
              await c.answer(m, choice);
            } catch (e) {
              if (mounted) toast(context, crewErrorText(e));
            }
          },
        ),
      const NvSection('Tugas', padding: EdgeInsets.fromLTRB(4, 18, 4, 8)),
      NvPanel(
        padding: const EdgeInsets.fromLTRB(14, 10, 14, 10),
        child: Column(
          children: [
            for (final (i, t) in crew.tasks.indexed)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 5),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    NvPill(
                      '${i + 1}',
                      color: t.status == 'done'
                          ? const Color(0xFF2F9E74)
                          : t.status == 'running'
                          ? NV.red
                          : null,
                      filled: t.status == 'done',
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(t.title, style: TextStyle(color: NV.text, fontSize: 14)),
                          Text(
                            '${crew.member(t.memberId)?.name ?? '—'} · ${crew.member(t.memberId)?.role ?? ''}',
                            style: TextStyle(color: NV.muted, fontSize: 12),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
          ],
        ),
      ),
      if (crew.proposed) ...[
        const NvSection('Anggota', padding: EdgeInsets.fromLTRB(4, 18, 4, 8)),
        NvPanel(
          padding: const EdgeInsets.fromLTRB(14, 10, 14, 10),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              for (final m in crew.members)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 5),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '${m.name} · ${m.role}',
                        style: TextStyle(color: NV.text, fontWeight: FontWeight.w600, fontSize: 13.5),
                      ),
                      if (m.goal.isNotEmpty) Text(m.goal, style: TextStyle(color: NV.muted, fontSize: 12)),
                      const SizedBox(height: 4),
                      Wrap(
                        spacing: 4,
                        runSpacing: 4,
                        children: [
                          if (m.tools.isEmpty) NvPill(tr('Tanpa alat')),
                          for (final t in m.tools)
                            NvPill(
                              tr(crewToolLabel[t] ?? t),
                              color: crewSideEffectTools.contains(t) ? (NV.palette.dark ? const Color(0xFFE0A63A) : const Color(0xFF7A4E00)) : null,
                            ),
                          NvPill(m.model.isEmpty ? tr('Bawaan gratis') : m.model),
                        ],
                      ),
                    ],
                  ),
                ),
            ],
          ),
        ),
      ],
      if (crew.finished && (crew.finalOutput.isNotEmpty || crew.error.isNotEmpty)) ...[
        const NvSection('Hasil', padding: EdgeInsets.fromLTRB(4, 18, 4, 8)),
        NvPanel(
          key: const ValueKey('crew-result'),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (crew.error.isNotEmpty) Text(crew.error, style: TextStyle(color: NV.redInk, fontSize: 13)),
              if (crew.finalOutput.isNotEmpty) SelectableText(crew.finalOutput, style: TextStyle(color: NV.text, fontSize: 13.5, height: 1.45)),
            ],
          ),
        ),
      ],
      if ((crew.proposed || crew.finished) && needsConsent)
        Padding(
          padding: const EdgeInsets.only(top: 12),
          child: CheckboxListTile(
            key: const ValueKey('crew-consent'),
            contentPadding: EdgeInsets.zero,
            controlAffinity: ListTileControlAffinity.leading,
            value: consent,
            onChanged: (v) => setState(() => consent = v ?? false),
            title: Text(tr('Crew ini bisa mengubah file atau menjalankan perintah.'), style: TextStyle(color: NV.text, fontSize: 13.5)),
            subtitle: Text(tr('Izinkan (perintah berisiko tetap minta izinmu)'), style: TextStyle(color: NV.muted, fontSize: 12)),
          ),
        ),
      const SizedBox(height: 12),
      Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          if (crew.proposed || crew.finished)
            FilledButton(
              key: const ValueKey('crew-approve'),
              onPressed: canStart ? () => _run((c) => c.approve(crew.id, allowSideEffects: crew.sideEffects.isNotEmpty)) : null,
              child: Text(tr(crew.proposed ? 'Setujui & mulai' : 'Jalankan lagi')),
            ),
          if (crew.running)
            OutlinedButton(key: const ValueKey('crew-stop'), onPressed: busy ? null : () => _run((c) => c.cancel(crew.id)), child: Text(tr('Hentikan'))),
          if (!crew.running && widget.onOpenAdvanced != null)
            OutlinedButton(key: const ValueKey('crew-edit'), onPressed: widget.onOpenAdvanced, child: Text(tr('Ubah di Lanjutan'))),
          if (!crew.running)
            TextButton(
              key: const ValueKey('crew-close'),
              onPressed: () {
                ref.read(crewOpenProvider.notifier).state = null;
                unawaited(load());
              },
              child: Text(tr(crew.proposed ? 'Nanti saja' : 'Crew baru')),
            ),
        ],
      ),
    ];
  }
}

/// "Lanjutan": hand-edit the open crew (role, goal, tools, model, tasks, flow),
/// then the old Kantor and Perusahaan views.
class RemoteCrewAdvanced extends ConsumerStatefulWidget {
  const RemoteCrewAdvanced({super.key, required this.onOpenChat, required this.onOpenApprovals, this.companySupported = true});
  final VoidCallback onOpenChat;
  final VoidCallback onOpenApprovals;
  final bool companySupported;
  @override
  ConsumerState<RemoteCrewAdvanced> createState() => _RemoteCrewAdvancedState();
}

class _RemoteCrewAdvancedState extends ConsumerState<RemoteCrewAdvanced> {
  String? editing; // id of the crew the draft belongs to
  late List<CrewMember> members;
  late List<CrewTask> tasks;
  String process = 'sequential';
  String? manager;
  bool busy = false;

  void _reset(Crew c) {
    editing = '${c.id}:${c.status}';
    members = [...c.members];
    tasks = [...c.tasks];
    process = c.process;
    manager = c.manager;
  }

  Future<void> _save(Crew crew) async {
    final api = ref.read(remoteProvider).crewApi;
    if (api == null) return;
    setState(() => busy = true);
    try {
      final saved = await CrewClient(api).update(crew.id, process: process, manager: manager, members: members, tasks: tasks);
      if (!mounted) return;
      ref.read(crewOpenProvider.notifier).state = saved;
      toast(context, tr('Tersimpan'));
    } catch (e) {
      if (mounted) toast(context, crewErrorText(e));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  void _push(Widget page) => Navigator.of(context).push(
    MaterialPageRoute(
      builder: (_) => Scaffold(backgroundColor: NV.bg, body: page),
    ),
  );

  // Home-screen widget "Agen" row (agent:<id>): the old Kantor view opens that agent's sheet.
  bool _officeOpen = false;
  void _onLaunchAction() {
    final v = remoteLaunchAction.value;
    if (!mounted || _officeOpen || v == null || !v.startsWith('agent:')) return;
    _officeOpen = true;
    Navigator.of(context)
        .push(
          MaterialPageRoute(
            builder: (_) => Scaffold(
              backgroundColor: NV.bg,
              body: RemoteOfficeScreen(onOpenChat: widget.onOpenChat, onOpenApprovals: widget.onOpenApprovals),
            ),
          ),
        )
        .whenComplete(() => _officeOpen = false);
  }

  @override
  void initState() {
    super.initState();
    remoteLaunchAction.addListener(_onLaunchAction);
  }

  @override
  void dispose() {
    remoteLaunchAction.removeListener(_onLaunchAction);
    super.dispose();
  }

  Widget _field(String key, String label, String value, ValueChanged<String> onChanged, {String? hint}) => Padding(
    padding: const EdgeInsets.only(bottom: 8),
    child: TextFormField(
      key: ValueKey(key),
      initialValue: value,
      onChanged: onChanged,
      decoration: InputDecoration(labelText: tr(label), hintText: hint == null ? null : tr(hint), isDense: true),
    ),
  );

  @override
  Widget build(BuildContext context) {
    final crew = ref.watch(crewOpenProvider);
    final pad = MediaQuery.paddingOf(context).bottom + 110;
    final editable = crew != null && !crew.running;
    if (editable && editing != '${crew.id}:${crew.status}') _reset(crew);
    return ListView(
      key: const ValueKey('crew-advanced'),
      padding: EdgeInsets.fromLTRB(16, 4, 16, pad),
      children: [
        const NvHeader(kicker: 'crew · lanjutan', title: 'Lanjutan', inset: 4),
        if (!editable)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Text(tr('Pilih usulan crew dulu, lalu ubah di sini.'), style: TextStyle(color: NV.muted, fontSize: 14)),
          )
        else ...[
          NvPanel(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  crew.title,
                  style: TextStyle(color: NV.text, fontWeight: FontWeight.w600, fontSize: 15),
                ),
                const SizedBox(height: 8),
                DropdownButtonFormField<String>(
                  key: const ValueKey('crew-flow'),
                  isExpanded: true,
                  initialValue: process,
                  decoration: InputDecoration(labelText: tr('Alur'), isDense: true),
                  items: [
                    DropdownMenuItem(value: 'sequential', child: Text(tr('Berurutan'))),
                    DropdownMenuItem(value: 'hierarchical', child: Text(tr('Dipimpin manajer'))),
                  ],
                  onChanged: (v) => setState(() => process = v ?? 'sequential'),
                ),
                if (process == 'hierarchical') ...[
                  const SizedBox(height: 8),
                  DropdownButtonFormField<String>(
                    key: const ValueKey('crew-manager'),
                    isExpanded: true,
                    initialValue: members.any((m) => m.id == manager) ? manager : members.first.id,
                    decoration: InputDecoration(labelText: tr('Manajer'), isDense: true),
                    items: [for (final m in members) DropdownMenuItem(value: m.id, child: Text(m.name.isEmpty ? m.role : m.name))],
                    onChanged: (v) => setState(() => manager = v),
                  ),
                ],
              ],
            ),
          ),
          const NvSection('Anggota', padding: EdgeInsets.fromLTRB(4, 18, 4, 8)),
          for (final (i, m) in members.indexed)
            NvPanel(
              key: ValueKey('crew-edit-${m.id}'),
              margin: const EdgeInsets.only(bottom: 8),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _field('crew-${m.id}-name', 'Nama', m.name, (v) => members[i] = members[i].copyWith(name: v)),
                  _field('crew-${m.id}-role', 'Peran', m.role, (v) => members[i] = members[i].copyWith(role: v)),
                  _field('crew-${m.id}-goal', 'Tujuan', m.goal, (v) => members[i] = members[i].copyWith(goal: v)),
                  _field(
                    'crew-${m.id}-model',
                    'Model (hanya gratis)',
                    m.model,
                    (v) => members[i] = members[i].copyWith(model: v.trim()),
                    hint: 'Bawaan gratis',
                  ),
                  Wrap(
                    spacing: 6,
                    runSpacing: 6,
                    children: [
                      for (final g in crewToolGroups)
                        FilterChip(
                          key: ValueKey('crew-${m.id}-tool-$g'),
                          label: Text(tr(crewToolLabel[g]!)),
                          selected: members[i].tools.contains(g),
                          onSelected: (on) => setState(
                            () => members[i] = members[i].copyWith(tools: on ? [...members[i].tools, g] : members[i].tools.where((x) => x != g).toList()),
                          ),
                        ),
                    ],
                  ),
                ],
              ),
            ),
          const NvSection('Tugas', padding: EdgeInsets.fromLTRB(4, 18, 4, 8)),
          for (final (i, t) in tasks.indexed)
            NvPanel(
              key: ValueKey('crew-edit-${t.id}'),
              margin: const EdgeInsets.only(bottom: 8),
              child: Column(
                children: [
                  _field('crew-${t.id}-title', 'Tugas', t.title, (v) => tasks[i] = tasks[i].copyWith(title: v)),
                  _field('crew-${t.id}-desc', 'Deskripsi', t.description, (v) => tasks[i] = tasks[i].copyWith(description: v)),
                  DropdownButtonFormField<String>(
                    key: ValueKey('crew-${t.id}-who'),
                    isExpanded: true,
                    initialValue: members.any((m) => m.id == t.memberId) ? t.memberId : members.first.id,
                    decoration: InputDecoration(labelText: tr('Dikerjakan'), isDense: true),
                    items: [for (final m in members) DropdownMenuItem(value: m.id, child: Text(m.name.isEmpty ? m.role : m.name))],
                    onChanged: (v) => tasks[i] = tasks[i].copyWith(memberId: v),
                  ),
                ],
              ),
            ),
          const SizedBox(height: 4),
          FilledButton(key: const ValueKey('crew-save'), onPressed: busy ? null : () => _save(crew), child: Text(tr('Simpan perubahan'))),
        ],
        const NvSection('Kantor & perusahaan lama', padding: EdgeInsets.fromLTRB(4, 22, 4, 8)),
        NvList(
          margin: EdgeInsets.zero,
          children: [
            NvRow(
              key: const ValueKey('crew-legacy-office'),
              icon: CupertinoIcons.building_2_fill,
              title: tr('Kantor'),
              subtitle: tr('Tampilan Kantor sebelumnya (3D, pegawai, aktivitas).'),
              onTap: () => _push(RemoteOfficeScreen(onOpenChat: widget.onOpenChat, onOpenApprovals: widget.onOpenApprovals)),
            ),
            if (widget.companySupported)
              NvRow(
                key: const ValueKey('crew-legacy-company'),
                icon: CupertinoIcons.briefcase_fill,
                title: tr('Perusahaan'),
                subtitle: tr('Organisasi, tiket, persetujuan, biaya.'),
                onTap: () => _push(const RemoteCompanyScreen()),
              ),
          ],
        ),
      ],
    );
  }
}
