// Chat with the agent on the PC: streamed replies, thinking, live tool rows
// and inline approval cards — the same transcript widgets as Desktop.
import 'dart:math' as math;

import 'package:flutter/cupertino.dart' show CupertinoIcons;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart' show ScrollDirection;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../data/platform_caps.dart';
import '../../models/models.dart' show ChatMsg;
import '../../state/app_controller.dart' show settingsProvider;
import '../../state/voice_service.dart';
import '../../theme/neovarch_mobile_theme.dart';
import '../../ui/screens/chat/message_widgets.dart';
import '../../ui/widgets/common.dart';
import '../agent_identity.dart';
import '../composer.dart';
import '../home_widget.dart' show remoteLaunchAction;
import '../remote_controller.dart';
import '../remote_gateway.dart';
import 'nv_glass_text.dart';
import 'glass/backdrop_luminance.dart';
import 'glass/glass_chat.dart';
import 'glass/liquid_glass.dart';
import 'nv_widgets.dart';
import 'remote_attachments.dart';
import 'model_picker.dart';
import 'remote_composer.dart';

class RemoteChatScreen extends ConsumerStatefulWidget {
  const RemoteChatScreen({super.key, required this.onOpenApprovals});
  final VoidCallback onOpenApprovals;
  @override
  ConsumerState<RemoteChatScreen> createState() => _RemoteChatScreenState();
}

class _RemoteChatScreenState extends ConsumerState<RemoteChatScreen> {
  final _input = TextEditingController();
  final _scroll = ScrollController();
  /// Height of the floating dock (approvals + composer) over the messages.
  double _dockH = 0;
  double _lastKb = 0;
  bool _dictating = false;
  /// Message ids already on screen; ids that arrive later play the glass
  /// "materialize" entrance once ([_fresh]).
  final _known = <String>{};
  final _fresh = <String>{};
  String? _knownSession;

  // Follow the newest message (1.4.5): on open and while replies stream the
  // list stays at the bottom, unless the user scrolled up to read; then a
  // floating ↓ (with the count of new messages) brings them back.
  static const _nearPx = 80.0;
  bool _follow = true;
  bool _atBottom = true;
  bool _settling = false;
  bool _settleQueued = false;
  int _unread = 0;
  String? _followKey;
  int _seenCount = 0;
  String _seenSig = '';

  void _followNewest(RemoteController r) {
    final msgs = r.transcript.messages;
    final key = '${r.storedId}|${r.runtimeId}|${r.opening}';
    if (key != _followKey) {
      // (re)opened session: land on the newest message
      _followKey = key;
      _follow = true;
      _unread = 0;
      _seenCount = msgs.length;
      _seenSig = _sig(msgs);
      if (msgs.isNotEmpty) _scrollToEnd();
      return;
    }
    final sig = _sig(msgs);
    if (sig == _seenSig) return;
    final added = msgs.length - _seenCount;
    if (_follow) {
      _scrollToEnd();
    } else if (added > 0) {
      _unread += msgs.skip(_seenCount).where((m) => m.role != 'user').length;
    }
    _seenCount = msgs.length;
    _seenSig = sig;
  }

  static String _sig(List<ChatMsg> msgs) {
    if (msgs.isEmpty) return '0';
    final l = msgs.last;
    return '${msgs.length}|${l.id}|${l.content.length}|${l.reasoning.length}|${l.tools.length}|${l.streaming}';
  }

  bool get _near {
    final p = _scroll.position;
    return p.maxScrollExtent - p.pixels <= _nearPx;
  }

  void _onScroll() {
    if (_settling || !_scroll.hasClients) return;
    final near = _near;
    // only the user's own scrolling changes whether we follow
    if (_scroll.position.userScrollDirection != ScrollDirection.idle || near) _follow = near;
    if (near) _unread = 0;
    if (near != _atBottom) setState(() => _atBottom = near);
  }

  /// Jump (or animate) to the real end. A lazy list only knows its true
  /// extent once the last items are built, so settle over a few frames.
  void _scrollToEnd({bool animate = false}) {
    if (_settleQueued) return;
    _settleQueued = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _settleQueued = false;
      _settle(animate);
    });
  }

  Future<void> _settle(bool animate) async {
    if (!mounted || !_scroll.hasClients) return;
    _settling = true;
    try {
      if (animate) {
        await _scroll.animateTo(_scroll.position.maxScrollExtent, duration: const Duration(milliseconds: 280), curve: Curves.easeOutCubic);
      }
      for (var i = 0; i < 8 && mounted && _scroll.hasClients; i++) {
        final p = _scroll.position;
        if ((p.maxScrollExtent - p.pixels).abs() < 0.5) break;
        _scroll.jumpTo(p.maxScrollExtent);
        await WidgetsBinding.instance.endOfFrame;
      }
    } finally {
      _settling = false;
    }
    if (!mounted || !_scroll.hasClients) return;
    final near = _near;
    if (near) {
      _follow = true;
      _unread = 0;
    }
    if (near != _atBottom || near) setState(() => _atBottom = near);
  }

  /// The list's extent changed without a scroll and without a new transcript
  /// state: the window/viewport resized (MIUI after the photo picker or the
  /// keyboard), a reasoning block folded, an image in a bubble loaded. While
  /// following, stay on the newest message instead of leaving the end of the
  /// reply under the composer and nav bar (1.4.5 report).
  bool _onMetrics(ScrollMetricsNotification n) {
    if (n.depth != 0 || _settling || !_scroll.hasClients) return false;
    final near = _near;
    if (_follow && !near) {
      _scrollToEnd();
    } else if (near != _atBottom) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) setState(() => _atBottom = near);
      });
    }
    return false;
  }

  void _jumpToLatest() {
    _follow = true;
    _unread = 0;
    setState(() => _atBottom = true);
    _scrollToEnd(animate: true);
  }

  void _track(RemoteController r) {
    final session = '${r.storedId}|${r.runtimeId}';
    final msgs = r.transcript.messages;
    if (session != _knownSession || r.opening) {
      // a (re)opened session shows its history without animation
      _knownSession = session;
      _known
        ..clear()
        ..addAll(msgs.map((m) => m.id));
      _fresh.clear();
      return;
    }
    for (final m in msgs) {
      if (_known.add(m.id)) _fresh.add(m.id);
    }
  }

  final _focus = FocusNode();

  // "/" and "@" suggestions (only when the PC serves the composer catalog)
  ComposerTrigger? _trigger;
  List<ComposerSuggestion> _suggestions = const [];
  bool _sugLoading = false;
  int _sugSeq = 0;
  bool _menuOpen = false;

  @override
  void initState() {
    super.initState();
    _input.addListener(_onInput);
    _scroll.addListener(_onScroll);
    remoteLaunchAction.addListener(_onLaunchAction);
    WidgetsBinding.instance.addPostFrameCallback((_) => _onLaunchAction());
  }

  /// Home-screen widget "Suara": start dictation once the PC is connected.
  bool _awaitLaunch = false;
  void _onLaunchAction() {
    if (!mounted || remoteLaunchAction.value != 'voice') return;
    final r = ref.read(remoteProvider);
    if (!r.connected) {
      // wait for the connection (the controller notifies on connect)
      if (_awaitLaunch) return;
      _awaitLaunch = true;
      void later() {
        if (mounted && (!r.connected)) return;
        r.removeListener(later);
        _awaitLaunch = false;
        _onLaunchAction();
      }
      r.addListener(later);
      return;
    }
    remoteLaunchAction.value = null;
    if (!_dictating) _dictate();
  }

  @override
  void dispose() {
    remoteLaunchAction.removeListener(_onLaunchAction);
    _input.removeListener(_onInput);
    _input.dispose();
    _scroll.dispose();
    _focus.dispose();
    super.dispose();
  }

  void _onInput() {
    final r = ref.read(remoteProvider);
    final c = r.composer;
    final sel = _input.selection;
    final t = c == null || !sel.isValid || !sel.isCollapsed ? null : detectTrigger(_input.text, sel.baseOffset);
    if (t == _trigger) return;
    if (t == null) {
      if (_trigger != null) setState(() => _trigger = null);
      return;
    }
    final seq = ++_sugSeq;
    if (t.kind == '/') {
      setState(() {
        _trigger = t;
        _suggestions = slashSuggestions(c!, t.query);
        _sugLoading = false;
      });
      return;
    }
    setState(() {
      _trigger = t;
      _sugLoading = true;
    });
    Future<void>.delayed(const Duration(milliseconds: 140), () async {
      if (seq != _sugSeq || !mounted) return;
      final items = await r.completeMentions(t.query);
      if (seq != _sugSeq || !mounted) return;
      setState(() {
        _suggestions = items;
        _sugLoading = false;
      });
    });
  }

  void _setText(String text, int cursor) {
    _input.value = TextEditingValue(text: text, selection: TextSelection.collapsed(offset: cursor));
  }

  void _pick(ComposerSuggestion s) {
    final t = _trigger;
    if (t == null) return;
    final r = ref.read(remoteProvider);
    if (s.kind == 'skill' || s.kind == 'command') {
      // The token becomes a chip (skill) or an action (command), not text.
      final text = _input.text.replaceRange(t.start, t.end, '').replaceFirst(RegExp(r'^ '), '');
      _sugSeq++;
      setState(() => _trigger = null);
      _setText(text, math.min(t.start, text.length));
      if (s.kind == 'skill') {
        final name = s.text.substring(1);
        if (!r.selectedSkills.contains(name)) r.toggleSkill(name);
      } else if (s.text == '/new') {
        r.newChat();
      } else if (s.text == '/model') {
        showModelSheet(context, r);
      }
      return;
    }
    final next = applySuggestion(_input.text, t, s.text);
    _setText(next.text, next.cursor);
    _focus.requestFocus();
  }

  /// Insert at the cursor with a separating space.
  void _insertText(String text) {
    final v = _input.value;
    final at = v.selection.isValid ? v.selection.baseOffset : v.text.length;
    final before = v.text.substring(0, at);
    final sep = before.isEmpty || before.endsWith(' ') || before.endsWith('\n') ? '' : ' ';
    final next = '$before$sep$text${v.text.substring(at)}';
    _setText(next, at + sep.length + text.length);
    _focus.requestFocus();
  }

  void _startMention() => _insertText('@');

  Future<void> _openMenu(RemoteController r) async {
    setState(() => _menuOpen = true);
    await showComposerMenu(context, r, ComposerActions(insertText: _insertText, startMention: _startMention));
    if (mounted) setState(() => _menuOpen = false);
  }

  /// Sending, opening a session, the keyboard coming up: back to the newest.
  void _toBottom() {
    _follow = true;
    _unread = 0;
    _scrollToEnd();
  }

  Future<void> _send([String? preset]) async {
    final text = (preset ?? _input.text).trim();
    final r = ref.read(remoteProvider);
    if (text.isEmpty && preset == null && r.pendingAttachments.isEmpty) return;
    if (text.isEmpty && preset != null) return;
    _follow = true;
    _input.clear();
    final err = await ref.read(remoteProvider).send(text);
    if (err != null && mounted) toast(context, err);
    _toBottom();
  }

  /// Mic: Android SpeechRecognizer (speech_to_text), Indonesian or English;
  /// partial words fill the field, the final result is sent to the agent.
  /// Long-press switches ID ↔ EN.
  Future<void> _dictate() async {
    final v = VoiceService.instance;
    if (_dictating) {
      await v.stopDictation();
      if (mounted) setState(() => _dictating = false);
      return;
    }
    setState(() => _dictating = true);
    var sent = false;
    await v.startDictation(
      locale: ref.read(settingsProvider).sttLocale,
      onText: (t, done) {
        if (!mounted) return;
        _input.text = t;
        _input.selection = TextSelection.collapsed(offset: t.length);
        if (done) {
          setState(() => _dictating = false);
          if (!sent && t.trim().isNotEmpty) {
            sent = true;
            _send();
          }
        }
      },
    );
    if (v.error != null && mounted) {
      setState(() => _dictating = false);
      toast(context, v.error!);
    }
  }

  void _switchSttLanguage() {
    final s = ref.read(settingsProvider);
    final en = s.sttLocale.startsWith('en');
    s.update((x) => x.sttLocale = en ? 'id_ID' : 'en_US');
    setState(() {});
    toast(context, en ? 'Dikte: Bahasa Indonesia' : 'Dictation: English');
  }

  void _sessions() => showPaperSheet(
        context: context,
        isScrollControlled: true,
        builder: (ctx) => _SessionsSheet(onPick: (id) {
          Navigator.pop(ctx);
          ref.read(remoteProvider).openSession(id).then((_) => _toBottom());
        }),
      );

  @override
  Widget build(BuildContext context) {
    final r = ref.watch(remoteProvider);
    final s = ref.watch(settingsProvider);
    final msgs = r.transcript.messages;
    final mine = r.approvals.where((a) => a.sessionId == r.runtimeId).toList();
    final others = r.approvals.length - mine.length;
    final pc = r.desktop?.name ?? 'PC';
    // the open session's pegawai (same name + avatar as Kantor and the desktop)
    final agent = r.office?.agents.where((a) => a.sessionId != null && (a.sessionId == r.storedId || a.sessionId == r.runtimeId)).firstOrNull;
    final tps = r.transcript.tokensPerSecond;

    _track(r);
    _followNewest(r);
    final empty = msgs.isEmpty && !r.opening;
    // Keyboard: the shell hides the nav pill and this screen does NOT let the
    // Scaffold shrink for it (the composer adds the keyboard inset itself);
    // both at once double-counted it and left the composer half a screen
    // above the keyboard (1.4.1 bug). Keep the newest message in view.
    final kb = MediaQuery.viewInsetsOf(context).bottom;
    if ((kb > 0) != (_lastKb > 0)) WidgetsBinding.instance.addPostFrameCallback((_) => _toBottom());
    _lastKb = kb;
    return GlassBackdrop(child: Scaffold(
      resizeToAvoidBottomInset: false,
      body: Column(children: [
        if (empty)
          _MinimalTopBar(
            onHistory: r.connected ? _sessions : null,
            onNew: r.connected ? r.newChat : null,
          )
        else ...[
        GlassChatHeader(
          kicker: 'chat · $pc',
          title: r.title.isNotEmpty ? r.title : (r.storedId == null ? 'Sesi baru' : 'Percakapan'),
          online: r.connected,
          status: '${r.statusLabel}${r.running ? ' · agen bekerja' : ''}${tps != null ? ' · ${tps.toStringAsFixed(0)} tok/s' : ''}',
          actions: [
            GlassHeaderAction(tooltip: 'Riwayat sesi di PC', icon: CupertinoIcons.clock, onPressed: r.connected ? _sessions : null),
            GlassHeaderAction(tooltip: 'Sesi baru', icon: CupertinoIcons.add, onPressed: r.connected ? r.newChat : null),
          ],
        ),
        ],
        // 1.4.2: approvals live in Chat. Inline cards for this session sit
        // above the composer; this pinned glass chip opens the full list.
        if (r.approvals.isNotEmpty)
          Padding(
            padding: EdgeInsets.fromLTRB(16, empty ? 8 : 10, 16, 0),
            child: Center(
              child: NvGlassChip(
                key: const ValueKey('chat-approvals-chip'),
                icon: CupertinoIcons.checkmark_shield_fill,
                label: '${r.approvals.length} menunggu persetujuan${others > 0 && mine.isNotEmpty ? ' · $others di sesi lain' : ''}',
                color: NV.red,
                onTap: widget.onOpenApprovals,
              ),
            ),
          ),
        // Messages run under the composer and the glass nav bar (both are
        // liquid glass), padded so the last message clears them at rest.
        Expanded(
          child: Stack(children: [
            Positioned.fill(
              child: r.opening
              ? const CenterLoader(label: 'membuka sesi di PC…')
              : msgs.isEmpty
                  ? _empty(context, r)
                  : NotificationListener<ScrollMetricsNotification>(
                    onNotification: _onMetrics,
                    child: BackdropGroup(child: ListView.builder(
                      controller: _scroll,
                      padding: EdgeInsets.fromLTRB(16, 16, 16, 12 + _dockH),
                      itemCount: msgs.length,
                      itemBuilder: (context, i) {
                        final m = msgs[i];
                        return Padding(
                          padding: const EdgeInsets.only(bottom: 18),
                          child: m.role == 'user'
                              ? (m.attachments.isEmpty
                                  ? GlassUserMessage(msg: m, scale: s.chatScale, appear: _fresh.remove(m.id))
                                  : Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                                      MessageAttachments(attachments: m.attachments, gateway: r.gateway),
                                      if (m.content.isNotEmpty) ...[
                                        const SizedBox(height: 6),
                                        GlassUserMessage(msg: m, scale: s.chatScale, appear: _fresh.remove(m.id)),
                                      ],
                                    ]))
                              : GlassAgentTurn(
                                  label: '${agent?.name ?? 'neovarch'} · $pc',
                                  avatar: agent == null ? null : NvAgentAvatar.of(agent, size: 18, dot: false),
                                  live: m.streaming,
                                  appear: _fresh.remove(m.id),
                                  child: AssistantMessage(
                                    msg: m,
                                    scale: s.chatScale,
                                    showReasoning: s.showReasoning,
                                    isLast: i == msgs.length - 1,
                                    onLink: (u) => launchUrl(Uri.parse(u), mode: LaunchMode.externalApplication),
                                    onOpenFile: (p) => openPcFile(context, r.gateway, p),
                                  ),
                                ),
                        );
                      },
                    ))),
            ),
            if (msgs.isNotEmpty && !r.opening)
              Positioned(
                right: 16,
                bottom: _dockH + 10,
                child: _ToLatestButton(visible: !_atBottom, unread: _unread, onTap: _jumpToLatest),
              ),
            Positioned(
              left: 0,
              right: 0,
              bottom: 0,
              child: NvSizeReporter(
                onHeight: (h) {
                  if ((h - _dockH).abs() > 0.5) {
                    setState(() => _dockH = h);
                    if (_follow) _scrollToEnd();
                  }
                },
                child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        for (final a in mine)
          NvApprovalCard(
            command: a.command,
            description: a.description,
            choices: a.choices,
            origin: a.toolName,
            color: NV.surface,
            onChoice: (c) async {
              final err = await r.respond(a, c);
              if (err != null && context.mounted) toast(context, err);
            },
          ),
        if (r.transcript.error != null && !r.running)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            child: GlassNotice(r.transcript.error!),
          ),
                  _composer(context, r),
                ]),
              ),
            ),
          ]),
        ),
      ]),
    ));
  }

  /// Minimal start: only a time-based greeting (the composer sits below).
  Widget _empty(BuildContext context, RemoteController r) => LayoutBuilder(
        builder: (context, c) => SingleChildScrollView(
          child: ConstrainedBox(
            constraints: BoxConstraints(minHeight: c.maxHeight),
            child: Center(
              child: Padding(
                padding: EdgeInsets.fromLTRB(28, 0, 28, _dockH),
                child: NvGlassText(greetingFor(DateTime.now()),
                    key: const ValueKey('chat-greeting'), textAlign: TextAlign.center, style: NV.display(size: 40)),
              ),
            ),
          ),
        ),
      );

  Widget _composer(BuildContext context, RemoteController r) {
    final s = ref.watch(settingsProvider);
    // At rest: above the nav pill (the shell reserves it in padding.bottom).
    // Keyboard open: 8px above the keyboard top (pill hidden).
    final bottom = MediaQuery.paddingOf(context).bottom;
    final kb = MediaQuery.viewInsetsOf(context).bottom;
    return Padding(
      key: const ValueKey('chat-composer-dock'),
      padding: EdgeInsets.fromLTRB(16, 6, 16, (kb > 0 ? kb : bottom) + 8),
      // themed liquid glass: the field's text / hint follow the glass tone
      child: LiquidGlass(
        key: const ValueKey('chat-composer'),
        themed: true,
        borderRadius: BorderRadius.circular(NV.rCard),
        padding: const EdgeInsets.fromLTRB(6, 6, 6, 6),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        AttachmentStrip(items: r.pendingAttachments, onRemove: r.removeAttachment),
        ComposerChipsRow(
          r: r,
          onModel: () => showModelSheet(context, r),
          onReasoning: () => showReasoningSheet(context, r),
          onSkills: () => showSkillPicker(context, r),
        ),
        if (_trigger != null && r.composer != null)
          ComposerSuggestionList(items: _suggestions, kind: _trigger!.kind, loading: _sugLoading, onPick: _pick),
        if (r.attachNotice != null && r.attachNotice!.isNotEmpty)
          Padding(
            padding: const EdgeInsets.fromLTRB(8, 2, 8, 4),
            child: Text(r.attachNotice!, key: const ValueKey('attach-notice'), style: TextStyle(fontSize: 12, color: NV.muted, height: 1.35)),
          ),
        const Align(alignment: Alignment.centerLeft, child: ModelChip()),
        Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
          // "+": uploads, and on a PC with the composer catalog also skills,
          // model, reasoning, mentions, URL and snippets (desktop parity).
          ComposerPlusButton(
            key: const ValueKey('attach-button'),
            open: _menuOpen,
            onPressed: r.connected ? () => _openMenu(r) : null,
          ),
          const SizedBox(width: 4),
          if (canDictate || VoiceService.hasTestEngine)
            KeyedSubtree(
              key: const ValueKey('composer-mic'),
              child: Stack(clipBehavior: Clip.none, children: [
                NvIconButton(
                  tooltip: _dictating ? 'Berhenti dikte' : 'Dikte perintah (tekan lama: ganti bahasa)',
                  icon: _dictating ? CupertinoIcons.mic_fill : CupertinoIcons.mic,
                  accent: _dictating,
                  onPressed: r.connected ? _dictate : null,
                  onLongPress: _switchSttLanguage,
                ),
                Positioned(
                  right: -2,
                  bottom: -2,
                  child: IgnorePointer(
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 3, vertical: 1),
                      decoration: BoxDecoration(color: NV.raised, borderRadius: BorderRadius.circular(5), border: Border.all(color: NV.border)),
                      child: Text(s.sttLocale.startsWith('en') ? 'EN' : 'ID', key: const ValueKey('composer-mic-lang'), style: TextStyle(fontSize: 8, fontWeight: FontWeight.w700, color: NV.muted)),
                    ),
                  ),
                ),
              ]),
            ),
          Expanded(
            child: TextField(
              controller: _input,
              focusNode: _focus,
              minLines: 1,
              maxLines: 5,
              enabled: r.connected,
              textInputAction: TextInputAction.send,
              onSubmitted: (_) => _send(),
              // Keyboard image insertion (Gboard paste of a screenshot / GIF).
              contentInsertionConfiguration: ContentInsertionConfiguration(
                allowedMimeTypes: kInsertableImageMimes,
                onContentInserted: (c) => attachInserted(context, r, c),
              ),
              // Long-press menu: "Tempel gambar" next to the usual paste.
              contextMenuBuilder: (context, editable) => AdaptiveTextSelectionToolbar.buttonItems(
                anchors: editable.contextMenuAnchors,
                buttonItems: [
                  ...editable.contextMenuButtonItems,
                  ContextMenuButtonItem(
                    label: 'Tempel gambar',
                    onPressed: () {
                      ContextMenuController.removeAny();
                      pasteClipboardImage(context, r);
                    },
                  ),
                ],
              ),
              style: const TextStyle(fontSize: 15, height: 1.4),
              decoration: InputDecoration(
                hintText: r.connected ? 'Ketik perintah untuk agen di PC…' : 'Menunggu koneksi ke PC…',
                border: InputBorder.none,
                enabledBorder: InputBorder.none,
                focusedBorder: InputBorder.none,
                disabledBorder: InputBorder.none,
                filled: false,
                isDense: true,
                contentPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 11),
              ),
            ),
          ),
          if (r.running)
            ComposerSendButton(key: const ValueKey('composer-stop'), stop: true, onPressed: r.stop)
          else
            ComposerSendButton(key: const ValueKey('composer-send'), onPressed: r.connected ? _send : null),
        ]),
        ]),
      ),
    );
  }
}

class _SessionsSheet extends ConsumerWidget {
  const _SessionsSheet({required this.onPick});
  final void Function(String id) onPick;
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final r = ref.watch(remoteProvider);
    return SafeArea(
      child: SizedBox(
        height: MediaQuery.sizeOf(context).height * 0.7,
        child: Column(children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 0, 16, 12),
            child: NvSheetTitle(
              kicker: 'riwayat · ${r.desktop?.name ?? 'pc'}',
              title: 'Sesi di PC',
              trailing: NvIconButton(tooltip: 'Segarkan', icon: CupertinoIcons.arrow_clockwise, onPressed: r.loadSessions),
            ),
          ),
          Expanded(
            child: r.sessionsLoading && r.sessions.isEmpty
                ? const CenterLoader()
                : r.sessions.isEmpty
                    ? const NvEmpty(title: 'Belum ada sesi', body: 'Percakapan yang dimulai di PC atau dari HP ini muncul di sini.')
                    : ListView(padding: const EdgeInsets.only(bottom: 16), children: [
                        NvList(children: [
                          for (final s in r.sessions)
                            NvRow(
                              icon: s.id == r.storedId ? CupertinoIcons.chat_bubble_fill : CupertinoIcons.chat_bubble,
                              accent: s.id == r.storedId,
                              title: s.title,
                              subtitle: '${relTime(s.updatedAt)} · ${s.messageCount} pesan',
                              mono: true,
                              trailing: r.active.any((a) => a.title == s.title && a.status == 'running')
                                  ? NvPill('jalan', color: NV.red)
                                  : null,
                              onTap: () => onPick(s.id),
                            ),
                        ]),
                      ]),
          ),
        ]),
      ),
    );
  }
}

/// Small helper so other tabs can show an approval with its session label.
String approvalOrigin(RemoteController r, RemoteApproval a) => r.sessionTitle(a.sessionId);

/// "Selamat pagi/siang/sore/malam" by the phone's local hour.
String greetingFor(DateTime t) {
  final h = t.hour;
  if (h >= 4 && h < 11) return 'Selamat pagi';
  if (h >= 11 && h < 15) return 'Selamat siang';
  if (h >= 15 && h < 18) return 'Selamat sore';
  return 'Selamat malam';
}

class _MinimalTopBar extends StatelessWidget {
  const _MinimalTopBar({required this.onHistory, required this.onNew});
  final VoidCallback? onHistory;
  final VoidCallback? onNew;
  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsets.fromLTRB(16, MediaQuery.paddingOf(context).top + 10, 12, 0),
        child: Row(mainAxisAlignment: MainAxisAlignment.end, children: [
          NvIconButton(tooltip: 'Riwayat sesi di PC', icon: CupertinoIcons.clock, onPressed: onHistory),
          const SizedBox(width: 6),
          NvIconButton(tooltip: 'Sesi baru', icon: CupertinoIcons.add, onPressed: onNew),
        ]),
      );
}


/// Floating "↓ newest" over the messages, with the count of replies that
/// arrived while the user was reading further up.
class _ToLatestButton extends StatelessWidget {
  const _ToLatestButton({required this.visible, required this.unread, required this.onTap});
  final bool visible;
  final int unread;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return IgnorePointer(
      ignoring: !visible,
      child: AnimatedOpacity(
        opacity: visible ? 1 : 0,
        duration: const Duration(milliseconds: 160),
        child: AnimatedScale(
          scale: visible ? 1 : 0.85,
          duration: const Duration(milliseconds: 160),
          child: Semantics(
            button: true,
            label: unread > 0 ? 'Ke pesan terbaru, $unread baru' : 'Ke pesan terbaru',
            child: GestureDetector(
              key: const ValueKey('chat-to-latest'),
              behavior: HitTestBehavior.opaque,
              onTap: onTap,
              child: Stack(clipBehavior: Clip.none, children: [
                LiquidGlass(
                  themed: true,
                  borderRadius: BorderRadius.circular(22),
                  child: const SizedBox(width: 44, height: 44, child: Icon(CupertinoIcons.arrow_down, size: 20)),
                ),
                if (unread > 0)
                  Positioned(
                    top: -4,
                    right: -4,
                    child: Container(
                      key: const ValueKey('chat-unread-badge'),
                      constraints: const BoxConstraints(minWidth: 20),
                      height: 20,
                      padding: const EdgeInsets.symmetric(horizontal: 5),
                      alignment: Alignment.center,
                      decoration: BoxDecoration(color: NV.red, borderRadius: BorderRadius.circular(10)),
                      child: Text(unread > 99 ? '99+' : '$unread',
                          style: TextStyle(color: NV.onRed, fontSize: 11, fontWeight: FontWeight.w700, height: 1)),
                    ),
                  ),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}
