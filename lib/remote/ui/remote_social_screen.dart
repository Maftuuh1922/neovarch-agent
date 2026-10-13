// Profil & Teman on the phone: the GitHub-backed profile (avatar, bio, 365-day
// heatmap in the accent colour, top stack, "lagi ngoding") and the friend
// list (mutual follows, coding first), read through the paired PC. The phone
// has no GitHub login and no username field: it syncs the PC's account; when
// the PC is signed out it can only ask the PC to start its device flow.
import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../theme/neovarch_mobile_theme.dart';
import '../../ui/widgets/common.dart' show CenterLoader;
import '../remote_controller.dart';
import '../social_models.dart';
import 'nv_widgets.dart';
import 'pc_github_signin.dart';
import 'tech_logo.dart';
import 'profile_header_slot.dart' show contributionColor;
import 'profile_share_card.dart' show showProfileShareSheet;

/// Test seam for avatars (network by default).
ImageProvider? Function(String? url) socialAvatarProvider = (url) => url == null || url.isEmpty ? null : NetworkImage(url);

class RemoteSocialScreen extends ConsumerStatefulWidget {
  const RemoteSocialScreen({super.key, this.autoLoad = true});
  final bool autoLoad;
  @override
  ConsumerState<RemoteSocialScreen> createState() => _RemoteSocialScreenState();
}

class _RemoteSocialScreenState extends ConsumerState<RemoteSocialScreen> {
  @override
  Widget build(BuildContext context) {
    final r = ref.watch(remoteProvider);
    final top = MediaQuery.paddingOf(context).top;
    return Scaffold(
      body: RefreshIndicator(
        onRefresh: r.refreshSocial,
        child: ListView(padding: EdgeInsets.only(top: top, bottom: 32 + MediaQuery.paddingOf(context).bottom), children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(8, 8, 16, 0),
            child: Row(children: [
              _BackLink(
                onPressed: () => Navigator.maybePop(context),
                child: Row(mainAxisSize: MainAxisSize.min, children: [
                  Icon(CupertinoIcons.chevron_back, size: 20, color: NV.red),
                  Text('PC', style: TextStyle(color: NV.redInk, fontSize: 16)),
                ]),
              ),
            ]),
          ),
          const NvHeader(kicker: 'github · lewat pc', title: 'Profil & Teman'),
          SocialSection(autoLoad: widget.autoLoad),
        ]),
      ),
    );
  }
}

/// The embeddable profile + friends block (no Scaffold): the Profil tab puts it
/// at its top; [RemoteSocialScreen] wraps it as a pushed page.
class SocialSection extends ConsumerStatefulWidget {
  const SocialSection({super.key, this.autoLoad = true, this.showProfile = true});
  final bool autoLoad;
  /// False on the Profil tab, whose header already shows the profile.
  final bool showProfile;
  @override
  ConsumerState<SocialSection> createState() => _SocialSectionState();
}

class _SocialSectionState extends ConsumerState<SocialSection> {
  @override
  void initState() {
    super.initState();
    if (widget.autoLoad) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) ref.read(remoteProvider).refreshSocial();
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final r = ref.watch(remoteProvider);
    final p = r.socialProfile;
    final f = r.socialFriends;
    return Column(key: const ValueKey('social-section'), crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
      if (r.socialError != null) const Padding(padding: EdgeInsets.fromLTRB(16, 0, 16, 12), child: SocialErrorBanner()),
      if (r.socialLoading && p == null && f == null)
        const SizedBox(height: 240, child: CenterLoader(label: 'memuat profil dari PC…'))
      else if (!r.socialSignedIn && r.socialError == null)
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          // The Profil tab's header already holds the sign-in card; here just
          // point at it instead of showing it twice.
          child: widget.showProfile
              ? const PcGithubSignInCard()
              : const NvNotice('Teman ikut akun GitHub yang masuk di PC. Masuk di PC dulu (kartu di atas).',
                  key: ValueKey('social-signed-out'), icon: CupertinoIcons.desktopcomputer),
        )
      else ...[
        if (p != null && widget.showProfile) Padding(padding: const EdgeInsets.symmetric(horizontal: 16), child: SocialProfileCard(profile: p)),
        if (p != null && widget.showProfile)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 10, 16, 0),
            child: OutlinedButton.icon(
              key: const ValueKey('share-profile'),
              onPressed: () => showProfileShareSheet(context, p, gistUrl: p.gistUrl),
              icon: const Icon(CupertinoIcons.share, size: 18),
              label: const Text('Bagikan profil'),
            ),
          ),
        NvSection('teman', count: f?.friends.length, trailing: (f?.codingCount ?? 0) > 0 ? NvPill('${f!.codingCount} lagi ngoding', color: NV.red) : null),
        if (f == null || f.friends.isEmpty)
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: 16),
            child: NvEmpty(title: 'Belum ada teman', body: 'Teman = akun GitHub yang saling follow. Tambah teman dari Neovarch di PC.'),
          )
        else
          NvList(children: [
            for (final fr in f.friends)
              FriendTile(
                friend: fr,
                onTap: () => Navigator.push(context, CupertinoPageRoute(builder: (_) => RemoteFriendScreen(login: fr.login, card: fr))),
              ),
          ]),
        if (f != null && f.pending.isNotEmpty) ...[
          const NvSection('menunggu follow balik'),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 20),
            child: Text(f.pending.join(' · '), style: TextStyle(fontSize: 13, color: NV.muted)),
          ),
        ],
      ],
    ]);
  }
}

class NvAvatar extends StatelessWidget {
  const NvAvatar({super.key, required this.name, this.url, this.size = 40});
  final String name;
  final String? url;
  final double size;
  @override
  Widget build(BuildContext context) {
    final img = socialAvatarProvider(url);
    // The initial is always painted underneath, so the circle never shows up
    // blank while the photo loads or when it can't be fetched (offline).
    final initial = Text(name.isEmpty ? '?' : name.characters.first.toUpperCase(),
        style: TextStyle(color: NV.onRed, fontWeight: FontWeight.w600, fontSize: size * 0.4));
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(shape: BoxShape.circle, color: NV.red),
      alignment: Alignment.center,
      child: img == null
          ? initial
          : Stack(fit: StackFit.expand, alignment: Alignment.center, children: [
              Center(child: initial),
              ClipOval(
                child: Image(
                  image: img,
                  fit: BoxFit.cover,
                  gaplessPlayback: true,
                  frameBuilder: (_, child, frame, sync) => sync || frame != null ? child : const SizedBox.shrink(),
                  errorBuilder: (_, _, _) => const SizedBox.shrink(),
                ),
              ),
            ]),
    );
  }
}

class CodingChip extends StatelessWidget {
  const CodingChip({super.key, required this.status});
  final CodingStatus? status;
  @override
  Widget build(BuildContext context) {
    final coding = status?.coding == true;
    final label = coding
        ? (status?.project != null ? 'Lagi ngoding · ${status!.project}' : 'Lagi ngoding')
        : (status?.lastActiveAt != null ? 'Aktif ${socialAgo(status!.lastActiveAt)}' : 'Tidak aktif');
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: coding ? NV.red : NV.border),
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        NvDot(coding ? NV.red : NV.faint, size: 7),
        const SizedBox(width: 6),
        Text(label, style: TextStyle(fontSize: 12, color: coding ? NV.text : NV.muted)),
      ]),
    );
  }
}

/// GitHub-style contribution grid: 7 rows, ~53 week columns, accent levels.
class SocialHeatmapView extends StatelessWidget {
  const SocialHeatmapView({super.key, required this.heatmap, this.cell = 5.0, this.gap = 1.6});
  final SocialHeatmap heatmap;
  final double cell, gap;

  /// Same accent mapping as the Profil contribution graph.
  static Color levelColor(int level) => contributionColor(level);

  @override
  Widget build(BuildContext context) {
    final weeks = heatmap.weeks();
    return LayoutBuilder(builder: (context, c) {
      // fit all weeks in the available width
      final n = weeks.length.clamp(1, 60);
      final size = ((c.maxWidth - gap * (n - 1)) / n).clamp(3.0, 12.0);
      return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SizedBox(
          key: const ValueKey('social-heatmap'),
          height: size * 7 + gap * 6,
          child: CustomPaint(
            size: Size(c.maxWidth, size * 7 + gap * 6),
            painter: _HeatPainter(weeks, heatmap.max, size, gap),
          ),
        ),
        const SizedBox(height: 8),
        Text('${heatmap.total} aktivitas · ${heatmap.activeDays} hari aktif · streak ${heatmap.streak} hari',
            maxLines: 1, overflow: TextOverflow.ellipsis, style: NV.monoLabel(size: 9.5, color: NV.muted)),
        const SizedBox(height: 6),
        Row(mainAxisAlignment: MainAxisAlignment.end, children: [
          Text('sedikit ', style: NV.monoLabel(size: 9, color: NV.faint)),
          for (var l = 0; l <= 4; l++)
            Container(
              width: 8,
              height: 8,
              margin: const EdgeInsets.only(left: 2),
              decoration: BoxDecoration(color: levelColor(l), borderRadius: BorderRadius.circular(2)),
            ),
          Text(' banyak', style: NV.monoLabel(size: 9, color: NV.faint)),
        ]),
      ]);
    });
  }
}

class _HeatPainter extends CustomPainter {
  _HeatPainter(this.weeks, this.max, this.cell, this.gap);
  final List<List<int>> weeks;
  final int max;
  final double cell, gap;
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint();
    final r = Radius.circular(cell * 0.28);
    for (var w = 0; w < weeks.length; w++) {
      for (var d = 0; d < 7; d++) {
        final v = weeks[w][d];
        if (v < 0) continue;
        paint.color = SocialHeatmapView.levelColor(SocialHeatmap.level(v, max));
        canvas.drawRRect(RRect.fromRectAndRadius(Rect.fromLTWH(w * (cell + gap), d * (cell + gap), cell, cell), r), paint);
      }
    }
  }

  @override
  bool shouldRepaint(_HeatPainter old) => old.weeks != weeks || old.max != max || old.cell != cell;
}

class StackChips extends StatelessWidget {
  const StackChips({super.key, required this.items});
  final List<StackItem> items;
  @override
  Widget build(BuildContext context) => Wrap(spacing: 6, runSpacing: 6, children: [
        for (final it in items)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
            decoration: BoxDecoration(
              color: NV.redWash,
              borderRadius: BorderRadius.circular(999),
              border: Border.all(color: NV.red.withValues(alpha: 0.35)),
            ),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              Text(it.name, style: TextStyle(fontSize: 12.5, color: NV.text)),
              const SizedBox(width: 5),
              Text('${(it.share * 100).round()}%', style: NV.monoLabel(size: 9.5, color: NV.muted)),
            ]),
          ),
      ]);
}

class SocialProfileCard extends StatelessWidget {
  const SocialProfileCard({super.key, required this.profile});
  final SocialProfile profile;
  @override
  Widget build(BuildContext context) {
    final p = profile;
    return NvPanel(
      key: const ValueKey('social-profile'),
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 16),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          NvAvatar(name: p.displayName, url: p.avatarUrl, size: 60),
          const SizedBox(width: 14),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(p.displayName, maxLines: 1, overflow: TextOverflow.ellipsis, style: NV.display(size: 26)),
              if (p.login != null) Text('@${p.login}', style: TextStyle(fontFamily: NV.mono, fontSize: 12, color: NV.muted)),
              if (p.bio.isNotEmpty) ...[
                const SizedBox(height: 6),
                Text(p.bio, style: TextStyle(fontSize: 13.5, color: NV.text, height: 1.4)),
              ],
              const SizedBox(height: 8),
              CodingChip(status: p.status),
            ]),
          ),
        ]),
        if (p.heatmap != null) ...[
          const SizedBox(height: 16),
          Text('AKTIVITAS 365 HARI', style: NV.monoLabel(size: 9.5)),
          const SizedBox(height: 8),
          SocialHeatmapView(heatmap: p.heatmap!),
        ],
        if (p.languages.isNotEmpty) ...[
          const SizedBox(height: 16),
          Text('STACK YANG SERING DIPAKAI', style: NV.monoLabel(size: 9.5)),
          const SizedBox(height: 8),
          TechStackChips(items: p.languages.take(8).toList()),
        ],
        if (p.tools.isNotEmpty) ...[
          const SizedBox(height: 12),
          Text('ALAT AGEN', style: NV.monoLabel(size: 9.5)),
          const SizedBox(height: 8),
          StackChips(items: p.tools.take(6).toList()),
        ],
      ]),
    );
  }
}

class FriendTile extends StatelessWidget {
  const FriendTile({super.key, required this.friend, required this.onTap});
  final FriendCard friend;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    final f = friend;
    final sub = f.coding
        ? (f.project != null ? 'Lagi ngoding · ${f.project}' : 'Lagi ngoding')
        : (!f.hasNeovarch ? 'Belum pakai Neovarch' : (f.lastActiveAt != null ? 'Aktif ${socialAgo(f.lastActiveAt)}' : 'Tidak aktif'));
    return InkWell(
      key: ValueKey('friend-${f.login}'),
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
        child: Row(children: [
          Stack(clipBehavior: Clip.none, children: [
            NvAvatar(name: f.name, url: f.avatarUrl, size: 40),
            Positioned(
              right: -1,
              bottom: -1,
              child: Container(
                width: 13,
                height: 13,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: f.coding ? NV.red : NV.faint,
                  border: Border.all(color: NV.surface, width: 2),
                ),
              ),
            ),
          ]),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(f.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 15, color: NV.text, fontWeight: FontWeight.w500)),
              const SizedBox(height: 2),
              Text(sub, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 12.5, color: f.coding ? NV.redInk : NV.muted)),
            ]),
          ),
          if (f.topStack.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(left: 8),
              child: TechLogoRow(names: f.topStack),
            ),
          const SizedBox(width: 4),
          Icon(CupertinoIcons.chevron_forward, size: 16, color: NV.faint),
        ]),
      ),
    );
  }
}

class RemoteFriendScreen extends ConsumerStatefulWidget {
  const RemoteFriendScreen({super.key, required this.login, this.card, this.debugDetail});
  final String login;
  final FriendCard? card;
  final FriendDetail? debugDetail;
  @override
  ConsumerState<RemoteFriendScreen> createState() => _RemoteFriendScreenState();
}

class _RemoteFriendScreenState extends ConsumerState<RemoteFriendScreen> {
  FriendDetail? detail;
  String? error;

  @override
  void initState() {
    super.initState();
    detail = widget.debugDetail;
    if (detail == null) {
      ref.read(remoteProvider).friendDetail(widget.login).then((d) {
        if (mounted) setState(() => detail = d);
      }, onError: (Object e) {
        if (mounted) setState(() => error = '$e');
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final d = detail;
    final card = d?.card ?? widget.card;
    final profile = d?.profile ??
        (card == null
            ? null
            : SocialProfile(
                login: card.login,
                name: card.name,
                bio: card.bio,
                avatarUrl: card.avatarUrl,
                status: CodingStatus(coding: card.coding, lastActiveAt: card.lastActiveAt, project: card.project)));
    return Scaffold(
      body: ListView(padding: EdgeInsets.only(top: MediaQuery.paddingOf(context).top, bottom: 32), children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(8, 8, 16, 0),
          child: Row(children: [
            _BackLink(
              onPressed: () => Navigator.maybePop(context),
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                Icon(CupertinoIcons.chevron_back, size: 20, color: NV.red),
                Text('Teman', style: TextStyle(color: NV.redInk, fontSize: 16)),
              ]),
            ),
            const Spacer(),
            if (card?.htmlUrl != null)
              NvIconButton(
                tooltip: 'Buka profil GitHub',
                icon: CupertinoIcons.arrow_up_right_square,
                onPressed: () => launchUrl(Uri.parse(card!.htmlUrl!), mode: LaunchMode.externalApplication),
              ),
          ]),
        ),
        const SizedBox(height: 8),
        if (error != null) Padding(padding: const EdgeInsets.all(16), child: NvNotice(error!)),
        if (profile != null) Padding(padding: const EdgeInsets.symmetric(horizontal: 16), child: SocialProfileCard(profile: profile)),
        if (d == null && error == null) const Padding(padding: EdgeInsets.all(24), child: CenterLoader()),
        if (d != null && d.profile == null)
          const Padding(
            padding: EdgeInsets.fromLTRB(16, 12, 16, 0),
            child: NvNotice('Teman ini belum memakai Neovarch, jadi belum ada grafik aktivitas atau stack.'),
          ),
      ]),
    );
  }
}

/// iOS-style "‹ Back" link in the accent colour.
class _BackLink extends StatelessWidget {
  const _BackLink({required this.onPressed, required this.child});
  final VoidCallback onPressed;
  final Widget child;
  @override
  Widget build(BuildContext context) => InkWell(
        borderRadius: BorderRadius.circular(NV.rCtl),
        onTap: onPressed,
        child: Padding(padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8), child: child),
      );
}
