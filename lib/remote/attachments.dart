// Chat attachments from the phone: picked / pasted / shot files are uploaded to
// the PC core (`POST /api/uploads`, multipart, max 25 MB) and referenced by id
// in `prompt.submit {attachments: [...]}`. Pure Dart.
import 'dart:typed_data';

const int kMaxAttachmentBytes = 25 * 1024 * 1024;

/// An upload stored on the PC (`/api/uploads` response / message attachments).
class RemoteAttachment {
  const RemoteAttachment({required this.id, required this.name, this.mime = 'application/octet-stream', this.size = 0, this.kind = 'file', this.url});
  final String id, name, mime, kind;
  final int size;
  final String? url;
  bool get isImage => kind == 'image' || mime.startsWith('image/');

  factory RemoteAttachment.fromJson(Map<String, dynamic> j) => RemoteAttachment(
        id: '${j['id'] ?? ''}',
        name: '${j['name'] ?? 'berkas'}',
        mime: '${j['mime'] ?? 'application/octet-stream'}',
        size: (j['size'] as num?)?.toInt() ?? 0,
        kind: '${j['kind'] ?? 'file'}',
        url: j['url'] == null ? null : '${j['url']}',
      );

  Map<String, dynamic> toJson() => {'id': id, 'name': name, 'mime': mime, 'size': size, 'kind': kind, if (url != null) 'url': url};
}

enum AttachState { uploading, done, failed }

/// A composer chip: local bytes until the upload finishes, then the remote id.
class PendingAttachment {
  PendingAttachment({required this.localId, required this.name, required this.mime, required this.bytes});
  final String localId;
  final String name;
  final String mime;
  final Uint8List bytes;
  AttachState state = AttachState.uploading;
  double progress = 0;
  RemoteAttachment? remote;
  String? error;

  bool get isImage => mime.startsWith('image/');
  int get size => bytes.length;
}

String mimeForName(String name, [String? fallback]) {
  final n = name.toLowerCase();
  final ext = n.contains('.') ? n.substring(n.lastIndexOf('.') + 1) : '';
  const map = {
    'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'gif': 'image/gif', 'webp': 'image/webp',
    'heic': 'image/heic', 'bmp': 'image/bmp', 'pdf': 'application/pdf', 'txt': 'text/plain', 'md': 'text/markdown',
    'csv': 'text/csv', 'json': 'application/json', 'zip': 'application/zip', 'docx':
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  };
  return map[ext] ?? fallback ?? 'application/octet-stream';
}

/// Sniff images by magic bytes (clipboard / keyboard content often lacks a name).
String? sniffImageMime(List<int> b) {
  if (b.length >= 8 && b[0] == 0x89 && b[1] == 0x50 && b[2] == 0x4E && b[3] == 0x47) return 'image/png';
  if (b.length >= 3 && b[0] == 0xFF && b[1] == 0xD8 && b[2] == 0xFF) return 'image/jpeg';
  if (b.length >= 6 && b[0] == 0x47 && b[1] == 0x49 && b[2] == 0x46) return 'image/gif';
  if (b.length >= 12 && b[0] == 0x52 && b[1] == 0x49 && b[2] == 0x46 && b[3] == 0x46 && b[8] == 0x57 && b[9] == 0x45 && b[10] == 0x42 && b[11] == 0x50) {
    return 'image/webp';
  }
  return null;
}

String humanSize(int bytes) {
  if (bytes < 1024) return '$bytes B';
  if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(0)} KB';
  return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
}

/// Files the PC agent makes that the phone should download instead of showing
/// "the file is on the PC": Word/PDF reports, PowerPoint decks, images
/// (screenshots the agent only named by path) and diagrams (.html/.svg pages
/// from `diagram_save`, which the phone's browser opens).
final _downloadableDoc = RegExp(
    r'\.(pptx?|docx?|pdf|xlsx?|odt|odp|csv|zip|html?|svg|mmd|png|jpe?g|gif|webp|bmp)$',
    caseSensitive: false);

bool isDownloadableDoc(String path) => _downloadableDoc.hasMatch(path.trim());
