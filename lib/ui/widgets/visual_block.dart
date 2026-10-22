// ```visual cards in chat on the phone: the same crisp vector visuals the
// desktop draws (graph / flow / bar / timeline / compare specs, raw SVG or
// HTML+CSS). Rendering happens offline in the bundled WebView page
// (assets/diagram/host.html + visual.js, the desktop renderer with DOMPurify);
// this widget adds the native card: title above, caption below, a
// "Menggambar…" placeholder while the fence streams, tap for full screen and a
// menu to view the code, save a PNG to the gallery or share the SVG.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../remote/l10n/strings.dart';
import '../../remote/ui/glass/liquid_glass.dart' show GlassCode, GlassForeground;
import '../../remote/ui/profile_share_card.dart' show shareChannel, writeShareFile;
import '../../theme/app_theme.dart';
import 'diagram_block.dart';
import 'markdown_view.dart' show CodeBlock;

/// Best-effort title of a block that is still streaming (JSON `"title": "…"` or a `title:` line).
String? visualPartialTitle(String code) {
  final json = RegExp(r'"title"\s*:\s*"((?:[^"\\]|\\.)*)"').firstMatch(code);
  if (json != null) {
    try {
      return jsonDecode('"${json.group(1)}"') as String;
    } catch (_) {
      return json.group(1);
    }
  }
  final line = RegExp(r'^\s*(?:title|judul)\s*:\s*(.+)$', multiLine: true, caseSensitive: false).firstMatch(code);
  return line?.group(1)?.trim();
}

String _fileSlug(String? title) {
  final s = (title ?? 'visual').toLowerCase().replaceAll(RegExp(r'[^a-z0-9]+'), '-').replaceAll(RegExp(r'^-+|-+$'), '');
  return s.isEmpty ? 'visual' : (s.length > 40 ? s.substring(0, 40) : s);
}

class VisualBlock extends StatefulWidget {
  const VisualBlock({super.key, required this.code, this.scale = 1.0, this.streaming = false});
  final String code;
  final double scale;
  final bool streaming;

  @override
  State<VisualBlock> createState() => _VisualBlockState();
}

class _VisualBlockState extends State<VisualBlock> {
  final _exporter = DiagramExporter();
  bool _showCode = false;
  bool _rendered = false;
  String? _error;
  String? _title;
  String? _caption;
  double _height = 180;

  @override
  void initState() {
    super.initState();
    _check();
  }

  void _check() {
    if (!widget.streaming && !DiagramBlock.canPreview) {
      _error = 'pratinjau tidak tersedia di perangkat ini';
    }
  }

  @override
  void didUpdateWidget(covariant VisualBlock old) {
    super.didUpdateWidget(old);
    if (old.code != widget.code || old.streaming != widget.streaming) {
      _error = null;
      _rendered = false;
      _showCode = false;
      _check();
    }
  }

  void _onResult(DiagramRenderResult r) {
    if (!mounted) return;
    if (r.ok) {
      final max = (MediaQuery.maybeSizeOf(context)?.height ?? 800) * 0.65;
      final h = (r.height ?? 180).clamp(60.0, max);
      if (_rendered && h == _height && r.title == _title && r.caption == _caption) return;
      setState(() {
        _rendered = true;
        _height = h;
        _title = r.title;
        _caption = r.caption;
      });
    } else if (_error != r.error) {
      setState(() => _error = r.error);
    }
  }

  String get _heading => _title ?? visualPartialTitle(widget.code) ?? tr('Visual');

  void _fullscreen() => Navigator.of(context).push(MaterialPageRoute<void>(
        fullscreenDialog: true,
        builder: (_) => DiagramFullscreen(code: widget.code, kind: DiagramKind.visual, title: _heading),
      ));

  void _say(String msg) =>
      ScaffoldMessenger.maybeOf(context)?.showSnackBar(SnackBar(content: Text(msg), duration: const Duration(seconds: 2)));

  Future<void> _savePng() async {
    try {
      final data = await _exporter.export('png');
      final comma = data.indexOf(',');
      final png = base64Decode(comma >= 0 ? data.substring(comma + 1) : data);
      final path = await writeShareFile(Uint8List.fromList(png), '${_fileSlug(_heading)}-${DateTime.now().millisecondsSinceEpoch}.png');
      final r = await shareChannel('saveImageToGallery', {'path': path, 'name': path.split('/').last});
      if (mounted) _say(r == true || r is String ? tr('Tersimpan di galeri (Pictures/Neovarch)') : tr('Gambar gagal disimpan'));
    } catch (_) {
      if (mounted) _say(tr('Gambar gagal disimpan'));
    }
  }

  Future<void> _shareSvg() async {
    try {
      final svg = await _exporter.export('svg');
      final path = await writeShareFile(Uint8List.fromList(utf8.encode(svg)), '${_fileSlug(_heading)}.svg');
      await shareChannel('shareImage', {'path': path, 'mime': 'image/svg+xml', 'text': _heading});
    } catch (_) {
      if (mounted) _say(tr('Gambar gagal disimpan'));
    }
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
    final muted = context.hc.mutedForeground;
    return Container(
      key: const ValueKey('visual-card'),
      decoration: BoxDecoration(
        color: context.hc.codeBg,
        border: Border.all(color: context.hc.strokeSoft),
        borderRadius: BorderRadius.circular(14),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
        Padding(
          padding: const EdgeInsets.only(left: 14, right: 2, top: 4),
          child: Row(children: [
            Expanded(
              child: Text(_heading,
                  key: const ValueKey('visual-title'),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: 13.5 * widget.scale, fontWeight: FontWeight.w600, color: context.cs.onSurface)),
            ),
            if (!streaming && !failed)
              IconButton(
                iconSize: 16,
                visualDensity: VisualDensity.compact,
                tooltip: tr('Layar penuh'),
                icon: const Icon(Icons.open_in_full_rounded),
                onPressed: _fullscreen,
              ),
            if (!streaming)
              PopupMenuButton<String>(
                key: const ValueKey('visual-menu'),
                tooltip: tr('Opsi visual'),
                icon: Icon(Icons.more_horiz_rounded, size: 18, color: muted),
                onSelected: (v) {
                  switch (v) {
                    case 'code':
                      setState(() => _showCode = !_showCode);
                    case 'full':
                      _fullscreen();
                    case 'png':
                      _savePng();
                    case 'svg':
                      _shareSvg();
                    case 'copy':
                      Clipboard.setData(ClipboardData(text: widget.code));
                      _say(tr('Kode disalin'));
                  }
                },
                itemBuilder: (_) => [
                  if (!failed) PopupMenuItem(value: 'code', child: Text(_showCode ? tr('Lihat gambar') : tr('Lihat kode'))),
                  if (!failed) PopupMenuItem(value: 'full', child: Text(tr('Layar penuh'))),
                  if (!failed && _rendered) PopupMenuItem(value: 'png', child: Text(tr('Simpan PNG'))),
                  if (!failed && _rendered) PopupMenuItem(value: 'svg', child: Text(tr('Bagikan SVG'))),
                  PopupMenuItem(value: 'copy', child: Text(tr('Salin kode'))),
                ],
              ),
            if (streaming) const SizedBox(height: 40),
          ]),
        ),
        if (streaming)
          SizedBox(
            key: const ValueKey('visual-drawing'),
            height: 120,
            child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
              SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 1.6, color: muted)),
              const SizedBox(width: 10),
              Text(tr('Menggambar…'), style: TextStyle(fontSize: 12.5, color: muted)),
            ]),
          ),
        if (failed) ...[
          Padding(
            padding: const EdgeInsets.fromLTRB(14, 2, 14, 0),
            child: Text(tr('Visual gagal digambar — menampilkan kode'),
                key: const ValueKey('visual-failed'), style: TextStyle(fontSize: 11.5, color: context.hc.destructive)),
          ),
          CodeBlock(code: widget.code, language: 'json', scale: widget.scale, embedded: true),
        ],
        if (!failed && !streaming) ...[
          Offstage(
            offstage: _showCode,
            child: GestureDetector(
              behavior: HitTestBehavior.opaque,
              onTap: _fullscreen,
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 180),
                height: _height,
                child: Stack(fit: StackFit.expand, children: [
                  IgnorePointer(
                    child: DiagramBlock.preview(context, widget.code, DiagramKind.visual, false, _onResult, exporter: _exporter),
                  ),
                  if (!_rendered) Center(child: SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: muted))),
                ]),
              ),
            ),
          ),
          if (_showCode) CodeBlock(code: widget.code, language: 'json', scale: widget.scale, embedded: true),
          if (_caption != null && !_showCode)
            Padding(
              padding: const EdgeInsets.fromLTRB(14, 0, 14, 12),
              child: Text(_caption!,
                  key: const ValueKey('visual-caption'), style: TextStyle(fontSize: 12.5 * widget.scale, height: 1.4, color: muted)),
            ),
        ],
      ]),
    );
  }
}
