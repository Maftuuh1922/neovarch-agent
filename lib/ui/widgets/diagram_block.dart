// Live diagram blocks in chat: ```mermaid, ```svg and inline <svg> content
// render as a picture with a "Pratinjau | Kode" toggle. Rendering happens in
// a small WebView that loads a bundled page (assets/diagram/host.html with a
// bundled mermaid.min.js), so it works offline. Tap the picture for a
// fullscreen view with pinch-zoom and pan. If anything goes wrong (no WebView
// on this platform, a mermaid syntax error, invalid SVG, no answer within
// ~4 s) the block falls back to the code with a small "gagal dirender" chip.
// While the agent is still writing the block (fence not closed yet) it shows
// Kode; it flips to Pratinjau once the fence closes.
import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:webview_flutter/webview_flutter.dart';

import '../../theme/app_theme.dart';
import '../../remote/ui/glass/liquid_glass.dart' show GlassCode, GlassForeground;
import 'markdown_view.dart' show CodeBlock;

enum DiagramKind { mermaid, svg, html }

/// Which diagram (if any) a fenced block or file holds. [lang] is the fence
/// info string or a file extension.
DiagramKind? diagramKindFor(String? lang, String code) {
  final l = (lang ?? '').trim().toLowerCase().split(RegExp(r'\s+')).first;
  if (l == 'mermaid' || l == 'mmd') return DiagramKind.mermaid;
  if (l == 'svg') return DiagramKind.svg;
  if (l.isEmpty || l == 'xml' || l == 'html') {
    if (looksLikeSvg(code)) return DiagramKind.svg;
  }
  return null;
}

/// A whole SVG document (optionally after an XML prolog / comments).
bool looksLikeSvg(String code) {
  var t = code.trimLeft();
  t = t.replaceFirst(RegExp(r'^<\?xml[^>]*\?>\s*'), '');
  t = t.replaceFirst(RegExp(r'^(<!--[\s\S]*?-->\s*)+'), '');
  t = t.replaceFirst(RegExp(r'^<!DOCTYPE[^>]*>\s*', caseSensitive: false), '');
  return t.startsWith('<svg') && code.trimRight().endsWith('</svg>');
}

/// Outcome of one render, reported by the preview.
class DiagramRenderResult {
  const DiagramRenderResult.ok(this.height) : error = null;
  const DiagramRenderResult.failed(this.error) : height = null;
  final double? height;
  final String? error;
  bool get ok => error == null;
}

typedef DiagramPreviewBuilder = Widget Function(
    BuildContext context, String code, DiagramKind kind, bool fullscreen, ValueChanged<DiagramRenderResult> onResult);

class DiagramBlock extends StatefulWidget {
  const DiagramBlock({super.key, required this.code, required this.kind, this.scale = 1.0, this.label, this.streaming = false});
  final String code;
  final DiagramKind kind;
  final double scale;
  final String? label;

  /// The block is still being written (closing fence not seen yet): show the
  /// code as it grows and only render once it is complete.
  final bool streaming;

  /// How long one render may take before the block gives up and shows Kode.
  static const renderTimeout = Duration(seconds: 4);

  /// Loading the bundled page (and mermaid) the first time is slower; this
  /// caps that part separately.
  static const loadTimeout = Duration(seconds: 12);

  /// Tests (and platforms without a WebView) swap the renderer here.
  @visibleForTesting
  static DiagramPreviewBuilder? debugPreviewBuilder;

  static bool get webViewAvailable =>
      !kIsWeb &&
      (defaultTargetPlatform == TargetPlatform.android || defaultTargetPlatform == TargetPlatform.iOS) &&
      WebViewPlatform.instance != null;

  static Widget preview(BuildContext context, String code, DiagramKind kind, bool fullscreen, ValueChanged<DiagramRenderResult> onResult) {
    final b = debugPreviewBuilder;
    if (b != null) return b(context, code, kind, fullscreen, onResult);
    return DiagramWebView(code: code, kind: kind, fullscreen: fullscreen, onResult: onResult);
  }

  @override
  State<DiagramBlock> createState() => _DiagramBlockState();
}

class _DiagramBlockState extends State<DiagramBlock> {
  bool _showCode = false;
  String? _error;
  double _height = 200;
  bool _rendered = false;

  @override
  void initState() {
    super.initState();
    _checkAvailable();
  }

  void _checkAvailable() {
    if (widget.streaming) {
      _showCode = true;
      return;
    }
    if (DiagramBlock.debugPreviewBuilder == null && !DiagramBlock.webViewAvailable) {
      _error = 'pratinjau tidak tersedia di perangkat ini';
      _showCode = true;
    }
  }

  @override
  void didUpdateWidget(covariant DiagramBlock old) {
    super.didUpdateWidget(old);
    if (old.code != widget.code || old.kind != widget.kind || old.streaming != widget.streaming) {
      _error = null;
      _rendered = false;
      _showCode = false;
      _checkAvailable();
    }
  }

  void _onResult(DiagramRenderResult r) {
    if (!mounted) return;
    if (r.ok) {
      final max = MediaQuery.maybeSizeOf(context)?.height ?? 800;
      // A page has no natural height inside the frame: give it most of the screen.
      final h = widget.kind == DiagramKind.html ? max * 0.6 : (r.height ?? 200).clamp(80.0, max * 0.6);
      if (_rendered && _error == null && h == _height) return;
      setState(() {
        _rendered = true;
        _error = null;
        _height = h;
      });
    } else {
      if (_error == r.error && _showCode) return;
      setState(() {
        _error = r.error;
        _showCode = true;
      });
    }
  }

  String get _label => widget.label ?? switch (widget.kind) { DiagramKind.mermaid => 'mermaid', DiagramKind.svg => 'svg', DiagramKind.html => 'html' };

  void _openFullscreen() {
    Navigator.of(context).push(MaterialPageRoute<void>(
      fullscreenDialog: true,
      builder: (_) => DiagramFullscreen(code: widget.code, kind: widget.kind, title: _label),
    ));
  }

  @override
  Widget build(BuildContext context) {
    final g = GlassForeground.maybeOf(context);
    if (g != null && !g.isCode) return GlassCode(child: Builder(builder: _build));
    return _build(context);
  }

  Widget _build(BuildContext context) {
    final failed = _error != null;
    final streaming = widget.streaming;
    return Container(
      decoration: BoxDecoration(
        color: context.hc.codeBg,
        border: Border.all(color: context.hc.strokeSoft),
        borderRadius: BorderRadius.circular(6),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
        Container(
          padding: const EdgeInsets.only(left: 12, right: 2),
          decoration: BoxDecoration(border: Border(bottom: BorderSide(color: context.hc.strokeSoft))),
          child: Row(children: [
            Text(_label, style: monoStyle(context, size: 11, color: context.hc.mutedForeground)),
            const SizedBox(width: 10),
            _Toggle(
              showCode: _showCode,
              previewEnabled: !failed && !streaming,
              onChanged: (code) => setState(() => _showCode = code),
            ),
            const Spacer(),
            if (streaming)
              Padding(
                padding: const EdgeInsets.only(right: 4),
                child: Text('menulis…',
                    key: const ValueKey('diagram-streaming'),
                    style: TextStyle(fontSize: 11, color: context.hc.mutedForeground)),
              ),
            if (!_showCode && !failed && !streaming)
              IconButton(
                iconSize: 16,
                visualDensity: VisualDensity.compact,
                tooltip: 'Layar penuh',
                icon: const Icon(Icons.open_in_full_rounded),
                onPressed: _openFullscreen,
              ),
            IconButton(
              iconSize: 15,
              visualDensity: VisualDensity.compact,
              tooltip: 'Salin kode',
              icon: const Icon(Icons.copy_rounded),
              onPressed: () {
                Clipboard.setData(ClipboardData(text: widget.code));
                ScaffoldMessenger.maybeOf(context)
                    ?.showSnackBar(const SnackBar(content: Text('Kode disalin'), duration: Duration(seconds: 1)));
              },
            ),
          ]),
        ),
        if (failed)
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
            child: Align(
              alignment: Alignment.centerLeft,
              child: Tooltip(
                message: _error ?? '',
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: context.hc.destructive.withValues(alpha: 0.12),
                    border: Border.all(color: context.hc.destructive.withValues(alpha: 0.35)),
                    borderRadius: BorderRadius.circular(999),
                  ),
                  child: Row(mainAxisSize: MainAxisSize.min, children: [
                    Icon(Icons.error_outline_rounded, size: 12, color: context.hc.mutedForeground),
                    const SizedBox(width: 5),
                    Flexible(
                      child: Text('gagal dirender — menampilkan kode',
                          key: const ValueKey('diagram-failed'),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(fontSize: 11, color: context.hc.mutedForeground)),
                    ),
                  ]),
                ),
              ),
            ),
          ),
        // Keep the preview alive while the code tab is shown so switching back
        // does not re-render.
        if (!failed && !streaming)
          Offstage(
          offstage: _showCode,
          child: GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: _openFullscreen,
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 180),
              height: _height,
              child: Stack(fit: StackFit.expand, children: [
                // The inline picture never takes the chat's scroll gestures;
                // zoom and pan live in the fullscreen view.
                IgnorePointer(child: DiagramBlock.preview(context, widget.code, widget.kind, false, _onResult)),
                if (!_rendered && !failed) const Center(child: SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))),
              ]),
            ),
          ),
        ),
        if (_showCode || failed || streaming)
          CodeBlock(
            code: widget.code,
            language: widget.kind == DiagramKind.mermaid ? null : 'xml',
            scale: widget.scale,
            embedded: true,
          ),
      ]),
    );
  }
}

class _Toggle extends StatelessWidget {
  const _Toggle({required this.showCode, required this.previewEnabled, required this.onChanged});
  final bool showCode;
  final bool previewEnabled;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    Widget seg(String label, bool selected, VoidCallback? onTap) => InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(8),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3),
            decoration: BoxDecoration(
              color: selected ? context.cs.primary.withValues(alpha: 0.18) : Colors.transparent,
              borderRadius: BorderRadius.circular(8),
            ),
            child: Text(label,
                style: TextStyle(
                  fontSize: 11.5,
                  fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
                  color: onTap == null && !selected
                      ? context.hc.mutedForeground.withValues(alpha: 0.5)
                      : selected
                          ? context.cs.primary
                          : context.hc.mutedForeground,
                )),
          ),
        );
    return Container(
      padding: const EdgeInsets.all(2),
      decoration: BoxDecoration(border: Border.all(color: context.hc.strokeSoft), borderRadius: BorderRadius.circular(10)),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        seg('Pratinjau', !showCode, previewEnabled ? () => onChanged(false) : null),
        seg('Kode', showCode, () => onChanged(true)),
      ]),
    );
  }
}

/// Fullscreen diagram: pinch to zoom, drag to pan.
class DiagramFullscreen extends StatefulWidget {
  const DiagramFullscreen({super.key, required this.code, required this.kind, this.title = 'Diagram'});
  final String code;
  final DiagramKind kind;
  final String title;

  @override
  State<DiagramFullscreen> createState() => _DiagramFullscreenState();
}

class _DiagramFullscreenState extends State<DiagramFullscreen> {
  String? _error;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: context.hc.codeBg,
      appBar: AppBar(
        backgroundColor: context.hc.codeBg,
        title: Text(widget.title, style: monoStyle(context, size: 13, color: context.hc.mutedForeground)),
        actions: [
          IconButton(
            tooltip: 'Salin kode',
            icon: const Icon(Icons.copy_rounded, size: 18),
            onPressed: () {
              Clipboard.setData(ClipboardData(text: widget.code));
              ScaffoldMessenger.maybeOf(context)
                  ?.showSnackBar(const SnackBar(content: Text('Kode disalin'), duration: Duration(seconds: 1)));
            },
          ),
        ],
      ),
      body: SafeArea(
        child: _error != null
            ? SingleChildScrollView(
                padding: const EdgeInsets.all(12),
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  Text('gagal dirender — menampilkan kode', style: TextStyle(fontSize: 12, color: context.hc.mutedForeground)),
                  const SizedBox(height: 8),
                  CodeBlock(code: widget.code, language: widget.kind == DiagramKind.mermaid ? null : 'xml'),
                ]),
              )
            : DiagramBlock.preview(context, widget.code, widget.kind, true, (r) {
                if (!r.ok && mounted) setState(() => _error = r.error);
              }),
      ),
    );
  }
}

/// The WebView renderer (Android / iOS).
class DiagramWebView extends StatefulWidget {
  const DiagramWebView({super.key, required this.code, required this.kind, required this.fullscreen, required this.onResult});
  final String code;
  final DiagramKind kind;
  final bool fullscreen;
  final ValueChanged<DiagramRenderResult> onResult;

  static const hostAsset = 'assets/diagram/host.html';

  @override
  State<DiagramWebView> createState() => _DiagramWebViewState();
}

class _DiagramWebViewState extends State<DiagramWebView> {
  WebViewController? _c;
  bool _ready = false;
  bool _done = false;
  Timer? _timeout;
  Map<String, Object?>? _theme;

  @override
  void initState() {
    super.initState();
    try {
      final c = WebViewController()
        ..setJavaScriptMode(JavaScriptMode.unrestricted)
        ..setBackgroundColor(Colors.transparent)
        ..addJavaScriptChannel('NV', onMessageReceived: (m) => _onMessage(m.message))
        ..setNavigationDelegate(NavigationDelegate(
          // Only the bundled host page; diagrams never navigate anywhere.
          onNavigationRequest: (r) =>
              r.url.startsWith('file:') || r.url.startsWith('about:') || r.url.contains('flutter_assets')
                  ? NavigationDecision.navigate
                  : NavigationDecision.prevent,
          onWebResourceError: (e) {
            if (e.isForMainFrame ?? true) _finish(DiagramRenderResult.failed(e.description));
          },
        ));
      if (widget.fullscreen) c.enableZoom(true);
      c.loadFlutterAsset(DiagramWebView.hostAsset);
      _c = c;
      _timeout = Timer(DiagramBlock.loadTimeout, () => _finish(const DiagramRenderResult.failed('waktu habis memuat')));
    } catch (e) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _finish(DiagramRenderResult.failed('$e')));
    }
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _theme = _themeFor(context);
  }

  @override
  void didUpdateWidget(covariant DiagramWebView old) {
    super.didUpdateWidget(old);
    if (old.code != widget.code || old.kind != widget.kind) {
      _done = false;
      _render();
    }
  }

  @override
  void dispose() {
    _timeout?.cancel();
    super.dispose();
  }

  void _finish(DiagramRenderResult r) {
    if (_done || !mounted) return;
    _done = true;
    _timeout?.cancel();
    widget.onResult(r);
  }

  void _onMessage(String raw) {
    Map<String, dynamic> m;
    try {
      m = jsonDecode(raw) as Map<String, dynamic>;
    } catch (_) {
      return;
    }
    if (m['ready'] == true) {
      _ready = true;
      _render();
    } else if (m['ok'] == true) {
      _finish(DiagramRenderResult.ok((m['h'] as num?)?.toDouble()));
    } else if (m['ok'] == false) {
      _finish(DiagramRenderResult.failed('${m['error'] ?? 'gagal'}'));
    }
  }

  void _render() {
    final c = _c;
    if (c == null || !_ready) return;
    // Each render gets ~4 s; mermaid that hangs falls back to Kode.
    _timeout?.cancel();
    _timeout = Timer(DiagramBlock.renderTimeout, () => _finish(const DiagramRenderResult.failed('waktu habis')));
    final payload = jsonEncode({
      'kind': widget.kind.name,
      'code': widget.code,
      'full': widget.fullscreen,
      'theme': _theme ?? const {},
    });
    c.runJavaScript('nvRender($payload)').catchError((Object e) => _finish(DiagramRenderResult.failed('$e')));
  }

  @override
  Widget build(BuildContext context) {
    final c = _c;
    if (c == null) return const SizedBox.shrink();
    return WebViewWidget(
      controller: c,
      gestureRecognizers: widget.fullscreen
          ? <Factory<OneSequenceGestureRecognizer>>{Factory<OneSequenceGestureRecognizer>(() => EagerGestureRecognizer())}
          : const <Factory<OneSequenceGestureRecognizer>>{},
    );
  }
}

String _hex(Color c) => '#${(c.toARGB32() & 0xFFFFFF).toRadixString(16).padLeft(6, '0')}';

Map<String, Object?> _themeFor(BuildContext context) {
  final bg = context.hc.codeBg.withValues(alpha: 1);
  final fg = context.cs.onSurface;
  final accent = context.cs.primary;
  return {
    'dark': Theme.of(context).brightness == Brightness.dark,
    'bg': _hex(bg),
    'fg': _hex(fg),
    'accent': _hex(accent),
    'line': _hex(context.hc.mutedForeground),
    'node': _hex(Color.alphaBlend(accent.withValues(alpha: 0.14), bg)),
    'node2': _hex(Color.alphaBlend(fg.withValues(alpha: 0.07), bg)),
  };
}
