// Settings persisted with shared_preferences; secrets (API keys, gateway
// token) with flutter_secure_storage — never in plain prefs.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../data/agent_runtime.dart';
import '../data/platform_caps.dart';
import '../data/llm_client.dart';
import '../models/chat_options.dart';
import '../models/models.dart';

class SettingsController extends ChangeNotifier {
  SettingsController(this._prefs);
  final SharedPreferences _prefs;
  final FlutterSecureStorage _secure = const FlutterSecureStorage();

  // connection
  ConnectionMode mode = ConnectionMode.local;
  String serverUrl = 'http://10.0.2.2:3000';
  String gatewayUrl = 'http://10.0.2.2:9319';
  String gatewayToken = '';
  Map<String, String> gatewayHeaders = {};
  String gatewayProfile = '';
  int pollMs = 4000;

  // providers
  List<ProviderConfig> providers = [];
  String activeProviderId = '';
  final Map<String, String> _keys = {};

  // tools
  Set<String> enabledTools = allTools.map((t) => t.name).toSet();

  // chat defaults (Pengaturan → Chat & thinking) and per-session overrides
  ChatOptions chatDefaults = const ChatOptions();
  final Map<String, Map<String, dynamic>> _sessionOptions = {};

  // appearance
  String themeName = 'neovarch';
  ThemeMode themeMode = ThemeMode.light; // light = the red brand base
  String fontChoice = 'tema';
  double chatScale = 1.1; // Desktop: Chat Text Size 110% by default
  bool showReasoning = true;

  // voice
  bool readAloud = false;
  String sttLocale = 'id_ID';
  /// Dictation route (1.4.9): `auto` (phone recogniser, PC as fallback) or `pc`.
  String dictationEngine = 'auto';
  /// Send the dictated text right away (off: it lands in the field to review).
  bool dictationAutoSend = false;
  double ttsRate = 0.5;

  // behaviour
  bool onboarded = false;
  bool introSeen = false; // the v1.1 brand intro carousel
  String defaultProfile = 'neovarch';
  bool autoRunTasks = true;
  bool resumeLastSession = true;
  String lastSessionId = '';
  String updateRepo = '';

  static const appVersion = '1.4.8';

  Future<void> load() async {
    final p = _prefs;
    mode = ConnectionMode.values.firstWhere((m) => m.name == p.getString('mode'), orElse: () => ConnectionMode.local);
    serverUrl = p.getString('serverUrl') ?? serverUrl;
    gatewayUrl = p.getString('gatewayUrl') ?? gatewayUrl;
    gatewayProfile = p.getString('gatewayProfile') ?? '';
    pollMs = p.getInt('pollMs') ?? 4000;
    try {
      gatewayHeaders = Map<String, String>.from(jsonDecode(p.getString('gatewayHeaders') ?? '{}') as Map);
    } catch (_) {}
    try {
      providers = ((jsonDecode(p.getString('providers') ?? '[]') as List))
          .map((e) => ProviderConfig.fromJson(Map<String, dynamic>.from(e)))
          .toList();
    } catch (_) {}
    activeProviderId = p.getString('activeProvider') ?? (providers.isNotEmpty ? providers.first.id : '');
    // Tools are stored as the DISABLED list so tools added in an update are
    // on by default. v1.0 stored the enabled list: migrate it once.
    final all = allTools.map((t) => t.name).toSet();
    final disabled = p.getStringList('disabledTools');
    if (disabled != null) {
      enabledTools = all.difference(disabled.toSet());
    } else {
      final old = p.getStringList('enabledTools');
      enabledTools = old == null ? all : all.difference(v10ToolNames.difference(old.toSet()));
    }
    try {
      chatDefaults = ChatOptions.fromJson(Map<String, dynamic>.from(jsonDecode(p.getString('chatDefaults') ?? '{}') as Map));
      final so = jsonDecode(p.getString('sessionOptions') ?? '{}') as Map;
      so.forEach((k, v) => _sessionOptions['$k'] = Map<String, dynamic>.from(v as Map));
    } catch (_) {}
    themeName = p.getString('theme') ?? 'neovarch';
    themeMode = ThemeMode.values.firstWhere((m) => m.name == p.getString('themeMode'), orElse: () => ThemeMode.light);
    // Neovarch rebrand: move existing installs onto the red brand theme once.
    if (p.getBool('brandRed') != true) {
      themeName = 'neovarch';
      themeMode = ThemeMode.light;
      p.setBool('brandRed', true);
      p.setString('theme', themeName);
      p.setString('themeMode', themeMode.name);
    }
    fontChoice = p.getString('font') ?? 'tema';
    chatScale = p.getDouble('chatScale') ?? 1.1;
    showReasoning = p.getBool('showReasoning') ?? true;
    readAloud = p.getBool('readAloud') ?? false;
    sttLocale = p.getString('sttLocale') ?? 'id_ID';
    dictationEngine = p.getString('dictationEngine') ?? 'auto';
    dictationAutoSend = p.getBool('dictationAutoSend') ?? false;
    ttsRate = p.getDouble('ttsRate') ?? 0.5;
    onboarded = p.getBool('onboarded') ?? false;
    introSeen = p.getBool('introSeen') ?? false;
    defaultProfile = p.getString('defaultProfile') ?? 'neovarch';
    autoRunTasks = p.getBool('autoRunTasks') ?? true;
    resumeLastSession = p.getBool('resumeLast') ?? true;
    lastSessionId = p.getString('lastSession') ?? '';
    updateRepo = p.getString('updateRepo') ?? '';
    try {
      gatewayToken = await _secRead('gateway.token') ?? '';
      for (final pr in providers) {
        final k = await _secRead('key.${pr.id}');
        if (k != null) _keys[pr.id] = k;
      }
    } catch (_) {
      // Keystore unavailable (rare emulator images): run without secrets.
    }
  }

  void _save() {
    final p = _prefs;
    p.setString('mode', mode.name);
    p.setString('serverUrl', serverUrl);
    p.setString('gatewayUrl', gatewayUrl);
    p.setString('gatewayProfile', gatewayProfile);
    p.setString('gatewayHeaders', jsonEncode(gatewayHeaders));
    p.setInt('pollMs', pollMs);
    p.setString('providers', jsonEncode(providers.map((e) => e.toJson()).toList()));
    p.setString('activeProvider', activeProviderId);
    p.setStringList('disabledTools', allTools.map((t) => t.name).where((n) => !enabledTools.contains(n)).toList());
    p.setString('chatDefaults', chatDefaults.encode());
    p.setString('sessionOptions', jsonEncode(_sessionOptions));
    p.setString('theme', themeName);
    p.setString('themeMode', themeMode.name);
    p.setString('font', fontChoice);
    p.setDouble('chatScale', chatScale);
    p.setBool('showReasoning', showReasoning);
    p.setBool('readAloud', readAloud);
    p.setString('sttLocale', sttLocale);
    p.setString('dictationEngine', dictationEngine);
    p.setBool('dictationAutoSend', dictationAutoSend);
    p.setDouble('ttsRate', ttsRate);
    p.setBool('onboarded', onboarded);
    p.setBool('introSeen', introSeen);
    p.setString('defaultProfile', defaultProfile);
    p.setBool('autoRunTasks', autoRunTasks);
    p.setBool('resumeLast', resumeLastSession);
    p.setString('lastSession', lastSessionId);
    p.setString('updateRepo', updateRepo);
  }

  void update(void Function(SettingsController s) f) {
    f(this);
    _save();
    notifyListeners();
  }

  /// Remember the last session without rebuilding the whole tree.
  void rememberSession(String id) {
    lastSessionId = id;
    _prefs.setString('lastSession', id);
  }

  // -------------------------------------------------------------- secrets --
  // Desktop note: Linux needs a Secret Service keyring (GNOME Keyring /
  // KWallet). When none is running, secrets fall back to app prefs on
  // desktop only so keys survive a restart; mobile always uses the keystore.
  static const _fallbackPrefix = 'secfallback.';

  Future<String?> _secRead(String key) async {
    try {
      final v = await _secure.read(key: key);
      if (v != null || !isDesktop) return v;
    } catch (_) {
      if (!isDesktop) rethrow;
    }
    return _prefs.getString('$_fallbackPrefix$key');
  }

  Future<void> _secWrite(String key, String value) async {
    try {
      await _secure.write(key: key, value: value);
      if (isDesktop) await _prefs.remove('$_fallbackPrefix$key');
    } catch (_) {
      if (!isDesktop) rethrow;
      await _prefs.setString('$_fallbackPrefix$key', value);
    }
  }

  Future<void> _secDelete(String key) async {
    try {
      await _secure.delete(key: key);
    } catch (_) {
      if (!isDesktop) rethrow;
    }
    if (isDesktop) await _prefs.remove('$_fallbackPrefix$key');
  }

  String keyFor(String providerId) => _keys[providerId] ?? '';
  bool hasKey(String providerId) => (_keys[providerId] ?? '').isNotEmpty;

  Future<void> setKey(String providerId, String key) async {
    if (key.isEmpty) {
      _keys.remove(providerId);
      await _secDelete('key.$providerId');
    } else {
      _keys[providerId] = key;
      await _secWrite('key.$providerId', key);
    }
    notifyListeners();
  }

  Future<void> setGatewayToken(String t) async {
    gatewayToken = t;
    await _secWrite('gateway.token', t);
    notifyListeners();
  }

  // ------------------------------------------------------------ providers --
  ProviderConfig? get activeProvider =>
      providers.where((p) => p.id == activeProviderId).firstOrNull ?? providers.firstOrNull;

  Future<void> upsertProvider(ProviderConfig p, {String? key, bool activate = false}) async {
    final i = providers.indexWhere((x) => x.id == p.id);
    if (i >= 0) {
      providers[i] = p;
    } else {
      providers.add(p);
    }
    if (activate || activeProviderId.isEmpty) activeProviderId = p.id;
    if (key != null) await setKey(p.id, key);
    _save();
    notifyListeners();
  }

  Future<void> removeProvider(String id) async {
    providers.removeWhere((p) => p.id == id);
    await setKey(id, '');
    if (activeProviderId == id) activeProviderId = providers.isNotEmpty ? providers.first.id : '';
    _save();
    notifyListeners();
  }

  /// Options for a chat session: its own overrides on top of the defaults.
  ChatOptions optionsFor(String sessionId) {
    final o = _sessionOptions[sessionId];
    return o == null ? chatDefaults : ChatOptions.fromJson(o, chatDefaults);
  }

  bool hasSessionOptions(String sessionId) => _sessionOptions.containsKey(sessionId);

  void setSessionOptions(String sessionId, ChatOptions? o) {
    if (o == null) {
      _sessionOptions.remove(sessionId);
    } else {
      _sessionOptions[sessionId] = o.toJson();
    }
    _save();
    notifyListeners();
  }

  LlmClient? llmClientFor(String providerId) {
    final p = providers.where((x) => x.id == providerId).firstOrNull;
    if (p == null) return null;
    return LlmClient(baseUrl: p.baseUrl, apiKey: keyFor(p.id), model: p.model);
  }

  LlmClient? llmClient() {
    final p = activeProvider;
    if (p == null) return null;
    return LlmClient(baseUrl: p.baseUrl, apiKey: keyFor(p.id), model: p.model);
  }

  bool get llmConfigured => llmClient()?.configured == true;
}
