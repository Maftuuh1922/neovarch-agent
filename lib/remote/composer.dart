// What the PC's desktop composer offers (skills, "/" commands, "@" mentions,
// prompt snippets, model, reasoning effort), read from the PC's
// `GET /api/composer/catalog`, plus the phone's current picks and the "/" / "@"
// trigger detection in the text field. A PC without the catalog (older
// version) yields no catalog and the composer shows its plain form.

/// One installed skill on the PC.
class ComposerSkill {
  const ComposerSkill(this.name, [this.description = '']);
  final String name;
  final String description;
  factory ComposerSkill.fromJson(Map<String, dynamic> j) => ComposerSkill('${j['name'] ?? ''}', '${j['description'] ?? ''}');
}

/// A built-in slash command (`/new`, `/model`).
class ComposerCommand {
  const ComposerCommand(this.name, [this.description = '']);
  final String name;
  final String description;
  factory ComposerCommand.fromJson(Map<String, dynamic> j) => ComposerCommand('${j['name'] ?? ''}', '${j['description'] ?? ''}');
}

/// Desktop "+" → prompt snippet.
class ComposerSnippet {
  const ComposerSnippet({required this.id, required this.label, required this.text, this.description = ''});
  final String id, label, text, description;
  factory ComposerSnippet.fromJson(Map<String, dynamic> j) => ComposerSnippet(
        id: '${j['id'] ?? ''}',
        label: '${j['label'] ?? ''}',
        text: '${j['text'] ?? ''}',
        description: '${j['description'] ?? ''}',
      );
}

/// One row in the "/" or "@" suggestion list.
class ComposerSuggestion {
  const ComposerSuggestion({required this.text, required this.display, this.meta = '', this.kind = 'mention', this.isDir = false});
  /// What picking it inserts (`@file:src/a.dart`, `/code-review`).
  final String text;
  final String display;
  final String meta;
  /// mention | folder | file | skill | command
  final String kind;
  final bool isDir;
  factory ComposerSuggestion.fromJson(Map<String, dynamic> j, {String? kind}) {
    final isDir = j['is_dir'] == true;
    final text = '${j['text'] ?? ''}';
    return ComposerSuggestion(
      text: text,
      display: '${j['display'] ?? j['name'] ?? text}',
      meta: '${j['meta'] ?? j['description'] ?? ''}',
      kind: kind ?? '${j['kind'] ?? (text.startsWith('@folder:') ? 'folder' : text.startsWith('@file:') ? 'file' : 'mention')}',
      isDir: isDir,
    );
  }
}

class ComposerModelProvider {
  const ComposerModelProvider({required this.slug, required this.name, required this.models, this.isCurrent = false});
  final String slug, name;
  final List<String> models;
  final bool isCurrent;
  factory ComposerModelProvider.fromJson(Map<String, dynamic> j) => ComposerModelProvider(
        slug: '${j['slug'] ?? ''}',
        name: '${j['name'] ?? j['slug'] ?? ''}',
        models: [for (final m in (j['models'] as List? ?? const [])) '$m'],
        isCurrent: j['is_current'] == true,
      );
}

/// The PC's desktop composer controls (catalog v1).
class ComposerCatalog {
  const ComposerCatalog({
    this.version = 1,
    this.skills = const [],
    this.commands = const [],
    this.snippets = const [],
    this.mentions = const [],
    this.model = '',
    this.provider = '',
    this.providers = const [],
    this.reasoningSupported = false,
    this.reasoningLevels = const [],
    this.reasoningLabels = const {},
    this.reasoningDefault = 'default',
    this.promptFields = const {},
  });
  final int version;
  final List<ComposerSkill> skills;
  final List<ComposerCommand> commands;
  final List<ComposerSnippet> snippets;
  final List<ComposerSuggestion> mentions;
  final String model, provider;
  final List<ComposerModelProvider> providers;
  final bool reasoningSupported;
  final List<String> reasoningLevels;
  final Map<String, String> reasoningLabels;
  final String reasoningDefault;
  /// `prompt.submit` fields this PC understands (skills, reasoning_effort).
  final Set<String> promptFields;

  bool get hasModels => providers.any((p) => p.models.isNotEmpty);
  bool get canSendSkills => promptFields.contains('skills');
  bool get canSendEffort => promptFields.contains('reasoning_effort') && reasoningSupported;

  /// Null unless the PC really answered a catalog (the core answers unknown
  /// routes with `{available: false}`; older PCs 404).
  static ComposerCatalog? tryParse(Object? json) {
    if (json is! Map) return null;
    final j = Map<String, dynamic>.from(json);
    final v = j['version'];
    if (v is! int || v < 1) return null;
    List<Map<String, dynamic>> list(Object? o) => [for (final e in (o is List ? o : const [])) if (e is Map) Map<String, dynamic>.from(e)];
    final models = j['models'] is Map ? Map<String, dynamic>.from(j['models'] as Map) : const <String, dynamic>{};
    final r = j['reasoning'] is Map ? Map<String, dynamic>.from(j['reasoning'] as Map) : const <String, dynamic>{};
    final f = j['features'] is Map ? Map<String, dynamic>.from(j['features'] as Map) : const <String, dynamic>{};
    return ComposerCatalog(
      version: v,
      skills: [for (final s in list(j['skills'])) ComposerSkill.fromJson(s)].where((s) => s.name.isNotEmpty).toList(),
      commands: [for (final c in list(j['commands'])) ComposerCommand.fromJson(c)].where((c) => c.name.isNotEmpty).toList(),
      snippets: [for (final s in list(j['snippets'])) ComposerSnippet.fromJson(s)].where((s) => s.text.isNotEmpty).toList(),
      mentions: [for (final m in list(j['mentions'])) ComposerSuggestion.fromJson(m, kind: 'mention')],
      model: '${models['model'] ?? ''}',
      provider: '${models['provider'] ?? ''}',
      providers: [for (final p in list(models['providers'])) ComposerModelProvider.fromJson(p)],
      reasoningSupported: r['supported'] == true,
      reasoningLevels: [for (final l in (r['levels'] as List? ?? const [])) '$l'],
      reasoningLabels: {
        if (r['labels'] is Map) for (final e in (r['labels'] as Map).entries) '${e.key}': '${e.value}',
      },
      reasoningDefault: '${r['default'] ?? 'default'}',
      promptFields: {for (final x in (f['prompt_fields'] as List? ?? const [])) '$x'},
    );
  }

  ComposerCatalog withModel(String provider, String model) => ComposerCatalog(
        version: version,
        skills: skills,
        commands: commands,
        snippets: snippets,
        mentions: mentions,
        model: model,
        provider: provider,
        providers: [
          for (final p in providers) ComposerModelProvider(slug: p.slug, name: p.name, models: p.models, isCurrent: p.slug == provider),
        ],
        reasoningSupported: reasoningSupported,
        reasoningLevels: reasoningLevels,
        reasoningLabels: reasoningLabels,
        reasoningDefault: reasoningDefault,
        promptFields: promptFields,
      );

  /// Label for a reasoning level ("default" = the provider's own default).
  String effortLabel(String? level) {
    if (level == null || level.isEmpty || level == 'default') return 'Bawaan';
    return reasoningLabels[level] ?? level;
  }
}

/// `prompt.submit` extras for the phone's current picks (only the fields the
/// PC said it understands, so an older PC never sees them).
Map<String, dynamic> composerSubmitFields(ComposerCatalog? c, {List<String> skills = const [], String? reasoningEffort}) => {
      if (c != null && c.canSendSkills && skills.isNotEmpty) 'skills': skills,
      if (c != null && c.canSendEffort && reasoningEffort != null && reasoningEffort.isNotEmpty && reasoningEffort != 'default')
        'reasoning_effort': reasoningEffort,
    };

/// A chat's reasoning level as the PC reports it (`session.info` /
/// `session.resume` → `reasoning_effort`) mapped onto the phone's pick: null =
/// Bawaan, and a level the current model does not offer falls back to Bawaan.
String? sessionEffort(Object? raw, ComposerCatalog? c) {
  final v = '${raw ?? ''}'.trim().toLowerCase();
  if (v.isEmpty || v == 'default' || v == 'null') return null;
  if (c != null && c.reasoningLevels.isNotEmpty && !c.reasoningLevels.contains(v)) return null;
  return v;
}

/// A "/" or "@" token being typed at the cursor.
class ComposerTrigger {
  const ComposerTrigger(this.kind, this.query, this.start, this.end);
  /// '/' or '@'
  final String kind;
  final String query;
  /// Range of the token (including the trigger char) in the text.
  final int start, end;
  @override
  bool operator ==(Object other) => other is ComposerTrigger && other.kind == kind && other.query == query && other.start == start && other.end == end;
  @override
  int get hashCode => Object.hash(kind, query, start, end);
}

/// The trigger token ending at [cursor], if any. A token starts at the
/// beginning of the text or after whitespace and runs to the cursor without
/// spaces (desktop rule; `@file:src/a b` is not supported, same as desktop
/// before the chip is placed).
ComposerTrigger? detectTrigger(String text, int cursor) {
  if (cursor < 0 || cursor > text.length) return null;
  var i = cursor - 1;
  while (i >= 0) {
    final ch = text[i];
    if (ch == ' ' || ch == '\n' || ch == '\t') return null;
    if (ch == '/' || ch == '@') {
      final atStart = i == 0 || text[i - 1] == ' ' || text[i - 1] == '\n' || text[i - 1] == '\t';
      if (!atStart) {
        // A slash inside a token (`@file:src/ma`) belongs to that token.
        i--;
        continue;
      }
      return ComposerTrigger(ch, text.substring(i + 1, cursor), i, cursor);
    }
    i--;
  }
  return null;
}

/// Replace the trigger token with [insert] (+ a trailing space unless it is a
/// folder/starter the user keeps typing into). Returns the new text and cursor.
({String text, int cursor}) applySuggestion(String text, ComposerTrigger t, String insert) {
  final keepOpen = insert.endsWith('/') || insert.endsWith(':');
  final value = keepOpen ? insert : '$insert ';
  final next = text.replaceRange(t.start, t.end, value);
  return (text: next, cursor: t.start + value.length);
}

/// Local "/" suggestions: built-in commands then skills, filtered by [query].
List<ComposerSuggestion> slashSuggestions(ComposerCatalog c, String query) {
  final q = query.toLowerCase();
  return [
    for (final cmd in c.commands)
      if (q.isEmpty || cmd.name.toLowerCase().contains(q))
        ComposerSuggestion(text: '/${cmd.name}', display: '/${cmd.name}', meta: cmd.description, kind: 'command'),
    for (final s in c.skills)
      if (q.isEmpty || s.name.toLowerCase().contains(q))
        ComposerSuggestion(text: '/${s.name}', display: '/${s.name}', meta: s.description, kind: 'skill'),
  ];
}
