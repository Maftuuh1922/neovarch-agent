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
    version: '1.4.8',
    date: '2026-10-14',
    summary: 'Codemode (satu program memanggil banyak alat dalam satu panggilan model), Kantor ala Paperclip yang benar-benar bekerja, perintah neovarch update dan cek pembaruan dari GitHub Releases, Pamerkan dengan radar pemakaian nyata, Vault jadi vault Obsidian asli, Tempest v2 dengan web_search tanpa konfigurasi, alat agen yang lebih pintar, Mode Desain, dan chat Android yang lebih rapi.',
    sections: [
      ChangelogSection('Penting saat memperbarui', [
        'Perbarui aplikasi desktop dan aplikasi HP bersamaan.',
        'Heartbeat Kantor kini aktif secara bawaan begitu perusahaan ada; perusahaan lama yang belum pernah diubah dinyalakan sekali saat upgrade. Bisa dijeda di desktop dan HP.',
        'Mulai versi ini desktop memeriksa pembaruan dari GitHub Releases; pembaruan berikutnya cukup lewat neovarch update atau tombol Perbarui.',
      ]),
      ChangelogSection('Codemode', [
        'Alat codemode: model menulis satu program Python yang memanggil alat lain (juga paralel) dan hanya mencetak yang penting, jadi satu panggilan model menggantikan banyak.',
        'Program jalan di proses terpisah yang dijaga (tanpa jaringan dan tanpa proses baru secara bawaan); setiap panggilan alat di dalamnya lewat gerbang yang sama: persetujuan, /rencana, cek sintaks, checkpoint, dan hooks.',
        'Uji replay 10 tugas: panggilan model −60% dibanding satu alat per panggilan.',
      ]),
      ChangelogSection('Kantor ala Paperclip', [
        'Pegawai tidak lagi diam: heartbeat aktif, CEO mendapat tiket Susun strategi untuk tiap tujuan aktif lalu mengajukan strategi yang disetujui, diminta revisi, atau ditolak dewan.',
        'Agen bisa minta rekrut (selalu lewat persetujuan), biaya dicatat per panggilan model dan batas anggaran menghentikan heartbeat lalu mengajukan persetujuan anggaran.',
        'Feed aktivitas live (desktop Aktivitas live, HP Feed), thread tiket berisi komentar + jejak audit + run heartbeat, bagan organisasi bersambung, dan kendali dari HP.',
      ]),
      ChangelogSection('Pembaruan', [
        'Perintah neovarch update dan tombol Perbarui di Pengaturan › Tentang: instalasi git di-fast-forward lalu dependensi dipasang ulang, dengan rollback otomatis bila gagal (neovarch update --rollback).',
        'Bukan instalasi git: installer resmi dijalankan untuk rilis terbaru; AppImage/.deb membuka halaman rilis.',
        'Cek pembaruan desktop dari GitHub Releases: Linux (install.sh) Update sekarang lalu mulai ulang, Windows mengunduh dan menjalankan setup.exe; cek senyap paling sering sekali sehari.',
      ]),
      ChangelogSection('Pamerkan', [
        'Kartu Pamerkan mendapat radar dari pemakaian nyata (coding, riset, PPT, browser, otomasi, token) plus grafik bar, donut, dan tren harian/mingguan.',
        'Widget bisa disembunyikan (pilihan tersimpan), lebih banyak tema, tata letak, dan latar, serta ekspor gambar. Data hanya dari file lokal PC; tanpa data, kartu tampil kosong, bukan angka palsu.',
      ]),
      ChangelogSection('Vault Obsidian', [
        'Vault jadi vault Obsidian asli (Markdown, [[wikilink]], #tag, folder .obsidian) yang tersambung ke proyek dan sesi agen, dengan graf ala Obsidian bergaris tautan.',
        'Migrasi aman: cadangan zip dulu, catatan lama tidak diubah, memori agen disalin. Perintah neovarch vault init / sync.',
        'Ekstra opsional seperti Obsidian dipasang otomatis dari sumber resmi saat instalasi, pembaruan, atau sesuai permintaan (dengan persetujuan); graf bawaan tetap jalan tanpa Obsidian.',
      ]),
      ChangelogSection('Tempest v2 & alat agen', [
        'web_search tanpa konfigurasi dan tanpa API key (rantai fallback + cache 10 menit), web_fetch dengan fallback browser headless, alat baca-saja jalan paralel, aturan grounding dan cek angka terhadap sumber.',
        'edit_file toleran spasi/indentasi dengan multi-edit, alat grep dan glob, shell menyimpan output saat timeout dan bisa jalan di latar (shell_job).',
        'apply_patch multi-berkas, repo_map, sub-agen baca-saja paralel (task), hooks di ~/.neovarch/hooks.json, mode /rencana, dan file instruksi CLAUDE.md serta ~/.neovarch/AGENTS.md global.',
        'Mode Desain (/desain): design system di .neovarch/design yang otomatis dipakai agen saat coding UI, cek token, dan skill desain bawaan berlisensi permisif.',
      ]),
      ChangelogSection('Chat & HP', [
        'Satu gelembung per giliran agen dengan timeline live, jawaban akhir di bawah, dan langkah lama dilipat di balik +N langkah.',
        'Status header selebar penuh (tidak lagi langkah 9/3…) dan mode fokus saat scroll.',
        'Diagram mermaid/svg live dengan toggle Pratinjau | Kode, offline, plus layar penuh.',
        'Pemakaian token dengan satu arti untuk semua penyedia dan tampil sebagai grafik (Hari ini | Sesi | Semua, tren 14 hari, per model).',
        'Mik: strip status dikte, alur izin dan Speech Services, watchdog. Mode ringan selalu bisa dimatikan. Nama model di composer tidak lagi tampil dua kali.',
        'Profil: token GitHub yang ditolak tidak lagi memunculkan "pasangkan ulang"; HP menampilkan Masuk GitHub lagi di PC.',
      ]),
      ChangelogSection('Kualitas', [
        '9 tes packaging/updater bawaan upstream yang dikarantina dihapus.',
      ]),
    ],
  ),
  ChangelogEntry(
    version: '1.4.7',
    date: '2026-10-13',
    summary: 'Tailscale jadi jalur utama HP ↔ PC dengan panduan setup, Wi-Fi di PC Linux dan Windows diperbaiki, Tempest jadi otak bawaan dengan prompt ~52% lebih ramping, Stop benar-benar berhenti, beberapa lampiran dalam satu pesan, antrean pesan, monitor token, dan CLI di terminal.',
    sections: [
      ChangelogSection('Penting saat memperbarui', [
        'Perbarui aplikasi desktop dan aplikasi HP bersamaan.',
        'Relay bawaan tidak ada lagi: dari luar rumah pakai Tailscale, atau isi URL relay sendiri.',
        'Tempest sekarang otak bawaan; loop lama tetap bisa dipilih lewat harness_mode: legacy atau Pengaturan › Agent › Otak agen.',
      ]),
      ChangelogSection('Tailscale jadi jalur utama', [
        'HP mencoba alamat Tailscale PC dulu (IP 100.x, lalu MagicDNS), baru LAN; bila VPN HP mati, LAN dicoba dulu.',
        'Panduan "Siapkan Tailscale" di tab PC di HP dan di Pengaturan › Remote › Tailscale di desktop, dengan tombol Coba lagi / Periksa lagi.',
        'Relay bawaan (yang tidak pernah aktif) dimatikan; relay hanya jalan dengan URL relay sendiri.',
      ]),
      ChangelogSection('Koneksi Wi-Fi', [
        'Linux: desktop mendeteksi ufw/firewalld dan membuka port gateway hanya untuk alamat LAN privat lewat satu prompt pkexec. Periksa koneksi kini jujur.',
        'Windows: aturan firewall berlaku juga di Wi-Fi berprofil Publik, aturan blokir lama untuk Python dihapus, timeout LAN di HP 4 detik.',
      ]),
      ChangelogSection('Tempest', [
        'Tempest jadi otak bawaan: prompt ramping, pemeriksaan lint/tes sebelum selesai, dan checkpoint yang bisa dipulihkan.',
        'Prompt diet: prompt pertama 11.388 → 5.473 token (−52%), skema alat jarang dipakai dibuka saat dibutuhkan.',
        'Fase 2: pencarian sesi lama, pengingat memori, skill dari pengalaman, gerbang klaim, dan /rewind di obrolan.',
        'Perbaikan: Stop saat pemeriksaan berjalan, proses latar belakang ikut dimatikan, tanpa pytest = tanpa vonis, tes yang sudah merah tidak memicu rollback, checkpoint aman untuk folder besar, pesan berisi lampiran saja tetap membawa konteks, dan bytecode basi tidak lagi terbaca saat verifikasi.',
      ]),
      ChangelogSection('Chat', [
        'Beberapa gambar/berkas dalam satu pesan (maks. 10 lampiran, 25 MB per berkas).',
        'Stop membatalkan model, alat, dan proses yang sedang berjalan di PC; status Dihentikan sama di HP dan desktop.',
        'Antrean pesan: kirim saat agen bekerja, pesan masuk antrean yang bisa diedit, dihapus, atau dikirim sekarang.',
        'Batas langkah berbasis kemajuan dan penjelasan berhenti yang jelas dengan satu tombol aksi.',
        'Pemakaian token: konteks % di header chat, Profil › Pemakaian token, dan Token monitor di desktop.',
        'Tabel Markdown satu baris dirender sebagai tabel; avatar maskot Neovarch; HP membuka chat terakhir saat dibuka lagi.',
        'MiMo bisa membaca gambar; HP menyambung ulang sendiri saat PC restart; mic Android tidak lagi salah melapor izin ditolak.',
      ]),
      ChangelogSection('Agen & CLI', [
        'Chat interaktif di terminal (neovarch), agen yang bisa memperbaiki dirinya (/perbaiki, /undo), 26 skill bawaan, dan vision fallback.',
      ]),
      ChangelogSection('Kualitas', [
        'Tes penjaga versi: versi PC yang tampil di HP selalu sama dengan versi aplikasi.',
        'Tes desktop flaky diperbaiki dan 9 berkas tes kembali menjaga CI.',
      ]),
    ],
  ),
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
