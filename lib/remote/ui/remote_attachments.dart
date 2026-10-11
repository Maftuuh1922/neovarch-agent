// Chat attachments on the phone: the attach sheet (Foto/Galeri, Kamera, File),
// clipboard / keyboard image paste, composer thumbnails with upload progress,
// and attachments inside sent message bubbles (tap an image to preview it, tap
// a file to open it through the PC's download route).
import 'dart:async';
import 'dart:io';

import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../data/device_tools.dart' show deviceCall;
import '../../models/models.dart' show ChatMsg;
import '../../theme/neovarch_mobile_theme.dart';
import '../../ui/widgets/brand.dart' show showPaperSheet;
import '../../ui/widgets/common.dart' show toast;
import '../attachments.dart';
import '../remote_controller.dart';
import '../remote_gateway.dart';
import 'nv_widgets.dart';
import '../remote_errors.dart';

enum AttachSource { gallery, camera, file }

/// Test seam: how a remote attachment URL becomes an image (default: network
/// with the PC session headers).
ImageProvider Function(Uri url, Map<String, String> headers) remoteImageProvider =
    (url, headers) => NetworkImage(url.toString(), headers: headers);

/// Test seam: picking from the platform (gallery/camera/file).
Future<({String name, Uint8List bytes, String? mime})?> Function(AttachSource src) attachPicker = _platformPick;

Future<({String name, Uint8List bytes, String? mime})?> _platformPick(AttachSource src) async {
  if (src == AttachSource.file) {
    final m = await deviceCall<Map>('pickFileForUpload', {'mime': '*/*'});
    if (m == null) return null;
    if (m['error'] == 'too_big') throw AttachError('${m['name'] ?? 'File'} terlalu besar (maks 25 MB).');
    if (m['path'] == null) throw const AttachError('File tidak bisa dibaca.');
    final f = File('${m['path']}');
    final bytes = await f.readAsBytes();
    unawaited(f.delete().then((_) {}, onError: (_) {}));
    return (name: '${m['name'] ?? 'berkas'}', bytes: bytes, mime: m['mime'] as String?);
  }
  if (src == AttachSource.camera) {
    try {
      await deviceCall<Map>('requestPermissions', {'permissions': ['android.permission.CAMERA']});
    } catch (_) {}
  }
  final x = await ImagePicker().pickImage(
    source: src == AttachSource.camera ? ImageSource.camera : ImageSource.gallery,
    maxWidth: 2400,
    maxHeight: 2400,
    imageQuality: 88,
  );
  if (x == null) return null;
  return (name: x.name, bytes: await x.readAsBytes(), mime: x.mimeType);
}

class AttachError implements Exception {
  const AttachError(this.message);
  final String message;
  @override
  String toString() => message;
}

Future<void> attachFrom(BuildContext context, RemoteController r, AttachSource src) async {
  try {
    final picked = await attachPicker(src);
    if (picked == null) return;
    final err = await r.addAttachment(picked.name, picked.bytes, mime: picked.mime);
    if (err != null && context.mounted) toast(context, err);
  } catch (e) {
    if (context.mounted) toast(context, friendlyRemoteError(e));
  }
}

/// Paste an image copied to the Android clipboard (long-press menu item).
Future<void> pasteClipboardImage(BuildContext context, RemoteController r) async {
  try {
    final m = await deviceCall<Map>('clipboardImage');
    if (m == null || m['path'] == null) {
      if (context.mounted) toast(context, m?['error'] == 'too_big' ? 'Gambar terlalu besar (maks 25 MB).' : 'Tidak ada gambar di papan klip.');
      return;
    }
    final f = File('${m['path']}');
    final bytes = await f.readAsBytes();
    final err = await r.addAttachment('${m['name'] ?? 'tempel.png'}', bytes, mime: m['mime'] as String?);
    if (err != null && context.mounted) toast(context, err);
  } catch (e) {
    if (context.mounted) toast(context, friendlyRemoteError(e));
  }
}

/// Images inserted by the keyboard (Gboard GIF/sticker/screenshot "paste").
Future<void> attachInserted(BuildContext context, RemoteController r, KeyboardInsertedContent c) async {
  final data = c.data;
  if (data == null || data.isEmpty) return;
  final ext = c.mimeType.split('/').last;
  final err = await r.addAttachment('tempel.${ext == 'jpeg' ? 'jpg' : ext}', data, mime: c.mimeType);
  if (err != null && context.mounted) toast(context, err);
}

const kInsertableImageMimes = ['image/png', 'image/jpeg', 'image/gif', 'image/webp'];

Future<void> showAttachSheet(BuildContext context, RemoteController r) => showPaperSheet(
      context: context,
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const Padding(padding: EdgeInsets.fromLTRB(20, 0, 16, 12), child: NvSheetTitle(kicker: 'lampiran · maks 25 MB', title: 'Lampirkan')),
            NvList(children: [
              for (final (src, icon, label, sub) in const [
                (AttachSource.gallery, CupertinoIcons.photo_on_rectangle, 'Foto / Galeri', 'Pilih gambar dari galeri'),
                (AttachSource.camera, CupertinoIcons.camera, 'Kamera', 'Ambil foto sekarang'),
                (AttachSource.file, CupertinoIcons.doc, 'File', 'PDF, kode, teks, dan lainnya'),
              ])
                NvRow(
                  key: ValueKey('attach-${src.name}'),
                  icon: icon,
                  title: label,
                  subtitle: sub,
                  onTap: () {
                    Navigator.pop(ctx);
                    attachFrom(context, r, src);
                  },
                ),
            ]),
          ]),
        ),
      ),
    );

/// Thumbnails above the composer: progress while uploading, x to remove.
class AttachmentStrip extends StatelessWidget {
  const AttachmentStrip({super.key, required this.items, required this.onRemove});
  final List<PendingAttachment> items;
  final void Function(String localId) onRemove;

  @override
  Widget build(BuildContext context) {
    if (items.isEmpty) return const SizedBox.shrink();
    return SizedBox(
      key: const ValueKey('attach-strip'),
      height: 76,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.fromLTRB(6, 6, 6, 4),
        itemCount: items.length,
        separatorBuilder: (_, _) => const SizedBox(width: 8),
        itemBuilder: (context, i) => _Thumb(item: items[i], onRemove: () => onRemove(items[i].localId)),
      ),
    );
  }
}

class _Thumb extends StatelessWidget {
  const _Thumb({required this.item, required this.onRemove});
  final PendingAttachment item;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) {
    final failed = item.state == AttachState.failed;
    final body = item.isImage
        ? Image.memory(item.bytes, fit: BoxFit.cover, width: 66, height: 66, gaplessPlayback: true)
        : Container(
            width: 120,
            height: 66,
            padding: const EdgeInsets.fromLTRB(9, 8, 22, 8),
            color: NV.surface,
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisAlignment: MainAxisAlignment.center, children: [
              Icon(CupertinoIcons.doc_text, size: 16, color: NV.red),
              const SizedBox(height: 3),
              Text(item.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 11.5, color: NV.text)),
              Text(humanSize(item.size), style: NV.monoLabel(size: 9, color: NV.muted)),
            ]),
          );
    return Semantics(
      label: 'Lampiran ${item.name}',
      child: Stack(clipBehavior: Clip.none, children: [
        ClipRRect(
          borderRadius: BorderRadius.circular(10),
          child: DecoratedBox(
            position: DecorationPosition.foreground,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: failed ? NV.red : NV.glassBorder),
            ),
            child: Stack(children: [
              body,
              if (item.state == AttachState.uploading)
                Positioned(
                  left: 0,
                  right: 0,
                  bottom: 0,
                  child: LinearProgressIndicator(
                    key: ValueKey('attach-progress-${item.localId}'),
                    value: item.progress,
                    minHeight: 3,
                    color: NV.red,
                    backgroundColor: NV.bg.withValues(alpha: 0.6),
                  ),
                ),
              if (failed)
                Positioned.fill(
                  child: Container(
                    color: NV.bg.withValues(alpha: 0.65),
                    alignment: Alignment.center,
                    child: Icon(CupertinoIcons.exclamationmark_circle, color: NV.red, size: 22),
                  ),
                ),
            ]),
          ),
        ),
        Positioned(
          top: -6,
          right: -6,
          child: GestureDetector(
            key: ValueKey('attach-remove-${item.localId}'),
            onTap: onRemove,
            child: Container(
              width: 22,
              height: 22,
              decoration: BoxDecoration(color: NV.raised, shape: BoxShape.circle, border: Border.all(color: NV.border)),
              child: Icon(CupertinoIcons.xmark, size: 12, color: NV.text),
            ),
          ),
        ),
      ]),
    );
  }
}

/// Files on a chat message: the person's own (right-aligned above their bubble)
/// or files the PC agent sent with send_file ([alignEnd] false, under its reply).
/// Images show inline (tap: full-screen zoom + download), others as a file card
/// that downloads from the PC.
class MessageAttachments extends StatelessWidget {
  const MessageAttachments({super.key, required this.attachments, required this.gateway, this.alignEnd = true});
  final List<Map<String, dynamic>> attachments;
  final RemoteGateway? gateway;
  final bool alignEnd;

  @override
  Widget build(BuildContext context) {
    final atts = [for (final a in attachments) RemoteAttachment.fromJson(a)];
    final g = gateway;
    final side = alignEnd ? 150.0 : 220.0; // the agent's screenshots get more room
    return Align(
      alignment: alignEnd ? Alignment.centerRight : Alignment.centerLeft,
      child: Wrap(alignment: alignEnd ? WrapAlignment.end : WrapAlignment.start, spacing: 6, runSpacing: 6, children: [
        for (final a in atts)
          if (a.isImage && g != null)
            GestureDetector(
              key: ValueKey('msg-att-${a.id}'),
              onTap: () => showImagePreview(
                  context, remoteImageProvider(g.restUri(a.url ?? '/api/uploads/${a.id}'), g.restHeaders), a.name,
                  onDownload: () => _download(context, g, a)),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(12),
                child: Image(
                  image: remoteImageProvider(g.restUri(a.url ?? '/api/uploads/${a.id}'), g.restHeaders),
                  width: side,
                  height: side,
                  fit: BoxFit.cover,
                  errorBuilder: (_, _, _) => _FileChip(att: a, onTap: () => _download(context, g, a)),
                ),
              ),
            )
          else
            _FileChip(
              att: a,
              onTap: g == null ? null : () => _download(context, g, a),
            ),
      ]),
    );
  }
}

/// The agent's reply with the files it sent (send_file) underneath it.
Widget withAgentFiles(ChatMsg m, RemoteGateway? gateway, Widget reply) {
  if (m.attachments.isEmpty) return reply;
  return Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
    reply,
    const SizedBox(height: 8),
    MessageAttachments(key: ValueKey('agent-files-${m.id}'), attachments: m.attachments, gateway: gateway, alignEnd: false),
  ]);
}

/// Downloads an attachment from the PC through the system browser / download
/// manager (keeps the `?token=` auth); says so in Indonesian when it fails.
Future<void> _download(BuildContext context, RemoteGateway g, RemoteAttachment a) async {
  bool ok;
  try {
    ok = await launchDownload(g.downloadUri(a));
  } catch (_) {
    ok = false;
  }
  if (!ok && context.mounted) toast(context, 'Gagal mengunduh ${a.name} dari PC. Pastikan HP masih terhubung ke PC.');
}

class _FileChip extends StatelessWidget {
  const _FileChip({required this.att, required this.onTap});
  final RemoteAttachment att;
  final VoidCallback? onTap;
  @override
  Widget build(BuildContext context) => Material(
        color: NV.surface,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12), side: BorderSide(color: NV.border)),
        child: InkWell(
          key: ValueKey('msg-file-${att.id}'),
          borderRadius: BorderRadius.circular(12),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(10, 8, 12, 8),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(att.isImage ? CupertinoIcons.photo : CupertinoIcons.doc_text, size: 18, color: NV.red),
              const SizedBox(width: 8),
              ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 180),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                  Text(att.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 13, color: NV.text)),
                  Text(humanSize(att.size), style: NV.monoLabel(size: 9.5, color: NV.muted)),
                ]),
              ),
            ]),
          ),
        ),
      );
}

Future<void> showImagePreview(BuildContext context, ImageProvider image, String name, {VoidCallback? onDownload}) =>
    showDialog<void>(
      context: context,
      barrierColor: Colors.black.withValues(alpha: 0.88),
      builder: (ctx) => Dialog.fullscreen(
        backgroundColor: Colors.transparent,
        child: Stack(children: [
          Positioned.fill(
            child: InteractiveViewer(
              key: const ValueKey('image-preview'),
              maxScale: 5,
              child: Center(child: Image(image: image, fit: BoxFit.contain)),
            ),
          ),
          Positioned(
            top: MediaQuery.paddingOf(ctx).top + 8,
            left: 16,
            right: 8,
            child: Row(children: [
              Expanded(child: Text(name, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Colors.white, fontSize: 14))),
              if (onDownload != null)
                IconButton(
                  key: const ValueKey('image-preview-download'),
                  tooltip: 'Unduh / simpan',
                  onPressed: onDownload,
                  icon: const Icon(CupertinoIcons.arrow_down_circle_fill, color: Colors.white, size: 28),
                ),
              IconButton(
                tooltip: 'Tutup',
                onPressed: () => Navigator.pop(ctx),
                icon: const Icon(CupertinoIcons.xmark_circle_fill, color: Colors.white, size: 28),
              ),
            ]),
          ),
        ]),
      ),
    );

/// Test seam: how the phone opens a download URL (default: the system browser /
/// download manager, which keeps the `?token=` auth).
Future<bool> Function(Uri url) launchDownload =
    (url) => launchUrl(url, mode: LaunchMode.externalApplication);

/// A file path the PC agent mentioned in chat. Decks and reports it made
/// (.pptx, .docx, .pdf …) are downloaded from the PC, just like attachments;
/// anything else (source files, folders) only says where it lives on the PC.
Future<void> openPcFile(BuildContext context, RemoteGateway? gateway, String path) async {
  if (gateway != null && isDownloadableDoc(path)) {
    toast(context, 'Mengunduh ${path.split(RegExp(r'[\\/]')).last} dari PC…');
    final ok = await launchDownload(gateway.fsDownloadUri(path));
    if (!ok && context.mounted) toast(context, 'Gagal membuka unduhan. Berkas ada di PC: $path');
    return;
  }
  toast(context, 'Berkas ada di PC: $path');
}
