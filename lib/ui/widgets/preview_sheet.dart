// The preview pane. Desktop shows it as a right-hand rail beside the chat;
// on a phone it is a tall bottom sheet (and a side panel on tablets is the
// same sheet). It renders web pages (webview_flutter), workspace files
// (markdown / code / text) and raw tool outputs. Opening it is always the
// user's choice — a tool result only offers the action.
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:webview_flutter/webview_flutter.dart';

import '../../theme/app_theme.dart';
import 'common.dart';
import 'diagram_block.dart';
import 'markdown_view.dart';

sealed class PreviewTarget {
  const PreviewTarget();
}

class UrlPreview extends PreviewTarget {
  final String url;
  const UrlPreview(this.url);
}

class FilePreview extends PreviewTarget {
  final String path;
  final String content;
  const FilePreview(this.path, this.content);
}

class TextPreview extends PreviewTarget {
  final String title;
  final String text;
  final bool markdown;
  const TextPreview(this.title, this.text, {this.markdown = false});
}

Future<void> showPreview(BuildContext context, PreviewTarget target) {
  return showPaperSheet(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    showDragHandle: false,
    builder: (ctx) => SizedBox(height: MediaQuery.sizeOf(ctx).height * 0.92, child: PreviewPane(target: target)),
  );
}

class PreviewPane extends StatelessWidget {
  const PreviewPane({super.key, required this.target});
  final PreviewTarget target;

  @override
  Widget build(BuildContext context) {
    final (title, icon) = switch (target) {
      UrlPreview(:final url) => (Uri.tryParse(url)?.host ?? url, Icons.public),
      FilePreview(:final path) => (path, Icons.description_outlined),
      TextPreview(:final title) => (title, Icons.terminal),
    };
    return Column(children: [
      Container(
        padding: const EdgeInsets.fromLTRB(16, 10, 6, 10),
        decoration: BoxDecoration(border: Border(bottom: BorderSide(color: context.hc.strokeSoft))),
        child: Row(children: [
          Icon(icon, size: 18, color: context.hc.mutedForeground),
          const SizedBox(width: 10),
          Expanded(child: Text(title, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.tt.titleSmall)),
          if (target is UrlPreview)
            IconButton(
              tooltip: 'Buka di peramban',
              icon: const Icon(Icons.open_in_new, size: 19),
              onPressed: () => launchUrl(Uri.parse((target as UrlPreview).url), mode: LaunchMode.externalApplication),
            ),
          IconButton(
            tooltip: 'Salin',
            icon: const Icon(Icons.copy_rounded, size: 18),
            onPressed: () {
              final t = switch (target) {
                UrlPreview(:final url) => url,
                FilePreview(:final content) => content,
                TextPreview(:final text) => text,
              };
              Clipboard.setData(ClipboardData(text: t));
              toast(context, 'Disalin');
            },
          ),
          IconButton(icon: const Icon(Icons.close), onPressed: () => Navigator.pop(context)),
        ]),
      ),
      Expanded(child: _body(context)),
    ]);
  }

  Widget _body(BuildContext context) {
    switch (target) {
      case UrlPreview(:final url):
        if (kIsWeb || !(defaultTargetPlatform == TargetPlatform.android || defaultTargetPlatform == TargetPlatform.iOS)) {
          return EmptyState(
            icon: Icons.public,
            title: 'Pratinjau web tersedia di aplikasi Android',
            body: url,
            action: FilledButton.icon(
              onPressed: () => launchUrl(Uri.parse(url)),
              icon: const Icon(Icons.open_in_new, size: 18),
              label: const Text('Buka di peramban'),
            ),
          );
        }
        return _WebPreview(url: url);
      case FilePreview(:final path, :final content):
        return FileContentView(path: path, content: content);
      case TextPreview(:final text, :final markdown):
        return SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: markdown ? MarkdownView(text) : SelectableText(text, style: monoStyle(context, size: 12)),
        );
    }
  }
}

class FileContentView extends StatelessWidget {
  const FileContentView({super.key, required this.path, required this.content});
  final String path;
  final String content;

  @override
  Widget build(BuildContext context) {
    final ext = path.contains('.') ? path.split('.').last.toLowerCase() : '';
    if (ext == 'md' || ext == 'markdown') {
      return SingleChildScrollView(padding: const EdgeInsets.all(16), child: MarkdownView(content));
    }
    // Diagram / page artifacts from the agent: rendered, with Pratinjau | Kode.
    final diagram = switch (ext) {
      'svg' => DiagramKind.svg,
      'mmd' || 'mermaid' => DiagramKind.mermaid,
      'html' || 'htm' => DiagramKind.html,
      _ => null,
    };
    if (diagram != null && content.trim().isNotEmpty) {
      return SingleChildScrollView(
        padding: const EdgeInsets.all(12),
        child: DiagramBlock(code: content, kind: diagram, label: path.split('/').last),
      );
    }
    const code = {
      'dart', 'py', 'js', 'ts', 'json', 'yaml', 'yml', 'html', 'css', 'sh', 'kt', 'java', 'go', 'rs', 'c', 'cpp', 'sql', 'xml', 'toml', 'tsx', 'jsx'
    };
    if (code.contains(ext)) {
      return SingleChildScrollView(padding: const EdgeInsets.all(12), child: CodeBlock(code: content, language: ext));
    }
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: SelectableText(content.isEmpty ? '(berkas kosong)' : content, style: monoStyle(context, size: 12.5)),
    );
  }
}

class _WebPreview extends StatefulWidget {
  const _WebPreview({required this.url});
  final String url;
  @override
  State<_WebPreview> createState() => _WebPreviewState();
}

class _WebPreviewState extends State<_WebPreview> {
  late final WebViewController _c;
  int progress = 0;
  String? error;

  @override
  void initState() {
    super.initState();
    _c = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setNavigationDelegate(NavigationDelegate(
        onProgress: (p) => setState(() => progress = p),
        onWebResourceError: (e) => setState(() => error = e.description),
        // Guest content never opens anything by itself: only http(s) stays inside.
        onNavigationRequest: (r) =>
            r.url.startsWith('http://') || r.url.startsWith('https://') ? NavigationDecision.navigate : NavigationDecision.prevent,
      ))
      ..loadRequest(Uri.parse(widget.url));
  }

  @override
  Widget build(BuildContext context) => Column(children: [
        if (progress < 100) LinearProgressIndicator(value: progress / 100, minHeight: 2),
        if (error != null) ErrorBanner(error!, dense: true),
        Expanded(child: WebViewWidget(controller: _c)),
      ]);
}
