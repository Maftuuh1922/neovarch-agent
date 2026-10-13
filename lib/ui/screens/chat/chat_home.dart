// Chat — the home surface. Transcript + composer stay primary; sessions
// sit in a drawer (phone) or a left column (wide); previews open on demand.
import 'dart:convert';

import 'package:flutter/material.dart';

import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../../../data/chat_engine.dart';
import '../../../data/device_tools.dart' show ensureCameraPermission;
import '../../../data/platform_caps.dart';
import '../../../models/models.dart';
import '../../../state/app_controller.dart';
import '../../../state/chat_controller.dart';
import '../../../state/voice_service.dart';
import '../../../remote/ui/dictation_strip.dart';
import '../../../theme/app_theme.dart';
import '../../widgets/common.dart';
import '../../widgets/preview_sheet.dart';
import '../settings/providers_screen.dart';
import 'chat_extras.dart';
import 'message_widgets.dart';
import 'sessions_panel.dart';

class ChatHome extends ConsumerStatefulWidget {
  const ChatHome({super.key});
  @override
  ConsumerState<ChatHome> createState() => _ChatHomeState();
}

class _ChatHomeState extends ConsumerState<ChatHome> {
  final _scaffold = GlobalKey<ScaffoldState>();
  bool _resumed = false;

  @override
  void initState() {
    super.initState();
    final chat = ref.read(chatProvider);
    final settings = ref.read(settingsProvider);
    chat.onReply = (text) {
      final s = ref.read(settingsProvider);
      if (s.readAloud) VoiceService.instance.speak(text, rate: s.ttsRate, language: s.sttLocale.replaceAll('_', '-'));
    };
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (_resumed || !settings.resumeLastSession) return;
      _resumed = true;
      await chat.loadSessions();
      final last = chat.sessions.where((s) => s.id == settings.lastSessionId).firstOrNull;
      if (last != null && chat.current == null) chat.open(last);
    });
  }

  @override
  Widget build(BuildContext context) {
    final chat = ref.watch(chatProvider);
    final wide = MediaQuery.sizeOf(context).width >= 840;
    final title = chat.current?.title ?? 'Neovarch';
    final body = ChatView(key: ValueKey(chat.current?.id ?? 'new'));
    final appBar = AppBar(
      automaticallyImplyLeading: false,
      leading: wide
          ? null
          : IconButton(icon: const Icon(Icons.menu), tooltip: 'Sesi', onPressed: () => _scaffold.currentState?.openDrawer()),
      titleSpacing: wide ? 16 : 0,
      title: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.tt.titleMedium),
        if (chat.current != null)
          Text(
            chat.engine.perAgentThreads ? 'thread agent ${chat.current!.profile}' : 'agent ${chat.current!.profile}',
            style: context.tt.bodySmall?.copyWith(fontSize: 11.5),
          ),
      ]),
      actions: [
        if (chat.current != null && chat.messages.isNotEmpty)
          IconButton(
            tooltip: 'Cari di chat',
            icon: const Icon(Icons.search, size: 21),
            onPressed: () async {
              final i = await showSearchSheet(context, ref);
              if (i != null) chatJump.value = i;
            },
          ),
        IconButton(
          tooltip: 'Pengaturan chat',
          icon: const Icon(Icons.tune, size: 20),
          onPressed: () => showChatSettingsSheet(context),
        ),
        if (chat.current != null && chat.messages.isNotEmpty)
          PopupMenuButton<String>(
            tooltip: 'Lainnya',
            onSelected: (v) => handleSlash(context, ref, '/$v'),
            itemBuilder: (_) => const [
              PopupMenuItem(value: 'usage', child: Text('Pemakaian & biaya')),
              PopupMenuItem(value: 'compress', child: Text('Kompres konteks')),
              PopupMenuItem(value: 'export', child: Text('Ekspor ke Markdown')),
              PopupMenuItem(value: 'undo', child: Text('Batalkan giliran terakhir')),
              PopupMenuItem(value: 'help', child: Text('Perintah slash')),
            ],
          ),
        if (chat.current != null && chat.engine.canRename)
          IconButton(
            tooltip: 'Ganti nama',
            icon: const Icon(Icons.edit_outlined, size: 20),
            onPressed: () async {
              final t = await promptText(context, title: 'Ganti nama sesi', initial: chat.current!.title);
              if (t != null && t.trim().isNotEmpty) await chat.rename(chat.current!, t.trim());
            },
          ),
        if (!chat.engine.perAgentThreads)
          IconButton(
            tooltip: 'Percakapan baru',
            icon: const Icon(Icons.edit_square, size: 20),
            onPressed: () => chat.newSession(),
          ),
        if (chat.engine.perAgentThreads && chat.current != null && chat.messages.isNotEmpty)
          IconButton(
            tooltip: 'Hapus riwayat percakapan ini',
            icon: const Icon(Icons.delete_sweep_outlined, size: 20),
            onPressed: () async {
              if (await confirmDialog(context,
                  title: 'Hapus riwayat?',
                  body: 'Pointer thread dilupakan. Riwayat tetap ada di penyimpanan sesi agen dan bisa dipulihkan.',
                  confirm: 'Hapus')) {
                final s = chat.current!;
                await chat.delete(s);
                chat.open(s);
              }
            },
          ),
        const SizedBox(width: 4),
      ],
    );

    if (wide) {
      return Scaffold(
        body: Row(children: [
          SizedBox(
            width: 300,
            child: DecoratedBox(
              decoration: BoxDecoration(border: Border(right: BorderSide(color: context.hc.sidebarBorder))),
              child: const SessionsPanel(),
            ),
          ),
          Expanded(child: Scaffold(appBar: appBar, body: body)),
        ]),
      );
    }
    return Scaffold(
      key: _scaffold,
      appBar: appBar,
      drawer: Drawer(width: 320, child: SessionsPanel(onPicked: () => Navigator.of(context).maybePop())),
      body: body,
    );
  }
}

/// Search → scroll to message index.
final chatJump = ValueNotifier<int?>(null);

class ChatView extends ConsumerStatefulWidget {
  const ChatView({super.key});
  @override
  ConsumerState<ChatView> createState() => _ChatViewState();
}

class _ChatViewState extends ConsumerState<ChatView> {
  final _scroll = ScrollController();
  bool _atBottom = true;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      final at = !_scroll.hasClients || _scroll.position.pixels >= _scroll.position.maxScrollExtent - 80;
      if (at != _atBottom) setState(() => _atBottom = at);
    });
  }

  int? _flash;

  void _jump() {
    final i = chatJump.value;
    if (i == null || !_scroll.hasClients) return;
    chatJump.value = null;
    final n = ref.read(chatProvider).messages.length;
    final target = (_scroll.position.maxScrollExtent * (i / (n <= 1 ? 1 : n - 1))).clamp(0.0, _scroll.position.maxScrollExtent);
    _scroll.animateTo(target, duration: const Duration(milliseconds: 380), curve: Curves.easeOutCubic);
    setState(() => _flash = i);
    Future.delayed(const Duration(milliseconds: 1600), () {
      if (mounted) setState(() => _flash = null);
    });
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    chatJump.removeListener(_jump);
    chatJump.addListener(_jump);
  }

  @override
  void dispose() {
    chatJump.removeListener(_jump);
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _messageMenu(ChatMsg m) async {
    final chat = ref.read(chatProvider);
    final user = m.role == 'user';
    final v = await showPaperSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(leading: const Icon(Icons.copy_rounded), title: const Text('Salin'), onTap: () => Navigator.pop(ctx, 'copy')),
          if (user && !chat.streaming) ListTile(leading: const Icon(Icons.edit_outlined), title: const Text('Sunting & kirim ulang'), onTap: () => Navigator.pop(ctx, 'edit')),
          if (!user && !chat.streaming) ListTile(leading: const Icon(Icons.refresh), title: const Text('Buat ulang jawaban'), onTap: () => Navigator.pop(ctx, 'regen')),
          if (!chat.streaming) ListTile(leading: const Icon(Icons.call_split), title: const Text('Cabangkan dari sini'), onTap: () => Navigator.pop(ctx, 'branch')),
        ]),
      ),
    );
    if (!mounted || v == null) return;
    switch (v) {
      case 'copy':
        await Clipboard.setData(ClipboardData(text: m.content));
        if (mounted) toast(context, 'Disalin');
      case 'edit':
        final t = await promptText(context, title: 'Sunting pesan', initial: m.content);
        if (t != null && t.trim().isNotEmpty) await chat.editAndResend(m, t.trim());
      case 'regen':
        await chat.regenerate(m);
      case 'branch':
        final s = await chat.branch(m);
        if (s != null && mounted) toast(context, 'Cabang dibuat: ${s.title}');
    }
  }

  void _follow() {
    // Follow new output only while the reader is near the bottom.
    if (!_atBottom) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) _scroll.jumpTo(_scroll.position.maxScrollExtent);
    });
  }

  void _openLink(String url) => showPreview(context, UrlPreview(url));

  void _openFile(String path) {
    final f = ref.read(storeProvider).readFile(path);
    if (f == null) {
      toast(context, 'Berkas $path tidak ada di workspace perangkat');
      return;
    }
    showPreview(context, FilePreview(f.path, f.content));
  }

  @override
  Widget build(BuildContext context) {
    final chat = ref.watch(chatProvider);
    final settings = ref.watch(settingsProvider);
    final scale = settings.chatScale;
    final opts = chat.current == null ? settings.chatDefaults : settings.optionsFor(chat.current!.id);
    _follow();
    final msgs = chat.messages.where((m) => m.role == 'user' || m.role == 'assistant').toList();
    final lastAssistant = msgs.lastIndexWhere((m) => m.role == 'assistant');

    Widget content;
    if (chat.historyLoading) {
      content = const CenterLoader(label: 'memuat riwayat');
    } else if (msgs.isEmpty) {
      content = _Welcome(onPick: (t) => chat.send(t));
    } else {
      content = ListView.builder(
        controller: _scroll,
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 20),
        itemCount: msgs.length,
        itemBuilder: (_, i) {
          final m = msgs[i];
          final flash = _flash != null && chat.messages.indexOf(m) == _flash;
          return Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 780),
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 400),
                decoration: BoxDecoration(
                  color: flash ? context.cs.primary.withValues(alpha: 0.12) : Colors.transparent,
                  borderRadius: BorderRadius.circular(context.hc.corner),
                ),
                padding: EdgeInsets.only(bottom: m.role == 'user' ? 14 : 18),
                child: GestureDetector(
                  onLongPress: () => _messageMenu(m),
                  child: EntranceFade(key: ValueKey('in${m.id}'), child: m.role == 'user'
                    ? UserBubble(msg: m, scale: scale)
                    : AssistantMessage(
                        msg: m,
                        scale: scale,
                        showReasoning: opts.showReasoning,
                        autoCollapse: opts.autoCollapseReasoning,
                        onLink: _openLink,
                        onOpenFile: _openFile,
                        isLast: i == lastAssistant,
                        onSpeak: () => VoiceService.instance.speak(m.content, rate: settings.ttsRate, language: settings.sttLocale.replaceAll('_', '-')),
                        onRetry: chat.streaming ? null : chat.retry,
                        onSwitchProvider: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const ProvidersScreen())),
                        onRegenerate: chat.streaming ? null : () => chat.regenerate(m),
                      ),
                  ),
                ),
              ),
            ),
          );
        },
      );
    }

    return Column(children: [
      if (chat.error != null && msgs.isEmpty) ErrorBanner(chat.error!, dense: true),
      Expanded(
        child: Stack(children: [
          Positioned.fill(child: content),
          if (!_atBottom && msgs.isNotEmpty)
            Positioned(
              right: 16,
              bottom: 10,
              child: FloatingActionButton.small(
                heroTag: 'tobottom',
                tooltip: 'Ke bawah',
                onPressed: () {
                  _scroll.animateTo(_scroll.position.maxScrollExtent, duration: const Duration(milliseconds: 200), curve: Curves.easeOut);
                },
                child: const Icon(Icons.arrow_downward),
              ),
            ),
        ]),
      ),
      if (chat.approval != null)
        ApprovalCard(
          command: chat.approval!.command,
          description: chat.approval!.description,
          choices: chat.approval!.choices,
          onChoice: chat.respondApproval,
        ),
      const Composer(),
    ]);
  }
}

class _Welcome extends ConsumerWidget {
  const _Welcome({required this.onPick});
  final void Function(String) onPick;
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final settings = ref.watch(settingsProvider);
    final app = ref.watch(appProvider);
    final needsProvider = app.mode == ConnectionMode.local && !settings.llmConfigured;
    const ideas = [
      'Rangkum berita teknologi hari ini dari https://news.ycombinator.com',
      'Buat rencana belajar Flutter 2 minggu dan simpan ke workspace',
      'Ingat bahwa aku lebih suka jawaban singkat',
      'Buat 3 tugas Kanban untuk peluncuran aplikasi',
    ];
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 560),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            if (context.hc.brand)
              const HalftoneBackdrop(reach: 0.62, child: Padding(padding: EdgeInsets.symmetric(horizontal: 60, vertical: 14), child: EntranceFade(child: LogoCard(height: 150))))
            else
              const BrandMark(size: 56),
            const SizedBox(height: 16),
            if (context.hc.brand) ...[
              const MetaLabel('Neovarch Agent · di ponselmu'),
              const SizedBox(height: 6),
              Text('APA YANG BISA\nNEOVARCH BANTU?', style: context.tt.displaySmall?.copyWith(height: 0.95), textAlign: TextAlign.center),
            ] else
              Text('Apa yang bisa Neovarch bantu?', style: context.tt.titleLarge, textAlign: TextAlign.center),
            const SizedBox(height: 6),
            Text(
              app.mode == ConnectionMode.local
                  ? 'Agent berjalan langsung di ponselmu — dengan memori, alat, dan papan Kanban.'
                  : 'Terhubung lewat ${app.mode.label}.',
              style: context.tt.bodySmall,
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 20),
            if (needsProvider)
              Padding(
                padding: const EdgeInsets.only(bottom: 16),
                child: Column(children: [
                  const NoteBanner('Penyedia model belum diatur. Tambahkan kunci API dulu agar agent bisa menjawab.'),
                  const SizedBox(height: 10),
                  FilledButton.icon(
                    onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const ProvidersScreen())),
                    icon: const Icon(Icons.key_outlined, size: 18),
                    label: const Text('Atur penyedia'),
                  ),
                ]),
              ),
            for (final i in ideas)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Material(
                  color: context.hc.card,
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8), side: BorderSide(color: context.hc.strokeSoft)),
                  child: InkWell(
                    borderRadius: BorderRadius.circular(8),
                    onTap: () => onPick(i),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                      child: Row(children: [
                        Icon(Icons.north_east, size: 16, color: context.hc.mutedForeground),
                        const SizedBox(width: 10),
                        Expanded(child: Text(i, style: const TextStyle(fontSize: 13.5))),
                      ]),
                    ),
                  ),
                ),
              ),
          ]),
        ),
      ),
    );
  }
}

class Composer extends ConsumerStatefulWidget {
  const Composer({super.key});
  @override
  ConsumerState<Composer> createState() => _ComposerState();
}

class _ComposerState extends ConsumerState<Composer> {
  final _ctl = TextEditingController();
  final _focus = FocusNode();
  final List<String> _images = [];
  String _baseBeforeDictation = '';

  @override
  void initState() {
    super.initState();
    final chat = ref.read(chatProvider);
    final id = chat.current?.id;
    if (id != null) _ctl.text = chat.drafts[id] ?? '';
    _ctl.addListener(() {
      final c = ref.read(chatProvider);
      final sid = c.current?.id;
      if (sid != null) c.drafts[sid] = _ctl.text;
      setState(() {});
    });
  }

  @override
  void dispose() {
    _ctl.dispose();
    _focus.dispose();
    super.dispose();
  }

  Future<void> _attach(ImageSource src) async {
    try {
      if (src == ImageSource.camera && !await ensureCameraPermission()) {
        if (mounted) toast(context, 'Izin kamera ditolak — aktifkan di Lainnya → Izin perangkat.');
        return;
      }
      final x = await ImagePicker().pickImage(source: src, maxWidth: 1400, maxHeight: 1400, imageQuality: 82);
      if (x == null) return;
      final bytes = await x.readAsBytes();
      final mime = x.name.toLowerCase().endsWith('.png') ? 'image/png' : 'image/jpeg';
      setState(() => _images.add('data:$mime;base64,${base64Encode(bytes)}'));
    } catch (e) {
      if (mounted) toast(context, 'Gagal melampirkan gambar: $e');
    }
  }

  Future<void> _send() async {
    final chat = ref.read(chatProvider);
    final text = _ctl.text;
    if (text.trim().isEmpty && _images.isEmpty) return;
    if (text.trim().startsWith('/') && _images.isEmpty) {
      _ctl.clear();
      final (handled, refill) = await handleSlash(context, ref, text);
      if (handled) {
        if (refill != null) {
          _ctl.text = refill;
          _ctl.selection = TextSelection.collapsed(offset: refill.length);
        }
        return;
      }
    }
    chat.send(text, images: List.of(_images));
    _ctl.clear();
    setState(() => _images.clear());
  }

  Future<void> _toggleMic() async {
    final v = VoiceService.instance;
    final s = ref.read(settingsProvider);
    if (v.listening) {
      await v.stopDictation();
      return;
    }
    _baseBeforeDictation = _ctl.text.isEmpty ? '' : '${_ctl.text.trimRight()} ';
    await v.startDictation(
      locale: s.sttLocale,
      rationale: () async => mounted && await micRationale(context),
      onText: (t, fin) {
        if (!mounted) return;
        _ctl.text = '$_baseBeforeDictation$t';
        _ctl.selection = TextSelection.collapsed(offset: _ctl.text.length);
      },
    );
    // failures stay in the dictation strip above the input
  }

  Future<void> _dictationAction(DictationAction a) async {
    if (a == DictationAction.retry) {
      VoiceService.instance.dismissDictationError();
      await _toggleMic();
      return;
    }
    final ok = await openDictationFix(a);
    if (!ok && mounted) toast(context, 'Tidak bisa membuka halaman itu di HP ini.');
  }

  @override
  Widget build(BuildContext context) {
    final chat = ref.watch(chatProvider);
    final settings = ref.watch(settingsProvider);
    final app = ref.watch(appProvider);
    final store = ref.watch(storeProvider);
    final local = chat.engine is LocalChatEngine;
    final profile = local ? store.profile(chat.current?.profile ?? settings.defaultProfile) : null;
    final model = profile?.model ?? settings.activeProvider?.model ?? '';
    final canSend = _ctl.text.trim().isNotEmpty || _images.isNotEmpty;

    return ListenableBuilder(
      listenable: VoiceService.instance,
      builder: (context, _) {
        final listening = VoiceService.instance.listening;
        return Container(
          decoration: BoxDecoration(
            color: context.cs.surface,
            border: Border(top: BorderSide(color: context.hc.strokeSoft)),
          ),
          child: SafeArea(
            top: false,
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 812),
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
                  child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                    if (chat.queue.isNotEmpty) _Queue(chat: chat),
                    if (canDictate)
                      DictationStrip(voice: VoiceService.instance, onStop: VoiceService.instance.stopDictation, onAction: _dictationAction),
                    AnimatedSize(
                      duration: const Duration(milliseconds: 180),
                      curve: Curves.easeOutCubic,
                      child: (_ctl.text.startsWith('/') && !_ctl.text.contains(' '))
                          ? SlashSuggestions(
                              query: _ctl.text.substring(1),
                              onPick: (v) {
                                _ctl.text = v;
                                _ctl.selection = TextSelection.collapsed(offset: v.length);
                                if (!v.endsWith(' ')) _send();
                              },
                            )
                          : const SizedBox(width: double.infinity),
                    ),
                    if (_images.isNotEmpty)
                      SizedBox(
                        height: 64,
                        child: ListView(scrollDirection: Axis.horizontal, children: [
                          for (var i = 0; i < _images.length; i++)
                            Padding(
                              padding: const EdgeInsets.only(right: 8, bottom: 6),
                              child: Stack(children: [
                                ClipRRect(
                                  borderRadius: BorderRadius.circular(8),
                                  child: Image.memory(base64Decode(_images[i].split(',').last), width: 58, height: 58, fit: BoxFit.cover),
                                ),
                                Positioned(
                                  right: 0,
                                  top: 0,
                                  child: InkWell(
                                    onTap: () => setState(() => _images.removeAt(i)),
                                    child: Container(
                                      decoration: const BoxDecoration(color: Colors.black54, shape: BoxShape.circle),
                                      child: const Icon(Icons.close, size: 14, color: Colors.white),
                                    ),
                                  ),
                                ),
                              ]),
                            ),
                        ]),
                      ),
                    Container(
                      decoration: BoxDecoration(
                        color: context.hc.card,
                        borderRadius: BorderRadius.circular(14),
                        border: Border.all(color: _focus.hasFocus ? context.cs.tertiary : context.hc.border, width: _focus.hasFocus ? 1.3 : 1),
                      ),
                      padding: const EdgeInsets.fromLTRB(6, 4, 6, 4),
                      child: Column(children: [
                        TextField(
                          controller: _ctl,
                          focusNode: _focus,
                          minLines: 1,
                          maxLines: 7,
                          textInputAction: TextInputAction.newline,
                          style: TextStyle(fontSize: 14.5 * settings.chatScale),
                          decoration: InputDecoration(
                            hintText: listening ? 'Mendengarkan…' : (chat.streaming ? 'Ketik untuk mengantre…' : 'Tanya apa saja… ( / untuk perintah)'),
                            border: InputBorder.none,
                            enabledBorder: InputBorder.none,
                            focusedBorder: InputBorder.none,
                            filled: false,
                            contentPadding: const EdgeInsets.fromLTRB(8, 10, 8, 6),
                          ),
                        ),
                        Row(children: [
                          if (chat.engine.supportsImages)
                            PopupMenuButton<ImageSource>(
                              tooltip: 'Lampirkan gambar',
                              icon: Icon(Icons.add_photo_alternate_outlined, size: 21, color: context.hc.mutedForeground),
                              onSelected: _attach,
                              itemBuilder: (_) => [
                                PopupMenuItem(value: ImageSource.gallery, child: Text(isDesktop ? 'Pilih berkas gambar' : 'Dari galeri')),
                                if (canUseCamera) const PopupMenuItem(value: ImageSource.camera, child: Text('Ambil foto')),
                              ],
                            ),
                          if (local) const ThinkingButton(),
                          Expanded(
                            child: local
                                ? Align(
                                    alignment: Alignment.centerLeft,
                                    child: _ModelChip(
                                      model: effectiveModel(ref),
                                      onTap: () => showChatSettingsSheet(context),
                                    ),
                                  )
                                : const SizedBox.shrink(),
                          ),
                          if (canDictate)
                          IconButton(
                            tooltip: listening ? 'Berhenti mendikte' : 'Dikte',
                            onPressed: _toggleMic,
                            icon: Icon(listening ? Icons.mic : Icons.mic_none, size: 21, color: listening ? context.hc.destructive : context.hc.mutedForeground),
                          ),
                          if (canSpeak)
                          IconButton(
                            tooltip: settings.readAloud ? 'Matikan baca balasan' : 'Bacakan balasan',
                            onPressed: () => settings.update((s) => s.readAloud = !s.readAloud),
                            icon: Icon(settings.readAloud ? Icons.volume_up : Icons.volume_off_outlined,
                                size: 20, color: settings.readAloud ? context.cs.primary : context.hc.mutedForeground),
                          ),
                          const SizedBox(width: 2),
                          if (chat.streaming && !canSend)
                            IconButton.filled(
                              tooltip: 'Hentikan',
                              onPressed: chat.stop,
                              style: IconButton.styleFrom(backgroundColor: context.cs.onSurface, foregroundColor: context.cs.surface),
                              icon: const Icon(Icons.stop_rounded, size: 20),
                            )
                          else
                            IconButton.filled(
                              tooltip: chat.streaming ? 'Antrekan' : 'Kirim',
                              onPressed: canSend ? _send : null,
                              icon: Icon(chat.streaming ? Icons.playlist_add : Icons.arrow_upward_rounded, size: 20),
                            ),
                        ]),
                      ]),
                    ),
                    const SizedBox(height: 4),
                    _StatusLine(chat: chat, mode: app.mode, model: local ? model : null),
                  ]),
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}

class _ModelChip extends StatelessWidget {
  const _ModelChip({required this.model, required this.onTap});
  final String model;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => InkWell(
        borderRadius: BorderRadius.circular(6),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 6),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.memory, size: 15, color: context.hc.mutedForeground),
            const SizedBox(width: 4),
            Flexible(
              child: Text(model.isEmpty ? 'pilih model' : model,
                  maxLines: 1, overflow: TextOverflow.ellipsis, style: monoStyle(context, size: 11.5, color: context.hc.mutedForeground)),
            ),
            Icon(Icons.expand_more, size: 15, color: context.hc.mutedForeground),
          ]),
        ),
      );
}

class _Queue extends StatelessWidget {
  const _Queue({required this.chat});
  final ChatController chat;
  @override
  Widget build(BuildContext context) => Container(
        margin: const EdgeInsets.only(bottom: 6),
        padding: const EdgeInsets.fromLTRB(10, 6, 4, 6),
        decoration: BoxDecoration(color: context.hc.muted, borderRadius: BorderRadius.circular(8)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('ANTREAN (${chat.queue.length})', style: context.tt.labelSmall),
          for (var i = 0; i < chat.queue.length; i++)
            Row(children: [
              Expanded(child: Text(chat.queue[i], maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 13))),
              IconButton(
                visualDensity: VisualDensity.compact,
                iconSize: 16,
                icon: const Icon(Icons.close),
                onPressed: () => chat.removeQueued(i),
              ),
            ]),
        ]),
      );
}

class _StatusLine extends StatelessWidget {
  const _StatusLine({required this.chat, required this.mode, this.model});
  final ChatController chat;
  final ConnectionMode mode;
  final String? model;
  @override
  Widget build(BuildContext context) {
    final parts = <String>[
      mode.short,
      if (chat.tokensPerSecond != null && chat.tokensPerSecond! > 0) '${chat.tokensPerSecond!.toStringAsFixed(0)} tok/s',
      if (chat.contextTokens > 0) '${(chat.contextTokens / 1000).toStringAsFixed(1)}k konteks',
      if (chat.streaming) 'menjawab…',
    ];
    return Row(children: [
      Container(
        width: 6,
        height: 6,
        margin: const EdgeInsets.only(left: 6, right: 6),
        decoration: BoxDecoration(color: chat.error != null ? context.hc.destructive : context.hc.success, shape: BoxShape.circle),
      ),
      Expanded(
        child: Text(parts.join(' · '), maxLines: 1, overflow: TextOverflow.ellipsis, style: monoStyle(context, size: 10.5, color: context.hc.mutedForeground)),
      ),
    ]);
  }
}
