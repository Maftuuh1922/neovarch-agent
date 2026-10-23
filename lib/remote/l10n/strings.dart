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
  'Mode ringan, tema, aksen, wallpaper, sudut': 'Lite mode, theme, accent, wallpaper, corners',
  'Mode ringan': 'Lite mode',
  'Mode ringan aktif': 'Lite mode on',
  'Matikan': 'Turn off',
  'Mode ringan aktif. Ketuk untuk mematikan.': 'Lite mode is on. Tap to turn it off.',
  'Aktif: efek kaca (blur) dimatikan, permukaan solid. Matikan untuk mengembalikan kaca dan blur.':
      'On: glass effects (blur) are off, surfaces are solid. Turn it off to bring the glass and blur back.',
  'Matikan efek kaca (blur) supaya aplikasi lebih lancar di HP dengan RAM kecil.':
      'Turn off glass effects (blur) so the app runs smoother on phones with little RAM.',
  'HP ini punya RAM {ram}. ': 'This phone has {ram} of RAM. ',
  'Aktifkan Mode ringan agar aplikasi lebih lancar? Bisa dimatikan lagi di Profil (paling atas).':
      'Turn on Lite mode so the app runs smoother? You can turn it off again at the top of Profile.',
  'Aktifkan': 'Turn on',
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
  'Radar pemakaian': 'Usage radar',
  'Perbarui Neovarch di PC untuk radar': 'Update Neovarch on the PC for the radar',
  'Belum ada data pemakaian di PC': 'No usage data on the PC yet',
  'Coding, riset, PPT, browser, otomasi, token · {days} hari': 'Coding, research, PPT, browser, automation, tokens · {days} days',

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
  // ---- dictation strip (v1.4.8) ------------------------------------------------------
  'Menyiapkan mikrofon…': 'Preparing the microphone…',
  'Mendengarkan…': 'Listening…',
  'Memproses…': 'Processing…',
  // ---- dictation via PC (1.4.9) --------------------------------------------------
  'Mentranskripsi di PC…': 'Transcribing on the PC…',
  'Merekam · ketuk mik lagi untuk kirim ke PC': 'Recording · tap the mic again to send to the PC',
  'Dikte suara': 'Voice dictation',
  'Mik di HP, STT lokal gratis di PC': 'Phone mic, free local STT on the PC',
  'Otomatis': 'Automatic',
  'Pengenal suara HP dulu; bila tidak ada, rekaman dikirim ke PC untuk ditranskripsi.':
      "The phone's recogniser first; without one, the recording is sent to the PC to transcribe.",
  'Lewat PC': 'Via the PC',
  'Selalu rekam di HP lalu transkripsi di PC (STT lokal gratis, tanpa Google).':
      'Always record on the phone and transcribe on the PC (free local STT, no Google).',
  'Kirim otomatis': 'Send automatically',
  'Mati: teks masuk ke kolom dulu untuk dicek.': 'Off: the text goes into the field first so you can check it.',
  'Cek apakah PC sudah punya STT lokal.': 'Check whether the PC has local STT.',
  'Cek PC': 'Check PC',
  'Mengecek…': 'Checking…',
  'STT PC siap: {engine} · model {model}': 'PC STT ready: {engine} · model {model}',
  'PC belum punya mesin STT. Di PC jalankan: {cmd}': 'The PC has no STT engine yet. On the PC run: {cmd}',
  'PC belum mendukung transkripsi — perbarui aplikasi PC.': "The PC doesn't support transcription yet — update the PC app.",
  'Berhenti': 'Stop',
  'Buka pengaturan': 'Open settings',
  'Pasang Speech Services': 'Install Speech Services',
  'Buka Speech Services': 'Open Speech Services',
  'Izinkan mikrofon': 'Allow the microphone',
  'Neovarch memakai mikrofon hanya saat kamu mengetuk tombol mik, untuk mengubah suaramu jadi teks di kolom chat. Setelah ini Android akan bertanya — pilih "Izinkan".':
      'Neovarch only uses the microphone when you tap the mic button, to turn your voice into text in the chat field. Android will ask next — choose "Allow".',
  'Tidak bisa membuka halaman itu di HP ini.': 'Could not open that page on this phone.',
  'Izin mikrofon ditolak. Ketuk mik lagi lalu pilih "Izinkan".': 'Microphone permission denied. Tap the mic again and choose "Allow".',
  'Izin mikrofon ditolak permanen. Buka pengaturan → Izin → Mikrofon → Izinkan, lalu ketuk mik lagi.':
      'Microphone permission is permanently denied. Open settings → Permissions → Microphone → Allow, then tap the mic again.',
  'Speech Services Google tidak ada di HP ini, jadi dikte tidak bisa jalan. Pasang "Speech Services by Google" (Play Store / GetApps), lalu ketuk mik lagi.':
      'Google Speech Services is missing on this phone, so dictation cannot run. Install "Speech Services by Google" (Play Store / GetApps), then tap the mic again.',
  'Suara tidak tertangkap: tidak ada suara terdeteksi. Coba lagi lebih dekat ke mikrofon.': 'No speech detected. Try again closer to the microphone.',
  'Jaringan bermasalah: pengenal suara Google butuh internet (atau unduh paket bahasa offline di pengaturan Google).':
      'Network problem: Google speech recognition needs the internet (or download the offline language pack in Google settings).',
  'Pengenal suara sedang dipakai aplikasi lain. Tunggu sebentar lalu coba lagi.': 'Speech recognition is in use by another app. Wait a moment and try again.',
  'Mikrofon sedang dipakai (mis. aplikasi lain atau "Hey Neo"). Coba lagi sebentar lagi.': 'The microphone is in use (another app or "Hey Neo"). Try again in a moment.',
  'Bahasa ini belum tersedia di pengenal suara HP. Tekan lama tombol mik untuk ganti ID/EN.': 'This language is not available in the phone\'s speech recognizer. Long-press the mic to switch ID/EN.',
  'Pengenal suara tidak menjawab. Coba lagi.': 'Speech recognition did not respond. Try again.',
  // ---- ```visual cards in chat (v1.4.9) -------------------------------------------------
  'Visual': 'Visual',
  'Diagram': 'Diagram',
  'Gaya Mermaid asli': 'Original Mermaid style',
  'Gaya baru': 'New style',
  'Menggambar…': 'Drawing…',
  'Layar penuh': 'Full screen',
  'Opsi visual': 'Visual options',
  'Lihat kode': 'View code',
  'Lihat gambar': 'View picture',
  'Simpan PNG': 'Save PNG',
  'Bagikan SVG': 'Share SVG',
  'Salin kode': 'Copy code',
  'Kode disalin': 'Code copied',
  'Visual gagal digambar — menampilkan kode': 'Could not draw this visual — showing the code',
  'Gambar gagal disimpan': 'Could not save the image',
  'Tersimpan di galeri (Pictures/Neovarch)': 'Saved to the gallery (Pictures/Neovarch)',
  // ---- crew --------------------------------------------------------------------
  'Crew': 'Crew',
  'Lanjutan': 'Advanced',
  'Tugas': 'Tasks',
  'crew · tim agen': 'crew · team of agents',
  'crew · lanjutan': 'crew · advanced',
  'Kenalan dengan Crew': 'Meet Crew',
  'Tulis tujuan, mis. “bandingkan 3 laptop di bawah 15 juta”.': 'Write a goal, e.g. “compare 3 laptops under 15 million”.',
  'Agen utama mengusulkan anggota, tugas dan alurnya.': 'The main agent proposes members, tasks and the flow.',
  'Kamu setujui, lalu lihat crew bekerja.': 'You approve, then watch the crew work.',
  'Mengerti': 'Got it',
  'Tujuan': 'Goal',
  'Apa yang harus diselesaikan crew?': 'What should the crew get done?',
  'Susun crew': 'Build crew',
  'Menyusun crew…': 'Building the crew…',
  'Atau mulai dari template': 'Or start from a template',
  'Hanya model gratis': 'Free models only',
  'Riwayat': 'History',
  '{done}/{total} tugas': '{done}/{total} tasks',
  'Riset': 'Research',
  'Konten': 'Content',
  'Coding': 'Coding',
  'Riset + Laporan': 'Research + Report',
  'Web': 'Web',
  'Baca file': 'Read files',
  'Tulis file': 'Write files',
  'Perintah': 'Commands',
  'santai': 'idle',
  'bekerja': 'working',
  'memeriksa': 'reviewing',
  'butuh kamu': 'needs you',
  'selesai': 'done',
  'galat': 'error',
  'Usulan': 'Proposal',
  'Bekerja': 'Working',
  'Gagal': 'Failed',
  'Dihentikan': 'Stopped',
  'Disusun agen utama': 'Designed by the main agent',
  'Dari template': 'From the template',
  'Dipimpin manajer': 'Led by a manager',
  'Berurutan': 'One after another',
  'Manajer': 'Manager',
  'Gedung crew: tiap anggota di mejanya': 'Crew building: each member at their desk',
  '{name} minta izin': '{name} asks for permission',
  'Anggota': 'Members',
  'Tanpa alat': 'No tools',
  'Bawaan gratis': 'Free default',
  'Hasil': 'Result',
  'Crew ini bisa mengubah file atau menjalankan perintah.': 'This crew can change files or run commands.',
  'Izinkan (perintah berisiko tetap minta izinmu)': 'Allow it (risky commands still ask you first)',
  'Setujui & mulai': 'Approve & start',
  'Jalankan lagi': 'Run again',
  'Hentikan': 'Stop',
  'Ubah di Lanjutan': 'Edit in Advanced',
  'Nanti saja': 'Not now',
  'Crew baru': 'New crew',
  'Tersimpan': 'Saved',
  'Alur': 'Flow',
  'Nama': 'Name',
  'Peran': 'Role',
  'Model (hanya gratis)': 'Model (free only)',
  'Deskripsi': 'Description',
  'Dikerjakan': 'Done by',
  'Simpan perubahan': 'Save changes',
  'Pilih usulan crew dulu, lalu ubah di sini.': 'Pick a crew proposal first, then edit it here.',
  'Kantor & perusahaan lama': 'Old office & company',
  'Tampilan Kantor sebelumnya (3D, pegawai, aktivitas).': 'The previous Office view (3D, staff, activity).',
  'Perusahaan': 'Company',
  'Organisasi, tiket, persetujuan, biaya.': 'Org chart, tickets, approvals, costs.',
  'PC belum mendukung Crew. Perbarui Neovarch di PC.': "Your PC doesn't support Crew yet. Update Neovarch on the PC.",
};
