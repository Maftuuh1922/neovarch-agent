// Kantor → Perusahaan: the PC's company of agents, controlled from the phone.
// Org chart (hire, edit, budgets, wake / pause / resume / stop), tickets
// (move, assign, comment, new), approvals (approve / reject), costs (company
// and per-agent budgets) and Rencana (mission, goals, projects, routines).
// Everything goes through the core's `company.*` RPCs; the PC pushes
// `company.changed` and this re-reads. Offline PC, network errors and older
// cores without the RPCs get an Indonesian notice with "Coba lagi".
import 'dart:async';

import 'package:flutter/cupertino.dart' show CupertinoIcons;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../theme/neovarch_mobile_theme.dart';
import '../../ui/widgets/common.dart' show toast;
import '../company_models.dart';
import '../remote_controller.dart';
import 'nv_widgets.dart';
import 'remote_company_forms.dart';

/// Sub-views of the Perusahaan screen.
const companySegOrg = 0, companySegTickets = 1, companySegApprovals = 2, companySegCosts = 3, companySegPlan = 4;

class RemoteCompanyScreen extends ConsumerStatefulWidget {
  const RemoteCompanyScreen({super.key, this.initialSegment = companySegOrg});
  final int initialSegment;
  @override
  ConsumerState<RemoteCompanyScreen> createState() => _RemoteCompanyScreenState();
}

class _RemoteCompanyScreenState extends ConsumerState<RemoteCompanyScreen> {
  late int seg = widget.initialSegment;
  CompanySnapshot? snap;
  List<CompanyTicket> tickets = const [];
  List<CompanyApproval> approvals = const [];
  CompanyCosts? costs;
  String? error;
  bool unsupported = false;
  bool loading = false;
  bool busy = false;
  int _rev = -1;
  bool _wasConnected = false;

  CompanyClient? get _client {
    final api = ref.read(remoteProvider).companyApi;
    return api == null ? null : CompanyClient(api);
  }

  Future<void> load() async {
    final c = _client;
    if (c == null || !ref.read(remoteProvider).connected) return;
    if (mounted) setState(() => loading = true);
    try {
      final s = await c.snapshot();
      final results = s.exists ? await Future.wait([c.tickets(), c.approvals(), c.costs()]) : const [];
      if (!mounted) return;
      setState(() {
        snap = s;
        if (s.exists) {
          tickets = results[0] as List<CompanyTicket>;
          approvals = results[1] as List<CompanyApproval>;
          costs = results[2] as CompanyCosts;
        }
        error = null;
        unsupported = false;
      });
    } catch (e) {
      if (mounted) {
        setState(() {
          error = companyErrorText(e);
          unsupported = isCompanyUnsupported(e);
        });
      }
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  /// "Coba lagi": reconnects first when the PC dropped, then re-reads.
  Future<void> retry() async {
    final r = ref.read(remoteProvider);
    if (!r.connected) {
      await r.reconnect();
      return; // connecting again triggers a load
    }
    if (unsupported) unawaited(r.probeCompany());
    await load();
  }

  /// Runs one action, toasts its result or error, then re-reads.
  Future<void> act(Future<Object?> Function(CompanyClient c) fn, {String? done, String Function(Object? result)? doneFor}) async {
    final c = _client;
    if (c == null || busy) return;
    if (!ref.read(remoteProvider).connected) {
      toast(context, 'Belum terhubung ke PC.');
      return;
    }
    setState(() => busy = true);
    try {
      final res = await fn(c);
      final msg = doneFor != null ? doneFor(res) : done;
      if (mounted && msg != null) toast(context, msg);
    } catch (e) {
      if (mounted) toast(context, companyErrorText(e));
    } finally {
      if (mounted) setState(() => busy = false);
    }
    await load();
  }

  Widget _retryButton({Key? key}) => TextButton(key: key ?? const ValueKey('company-retry'), onPressed: loading ? null : retry, child: const Text('Coba lagi'));

  @override
  Widget build(BuildContext context) {
    final r = ref.watch(remoteProvider);
    final reconnected = r.connected && !_wasConnected;
    _wasConnected = r.connected;
    if (r.companyRevision != _rev || reconnected) {
      _rev = r.companyRevision;
      scheduleMicrotask(load);
    }
    final s = snap;
    final online = r.connected;
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: RefreshIndicator(
        onRefresh: online ? load : retry,
        child: ListView(
          key: const ValueKey('company-list'),
          padding: EdgeInsets.only(bottom: 120 + MediaQuery.paddingOf(context).bottom),
          children: [
            NvHeader(
              kicker: 'perusahaan · ${r.desktop?.name ?? 'pc'}',
              title: s?.exists == true ? s!.name : 'Perusahaan',
              status: Text(
                !online
                    ? 'tidak terhubung ke PC'
                    : s == null
                        ? (error != null ? 'gagal memuat' : 'memuat…')
                        : !s.exists
                            ? 'belum dibuat di PC'
                            : '${s.agents.length} pegawai · ${s.pendingApprovals} menunggu persetujuan',
                style: NV.monoLabel(size: 10).copyWith(letterSpacing: 0.4),
              ),
              actions: [NvIconButton(tooltip: 'Segarkan', icon: CupertinoIcons.arrow_clockwise, onPressed: online ? load : retry)],
            ),
            // ---- not loaded: offline / unsupported / failed / loading
            if (s == null && !online)
              NvEmpty(
                key: const ValueKey('company-offline'),
                kicker: 'perusahaan',
                title: 'PC tidak terhubung',
                body: 'Perusahaan berjalan di PC. Sambungkan HP ke PC (pindai QR di PC sekali) untuk melihat dan mengaturnya.',
                action: _retryButton(),
              )
            else if (s == null && error != null)
              NvEmpty(
                key: const ValueKey('company-error'),
                kicker: 'perusahaan',
                title: unsupported ? 'Belum didukung PC' : 'Gagal memuat perusahaan',
                body: error,
                action: _retryButton(),
              )
            else if (s == null)
              const NvEmpty(key: ValueKey('company-loading'), title: 'Memuat perusahaan…'),
            // ---- loaded, but the latest read failed or the PC dropped
            if (s != null && (!online || error != null))
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                child: NvNotice(
                  !online ? 'Terputus dari PC. Yang tampil data terakhir.' : error!,
                  key: const ValueKey('company-stale'),
                  action: _retryButton(),
                ),
              ),
            if (s != null && !s.exists)
              const NvEmpty(
                key: ValueKey('company-empty'),
                kicker: 'kantor',
                title: 'Kantor masih kosong',
                body: 'Susunannya Organisasi → Agency → Orang. Minta Neovarch Agent di Chat, misalnya “buat organisasi '
                    'Neovarch Labs dengan agency Kreatif, lalu rekrut Sinta sebagai copywriter”. '
                    'Tidak ada pegawai yang berjalan sendiri sampai kamu menyalakan “Jalan otomatis”.',
              ),
            if (s != null && s.exists) ...[
              if (s.mission.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
                  child: Text(s.mission, style: TextStyle(fontSize: 13, height: 1.4, color: NV.muted)),
                ),
              NvPanel(
                margin: const EdgeInsets.fromLTRB(16, 0, 16, 10),
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 4),
                child: SwitchListTile(
                  key: const ValueKey('company-autorun'),
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Jalan otomatis'),
                  subtitle: Text('Agen bangun sendiri saat ada tiket, komentar, atau jadwal', style: TextStyle(fontSize: 12, color: NV.muted)),
                  value: s.autorun,
                  onChanged: busy || !online ? null : (v) => act((c) => c.setAutorun(v)),
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 4),
                child: NvGlassSegmented(
                  key: const ValueKey('company-segments'),
                  labels: ['Organisasi', 'Tiket', 'Setujui${approvals.isEmpty ? '' : ' (${approvals.length})'}', 'Biaya', 'Rencana'],
                  index: seg,
                  onChanged: (i) => setState(() => seg = i),
                ),
              ),
              ...switch (seg) {
                companySegTickets => _tickets(s),
                companySegApprovals => _approvals(),
                companySegCosts => _costs(s),
                companySegPlan => _plan(s),
                _ => _org(s),
              },
            ],
          ],
        ),
      ),
    );
  }

  bool get _locked => busy || !ref.read(remoteProvider).connected;

  // ------------------------------------------------------------------ org --
  List<Widget> _org(CompanySnapshot s) => [
        NvSection('organisasi',
            count: s.agents.length,
            trailing: TextButton.icon(
              key: const ValueKey('company-hire'),
              onPressed: _locked ? null : () => _hire(s),
              icon: const Icon(CupertinoIcons.person_add, size: 16),
              label: const Text('Rekrut'),
            )),
        for (final (a, depth) in s.orgTree)
          NvPanel(
            key: ValueKey('company-agent-${a.id}'),
            margin: EdgeInsets.fromLTRB(16.0 + depth * 18, 0, 16, 8),
            padding: const EdgeInsets.fromLTRB(14, 12, 14, 8),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                NvDot(s.isRunning(a) ? NV.red : (a.paused ? NV.muted : NV.faint)),
                const SizedBox(width: 8),
                Expanded(
                  child: Text.rich(TextSpan(children: [
                    TextSpan(text: a.name, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15)),
                    TextSpan(text: '  ${a.title}', style: TextStyle(fontSize: 12, color: NV.muted)),
                  ])),
                ),
                NvPill(s.isRunning(a) ? 'bekerja' : (a.pauseReason == 'budget' && a.status == 'paused' ? 'dijeda · anggaran' : a.statusLabel),
                    color: s.isRunning(a) ? NV.red : null),
              ]),
              const SizedBox(height: 6),
              Text(
                a.status == 'pending_approval'
                    ? 'Rekrutmen menunggu persetujuanmu di Setujui'
                    : a.ticketKey != null
                        ? '${a.ticketKey} · ${a.ticketTitle} (${ticketStatusLabel[a.ticketStatus] ?? a.ticketStatus})'
                        : 'Tidak memegang tiket',
                style: TextStyle(fontSize: 12.5, color: NV.muted),
              ),
              if (a.budget.pct != null) ...[
                const SizedBox(height: 6),
                CompanyMeter(pct: a.budget.pct!, level: a.budget.level),
              ],
              Wrap(spacing: 4, children: [
                if (!s.isRunning(a) && !a.paused && a.status != 'pending_approval')
                  TextButton(onPressed: _locked ? null : () => act((c) => c.wake(a.id), done: '${a.name} dibangunkan'), child: const Text('Bangunkan')),
                if (s.isRunning(a))
                  TextButton(onPressed: _locked ? null : () => act((c) => c.stop(a.id), done: '${a.name} dihentikan'), child: const Text('Hentikan')),
                if (a.paused)
                  TextButton(onPressed: _locked ? null : () => act((c) => c.resume(a.id), done: '${a.name} lanjut'), child: const Text('Lanjutkan'))
                else if (a.status != 'pending_approval')
                  TextButton(onPressed: _locked ? null : () => act((c) => c.pause(a.id), done: '${a.name} dijeda'), child: const Text('Jeda')),
                TextButton(
                  key: ValueKey('company-edit-agent-${a.id}'),
                  onPressed: _locked ? null : () => _editAgent(s, a),
                  child: const Text('Ubah'),
                ),
              ]),
            ]),
          ),
        if (s.agents.isEmpty) const NvEmpty(title: 'Belum ada pegawai', body: 'Ketuk Rekrut untuk menambah pegawai pertama.'),
      ];

  Future<void> _hire(CompanySnapshot s) async {
    final body = await showAgentForm(context, snap: s);
    if (body == null) return;
    await act((c) => c.saveAgent(body),
        doneFor: (a) => a is CompanyAgent && a.status == 'pending_approval'
            ? 'Rekrut ${a.name} menunggu persetujuan di Setujui'
            : '${body['name']} direkrut');
  }

  Future<void> _editAgent(CompanySnapshot s, CompanyAgent a) async {
    final body = await showAgentForm(context, snap: s, agent: a);
    if (body == null) return;
    if (body['terminate'] == true) {
      await act((c) => c.terminate(a.id), done: '${a.name} diberhentikan');
      return;
    }
    await act((c) => c.saveAgent(body), done: 'Profil ${a.name} disimpan');
  }

  // -------------------------------------------------------------- tickets --
  List<Widget> _tickets(CompanySnapshot s) => [
        NvSection('tiket', count: tickets.where((t) => t.status != 'cancelled').length, trailing: TextButton.icon(
          key: const ValueKey('company-new-ticket'),
          onPressed: _locked ? null : () => _newTicket(s),
          icon: const Icon(CupertinoIcons.add, size: 16),
          label: const Text('Baru'),
        )),
        for (final status in ticketStatusOrder)
          if (tickets.any((t) => t.status == status)) ...[
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 8, 20, 6),
              child: Text((ticketStatusLabel[status] ?? status).toUpperCase(), style: NV.monoLabel(color: NV.redInk)),
            ),
            for (final t in tickets.where((t) => t.status == status))
              NvPanel(
                key: ValueKey('company-ticket-${t.key}'),
                margin: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                padding: const EdgeInsets.all(12),
                onTap: () => _openTicket(s, t),
                child: Row(children: [
                  Text(t.key, style: NV.code(size: 11, color: NV.redInk)),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(t.title, maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 14)),
                      Text(
                        '${t.assigneeName ?? 'belum ditugaskan'}${t.locked ? ' · dikerjakan' : ''}${t.blockedBy > 0 ? ' · ${t.blockedBy} hambatan' : ''}',
                        style: TextStyle(fontSize: 11.5, color: NV.muted),
                      ),
                    ]),
                  ),
                  Icon(CupertinoIcons.chevron_right, size: 14, color: NV.faint),
                ]),
              ),
          ],
        if (tickets.isEmpty) const NvEmpty(title: 'Belum ada tiket', body: 'Buat tiket dan tugaskan ke pegawai.'),
      ];

  Future<void> _newTicket(CompanySnapshot s) async {
    final title = TextEditingController();
    int? assignee;
    final ok = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      showDragHandle: true,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setSheet) => Padding(
          padding: EdgeInsets.fromLTRB(20, 0, 20, 20 + MediaQuery.viewInsetsOf(ctx).bottom),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            const NvSheetTitle(kicker: 'perusahaan', title: 'Tiket baru'),
            TextField(key: const ValueKey('company-ticket-title'), controller: title, autofocus: true, decoration: const InputDecoration(hintText: 'Judul tiket')),
            const SizedBox(height: 12),
            DropdownButton<int?>(
              key: const ValueKey('company-ticket-assignee'),
              isExpanded: true,
              value: assignee,
              hint: const Text('Penanggung jawab'),
              items: [
                const DropdownMenuItem<int?>(value: null, child: Text('Tanpa penanggung jawab')),
                for (final a in s.agents.where((a) => a.status != 'pending_approval')) DropdownMenuItem<int?>(value: a.id, child: Text(a.name)),
              ],
              onChanged: (v) => setSheet(() => assignee = v),
            ),
            const SizedBox(height: 12),
            Align(
              alignment: Alignment.centerRight,
              child: FilledButton(key: const ValueKey('company-ticket-create'), onPressed: () => Navigator.pop(ctx, true), child: const Text('Buat')),
            ),
          ]),
        ),
      ),
    );
    if (ok == true && title.text.trim().isNotEmpty) {
      await act((c) => c.createTicket(title.text.trim(), assignee), done: 'Tiket dibuat');
    }
  }

  Future<void> _openTicket(CompanySnapshot s, CompanyTicket t) {
    final c = _client;
    if (c == null) return Future.value();
    return showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      showDragHandle: true,
      builder: (ctx) => _TicketSheet(client: c, ticket: t, snap: s, onChanged: load),
    );
  }

  // ------------------------------------------------------------ approvals --
  List<Widget> _approvals() => [
        NvSection('persetujuan', count: approvals.length),
        if (approvals.isEmpty) const NvEmpty(kicker: 'aman', title: 'Tidak ada yang menunggu', body: 'Rekrutmen, rencana, dan hasil kerja yang perlu kamu tinjau muncul di sini.'),
        for (final ap in approvals)
          NvPanel(
            key: ValueKey('company-approval-${ap.id}'),
            margin: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [NvPill(ap.kindLabel), const SizedBox(width: 8), if (ap.agentName != null) Text(ap.agentName!, style: TextStyle(fontSize: 12, color: NV.muted))]),
              const SizedBox(height: 8),
              Text(ap.title, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
              if (ap.detail.isNotEmpty) ...[const SizedBox(height: 6), Text(ap.detail, style: TextStyle(fontSize: 13, height: 1.4, color: NV.muted))],
              const SizedBox(height: 10),
              Row(mainAxisAlignment: MainAxisAlignment.end, children: [
                TextButton(onPressed: _locked ? null : () => act((c) => c.decide(ap.id, false), done: 'Ditolak'), child: const Text('Tolak')),
                const SizedBox(width: 6),
                FilledButton(onPressed: _locked ? null : () => act((c) => c.decide(ap.id, true), done: 'Disetujui'), child: const Text('Setujui')),
              ]),
            ]),
          ),
      ];

  // ---------------------------------------------------------------- costs --
  List<Widget> _costs(CompanySnapshot s) {
    final c = costs;
    if (c == null) return const [NvEmpty(title: 'Memuat biaya…')];
    String limit(int cents, int tokens) => [
          if (cents > 0) 'batas ${formatCents(cents.toDouble())}',
          if (tokens > 0) 'batas ${formatTokens(tokens)}',
        ].join(' · ');
    final companyLimit = limit(s.budgetMonthlyCents, s.budgetMonthlyTokens);
    return [
      NvSection('biaya · ${c.month}',
          trailing: TextButton.icon(
            key: const ValueKey('company-budget-company'),
            onPressed: _locked ? null : () => _editBudget(s, null),
            icon: const Icon(CupertinoIcons.slider_horizontal_3, size: 16),
            label: const Text('Atur'),
          )),
      NvPanel(
        margin: const EdgeInsets.fromLTRB(16, 0, 16, 8),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${formatCents(c.total.cents)} · ${formatTokens(c.total.tokens)}', style: NV.display(size: 26)),
          const SizedBox(height: 6),
          if (c.total.pct != null) CompanyMeter(pct: c.total.pct!, level: c.total.level) else Text('tanpa batas anggaran', style: TextStyle(fontSize: 12, color: NV.muted)),
          if (companyLimit.isNotEmpty) ...[const SizedBox(height: 4), Text(companyLimit, style: TextStyle(fontSize: 11.5, color: NV.faint))],
        ]),
      ),
      Padding(
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 6),
        child: Text('PER PEGAWAI · KETUK UNTUK ATUR ANGGARAN', style: NV.monoLabel(size: 10, color: NV.muted)),
      ),
      for (final row in c.byAgent)
        Builder(builder: (context) {
          final a = s.agents.where((a) => a.name == row.name).firstOrNull;
          final lim = a == null ? '' : limit(a.budgetMonthlyCents, a.budgetMonthlyTokens);
          return NvPanel(
            key: ValueKey('company-cost-${row.name}'),
            margin: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            padding: const EdgeInsets.all(12),
            onTap: a == null || _locked ? null : () => _editBudget(s, a),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Expanded(child: Text(row.name, style: const TextStyle(fontWeight: FontWeight.w600))),
                Text('${formatCents(row.cents)} · ${formatTokens(row.tokens)}', style: NV.code(size: 11, color: NV.muted)),
              ]),
              if (row.pct != null) ...[const SizedBox(height: 6), CompanyMeter(pct: row.pct!, level: row.pct! >= 100 ? 'exceeded' : (row.pct! >= 80 ? 'warning' : 'ok'))],
              const SizedBox(height: 4),
              Text(lim.isEmpty ? 'tanpa batas' : lim, style: TextStyle(fontSize: 11.5, color: NV.faint)),
            ]),
          );
        }),
    ];
  }

  Future<void> _editBudget(CompanySnapshot s, CompanyAgent? a) async {
    final b = await showBudgetForm(
      context,
      title: a == null ? 'Anggaran perusahaan' : 'Anggaran ${a.name}',
      cents: a?.budgetMonthlyCents ?? s.budgetMonthlyCents,
      tokens: a?.budgetMonthlyTokens ?? s.budgetMonthlyTokens,
    );
    if (b == null) return;
    if (a == null) {
      await act((c) => c.updateCompany(b), done: 'Anggaran perusahaan disimpan');
    } else {
      await act((c) => c.saveAgent({'id': a.id, ...b}), done: 'Anggaran ${a.name} disimpan');
    }
  }

  // ----------------------------------------------------------------- plan --
  List<Widget> _plan(CompanySnapshot s) => [
        NvSection('misi',
            trailing: TextButton.icon(
              key: const ValueKey('company-edit-mission'),
              onPressed: _locked ? null : () => _editMission(s),
              icon: const Icon(CupertinoIcons.pencil, size: 16),
              label: const Text('Ubah'),
            )),
        NvPanel(
          margin: const EdgeInsets.fromLTRB(16, 0, 16, 8),
          padding: const EdgeInsets.all(14),
          child: Text(s.mission.isEmpty ? 'Belum ada misi. Misi jadi “kenapa” di setiap tiket.' : s.mission,
              style: TextStyle(fontSize: 14, height: 1.4, color: s.mission.isEmpty ? NV.muted : NV.text)),
        ),
        // goals
        NvSection('tujuan',
            count: s.goals.length,
            trailing: TextButton.icon(
              key: const ValueKey('company-new-goal'),
              onPressed: _locked ? null : () => _editGoal(s, null),
              icon: const Icon(CupertinoIcons.add, size: 16),
              label: const Text('Baru'),
            )),
        for (final (g, depth) in s.goalTree)
          NvPanel(
            key: ValueKey('company-goal-${g.id}'),
            margin: EdgeInsets.fromLTRB(16.0 + depth * 18, 0, 16, 8),
            padding: const EdgeInsets.all(12),
            onTap: _locked ? null : () => _editGoal(s, g),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Expanded(child: Text(g.title, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 14.5))),
                NvPill(goalStatusLabel[g.status] ?? g.status),
              ]),
              if (g.description.isNotEmpty) ...[const SizedBox(height: 4), Text(g.description, style: TextStyle(fontSize: 12.5, color: NV.muted))],
              for (final p in s.projects.where((p) => p.goalId == g.id))
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text('▸ ${p.name}', style: TextStyle(fontSize: 12.5, color: NV.muted)),
                ),
            ]),
          ),
        if (s.goals.isEmpty) const NvEmpty(title: 'Belum ada tujuan', body: 'Pecah misi jadi tujuan; tiket dan proyek menempel ke tujuan.'),
        // projects
        NvSection('proyek',
            count: s.projects.length,
            trailing: TextButton.icon(
              key: const ValueKey('company-new-project'),
              onPressed: _locked ? null : () => _editProject(s, null),
              icon: const Icon(CupertinoIcons.add, size: 16),
              label: const Text('Baru'),
            )),
        for (final p in s.projects)
          NvPanel(
            key: ValueKey('company-project-${p.id}'),
            margin: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            padding: const EdgeInsets.all(12),
            onTap: _locked ? null : () => _editProject(s, p),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Expanded(child: Text(p.name, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 14.5))),
                NvPill(projectStatusLabel[p.status] ?? p.status),
              ]),
              const SizedBox(height: 4),
              Text(
                [
                  if (p.goalId != null) 'tujuan: ${s.goals.where((g) => g.id == p.goalId).map((g) => g.title).firstOrNull ?? '-'}',
                  p.budgetMonthlyCents > 0 ? 'anggaran ${formatCents(p.budgetMonthlyCents.toDouble())}/bln' : 'tanpa batas anggaran',
                ].join(' · '),
                style: TextStyle(fontSize: 12, color: NV.muted),
              ),
            ]),
          ),
        if (s.projects.isEmpty) const NvEmpty(title: 'Belum ada proyek'),
        // routines
        NvSection('rutinitas',
            count: s.routines.length,
            trailing: TextButton.icon(
              key: const ValueKey('company-new-routine'),
              onPressed: _locked ? null : () => _editRoutine(s, null),
              icon: const Icon(CupertinoIcons.add, size: 16),
              label: const Text('Baru'),
            )),
        for (final rt in s.routines)
          NvPanel(
            key: ValueKey('company-routine-${rt.id}'),
            margin: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            padding: const EdgeInsets.fromLTRB(12, 8, 4, 4),
            onTap: _locked ? null : () => _editRoutine(s, rt),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(rt.name, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 14.5)),
                    const SizedBox(height: 2),
                    Text(
                      '${rt.schedule} · ${rt.nextLabel}${rt.agentId != null ? ' · ${s.agentName(rt.agentId)}' : ''}',
                      style: TextStyle(fontSize: 12, color: NV.muted),
                    ),
                  ]),
                ),
                Switch(
                  key: ValueKey('company-routine-enabled-${rt.id}'),
                  value: rt.enabled,
                  onChanged: _locked ? null : (v) => act((c) => c.saveRoutine({'id': rt.id, 'enabled': v}), done: v ? '${rt.name} aktif' : '${rt.name} nonaktif'),
                ),
              ]),
              Align(
                alignment: Alignment.centerRight,
                child: TextButton(
                  key: ValueKey('company-routine-run-${rt.id}'),
                  onPressed: _locked ? null : () => act((c) => c.triggerRoutine(rt.id), done: 'Tiket dari ${rt.name} dibuat'),
                  child: const Text('Jalankan sekarang'),
                ),
              ),
            ]),
          ),
        if (s.routines.isEmpty) const NvEmpty(title: 'Belum ada rutinitas', body: 'Rutinitas membuat tiket terjadwal, mis. laporan setiap pagi.'),
      ];

  Future<void> _editMission(CompanySnapshot s) async {
    final b = await showMissionForm(context, name: s.name, mission: s.mission);
    if (b != null) await act((c) => c.updateCompany(b), done: 'Misi disimpan');
  }

  Future<void> _editGoal(CompanySnapshot s, CompanyGoal? g) async {
    final b = await showGoalForm(context, snap: s, goal: g);
    if (b == null) return;
    if (b['delete'] == true) {
      await act((c) => c.deleteGoal(g!.id), done: 'Tujuan dihapus');
    } else {
      await act((c) => c.saveGoal(b), done: g == null ? 'Tujuan ditambah' : 'Tujuan disimpan');
    }
  }

  Future<void> _editProject(CompanySnapshot s, CompanyProject? p) async {
    final b = await showProjectForm(context, snap: s, project: p);
    if (b == null) return;
    if (b['delete'] == true) {
      await act((c) => c.deleteProject(p!.id), done: 'Proyek dihapus');
    } else {
      await act((c) => c.saveProject(b), done: p == null ? 'Proyek dibuat' : 'Proyek disimpan');
    }
  }

  Future<void> _editRoutine(CompanySnapshot s, CompanyRoutine? rt) async {
    final b = await showRoutineForm(context, snap: s, routine: rt);
    if (b == null) return;
    if (b['delete'] == true) {
      await act((c) => c.deleteRoutine(rt!.id), done: 'Rutinitas dihapus');
    } else {
      await act((c) => c.saveRoutine(b), done: rt == null ? 'Rutinitas dibuat' : 'Rutinitas disimpan');
    }
  }
}

class CompanyMeter extends StatelessWidget {
  const CompanyMeter({super.key, required this.pct, required this.level});
  final double pct;
  final String level;
  @override
  Widget build(BuildContext context) => Row(children: [
        Expanded(
          child: ClipRRect(
            borderRadius: BorderRadius.circular(999),
            child: LinearProgressIndicator(
              value: (pct / 100).clamp(0, 1).toDouble(),
              minHeight: 6,
              backgroundColor: NV.border,
              color: level == 'ok' ? NV.text : NV.red,
            ),
          ),
        ),
        const SizedBox(width: 8),
        Text('${pct.toStringAsFixed(pct.truncateToDouble() == pct ? 0 : 1)}%', style: NV.monoLabel(size: 10)),
      ]);
}

class _TicketSheet extends StatefulWidget {
  const _TicketSheet({required this.client, required this.ticket, required this.snap, required this.onChanged});
  final CompanyClient client;
  final CompanyTicket ticket;
  final CompanySnapshot snap;
  final Future<void> Function() onChanged;
  @override
  State<_TicketSheet> createState() => _TicketSheetState();
}

class _TicketSheetState extends State<_TicketSheet> {
  TicketDetail? d;
  String? error;
  final comment = TextEditingController();
  bool busy = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final x = await widget.client.ticket(widget.ticket.id);
      if (mounted) {
        setState(() {
          d = x;
          error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => error = companyErrorText(e));
    }
  }

  Future<void> _act(Future<void> Function() fn) async {
    if (busy) return;
    setState(() => busy = true);
    try {
      await fn();
      await _load();
      await widget.onChanged();
    } catch (e) {
      if (mounted) toast(context, companyErrorText(e));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = d?.ticket ?? widget.ticket;
    return Padding(
      padding: EdgeInsets.fromLTRB(20, 0, 20, 20 + MediaQuery.viewInsetsOf(context).bottom),
      child: SingleChildScrollView(
        child: Column(key: ValueKey('company-ticket-sheet-${t.key}'), crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
          NvSheetTitle(kicker: '${t.key} · ${ticketStatusLabel[t.status] ?? t.status}', title: t.title),
          if (error != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: NvNotice(error!, action: TextButton(key: const ValueKey('company-ticket-retry'), onPressed: _load, child: const Text('Coba lagi'))),
            ),
          if (t.description.isNotEmpty) Text(t.description, style: TextStyle(fontSize: 13, height: 1.4, color: NV.muted)),
          if (d != null && d!.ancestry.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text('Kenapa: ${d!.ancestry.join(' → ')}', style: TextStyle(fontSize: 12, color: NV.faint)),
          ],
          const SizedBox(height: 10),
          DropdownButton<int?>(
            isExpanded: true,
            value: widget.snap.agents.any((a) => a.id == t.assigneeId) ? t.assigneeId : null,
            hint: const Text('Penanggung jawab'),
            items: [
              const DropdownMenuItem<int?>(value: null, child: Text('Tanpa penanggung jawab')),
              for (final a in widget.snap.agents) DropdownMenuItem<int?>(value: a.id, child: Text(a.name)),
            ],
            onChanged: busy || t.locked ? null : (v) => _act(() => widget.client.assign(t.id, v)),
          ),
          Wrap(spacing: 6, runSpacing: 6, children: [
            for (final to in ticketTransitions[t.status] ?? const <String>[])
              ActionChip(
                key: ValueKey('company-move-$to'),
                label: Text(to == 'todo' && (t.status == 'done' || t.status == 'cancelled') ? 'Buka lagi' : '→ ${ticketStatusLabel[to] ?? to}'),
                onPressed: busy ? null : () => _act(() => widget.client.move(t.id, to)),
              ),
          ]),
          const SizedBox(height: 12),
          for (final c in d?.comments ?? const <TicketComment>[])
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Text.rich(TextSpan(children: [
                TextSpan(text: '${c.author}: ', style: TextStyle(fontWeight: FontWeight.w600, color: c.fromUser ? NV.redInk : NV.text)),
                TextSpan(text: c.body, style: TextStyle(color: NV.muted)),
              ])),
            ),
          Row(children: [
            Expanded(child: TextField(key: const ValueKey('company-comment'), controller: comment, decoration: const InputDecoration(hintText: 'Tulis komentar…'))),
            IconButton(
              tooltip: 'Kirim',
              icon: const Icon(CupertinoIcons.paperplane),
              onPressed: busy
                  ? null
                  : () {
                      final text = comment.text.trim();
                      if (text.isEmpty) return;
                      comment.clear();
                      _act(() => widget.client.comment(t.id, text));
                    },
            ),
          ]),
        ]),
      ),
    );
  }
}
