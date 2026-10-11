// Changelog for the phone app: the bundled history ("Riwayat perubahan"),
// the one-time "Apa yang baru di vX" after an update, and the GitHub release
// body trimmed for the update dialog. Mirrors CHANGELOG.md at the repo root
// (test/changelog_test.dart keeps the two in step). Pure Dart.
import 'package:shared_preferences/shared_preferences.dart';

import 'update_check.dart' show isNewerVersion, parseVersion;

class ChangelogSection {
  const ChangelogSection(this.title, this.items);
  final String title;
  final List<String> items;
}

class ChangelogEntry {
  const ChangelogEntry({required this.version, this.date, required this.summary, required this.sections});
  final String version;

  /// Release date (YYYY-MM-DD); null = not released yet.
  final String? date;
  final String summary;
  final List<ChangelogSection> sections;

  bool get released => date != null;
}

/// Newest first. Keep in step with CHANGELOG.md.
const changelog = <ChangelogEntry>[
  ChangelogEntry(
    version: '1.4.6',
    date: '2026-10-11',
    summary: 'Pemasangan HP yang lebih aman, remote dari mana saja lewat relay terenkripsi, pilihan bahasa di Android, agen bisa mengirim berkas ke obrolan, Tempest Fase 1 (opsional), pembaruan langsung dari aplikasi, dan PowerPoint dari HP.',
    sections: [
      ChangelogSection('Penting saat memperbarui', [
        'Perbarui aplikasi desktop dan aplikasi HP bersamaan.',
        'Setelah memperbarui, tekan Buat token baru sekali di Pengaturan › Remote di PC agar QR dan token akses lama tidak berlaku lagi.',
      ]),
      ChangelogSection('Keamanan pemasangan HP', [
        'QR pemasangan sekarang sekali pakai dan berlaku 10 menit; QR baru muncul otomatis setelah dipindai. Kode pemasangan relay juga 10 menit dan sekali pakai.',
        'Setiap HP mendapat token sesi sendiri. Memasangkan ulang mengganti token lama, dan HP yang sudah terpasang otomatis pindah ke token sesi.',
        'HP yang tidak aktif 30 hari dilepas otomatis dengan pesan "Sesi kedaluwarsa, pasangkan ulang".',
        'Daftar perangkat terpasang di desktop menampilkan Terakhir aktif dan kapan perangkat kedaluwarsa. Tombol Cabut tetap ada.',
      ]),
      ChangelogSection('Remote dari mana saja', [
        'HP tersambung ke PC lewat relay cloud terenkripsi ujung-ke-ujung saat tidak satu jaringan: LAN dulu, lalu otomatis lewat relay, dan kembali ke LAN saat terjangkau lagi.',
        'Jalankan di latar belakang: gateway PC dan relay tetap jalan setelah jendela ditutup.',
      ]),
      ChangelogSection('Bahasa', [
        'Pilihan bahasa di Profil › Bahasa: Bahasa Indonesia, English, atau Ikuti sistem. Bahasa langsung berganti tanpa restart.',
        'Langkah "Pilih bahasa" jadi layar pertama di intro.',
        'Sebagian layar (Chat, Kantor, PC, Tugas, Vault, dll.) masih berbahasa Indonesia.',
      ]),
      ChangelogSection('Lampiran dari agen', [
        'Agen bisa mengirim berkas dan screenshot ke obrolan; lampiran tampil di HP dan desktop dan bisa diunduh.',
        'Windows: QR tidak lagi memilih adaptor virtual, aturan Firewall untuk port HP lewat UAC, dan pesan jelas bila HP terblokir.',
      ]),
      ChangelogSection('Tempest Fase 1 (opsional)', [
        'Harness agen baru lewat agent.harness_mode: tempest di config.yaml: cache prompt v2, compaction di 50% konteks, gerbang lint delta, checkpoint dengan rollback, dan neovarch rewind. Harness legacy tetap bawaan.',
      ]),
      ChangelogSection('Pembaruan & aplikasi', [
        'Perbarui langsung dari aplikasi: APK diunduh di dalam aplikasi dengan progres dan tombol Batal, dicek ukurannya (dan checksum bila ada), lalu penginstal Android terbuka. Kalau gagal, halaman unduhan dibuka di browser.',
        'Catatan rilis tampil di dialog pembaruan, "Apa yang baru" muncul sekali setelah memperbarui, dan ada layar Riwayat perubahan.',
        'Layar Tentang aplikasi di Profil: versi aplikasi HP dan core di PC, tautan GitHub dan situs, lisensi, serta tombol Periksa pembaruan.',
        'Mode ringan di Profil › Tampilan: efek kaca (blur) dimatikan dan diganti permukaan solid. Disarankan otomatis di HP dengan RAM kecil.',
        'Chat lebih lancar saat balasan mengalir: hanya gelembung yang sedang ditulis yang digambar ulang (maks. ~30 kali per detik), dan gambar latar dimuat seukuran layar.',
      ]),
      ChangelogSection('Chat & suara', [
        'Mic di chat jalan tanpa layanan Google: pengenal suara bawaan, lalu dialog suara sistem, lalu dikte offline, dengan pesan yang jelas kalau semuanya tidak tersedia.',
        '"Hey Neo" lebih andal mendengar panggilannya, memulai ulang dengan jujur, dan punya tombol Tes Hey Neo.',
        'Di Xiaomi, pintasan "Tampil di atas aplikasi lain" dan "Izinkan jalan di latar" membuka halaman Pengaturan yang benar.',
        'Pill model di chat HP menampilkan model yang dipakai PC; ketuk sekali untuk mengganti.',
        'Chat di HP dan desktop selalu sinkron.',
        'Profil & Teman di HP sinkron otomatis dari akun GitHub di PC.',
      ]),
      ChangelogSection('Agen & dokumen', [
        'PowerPoint dengan PPT Master: minta "buatin PPT dari …" dari desktop atau HP. Berkas .pptx, .docx, dan .pdf hasil agen punya tombol Unduh di HP.',
        'Kantor mulai kosong; agen utama Neovarch Agent menjawab semua chat dan mengelola Kantor.',
        'Model default MiMo V2.6 lewat 9Router.',
      ]),
      ChangelogSection('Desktop', [
        'Pengaturan: halaman Vault Obsidian dengan pemilih folder, login GitHub tanpa menempel Client ID, ganti bahasa ID/EN yang berfungsi, dan halaman Perilaku, Proyek, Shell, serta File yang terisi.',
        'Gateway LAN yang tertinggal di port 9319 dihentikan otomatis.',
      ]),
    ],
  ),
  ChangelogEntry(
    version: '1.4.5',
    date: '2026-10-10',
    summary: 'Desktop dan aplikasi HP satu versi. Kantor Perusahaan, widget layar utama, Kartu Neovarch, dan wake word "Hey Neo".',
    sections: [
      ChangelogSection('Sorotan', [
        'Kantor › Perusahaan: bagan organisasi agen, tiket, persetujuan, biaya, tujuan, dan rutinitas — di desktop dan di HP.',
        'Lampiran gambar dari HP sampai ke model.',
        'Scroll chat di HP diperbaiki: ikut balasan terbaru, tombol ↓ dengan jumlah balasan baru.',
      ]),
      ChangelogSection('HP', [
        'Tiga widget layar utama: Aksi cepat, Status, dan Agen.',
        'Kartu Neovarch untuk dibagikan ke Instagram, WhatsApp, TikTok, X, Facebook, Telegram, atau galeri.',
        'Taman di Kantor 3D, repo disematkan di Profil, dan heatmap kontribusi yang ikut warna tema.',
        'Wake word "Hey Neo" (opsional) dengan progres unduhan model suara.',
        'APK ditandatangani dengan kunci rilis Neovarch.',
      ]),
      ChangelogSection('Desktop', [
        'Kantor 3D dengan taman, model per agen, dan satu pemilih model di chat.',
        '9Router: model gratis tanpa API key, pindah otomatis saat model kena batas.',
      ]),
    ],
  ),
  ChangelogEntry(
    version: '1.3.0',
    date: '2026-10-08',
    summary: 'Core Neovarch sendiri, data di ~/.neovarch, port remote 9319, dan tampilan baru.',
    sections: [
      ChangelogSection('Yang baru', [
        'Core agen sendiri (perintah neovarch, loop agen, tools, sesi, memori, skill, dan gateway neovarch serve).',
        'Data terpisah di ~/.neovarch.',
        'Port remote baru 9319: pindai ulang QR dari desktop sekali.',
        'Tampilan baru merah gelap yang flat dengan sudut membulat di desktop dan Android.',
      ]),
    ],
  ),
  ChangelogEntry(
    version: '1.2.1',
    date: '2026-10-08',
    summary: 'Aplikasi desktop berbasis Electron, aplikasi HP sebagai remote.',
    sections: [
      ChangelogSection('Yang baru', [
        'Aplikasi HP tersambung ke PC lewat QR (Wi-Fi/LAN yang sama atau Tailscale).',
      ]),
    ],
  ),
];

/// The entry for [version] (major.minor.patch; build number ignored).
ChangelogEntry? changelogFor(String version) {
  final v = parseVersion(version);
  for (final e in changelog) {
    final ev = parseVersion(e.version);
    if (ev[0] == v[0] && ev[1] == v[1] && ev[2] == v[2]) return e;
  }
  return null;
}

/// True when [e] is newer than the running app (built from a branch ahead
/// of the last release): shown as "belum dirilis".
bool isUpcoming(ChangelogEntry e, String current) => !e.released || isNewerVersion(e.version, current);

/// The one-time "Apa yang baru di vX" after an update.
class WhatsNew {
  static const kSeen = 'nv.whatsnew.seen';

  /// Version whose sheet is still owed this launch (set by [prepare]).
  static String? pending;

  /// Call at app start, before anything writes preferences. A fresh install
  /// (no `nv.*` keys yet) just records [current]; an install that ran an
  /// older version (or ran before this feature existed) owes the sheet.
  static void prepare(SharedPreferences prefs, String current) {
    final seen = prefs.getString(kSeen);
    pending = null;
    if (seen == current) return;
    final prior = seen != null || prefs.getKeys().any((k) => k.startsWith('nv.') && k != kSeen);
    if (!prior) {
      prefs.setString(kSeen, current);
      return;
    }
    if (seen != null && !isNewerVersion(current, seen)) {
      // downgrade or same release: nothing new to show
      prefs.setString(kSeen, current);
      return;
    }
    pending = current;
  }

  /// The entry to show now (and marks it seen), or null.
  static ChangelogEntry? take(SharedPreferences prefs) {
    final v = pending;
    if (v == null) return null;
    pending = null;
    prefs.setString(kSeen, v);
    return changelogFor(v);
  }
}

/// A GitHub release body for the phone: install / download sections and
/// the top title are dropped (the dialog has its own), long bodies are cut.
String phoneReleaseNotes(String? body, {int maxChars = 3000}) {
  final raw = (body ?? '').replaceAll('\r\n', '\n').trim();
  if (raw.isEmpty) return '';
  final out = <String>[];
  var skip = false;
  for (final line in raw.split('\n')) {
    final t = line.trim();
    final h = RegExp(r'^(#{1,6})\s+(.*)$').firstMatch(t);
    if (h != null) {
      final level = h.group(1)!.length;
      final title = h.group(2)!.toLowerCase();
      if (level <= 2 && out.isEmpty) continue; // "## Neovarch Agent 1.4.5"
      skip = title.startsWith('pasang') || title.startsWith('unduhan') || title.startsWith('install') || title.startsWith('download');
      if (skip) continue;
    }
    if (skip) continue;
    out.add(line.trimRight());
  }
  var s = out.join('\n').replaceAll(RegExp(r'\n{3,}'), '\n\n').trim();
  if (s.length > maxChars) {
    final cut = s.lastIndexOf('\n', maxChars);
    s = '${s.substring(0, cut > maxChars ~/ 2 ? cut : maxChars).trimRight()}\n…';
  }
  return s;
}

/// One rendered line of release notes.
class NoteLine {
  const NoteLine(this.kind, this.text);

  /// 'heading', 'bullet' or 'text'.
  final String kind;
  final String text;
}

/// Markdown-lite → lines: headings, bullets, text; **bold**, `code` and
/// [links](url) reduced to their text.
List<NoteLine> parseNoteLines(String notes) {
  String clean(String s) => s
      .replaceAllMapped(RegExp(r'\[([^\]]+)\]\([^)]*\)'), (m) => m.group(1)!)
      .replaceAll('**', '')
      .replaceAll('__', '')
      .replaceAll('`', '')
      .trim();
  final out = <NoteLine>[];
  for (final line in notes.split('\n')) {
    final t = line.trim();
    if (t.isEmpty) continue;
    final h = RegExp(r'^#{1,6}\s+(.*)$').firstMatch(t);
    if (h != null) {
      out.add(NoteLine('heading', clean(h.group(1)!)));
    } else if (RegExp(r'^[-*•]\s+').hasMatch(t)) {
      out.add(NoteLine('bullet', clean(t.replaceFirst(RegExp(r'^[-*•]\s+'), ''))));
    } else {
      out.add(NoteLine('text', clean(t)));
    }
  }
  return out;
}
