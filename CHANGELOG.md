# Riwayat perubahan

Semua perubahan penting Neovarch Agent (desktop, core, dan aplikasi HP). Yang terbaru di atas.
Aplikasi HP menampilkan isi yang sama di **Profil › Riwayat perubahan** (`lib/remote/changelog.dart`; `test/changelog_test.dart` menjaga keduanya tetap sama).

## [1.4.6] — belum dirilis

Pembaruan langsung dari aplikasi, PowerPoint dari HP, mic dan Hey Neo yang lebih andal di Xiaomi, dan aplikasi yang lebih ringan.
Berisi pekerjaan PR #2 (`fix-obsidian-vault-settings`) dan PR #3 (`ppt-master`).

### Pembaruan & aplikasi (PR #3)

- Perbarui langsung dari aplikasi: APK diunduh di dalam aplikasi dengan progres dan tombol Batal, dicek ukurannya (dan checksum SHA-256 bila rilis menyertakannya), lalu penginstal Android terbuka. Kalau gagal, halaman unduhan dibuka di browser. Pengecekan dibatasi sekali per 6 jam dan notifikasi muncul sekali per versi.
- Catatan rilis (dari halaman rilis GitHub) tampil di dialog pembaruan, "Apa yang baru di vX" muncul sekali setelah memperbarui, dan ada layar Riwayat perubahan.
- Layar **Tentang aplikasi** di Profil: versi aplikasi HP dan core di PC, tautan GitHub dan situs, lisensi, serta tombol Periksa pembaruan.
- **Mode ringan** di Profil › Tampilan: efek kaca (blur) dimatikan dan diganti permukaan solid. Disarankan otomatis sekali di HP dengan RAM kecil.
- Chat lebih lancar saat balasan mengalir: hanya gelembung yang sedang ditulis yang digambar ulang (maks. ~30 kali per detik), dan gambar latar dimuat seukuran layar.

### Chat & suara (PR #2, PR #3)

- Mic di chat jalan tanpa layanan Google: pengenal suara bawaan, lalu dialog suara sistem, lalu dikte offline, dengan pesan yang jelas kalau semuanya tidak tersedia. Mic yang gagal tidak lagi membuat aplikasi crash.
- "Hey Neo" lebih andal mendengar panggilannya, memulai ulang dengan jujur, dan punya tombol Tes Hey Neo.
- Di Xiaomi, pintasan "Tampil di atas aplikasi lain" dan "Izinkan jalan di latar" membuka halaman Pengaturan yang benar.
- Pill model di chat HP menampilkan model yang dipakai PC; ketuk sekali untuk mengganti.
- Chat di HP dan desktop selalu sinkron.

### Agen & dokumen (PR #2, PR #3)

- PowerPoint dengan PPT Master: minta "buatin PPT dari …" dari desktop atau HP. Berkas .pptx, .docx, dan .pdf hasil agen punya tombol Unduh di HP.
- Kantor mulai kosong; agen utama Neovarch Agent menjawab semua chat dan mengelola Kantor.
- Model default MiMo V2.6 lewat 9Router.

### Desktop (PR #2)

- Pengaturan: halaman Vault Obsidian dengan pemilih folder, login GitHub tanpa menempel Client ID, ganti bahasa ID/EN yang berfungsi, dan halaman Perilaku, Proyek, Shell, serta File yang terisi.
- Gateway LAN yang tertinggal di port 9319 dihentikan otomatis.

## [1.4.5] — 2026-10-10

Desktop dan aplikasi HP satu versi. Kantor Perusahaan, widget layar utama, Kartu Neovarch, dan wake word "Hey Neo".

### Sorotan

- Kantor › Perusahaan: bagan organisasi agen, tiket, persetujuan, biaya, tujuan, dan rutinitas — di desktop dan di HP.
- Lampiran gambar dari HP sampai ke model.
- Scroll chat di HP diperbaiki: ikut balasan terbaru, tombol ↓ dengan jumlah balasan baru.

### HP

- Tiga widget layar utama: Aksi cepat, Status, dan Agen.
- Kartu Neovarch untuk dibagikan ke Instagram, WhatsApp, TikTok, X, Facebook, Telegram, atau galeri.
- Taman di Kantor 3D, repo disematkan di Profil, dan heatmap kontribusi yang ikut warna tema.
- Wake word "Hey Neo" (opsional) dengan progres unduhan model suara.
- APK ditandatangani dengan kunci rilis Neovarch.

### Desktop

- Kantor 3D dengan taman, model per agen, dan satu pemilih model di chat.
- 9Router: model gratis tanpa API key, pindah otomatis saat model kena batas.

## [1.3.0] — 2026-10-08

Core Neovarch sendiri, data di ~/.neovarch, port remote 9319, dan tampilan baru.

- Core agen sendiri (perintah `neovarch`, loop agen, tools, sesi, memori, skill, dan gateway `neovarch serve`).
- Data terpisah di `~/.neovarch`.
- Port remote baru 9319: pindai ulang QR dari desktop sekali.
- Tampilan baru merah gelap yang flat dengan sudut membulat di desktop dan Android.

## [1.2.1] — 2026-10-08

Aplikasi desktop berbasis Electron, aplikasi HP sebagai remote.

- Aplikasi HP tersambung ke PC lewat QR (Wi-Fi/LAN yang sama atau Tailscale).
