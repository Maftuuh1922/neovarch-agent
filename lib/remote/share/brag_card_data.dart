// Kartu Neovarch: everything the brag card shows, gathered from what the phone
// already has (GitHub profile, the PC's Office snapshot, Kanban, sessions,
// default model) and scrubbed so nothing private ends up in a public post:
// no tokens, keys, file paths, host names or gateway URLs, only short labels
// and numbers.
import 'dart:typed_data';

import '../models_api.dart' show ModelRef;
import '../office_models.dart';
import '../remote_gateway.dart' show KanbanSnapshot;
import '../social_models.dart';
import '../../models/models.dart' show ChatSessionInfo;

/// The public landing page the QR code and "Salin tautan" point at
/// (GitHub Pages of the neorachAgent_lp repo; download buttons live there).
const kNeovarchLandingUrl = 'https://maftuuh1922.github.io/neorachAgent_lp/';

/// Card styles, swiped in the preview ("1 dari 3").
enum BragStyle { kaca, gelap, warna }

extension BragStyleX on BragStyle {
  String get label => switch (this) {
        BragStyle.kaca => 'Kaca',
        BragStyle.gelap => 'Gelap',
        BragStyle.warna => 'Warna-warni',
      };
}

/// Export formats (logical size × [kBragPixelRatio] = pixels).
enum BragFormat { story, feed }

const double kBragPixelRatio = 3;

extension BragFormatX on BragFormat {
  ({double w, double h}) get logical => this == BragFormat.story ? (w: 360.0, h: 640.0) : (w: 360.0, h: 360.0);
  ({int w, int h}) get pixels => (w: (logical.w * kBragPixelRatio).round(), h: (logical.h * kBragPixelRatio).round());
  String get label => this == BragFormat.story ? 'Story 9:16' : 'Feed 1:1';
}

class BragStats {
  const BragStats({this.agentsActive, this.agentsTotal, this.tasksDone, this.sessions, this.messages, this.model, this.tokensToday, this.tokensTotal});
  final int? agentsActive, agentsTotal, tasksDone, sessions, messages;
  final String? model;

  /// Token usage counted by the PC core (`GET /api/usage`, core ≥ 1.4.7): today
  /// (PC's local date) and lifetime, input + output. Null on older PCs.
  final int? tokensToday, tokensTotal;
  bool get isEmpty =>
      agentsActive == null && tasksDone == null && sessions == null && messages == null && model == null && tokensToday == null && tokensTotal == null;

  /// Number of stat tiles shown (the layouts make room for the token tiles).
  int get tileCount => [agentsActive, tasksDone, sessions, messages, tokensToday, tokensTotal].where((v) => v != null).length;
}

class BragCardData {
  const BragCardData({
    required this.name,
    this.login,
    this.avatarUrl,
    this.heatmap,
    this.stats = const BragStats(),
    this.officeShot,
    this.link = kNeovarchLandingUrl,
  });

  final String name;
  final String? login, avatarUrl;
  final SocialHeatmap? heatmap;
  final BragStats stats;

  /// JPEG/PNG of the Kantor 3D scene (WebGL canvas), if one was captured.
  final Uint8List? officeShot;
  final String link;

  BragCardData withOfficeShot(Uint8List? shot) =>
      BragCardData(name: name, login: login, avatarUrl: avatarUrl, heatmap: heatmap, stats: stats, officeShot: shot, link: link);

  /// Build from the remote controller's state. Every field is optional on
  /// purpose: a phone that is offline or not signed in to GitHub still gets a
  /// card ("Pengguna Neovarch").
  factory BragCardData.gather({
    SocialProfile? profile,
    OfficeSnapshot? office,
    KanbanSnapshot? board,
    List<ChatSessionInfo> sessions = const [],
    ModelRef? defaultModel,
    Uint8List? officeShot,
    Map<String, dynamic>? usage,
  }) {
    final login = safeHandle(profile?.login);
    final name = safeLabel(profile?.name, max: 32) ?? login ?? 'Pengguna Neovarch';
    int? done;
    if (board != null) {
      final lanes = board.lanes.where((l) => const {'done', 'selesai', 'completed', 'archived'}.contains(l.name.toLowerCase()));
      done = lanes.isEmpty ? null : lanes.fold<int>(0, (a, l) => a + l.cards.length);
    }
    done ??= office?.kanban['done'];
    final msgs = sessions.isEmpty ? null : sessions.fold<int>(0, (a, s) => a + s.messageCount);
    final model = office?.defaultModel ?? defaultModel;
    return BragCardData(
      name: name,
      login: login,
      avatarUrl: _safeAvatar(profile?.avatarUrl, login),
      heatmap: profile?.heatmap,
      officeShot: officeShot,
      stats: BragStats(
        agentsActive: office?.working,
        agentsTotal: office?.agents.length,
        tasksDone: done,
        sessions: sessions.isEmpty ? null : sessions.length,
        messages: msgs,
        model: safeModelName(model?.model),
        tokensToday: _usageTotal(usage, 'today'),
        tokensTotal: _usageTotal(usage, 'lifetime'),
      ),
    );
  }
}

/// `{"today": {"total": n}}` → n (null when absent; numbers only, nothing private).
int? _usageTotal(Map<String, dynamic>? usage, String key) {
  final b = usage?[key];
  if (b is! Map) return null;
  final t = b['total'];
  return t is num && t >= 0 ? t.toInt() : null;
}

final _secretLike = RegExp(r'(sk-|ghp_|gho_|github_pat_|xox[abp]-|AKIA|AIza|Bearer\s)', caseSensitive: false);
final _longToken = RegExp(r'[A-Za-z0-9_\-]{28,}');
final _pathLike = RegExp(r'(^~|^/|[A-Za-z]:\\|\\\\|/home/|/Users/|\.neovarch)');
final _urlLike = RegExp(r'(https?://|wss?://|\b\d{1,3}(\.\d{1,3}){3}\b|localhost|:\d{2,5}\b)', caseSensitive: false);

/// A short display label, or null when it looks like a secret, path or URL.
String? safeLabel(String? raw, {int max = 40}) {
  final s = (raw ?? '').replaceAll(RegExp(r'\s+'), ' ').trim();
  if (s.isEmpty) return null;
  if (_secretLike.hasMatch(s) || _longToken.hasMatch(s) || _pathLike.hasMatch(s) || _urlLike.hasMatch(s)) return null;
  return s.length > max ? '${s.substring(0, max - 1)}…' : s;
}

/// GitHub handle: letters, digits and dashes only.
String? safeHandle(String? raw) {
  final s = (raw ?? '').trim().replaceFirst(RegExp(r'^@'), '');
  return RegExp(r'^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$').hasMatch(s) ? s : null;
}

/// "openrouter/anthropic/claude-sonnet-4:free" -> "claude-sonnet-4"; a local
/// path or endpoint used as a model id is dropped.
String? safeModelName(String? raw) {
  var s = (raw ?? '').trim();
  if (s.isEmpty || _pathLike.hasMatch(s) || _urlLike.hasMatch(s) || _secretLike.hasMatch(s)) return null;
  s = s.split('/').last.split(':').first.trim();
  if (s.isEmpty || RegExp(r'[A-Za-z0-9]{32,}').hasMatch(s)) return null; // a key pasted as a model id
  return s.length > 26 ? '${s.substring(0, 25)}…' : s;
}

/// Only GitHub-hosted avatars (no private gateway / file URLs on the card).
String? _safeAvatar(String? url, String? login) {
  final u = Uri.tryParse(url ?? '');
  if (u != null && u.scheme == 'https' && (u.host == 'avatars.githubusercontent.com' || u.host == 'github.com')) return url;
  return login == null ? null : 'https://github.com/$login.png?size=160';
}
