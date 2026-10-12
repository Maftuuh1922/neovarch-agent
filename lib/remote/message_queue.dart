// Antrean pesan (v1.4.7). Messages sent while the agent works wait in the PC's
// per-session queue (core `msg_queue.py`), so the phone and the desktop show the
// same list. The PC sends them in order when the turn ends; a Stop or an error
// pauses the queue until the person resumes it or taps "Kirim sekarang".
import 'l10n/strings.dart';

class QueuedMessage {
  const QueuedMessage({required this.id, required this.text, this.ts, this.attachmentCount = 0});
  final String id;
  final String text;
  final double? ts;
  final int attachmentCount;

  static QueuedMessage? fromJson(Object? j) {
    if (j is! Map) return null;
    final id = '${j['id'] ?? ''}';
    if (id.isEmpty) return null;
    return QueuedMessage(
      id: id,
      text: '${j['text'] ?? ''}',
      ts: (j['ts'] as num?)?.toDouble(),
      attachmentCount: (j['attachments'] as List?)?.length ?? 0,
    );
  }
}

class MessageQueueState {
  const MessageQueueState({this.items = const [], this.paused = false, this.pausedReason});
  final List<QueuedMessage> items;
  final bool paused;

  /// 'stopped' (the person pressed Stop) or 'error' (the turn failed).
  final String? pausedReason;

  static const empty = MessageQueueState();
  bool get isEmpty => items.isEmpty;
  int get count => items.length;

  /// `queue.update` payload / `session.resume.queue` / `prompt.submit.queue`.
  static MessageQueueState fromJson(Object? j) {
    if (j is! Map) return empty;
    final items = [for (final i in (j['items'] as List? ?? const [])) QueuedMessage.fromJson(i)].whereType<QueuedMessage>().toList();
    return MessageQueueState(
      items: items,
      paused: j['paused'] == true && items.isNotEmpty,
      pausedReason: j['paused_reason'] is String ? j['paused_reason'] as String : null,
    );
  }

  /// "Antre (2)" / "Queued (2)".
  String get label => tr('Antre ({n})', {'n': count});

  /// Why the queue waits, or null while it drains normally.
  String? get pausedLabel {
    if (!paused) return null;
    return pausedReason == 'error'
        ? tr('Antrean dijeda karena giliran gagal. Kirim sekarang atau lanjutkan.')
        : tr('Antrean dijeda karena agen dihentikan. Kirim sekarang atau lanjutkan.');
  }
}

/// Raw core errors a person must never see in English (older PCs answer
/// `a turn is already running in this session` instead of queueing).
String? friendlyCoreError(String raw) {
  final s = raw.toLowerCase();
  if (s.contains('turn is already running')) {
    return tr('Agen masih bekerja. Tunggu sampai selesai atau tekan Stop. Perbarui Neovarch di PC (≥ 1.4.7) agar pesan otomatis diantre.');
  }
  if (s.contains('antrean penuh')) return tr('Antrean penuh (maks 20 pesan).');
  if (s.contains('pesan antrean tidak ditemukan')) return tr('Pesan antrean sudah terkirim atau dihapus.');
  if (s.contains('text is required')) return tr('Pesan kosong.');
  return null;
}
