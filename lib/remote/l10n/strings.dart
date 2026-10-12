// UI strings of the phone remote. Indonesian is the source language: the
// Indonesian text itself is the key, so untranslated strings simply stay
// Indonesian. `tr('Lanjut')` → "Continue" when English is active.
// Placeholders: `tr('Terhubung ke {name}', {'name': pc})`.
//
// Shared headings ([NvHeader], [NvSection]) and the Profil groups run their
// labels through [tr] themselves, so most screens only need entries here.

class L10n {
  L10n._();

  /// Language in effect (`id` or `en`), kept by AppLanguageController.
  static String code = 'id';

  static bool get english => code == 'en';
}

String tr(String id, [Map<String, Object?> args = const {}]) {
  var s = L10n.english ? (enStrings[id] ?? id) : id;
  if (args.isNotEmpty) {
    args.forEach((k, v) => s = s.replaceAll('{$k}', '$v'));
  }
  return s;
}

/// English for every translated Indonesian string (key = Indonesian text).
const enStrings = <String, String>{
  // ---- language ---------------------------------------------------------------
  'Ikuti sistem': 'Follow system',
  'Sekarang: {lang}': 'Now: {lang}',
  'Bahasa': 'Language',
  'Bahasa Indonesia, English, atau ikuti sistem': 'Bahasa Indonesia, English, or follow the system',
  'bahasa · language': 'bahasa · language',
  'Pilih bahasa.': 'Choose your language.',
  'Bisa diganti kapan saja di Profil → Bahasa.': 'You can change it anytime in Profile → Language.',

  // ---- intro --------------------------------------------------------------------
  'pc = otak · hp = remote': 'pc = brain · phone = remote',
  'Agen di PC,\nremote di saku.': 'Agents on your PC,\nthe remote in your pocket.',
  'Neovarch berjalan di aplikasi desktop. HP ini hanya remote: kirim perintah dan lihat hasilnya.':
      'Neovarch runs in the desktop app. This phone is just the remote: send commands and see the results.',
  'Tanpa kunci API di HP': 'No API keys on the phone',
  'Satu PC atau beberapa': 'One PC or several',
  'tugas · kanban': 'tasks · kanban',
  'Pantau kerja\npara agen.': 'Keep an eye\non your agents.',
  'Papan tugas di PC tampil di sini: siapa mengerjakan apa, sampai mana, dan apa yang menunggu review.':
      "Your PC's task board shows up here: who is doing what, how far along, and what is waiting for review.",
  'Pindahkan tugas': 'Move tasks',
  'Kirim arahan': 'Send directions',
  'persetujuan · aman': 'approvals · safe',
  'Kamu yang\nmemutuskan.': 'You make\nthe call.',
  'Perintah berisiko berhenti dulu sampai kamu setujui dari HP. Token pemasangan disimpan terenkripsi.':
      'Risky commands wait until you approve them from your phone. The pairing token is stored encrypted.',
  'Izinkan sekali': 'Allow once',
  'Tolak kapan saja': 'Deny anytime',
  'Tutup': 'Close',
  'Lewati': 'Skip',
  'Selesai': 'Done',
  'Hubungkan PC': 'Connect PC',
  'Lanjut': 'Continue',
  'TAMPILAN · TEMA': 'APPEARANCE · THEME',
  'Pilih temamu.': 'Pick your theme.',
  'Pilih warna dan mode. Kalau dilewati, HP mengikuti tema PC setelah terhubung.':
      "Pick a colour and mode. If you skip this, the phone follows your PC's theme once connected.",
  'Tema khusus HP ini dipakai, juga setelah terhubung. Ubah kapan saja di Profil → Tampilan.':
      "This phone's own theme is used, also after connecting. Change it anytime in Profile → Appearance.",

  'Kembali': 'Back',

  // ---- shell --------------------------------------------------------------------
  'Chat': 'Chat',
  'Kantor': 'Office',
  'PC': 'PC',
  'Profil': 'Profile',
  'Agen di PC menunggu persetujuanmu': 'An agent on your PC is waiting for your approval',
  'Lihat': 'View',
  'BELUM ADA PC': 'NO PC YET',
  'Coba lagi': 'Try again',
  'Perbarui': 'Update',
  'Update tersedia v{v}': 'Update available v{v}',
  'Mengunduh v{v}': 'Downloading v{v}',

  // ---- profil -------------------------------------------------------------------
  'hp ini': 'this phone',
  'pengaturan': 'settings',
  'Model AI': 'AI model',
  'Model default agen di PC': "Default model of the agents on your PC",
  'Hey Neo': 'Hey Neo',
  'Panggil agen dengan suara (opsional)': 'Call the agent by voice (optional)',
  'Tampilan': 'Appearance',
  'Tema, aksen, wallpaper, sudut, mode ringan': 'Theme, accent, wallpaper, corners, lite mode',
  'Gaya kaca': 'Glass style',
  'Reguler, bening, gelap, warna, tanpa': 'Regular, clear, dark, tinted, none',
  'Ikon aplikasi': 'App icon',
  'Warna ikon di layar utama': 'Icon colour on the home screen',
  'Teman': 'Friends',
  'Teman GitHub & bagikan profil': 'GitHub friends & share your profile',
  'aplikasi': 'app',
  'Tentang aplikasi': 'About the app',
  'v{v} · pembaruan, tautan, lisensi': 'v{v} · updates, links, licences',
  'Riwayat perubahan': 'Changelog',
  'Yang baru di setiap versi': "What's new in each version",
  'Pamerkan': 'Show off',

  // ---- hubungkan PC -------------------------------------------------------------
  'Terhubung ke {name}': 'Connected to {name}',
  'QR tidak dikenali.': 'QR code not recognised.',
  'QR ini tidak memuat token. Salin token dari PC lalu tekan Hubungkan.':
      "This QR code has no token. Copy the token from your PC, then tap Connect.",
  'Alamat tidak valid. Contoh: 192.168.1.5:9319': 'Invalid address. Example: 192.168.1.5:9319',
  'perangkat · tambah': 'devices · add',
  'Tambah PC': 'Add PC',
  'Hubungkan ke PC': 'Connect to your PC',
  'Agen Neovarch berjalan di aplikasi desktop. HP ini hanya remote: kirim perintah, pantau tugas, dan setujui aksi agen dari jaringan yang sama.':
      "Neovarch agents run in the desktop app. This phone is just the remote: send commands, follow tasks and approve the agents' actions from the same network.",
  'Buka Neovarch Desktop di PC.': 'Open Neovarch Desktop on your PC.',
  'Masuk ke Pengaturan → Remote / Perangkat, aktifkan akses remote.': 'Go to Settings → Remote / Devices and turn on remote access.',
  'Pindai QR yang muncul, atau ketik alamat dan token-nya di bawah.': 'Scan the QR code it shows, or type its address and token below.',
  'Pindai QR dari PC': 'Scan QR from PC',
  'Masukkan alamat & token': 'Enter address & token',
  'manual': 'manual',
  'Alamat gateway PC': 'PC gateway address',
  '192.168.1.5:9319 atau tautan pemasangan': '192.168.1.5:9319 or a pairing link',
  'Port bawaan 9319. Tautan neovarch://pair… juga bisa ditempel di sini.': 'Default port 9319. A neovarch://pair… link can be pasted here too.',
  'Token': 'Token',
  'token dari Remote / Perangkat di PC': 'token from Remote / Devices on your PC',
  'Sembunyikan': 'Hide',
  'Tampilkan': 'Show',
  'Nama PC (opsional)': 'PC name (optional)',
  'Menghubungkan…': 'Connecting…',
  'Hubungkan': 'Connect',
  'menghubungi PC…': 'contacting PC…',
  'pc tersimpan': 'saved pcs',
  'Cukup pindai sekali. Di Wi-Fi yang sama HP tersambung langsung; di luar rumah otomatis lewat relay terenkripsi — tanpa aplikasi tambahan. Kunci disimpan terenkripsi di HP.':
      'Scan once. On the same Wi-Fi the phone connects directly; away from home it goes through the encrypted relay automatically — no extra app. Keys are stored encrypted on the phone.',

  // ---- antrean pesan (v1.4.7) ------------------------------------------------------
  'Antre ({n})': 'Queued ({n})',
  'Antrean dijeda karena giliran gagal. Kirim sekarang atau lanjutkan.': 'Queue paused because the turn failed. Send now or resume.',
  'Antrean dijeda karena agen dihentikan. Kirim sekarang atau lanjutkan.': 'Queue paused because the agent was stopped. Send now or resume.',
  'Agen masih bekerja. Tunggu sampai selesai atau tekan Stop. Perbarui Neovarch di PC (≥ 1.4.7) agar pesan otomatis diantre.':
      'The agent is still working. Wait for it to finish or press Stop. Update Neovarch on your PC (≥ 1.4.7) to queue messages automatically.',
  'Antrean penuh (maks 20 pesan).': 'Queue is full (max 20 messages).',
  'Pesan antrean sudah terkirim atau dihapus.': 'That queued message was already sent or removed.',
  'Pesan kosong.': 'Empty message.',
  'Belum terhubung ke PC.': 'Not connected to the PC yet.',
  'Kirim sekarang': 'Send now',
  'Lanjutkan antrean': 'Resume queue',
  'Edit pesan antrean': 'Edit queued message',
  'Hapus dari antrean': 'Remove from queue',
  'Simpan': 'Save',
  'Batal': 'Cancel',
  'Masuk antrean · dikirim setelah agen selesai': 'Queued · sent when the agent finishes',
  '{n} lampiran': '{n} attachments',
  // ---- restart PC (v1.4.7) ----------------------------------------------------------
  'PC sedang restart… menyambung ulang': 'PC is restarting… reconnecting',
  'PC belum kembali setelah restart. Pastikan aplikasi Neovarch di PC berjalan, lalu tarik untuk menyambung ulang.':
      'The PC has not come back after the restart. Make sure the Neovarch app is running on your PC, then pull to reconnect.',
};
