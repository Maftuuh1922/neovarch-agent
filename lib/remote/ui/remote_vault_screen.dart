// Obsidian vault on the PC, read-only on the phone: file tree, search,
// rendered notes with clickable [[wikilinks]] and backlinks, "Buka di
// Obsidian" (obsidian://open), and a node graph of notes and their links.
// A `vault.changed` push (agent wrote a note) re-reads what is open.
import 'dart:math' as math;

import 'package:flutter/cupertino.dart' show CupertinoIcons;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../theme/neovarch_mobile_theme.dart';
import '../../ui/widgets/common.dart' show CenterLoader, toast;
import '../../ui/widgets/markdown_view.dart';
import '../remote_controller.dart';
import '../vault_models.dart';
import 'nv_widgets.dart';
import '../remote_errors.dart';

const _wikiScheme = 'nvwiki:';

/// `[[Target|Label]]` → `[Label](nvwiki:Target)` so the Markdown view makes
/// it a tappable link; embeds (`![[…]]`) become plain links too.
String wikilinksToMarkdown(String md) => md.replaceAllMapped(RegExp(r'!?\[\[([^\[\]\n]+?)\]\]'), (m) {
      final raw = m.group(1)!;
      final label = wikiLabel(raw).replaceAll('[', '(').replaceAll(']', ')');
      return '[$label]($_wikiScheme${Uri.encodeComponent(wikiTarget(raw))})';
    });

Future<void> openInObsidian(BuildContext context, String? uri) async {
  if (uri == null || uri.isEmpty) return;
  final ok = await launchUrl(Uri.parse(uri), mode: LaunchMode.externalApplication).catchError((_) => false);
  if (!ok && context.mounted) toast(context, 'Aplikasi Obsidian tidak ditemukan di HP ini.');
}

class RemoteVaultScreen extends ConsumerStatefulWidget {
  const RemoteVaultScreen({super.key});
  @override
  ConsumerState<RemoteVaultScreen> createState() => _RemoteVaultScreenState();
}

class _RemoteVaultScreenState extends ConsumerState<RemoteVaultScreen> {
  VaultTree? _tree;
  String? _error;
  bool _loading = true;
  final _q = TextEditingController();
  List<VaultHit>? _hits;
  int _rev = -1;
  final _open = <String>{''};

  @override
  void dispose() {
    _q.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final g = ref.read(remoteProvider).vault;
    if (g == null) {
      setState(() {
        _loading = false;
        _error = 'Belum terhubung ke PC.';
      });
      return;
    }
    try {
      final t = await g.vaultTree();
      if (!mounted) return;
      setState(() {
        _tree = t;
        _error = null;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = friendlyRemoteError(e);
        _loading = false;
      });
    }
  }

  Future<void> _search(String q) async {
    final g = ref.read(remoteProvider).vault;
    if (q.trim().isEmpty || g == null) {
      setState(() => _hits = null);
      return;
    }
    try {
      final h = await g.vaultSearch(q.trim());
      if (mounted) setState(() => _hits = h);
    } catch (e) {
      if (mounted) toast(context, friendlyRemoteError(e));
    }
  }

  void _openNote(String path) => Navigator.of(context).push(MaterialPageRoute(builder: (_) => VaultNoteScreen(path: path)));

  @override
  Widget build(BuildContext context) {
    final r = ref.watch(remoteProvider);
    if (_rev != r.vaultRevision) {
      _rev = r.vaultRevision;
      WidgetsBinding.instance.addPostFrameCallback((_) => _load());
    }
    final t = _tree;
    return Scaffold(
      body: Column(children: [
        NvHeader(
          kicker: 'vault · ${t?.vault.isNotEmpty == true ? t!.vault : (r.desktop?.name ?? 'pc')}',
          title: 'Memori',
          onBack: () => Navigator.of(context).maybePop(),
          actions: [
            NvIconButton(
              tooltip: 'Graf catatan',
              icon: CupertinoIcons.circle_grid_hex,
              onPressed: t?.configured == true
                  ? () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const VaultGraphScreen()))
                  : null,
            ),
          ],
        ),
        if (t?.configured == true)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            child: TextField(
              key: const ValueKey('vault-search'),
              controller: _q,
              textInputAction: TextInputAction.search,
              onSubmitted: _search,
              decoration: InputDecoration(
                hintText: 'Cari catatan…',
                prefixIcon: const Icon(CupertinoIcons.search, size: 20),
                suffixIcon: _hits == null
                    ? null
                    : IconButton(
                        tooltip: 'Hapus pencarian',
                        icon: const Icon(CupertinoIcons.xmark, size: 18),
                        onPressed: () {
                          _q.clear();
                          setState(() => _hits = null);
                        }),
              ),
            ),
          ),
        Expanded(child: _body(context, t)),
      ]),
    );
  }

  Widget _body(BuildContext context, VaultTree? t) {
    final bottom = MediaQuery.paddingOf(context).bottom + 16;
    if (_loading && t == null) return const CenterLoader(label: 'membaca vault di PC…');
    if (_error != null && t == null) return ListView(children: [Padding(padding: const EdgeInsets.all(16), child: NvNotice(_error!))]);
    if (t == null || !t.configured || t.root == null) {
      return ListView(children: const [
        NvEmpty(
          kicker: 'vault belum dipilih',
          title: 'Pilih vault di PC',
          body: 'Buka Pengaturan → Memori di aplikasi Neovarch PC dan pilih folder vault Obsidian. Catatannya lalu bisa dibaca di sini.',
        ),
      ]);
    }
    final hits = _hits;
    if (hits != null) {
      return ListView(padding: EdgeInsets.only(bottom: bottom), children: [
        NvSection('hasil', count: hits.length),
        if (hits.isEmpty)
          Padding(padding: const EdgeInsets.symmetric(horizontal: 20), child: Text('Tidak ada catatan yang cocok.', style: TextStyle(color: NV.muted)))
        else
          NvList(children: [
            for (final h in hits)
              NvRow(icon: CupertinoIcons.doc_text, title: h.title, subtitle: h.snippet.isNotEmpty ? h.snippet : h.path, onTap: () => _openNote(h.path)),
          ]),
      ]);
    }
    final rows = <Widget>[];
    void walk(VaultNode n, int depth) {
      for (final c in n.children) {
        rows.add(_TreeRow(
          node: c,
          depth: depth,
          open: _open.contains(c.path),
          onTap: c.folder ? () => setState(() => _open.contains(c.path) ? _open.remove(c.path) : _open.add(c.path)) : () => _openNote(c.path),
        ));
        if (c.folder && _open.contains(c.path)) walk(c, depth + 1);
      }
    }

    walk(t.root!, 0);
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(padding: EdgeInsets.only(bottom: bottom), children: [
        NvSection('catatan', count: t.root!.noteCount),
        if (rows.isEmpty)
          Padding(padding: const EdgeInsets.symmetric(horizontal: 20), child: Text('Vault masih kosong.', style: TextStyle(color: NV.muted)))
        else
          NvPanel(
            key: const ValueKey('vault-tree'),
            margin: const EdgeInsets.symmetric(horizontal: 16),
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: Column(children: rows),
          ),
      ]),
    );
  }
}

class _TreeRow extends StatelessWidget {
  const _TreeRow({required this.node, required this.depth, required this.open, required this.onTap});
  final VaultNode node;
  final int depth;
  final bool open;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => InkWell(
        onTap: onTap,
        child: Padding(
          padding: EdgeInsets.fromLTRB(14.0 + depth * 18, 11, 14, 11),
          child: Row(children: [
            Icon(node.folder ? (open ? CupertinoIcons.folder_open : CupertinoIcons.folder) : CupertinoIcons.doc_text,
                size: 18, color: node.folder ? NV.red : NV.muted),
            const SizedBox(width: 10),
            Expanded(child: Text(node.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 14.5, color: NV.text))),
            if (node.folder) Text('${node.noteCount}', style: NV.monoLabel(size: 10, color: NV.faint)),
          ]),
        ),
      );
}

class VaultNoteScreen extends ConsumerStatefulWidget {
  const VaultNoteScreen({super.key, required this.path});
  final String path;
  @override
  ConsumerState<VaultNoteScreen> createState() => _VaultNoteScreenState();
}

class _VaultNoteScreenState extends ConsumerState<VaultNoteScreen> {
  VaultNote? _note;
  String? _error;
  int _rev = -1;

  Future<void> _load() async {
    final g = ref.read(remoteProvider).vault;
    if (g == null) return;
    try {
      final n = await g.vaultNote(widget.path);
      if (mounted) {
        setState(() {
          _note = n;
          _error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = friendlyRemoteError(e));
    }
  }

  void _follow(String url) {
    if (url.startsWith(_wikiScheme)) {
      final target = Uri.decodeComponent(url.substring(_wikiScheme.length));
      final path = _note?.resolve(target);
      if (path == null) {
        toast(context, 'Catatan "$target" belum ada di vault.');
        return;
      }
      Navigator.of(context).push(MaterialPageRoute(builder: (_) => VaultNoteScreen(path: path)));
      return;
    }
    launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
  }

  @override
  Widget build(BuildContext context) {
    final r = ref.watch(remoteProvider);
    if (_rev != r.vaultRevision) {
      _rev = r.vaultRevision;
      WidgetsBinding.instance.addPostFrameCallback((_) => _load());
    }
    final n = _note;
    return Scaffold(
      body: Column(children: [
        NvHeader(
          kicker: n == null ? 'catatan' : 'catatan · ${n.path}',
          title: n?.title ?? widget.path.split('/').last.replaceAll(RegExp(r'\.md$'), ''),
          onBack: () => Navigator.of(context).maybePop(),
        ),
        Expanded(
          child: n == null
              ? (_error != null ? ListView(children: [Padding(padding: const EdgeInsets.all(16), child: NvNotice(_error!))]) : const CenterLoader())
              : ListView(padding: EdgeInsets.fromLTRB(0, 0, 0, MediaQuery.paddingOf(context).bottom + 16), children: [
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
                    child: Row(children: [
                      Expanded(
                        child: FilledButton.icon(
                          key: const ValueKey('open-obsidian'),
                          onPressed: n.openUri == null ? null : () => openInObsidian(context, n.openUri),
                          icon: const Icon(CupertinoIcons.arrow_up_right_square, size: 18),
                          label: const Text('Buka di Obsidian'),
                        ),
                      ),
                    ]),
                  ),
                  if (n.tags.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
                      child: Wrap(spacing: 6, runSpacing: 6, children: [for (final t in n.tags) NvPill('#$t', color: NV.red)]),
                    ),
                  NvPanel(
                    key: const ValueKey('note-body'),
                    margin: const EdgeInsets.symmetric(horizontal: 16),
                    child: MarkdownView(wikilinksToMarkdown(n.body), onLink: _follow),
                  ),
                  NvSection('backlink', count: n.backlinks.length),
                  if (n.backlinks.isEmpty)
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 20),
                      child: Text('Belum ada catatan yang menautkan ke sini.', style: TextStyle(color: NV.muted, fontSize: 13.5)),
                    )
                  else
                    NvList(children: [
                      for (final b in n.backlinks)
                        NvRow(
                          icon: CupertinoIcons.arrow_turn_down_left,
                          title: b.title,
                          subtitle: b.snippet.isNotEmpty ? b.snippet : b.path,
                          onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => VaultNoteScreen(path: b.path))),
                        ),
                    ]),
                ]),
        ),
      ]),
    );
  }
}

// ------------------------------------------------------------------ graph --

/// Force-directed layout (Fruchterman–Reingold), deterministic seed so the
/// same vault always draws the same picture. Positions in a unit square.
Map<String, Offset> layoutGraph(VaultGraph g, {int iterations = 220, int seed = 7}) {
  final ids = [for (final n in g.nodes) n.id];
  final n = ids.length;
  if (n == 0) return const {};
  final rnd = math.Random(seed);
  final pos = <String, Offset>{for (final id in ids) id: Offset(rnd.nextDouble(), rnd.nextDouble())};
  if (n == 1) return {ids.first: const Offset(0.5, 0.5)};
  final k = math.sqrt(1.0 / n);
  var temp = 0.1;
  final edges = [for (final e in g.edges) if (pos.containsKey(e.$1) && pos.containsKey(e.$2) && e.$1 != e.$2) e];
  for (var it = 0; it < iterations; it++) {
    final disp = <String, Offset>{for (final id in ids) id: Offset.zero};
    for (var i = 0; i < n; i++) {
      for (var j = i + 1; j < n; j++) {
        var d = pos[ids[i]]! - pos[ids[j]]!;
        var dist = d.distance;
        if (dist < 1e-4) {
          d = Offset(rnd.nextDouble() * 1e-3, rnd.nextDouble() * 1e-3);
          dist = d.distance;
        }
        final f = d / dist * (k * k / dist);
        disp[ids[i]] = disp[ids[i]]! + f;
        disp[ids[j]] = disp[ids[j]]! - f;
      }
    }
    for (final (a, b) in edges) {
      final d = pos[a]! - pos[b]!;
      final dist = math.max(d.distance, 1e-4);
      final f = d / dist * (dist * dist / k);
      disp[a] = disp[a]! - f;
      disp[b] = disp[b]! + f;
    }
    for (final id in ids) {
      // gentle pull to the centre keeps disconnected notes on screen
      final c = (const Offset(0.5, 0.5) - pos[id]!) * 0.02;
      final d = disp[id]! + c;
      final len = d.distance;
      final p = pos[id]! + (len > 0 ? d / len * math.min(len, temp) : Offset.zero);
      pos[id] = Offset(p.dx.clamp(0.0, 1.0), p.dy.clamp(0.0, 1.0));
    }
    temp = math.max(0.002, temp * 0.97);
  }
  // normalise into [0.05, 0.95]
  var minX = 1.0, minY = 1.0, maxX = 0.0, maxY = 0.0;
  for (final p in pos.values) {
    minX = math.min(minX, p.dx);
    minY = math.min(minY, p.dy);
    maxX = math.max(maxX, p.dx);
    maxY = math.max(maxY, p.dy);
  }
  final w = math.max(maxX - minX, 1e-3), h = math.max(maxY - minY, 1e-3);
  return {for (final e in pos.entries) e.key: Offset(0.05 + (e.value.dx - minX) / w * 0.9, 0.05 + (e.value.dy - minY) / h * 0.9)};
}

class VaultGraphScreen extends ConsumerStatefulWidget {
  const VaultGraphScreen({super.key});
  @override
  ConsumerState<VaultGraphScreen> createState() => _VaultGraphScreenState();
}

class _VaultGraphScreenState extends ConsumerState<VaultGraphScreen> {
  VaultGraph? _g;
  Map<String, Offset> _pos = const {};
  String? _error;
  String? _selected;
  int _rev = -1;

  Future<void> _load() async {
    final gw = ref.read(remoteProvider).vault;
    if (gw == null) return;
    try {
      var g = await gw.vaultGraph();
      // Very large vaults: keep the best-connected notes so it stays legible.
      if (g.nodes.length > 400) {
        final keep = ([...g.nodes]..sort((a, b) => b.degree.compareTo(a.degree))).take(400).map((n) => n.id).toSet();
        g = VaultGraph(
          configured: g.configured,
          nodes: g.nodes.where((n) => keep.contains(n.id)).toList(),
          edges: g.edges.where((e) => keep.contains(e.$1) && keep.contains(e.$2)).toList(),
        );
      }
      final pos = layoutGraph(g, iterations: g.nodes.length > 150 ? 90 : 220);
      if (mounted) {
        setState(() {
          _g = g;
          _pos = pos;
          _error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = friendlyRemoteError(e));
    }
  }

  @override
  Widget build(BuildContext context) {
    final r = ref.watch(remoteProvider);
    if (_rev != r.vaultRevision) {
      _rev = r.vaultRevision;
      WidgetsBinding.instance.addPostFrameCallback((_) => _load());
    }
    final g = _g;
    final sel = g?.nodes.where((n) => n.id == _selected).firstOrNull;
    return Scaffold(
      body: Column(children: [
        NvHeader(
          kicker: g == null ? 'graf' : 'graf · ${g.nodes.length} catatan · ${g.edges.length} tautan',
          title: 'Graf',
          onBack: () => Navigator.of(context).maybePop(),
        ),
        Expanded(
          child: g == null
              ? (_error != null ? Padding(padding: const EdgeInsets.all(16), child: NvNotice(_error!)) : const CenterLoader(label: 'menyusun graf…'))
              : g.nodes.isEmpty
                  ? const NvEmpty(title: 'Graf kosong', body: 'Belum ada catatan di vault.')
                  : Padding(
                      padding: const EdgeInsets.fromLTRB(16, 0, 16, 0),
                      child: NvPanel(
                        padding: EdgeInsets.zero,
                        child: LayoutBuilder(builder: (context, c) {
                          final size = Size(c.maxWidth, c.maxHeight);
                          return InteractiveViewer(
                            minScale: 0.5,
                            maxScale: 6,
                            boundaryMargin: const EdgeInsets.all(200),
                            child: GestureDetector(
                              behavior: HitTestBehavior.opaque,
                              onTapUp: (d) => setState(() => _selected = _hit(g, size, d.localPosition)),
                              child: CustomPaint(
                                key: const ValueKey('vault-graph'),
                                size: size,
                                painter: VaultGraphPainter(graph: g, pos: _pos, selected: _selected, palette: NV.palette),
                              ),
                            ),
                          );
                        }),
                      ),
                    ),
        ),
        if (sel != null)
          Padding(
            padding: EdgeInsets.fromLTRB(16, 10, 16, MediaQuery.paddingOf(context).bottom + 12),
            child: NvGlass(
              padding: const EdgeInsets.fromLTRB(14, 10, 8, 10),
              child: Row(children: [
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                    Text(sel.title, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontWeight: FontWeight.w600, color: NV.text)),
                    Text(sel.exists ? '${sel.degree} tautan' : 'belum ada (tautan kosong)', style: NV.monoLabel(size: 10)),
                  ]),
                ),
                if (sel.exists)
                  TextButton(
                    onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => VaultNoteScreen(path: sel.id))),
                    child: const Text('Buka'),
                  ),
              ]),
            ),
          )
        else
          SizedBox(height: MediaQuery.paddingOf(context).bottom + 12),
      ]),
    );
  }

  String? _hit(VaultGraph g, Size size, Offset p) {
    String? best;
    var bestD = 28.0;
    for (final n in g.nodes) {
      final o = _pos[n.id];
      if (o == null) continue;
      final d = (Offset(o.dx * size.width, o.dy * size.height) - p).distance;
      if (d < bestD) {
        bestD = d;
        best = n.id;
      }
    }
    return best;
  }
}

class VaultGraphPainter extends CustomPainter {
  VaultGraphPainter({required this.graph, required this.pos, required this.selected, required this.palette});
  final VaultGraph graph;
  final Map<String, Offset> pos;
  final String? selected;
  final NvPalette palette;

  @override
  void paint(Canvas canvas, Size size) {
    Offset at(String id) => Offset(pos[id]!.dx * size.width, pos[id]!.dy * size.height);
    final near = <String>{?selected};
    for (final (a, b) in graph.edges) {
      if (a == selected) near.add(b);
      if (b == selected) near.add(a);
    }
    final line = Paint()
      ..strokeWidth = 1
      ..color = palette.border;
    final hot = Paint()
      ..strokeWidth = 1.4
      ..color = palette.accent;
    for (final (a, b) in graph.edges) {
      if (!pos.containsKey(a) || !pos.containsKey(b)) continue;
      canvas.drawLine(at(a), at(b), (a == selected || b == selected) ? hot : line);
    }
    final labels = graph.nodes.length <= 60;
    for (final n in graph.nodes) {
      if (!pos.containsKey(n.id)) continue;
      final o = at(n.id);
      final r = 3.5 + math.min(n.degree, 12) * 0.7;
      final isSel = n.id == selected;
      final fill = Paint()..color = isSel || near.contains(n.id) ? palette.accent : (n.exists ? palette.text.withValues(alpha: 0.85) : palette.faint);
      canvas.drawCircle(o, r, fill);
      if (!n.exists) {
        canvas.drawCircle(o, r, Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1
          ..color = palette.muted);
      }
      if (labels || isSel || near.contains(n.id)) {
        final tp = TextPainter(
          text: TextSpan(text: n.title, style: TextStyle(fontSize: 10.5, color: isSel ? palette.text : palette.muted, fontFamily: NV.sans)),
          textDirection: TextDirection.ltr,
          maxLines: 1,
          ellipsis: '…',
        )..layout(maxWidth: 120);
        tp.paint(canvas, o + Offset(-tp.width / 2, r + 3));
      }
    }
  }

  @override
  bool shouldRepaint(VaultGraphPainter old) => old.graph != graph || old.pos != pos || old.selected != selected || old.palette != palette;
}
