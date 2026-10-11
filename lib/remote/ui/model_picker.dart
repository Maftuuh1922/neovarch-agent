// Model switcher: the PC's live model list (9Router first), as a searchable
// sheet. For the PC default (composer chip, Profil) or for one agent (agent
// sheet in Kantor, with "Ikuti default PC").
import 'package:flutter/cupertino.dart' show CupertinoIcons;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../theme/neovarch_mobile_theme.dart';
import '../../ui/widgets/common.dart' show toast;
import '../models_api.dart';
import '../office_models.dart';
import '../remote_controller.dart';
import 'nv_widgets.dart';

Future<void> showModelPicker(BuildContext context, {OfficeAgent? agent}) {
  final r = ProviderScope.containerOf(context, listen: false).read(remoteProvider);
  if (r.models == null) r.refreshModels();
  return showModalBottomSheet(
    context: context,
    isScrollControlled: true,
    builder: (_) => FractionallySizedBox(heightFactor: 0.78, child: ModelPickerSheet(agent: agent)),
  );
}

class ModelPickerSheet extends ConsumerStatefulWidget {
  const ModelPickerSheet({super.key, this.agent});
  final OfficeAgent? agent;
  @override
  ConsumerState<ModelPickerSheet> createState() => _ModelPickerSheetState();
}

class _ModelPickerSheetState extends ConsumerState<ModelPickerSheet> {
  final _q = TextEditingController();
  String? _busy;

  @override
  void dispose() {
    _q.dispose();
    super.dispose();
  }

  Future<void> _pick(ModelEntry? m) async {
    final r = ref.read(remoteProvider);
    final a = widget.agent;
    setState(() => _busy = m?.id ?? '');
    final err = a == null ? await r.setDefaultModel(m!) : await r.setAgentModel(a.id, m);
    if (!mounted) return;
    setState(() => _busy = null);
    if (err != null) {
      toast(context, err);
      return;
    }
    toast(context, a == null ? 'Model default PC: ${modelShort(m!.id)}' : (m == null ? '${a.name} ikut default PC' : 'Model ${a.name}: ${modelShort(m.id)}'));
    Navigator.pop(context);
  }

  @override
  Widget build(BuildContext context) {
    final r = ref.watch(remoteProvider);
    final snap = r.models;
    final a = widget.agent;
    final live = a == null ? null : r.office?.agents.where((x) => x.id == a.id).firstOrNull ?? a;
    final current = a == null ? snap?.defaultModel.model : (live!.modelOverride?.model);
    final groups = snap?.groups(query: _q.text) ?? const [];
    return Padding(
      key: const ValueKey('model-picker'),
      padding: EdgeInsets.fromLTRB(16, 0, 16, MediaQuery.viewInsetsOf(context).bottom),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        NvSheetTitle(kicker: a == null ? 'model · default PC' : 'model · ${a.name}', title: 'Pilih model'),
        const SizedBox(height: 10),
        TextField(
          key: const ValueKey('model-search'),
          controller: _q,
          onChanged: (_) => setState(() {}),
          decoration: const InputDecoration(hintText: 'Cari model…', prefixIcon: Icon(CupertinoIcons.search, size: 18), isDense: true),
        ),
        const SizedBox(height: 8),
        if (snap != null && !snap.routerReady && snap.routerMessage != null)
          Padding(padding: const EdgeInsets.only(bottom: 8), child: NvNotice(snap.routerMessage!, icon: CupertinoIcons.info)),
        Expanded(
          child: snap == null
              ? Center(
                  child: Text(
                    r.modelsUnsupported
                        ? 'PC ini belum punya daftar model 9Router. Perbarui Neovarch di PC, atau pakai "+" → Model di chat.'
                        : (r.modelsError ?? 'Memuat model dari PC…'),
                    textAlign: TextAlign.center,
                    style: TextStyle(color: NV.muted, fontSize: 13.5),
                  ),
                )
              : ListView(children: [
                  if (a != null)
                    _Row(
                      key: const ValueKey('model-follow-default'),
                      title: 'Ikuti default PC',
                      subtitle: snap.defaultModel.model.isEmpty ? null : modelShort(snap.defaultModel.model),
                      selected: live!.modelOverride == null,
                      busy: _busy == '',
                      onTap: () => _pick(null),
                    ),
                  for (final (g, items) in groups) ...[
                    NvSection(g, count: items.length),
                    NvList(children: [
                      for (final m in items)
                        _Row(
                          key: ValueKey('model-${m.id}'),
                          title: m.label,
                          subtitle: m.id,
                          free: m.free,
                          recommended: m.recommended,
                          selected: current == m.id,
                          busy: _busy == m.id,
                          onTap: () => _pick(m),
                        ),
                    ]),
                  ],
                  if (groups.isEmpty) Padding(padding: const EdgeInsets.all(24), child: Text('Tidak ada model yang cocok.', textAlign: TextAlign.center, style: TextStyle(color: NV.muted))),
                  const SizedBox(height: 24),
                ]),
        ),
      ]),
    );
  }
}

class _Row extends StatelessWidget {
  const _Row({super.key, required this.title, this.subtitle, this.free = false, this.recommended = false, required this.selected, required this.onTap, this.busy = false});
  final String title;
  final String? subtitle;
  final bool free, recommended, selected, busy;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => InkWell(
        onTap: busy ? null : onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
          child: Row(children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(title, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 14.5, fontWeight: FontWeight.w600, color: NV.text)),
                if (subtitle != null) Text(subtitle!, maxLines: 1, overflow: TextOverflow.ellipsis, style: NV.code(size: 11.5, color: NV.muted)),
              ]),
            ),
            if (recommended) ...[NvPill('rekomendasi', color: NV.redInk), const SizedBox(width: 6)],
            if (free) ...[NvPill('gratis', color: NV.muted), const SizedBox(width: 6)],
            if (busy)
              const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
            else
              Icon(selected ? CupertinoIcons.checkmark_circle_fill : CupertinoIcons.circle, size: 20, color: selected ? NV.red : NV.faint),
          ]),
        ),
      );
}

/// Compact chip with the PC's default model (composer, Profil).
class ModelChip extends ConsumerWidget {
  const ModelChip({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final r = ref.watch(remoteProvider);
    final m = r.models?.defaultModel.model;
    if (r.modelsUnsupported || m == null || m.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.fromLTRB(4, 0, 0, 6),
      child: GestureDetector(
      key: const ValueKey('model-chip'),
      onTap: () => showModelPicker(context),
      child: Container(
        padding: const EdgeInsets.fromLTRB(8, 4, 8, 4),
        decoration: BoxDecoration(color: NV.glass, borderRadius: BorderRadius.circular(999), border: Border.all(color: NV.glassBorder)),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Icon(CupertinoIcons.sparkles, size: 13, color: NV.red),
          const SizedBox(width: 5),
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 180),
            child: Text(modelShort(m), maxLines: 1, overflow: TextOverflow.ellipsis, style: NV.monoLabel(size: 9.5, color: NV.text)),
          ),
          const SizedBox(width: 3),
          Icon(CupertinoIcons.chevron_down, size: 11, color: NV.muted),
        ]),
      ),
    ),
    );
  }
}

/// "9router" → "9Router"; other provider slugs keep their own spelling, capitalised.
String providerLabel(String slug) {
  final s = slug.trim();
  if (s.isEmpty) return '';
  if (s.toLowerCase() == '9router') return '9Router';
  if (s.startsWith('custom')) return 'Kustom';
  return s[0].toUpperCase() + s.substring(1);
}

/// The text of [ModelSwitcherPill]: "MiMo 2.6 · 9Router", or "—" with no PC.
String modelPillText(RemoteController r) {
  final m = r.models;
  if (!r.connected || r.modelsUnsupported || m == null || m.defaultModel.model.isEmpty) return '—';
  final cur = m.defaultModel.model;
  final label = m.entry(cur)?.label ?? modelShort(cur);
  final prov = providerLabel(m.defaultModel.provider);
  return prov.isEmpty ? label : '$label · $prov';
}

/// Chat top bar, left: the PC's current model as a pill. Tapping opens the
/// model picker and switches the PC default (the model new chats and new
/// Kantor employees use). Greyed with "—" while no PC is connected.
class ModelSwitcherPill extends ConsumerWidget {
  const ModelSwitcherPill({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final r = ref.watch(remoteProvider);
    if (r.connected && r.models == null && !r.modelsUnsupported && r.modelsError == null) {
      // first visit after connecting: fetch the list once (no-op while one is in flight)
      WidgetsBinding.instance.addPostFrameCallback((_) => r.models == null ? r.refreshModels() : null);
    }
    final text = modelPillText(r);
    final enabled = r.connected && !r.modelsUnsupported;
    final fg = enabled ? NV.text : NV.faint;
    return Semantics(
      button: true,
      enabled: enabled,
      label: enabled ? 'Model PC: $text. Ketuk untuk ganti' : 'Model PC: belum terhubung',
      child: Opacity(
        opacity: enabled ? 1 : 0.55,
        child: GestureDetector(
          key: const ValueKey('model-switcher-pill'),
          behavior: HitTestBehavior.opaque,
          onTap: enabled ? () => showModelPicker(context) : null,
          child: Container(
            height: 34,
            padding: const EdgeInsets.fromLTRB(11, 0, 9, 0),
            decoration: BoxDecoration(color: NV.glass, borderRadius: BorderRadius.circular(999), border: Border.all(color: NV.glassBorder)),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(CupertinoIcons.sparkles, size: 14, color: enabled ? NV.red : NV.faint),
              const SizedBox(width: 6),
              ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 190),
                child: Text(text, key: const ValueKey('model-switcher-text'), maxLines: 1, overflow: TextOverflow.ellipsis,
                    style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: fg)),
              ),
              const SizedBox(width: 4),
              Icon(CupertinoIcons.chevron_down, size: 12, color: enabled ? NV.muted : NV.faint),
            ]),
          ),
        ),
      ),
    );
  }
}

/// Profil → "Model AI": the PC default and a button to change it.
class ModelSettingsPanel extends ConsumerWidget {
  const ModelSettingsPanel({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final r = ref.watch(remoteProvider);
    final m = r.models;
    final cur = m?.defaultModel.model ?? '';
    final e = m?.entry(cur);
    return NvPanel(
      key: const ValueKey('model-settings'),
      margin: const EdgeInsets.symmetric(horizontal: 16),
      padding: const EdgeInsets.fromLTRB(14, 12, 10, 12),
      child: Row(children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('MODEL DEFAULT PC', style: NV.monoLabel(size: 9.5)),
            const SizedBox(height: 4),
            Text(
              r.modelsUnsupported ? 'PC belum mendukung daftar model' : (cur.isEmpty ? (r.connected ? 'memuat…' : 'belum terhubung') : (e?.label ?? modelShort(cur))),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: NV.text),
            ),
            if (cur.isNotEmpty) Text('${e?.group ?? ''}${e?.group.isNotEmpty == true ? ' · ' : ''}$cur', maxLines: 1, overflow: TextOverflow.ellipsis, style: NV.code(size: 11, color: NV.muted)),
          ]),
        ),
        TextButton(
          key: const ValueKey('model-settings-change'),
          onPressed: r.connected && !r.modelsUnsupported ? () => showModelPicker(context) : null,
          child: const Text('Ganti'),
        ),
      ]),
    );
  }
}
