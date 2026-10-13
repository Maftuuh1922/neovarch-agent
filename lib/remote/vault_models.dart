// The PC's Obsidian vault as the phone sees it (read-only):
// `GET /api/obsidian/{tree,note,graph,search}`. Pure Dart.

class VaultNode {
  final String name;
  final String path;
  final bool folder;
  final List<VaultNode> children;
  const VaultNode({required this.name, required this.path, required this.folder, this.children = const []});
  factory VaultNode.fromJson(Map<String, dynamic> j) => VaultNode(
        name: '${j['name'] ?? ''}',
        path: '${j['path'] ?? ''}',
        folder: j['type'] == 'folder',
        children: [for (final c in (j['children'] as List? ?? const []).whereType<Map>()) VaultNode.fromJson(Map<String, dynamic>.from(c))],
      );

  int get noteCount => folder ? children.fold(0, (n, c) => n + c.noteCount) : 1;
}

class VaultTree {
  final bool configured;
  final String vault;
  final String? detail;
  final VaultNode? root;
  const VaultTree({required this.configured, this.vault = '', this.detail, this.root});
  factory VaultTree.fromJson(Map<String, dynamic> j) => VaultTree(
        configured: j['configured'] == true,
        vault: '${j['vault'] ?? ''}',
        detail: j['detail'] as String?,
        root: j['tree'] is Map ? VaultNode.fromJson(Map<String, dynamic>.from(j['tree'] as Map)) : null,
      );
}

class VaultLink {
  final String target; // as written inside [[…]]
  final String? path; // resolved note path, null when the note does not exist
  const VaultLink(this.target, this.path);
}

class VaultBacklink {
  final String path;
  final String title;
  final String snippet;
  const VaultBacklink({required this.path, required this.title, this.snippet = ''});
}

class VaultNote {
  final String path;
  final String title;
  final String content;
  final List<String> tags;
  final List<VaultLink> outgoing;
  final List<VaultBacklink> backlinks;
  final String? openUri;
  const VaultNote({
    required this.path,
    required this.title,
    required this.content,
    this.tags = const [],
    this.outgoing = const [],
    this.backlinks = const [],
    this.openUri,
  });

  factory VaultNote.fromJson(Map<String, dynamic> j) => VaultNote(
        path: '${j['path'] ?? ''}',
        title: '${j['title'] ?? ''}',
        content: '${j['content'] ?? ''}',
        tags: [for (final t in (j['tags'] as List? ?? const [])) '$t'],
        outgoing: [
          for (final o in (j['outgoing'] as List? ?? const []))
            if (o is Map) VaultLink('${o['target'] ?? ''}', o['path'] as String?) else VaultLink('$o', null),
        ],
        backlinks: [
          for (final b in (j['backlinks'] as List? ?? const []).whereType<Map>())
            VaultBacklink(path: '${b['path'] ?? ''}', title: '${b['title'] ?? ''}', snippet: '${b['snippet'] ?? ''}'),
        ],
        openUri: j['open_uri'] as String?,
      );

  /// Body without the YAML front matter.
  String get body {
    final m = RegExp(r'^---\r?\n[\s\S]*?\r?\n---\r?\n?').firstMatch(content);
    return m == null ? content : content.substring(m.end);
  }

  /// Note path a wikilink target points at: the core's resolution first,
  /// then a case-insensitive match on the last path segment. Null when the
  /// note does not exist yet.
  String? resolve(String target) {
    final t = wikiTarget(target);
    for (final o in outgoing) {
      if (wikiTarget(o.target) == t && o.path != null) return o.path;
    }
    final base = t.split('/').last.toLowerCase();
    for (final o in outgoing) {
      final p = o.path;
      if (p == null) continue;
      final stem = p.split('/').last.replaceAll(RegExp(r'\.md$', caseSensitive: false), '').toLowerCase();
      if (stem == base) return p;
    }
    return null;
  }
}

/// `Note|alias` / `Note#Heading` → `Note`.
String wikiTarget(String raw) => raw.split('|').first.split('#').first.trim();

/// `Note|alias` → `alias`, else the target.
String wikiLabel(String raw) {
  final i = raw.indexOf('|');
  return i >= 0 ? raw.substring(i + 1).trim() : raw.trim();
}

class VaultGraphNode {
  final String id;
  final String title;
  final bool exists;
  final int degree;

  /// hub | project | session | file | memory | note | unresolved (Neovarch's notes carry
  /// `neovarch:` in their frontmatter; the PC sends it as `kind`).
  final String kind;
  final List<String> tags;
  final String? project;
  const VaultGraphNode(
      {required this.id, required this.title, required this.exists, required this.degree, this.kind = 'note', this.tags = const [], this.project});
}

const vaultNodeKinds = ['project', 'session', 'file', 'memory', 'hub', 'note', 'unresolved'];
const vaultKindLabels = {
  'project': 'Proyek',
  'session': 'Sesi',
  'file': 'Berkas',
  'memory': 'Memori',
  'hub': 'Hub',
  'note': 'Catatan',
  'unresolved': 'Belum ada',
};

String _kindOf(Map n) {
  if (n['exists'] == false) return 'unresolved';
  final k = '${n['kind'] ?? 'note'}';
  return vaultNodeKinds.contains(k) ? k : 'note';
}

class VaultGraph {
  final bool configured;
  final List<VaultGraphNode> nodes;
  final List<(String, String)> edges;
  const VaultGraph({required this.configured, this.nodes = const [], this.edges = const []});
  factory VaultGraph.fromJson(Map<String, dynamic> j) => VaultGraph(
        configured: j['configured'] != false,
        nodes: [
          for (final n in (j['nodes'] as List? ?? const []).whereType<Map>())
            VaultGraphNode(
              id: '${n['id']}',
              title: '${n['title'] ?? n['id']}',
              exists: n['exists'] != false,
              degree: (n['degree'] as num?)?.toInt() ?? 0,
              kind: _kindOf(n),
              tags: [for (final t in (n['tags'] as List? ?? const [])) '$t'],
              project: n['project'] == null ? null : '${n['project']}',
            ),
        ],
        edges: [
          for (final e in (j['edges'] as List? ?? const []).whereType<Map>()) ('${e['source']}', '${e['target']}'),
        ],
      );

  /// Undirected neighbours of every node.
  Map<String, Set<String>> adjacency() {
    final adj = <String, Set<String>>{for (final n in nodes) n.id: <String>{}};
    for (final (a, b) in edges) {
      if (a == b) continue;
      adj[a]?.add(b);
      adj[b]?.add(a);
    }
    return adj;
  }

  VaultGraph _keep(Set<String> ids) => VaultGraph(
        configured: configured,
        nodes: [for (final n in nodes) if (ids.contains(n.id)) n],
        edges: [for (final e in edges) if (ids.contains(e.$1) && ids.contains(e.$2)) e],
      );

  /// Obsidian's local graph: [center] plus every note within [depth] links, both directions.
  VaultGraph local(String center, {int depth = 1}) {
    final adj = adjacency();
    if (!adj.containsKey(center)) return VaultGraph(configured: configured);
    final seen = <String>{center};
    var frontier = [center];
    for (var d = 0; d < depth; d++) {
      final next = <String>[];
      for (final id in frontier) {
        for (final nb in adj[id] ?? const <String>{}) {
          if (seen.add(nb)) next.add(nb);
        }
      }
      frontier = next;
    }
    return _keep(seen);
  }

  /// Hide node kinds (legend chips) and, optionally, orphans (notes with no links at all).
  VaultGraph filtered({Set<String> hiddenKinds = const {}, bool orphans = true}) {
    final adj = adjacency();
    return _keep({
      for (final n in nodes)
        if (!hiddenKinds.contains(n.kind) && (orphans || (adj[n.id]?.isNotEmpty ?? false))) n.id,
    });
  }
}

class VaultHit {
  final String path;
  final String title;
  final String snippet;
  const VaultHit({required this.path, required this.title, this.snippet = ''});
  factory VaultHit.fromJson(Map<String, dynamic> j) =>
      VaultHit(path: '${j['path'] ?? ''}', title: '${j['title'] ?? ''}', snippet: '${j['snippet'] ?? ''}');
}

/// What the vault screens read (the live gateway, or a fake in tests).
abstract interface class VaultApi {
  Future<VaultTree> vaultTree();
  Future<VaultNote> vaultNote(String path);
  Future<VaultGraph> vaultGraph();
  Future<List<VaultHit>> vaultSearch(String q);
}
