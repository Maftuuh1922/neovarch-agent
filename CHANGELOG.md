# Riwayat perubahan

Semua perubahan penting Neovarch Agent (desktop, core, dan aplikasi HP). Yang terbaru di atas.
Aplikasi HP menampilkan isi yang sama di **Profil › Riwayat perubahan** (`lib/remote/changelog.dart`; `test/changelog_test.dart` menjaga keduanya tetap sama).

## [1.4.8] — 2026-10-14

Codemode (satu program memanggil banyak alat dalam satu panggilan model), Kantor ala Paperclip yang benar-benar bekerja, perintah neovarch update dan cek pembaruan dari GitHub Releases, Pamerkan dengan radar pemakaian nyata, Vault jadi vault Obsidian asli, Tempest v2 dengan web_search tanpa konfigurasi, alat agen yang lebih pintar, Mode Desain, dan chat Android yang lebih rapi.
Berisi pekerjaan PR #37–#57 (antara lain #38 cek pembaruan, #39 Tempest v2, #52/#53 Vault Obsidian, #54 codemode, #55 Kantor, #56 neovarch update, #57 Pamerkan).

### Penting saat memperbarui

- Perbarui aplikasi desktop dan aplikasi HP bersamaan.
- Heartbeat Kantor kini aktif secara bawaan begitu perusahaan ada; perusahaan lama yang belum pernah diubah dinyalakan sekali saat upgrade. Bisa dijeda di desktop dan HP.
- Mulai versi ini desktop memeriksa pembaruan dari GitHub Releases; pembaruan berikutnya cukup lewat neovarch update atau tombol Perbarui.

### Codemode

- Alat codemode: model menulis satu program Python yang memanggil alat lain (juga paralel) dan hanya mencetak yang penting, jadi satu panggilan model menggantikan banyak.
- Program jalan di proses terpisah yang dijaga (tanpa jaringan dan tanpa proses baru secara bawaan); setiap panggilan alat di dalamnya lewat gerbang yang sama: persetujuan, /rencana, cek sintaks, checkpoint, dan hooks.
- Uji replay 10 tugas: panggilan model −60% dibanding satu alat per panggilan.

### Kantor ala Paperclip

- Pegawai tidak lagi diam: heartbeat aktif, CEO mendapat tiket Susun strategi untuk tiap tujuan aktif lalu mengajukan strategi yang disetujui, diminta revisi, atau ditolak dewan.
- Agen bisa minta rekrut (selalu lewat persetujuan), biaya dicatat per panggilan model dan batas anggaran menghentikan heartbeat lalu mengajukan persetujuan anggaran.
- Feed aktivitas live (desktop Aktivitas live, HP Feed), thread tiket berisi komentar + jejak audit + run heartbeat, bagan organisasi bersambung, dan kendali dari HP.

### Pembaruan

- Perintah neovarch update dan tombol Perbarui di Pengaturan › Tentang: instalasi git di-fast-forward lalu dependensi dipasang ulang, dengan rollback otomatis bila gagal (neovarch update --rollback).
- Bukan instalasi git: installer resmi dijalankan untuk rilis terbaru; AppImage/.deb membuka halaman rilis.
- Cek pembaruan desktop dari GitHub Releases: Linux (install.sh) Update sekarang lalu mulai ulang, Windows mengunduh dan menjalankan setup.exe; cek senyap paling sering sekali sehari.

### Pamerkan

- Kartu Pamerkan mendapat radar dari pemakaian nyata (coding, riset, PPT, browser, otomasi, token) plus grafik bar, donut, dan tren harian/mingguan.
- Widget bisa disembunyikan (pilihan tersimpan), lebih banyak tema, tata letak, dan latar, serta ekspor gambar. Data hanya dari file lokal PC; tanpa data, kartu tampil kosong, bukan angka palsu.

### Vault Obsidian

- Vault jadi vault Obsidian asli (Markdown, [[wikilink]], #tag, folder .obsidian) yang tersambung ke proyek dan sesi agen, dengan graf ala Obsidian bergaris tautan.
- Migrasi aman: cadangan zip dulu, catatan lama tidak diubah, memori agen disalin. Perintah neovarch vault init / sync.
- Ekstra opsional seperti Obsidian dipasang otomatis dari sumber resmi saat instalasi, pembaruan, atau sesuai permintaan (dengan persetujuan); graf bawaan tetap jalan tanpa Obsidian.

### Tempest v2 & alat agen

- web_search tanpa konfigurasi dan tanpa API key (rantai fallback + cache 10 menit), web_fetch dengan fallback browser headless, alat baca-saja jalan paralel, aturan grounding dan cek angka terhadap sumber.
- edit_file toleran spasi/indentasi dengan multi-edit, alat grep dan glob, shell menyimpan output saat timeout dan bisa jalan di latar (shell_job).
- apply_patch multi-berkas, repo_map, sub-agen baca-saja paralel (task), hooks di ~/.neovarch/hooks.json, mode /rencana, dan file instruksi CLAUDE.md serta ~/.neovarch/AGENTS.md global.
- Mode Desain (/desain): design system di .neovarch/design yang otomatis dipakai agen saat coding UI, cek token, dan skill desain bawaan berlisensi permisif.

### Chat & HP

- Satu gelembung per giliran agen dengan timeline live, jawaban akhir di bawah, dan langkah lama dilipat di balik +N langkah.
- Status header selebar penuh (tidak lagi langkah 9/3…) dan mode fokus saat scroll.
- Diagram mermaid/svg live dengan toggle Pratinjau | Kode, offline, plus layar penuh.
- Pemakaian token dengan satu arti untuk semua penyedia dan tampil sebagai grafik (Hari ini | Sesi | Semua, tren 14 hari, per model).
- Mik: strip status dikte, alur izin dan Speech Services, watchdog. Mode ringan selalu bisa dimatikan. Nama model di composer tidak lagi tampil dua kali.
- Profil: token GitHub yang ditolak tidak lagi memunculkan "pasangkan ulang"; HP menampilkan Masuk GitHub lagi di PC.

### Kualitas

- 9 tes packaging/updater bawaan upstream yang dikarantina dihapus.

## [1.4.7] — 2026-10-13

Tailscale jadi jalur utama HP ↔ PC dengan panduan setup, Wi-Fi di PC Linux dan Windows diperbaiki, Tempest jadi otak bawaan dengan prompt ~52% lebih ramping, Stop benar-benar berhenti, beberapa lampiran dalam satu pesan, antrean pesan, monitor token, dan CLI di terminal.
Berisi pekerjaan PR #13–#35 (antara lain #25 multi-lampiran, #26 prompt diet, #27 Stop, #29 firewall Linux, #33 Tailscale, #35 Tempest bawaan).

### Penting saat memperbarui

- Perbarui aplikasi desktop dan aplikasi HP bersamaan.
- Relay bawaan tidak ada lagi: dari luar rumah pakai Tailscale, atau isi URL relay sendiri.
- Tempest sekarang otak bawaan; loop lama tetap bisa dipilih lewat harness_mode: legacy atau Pengaturan › Agent › Otak agen.

### Tailscale jadi jalur utama

- HP mencoba alamat Tailscale PC dulu (IP 100.x, lalu MagicDNS), baru LAN; bila VPN HP mati, LAN dicoba dulu.
- Panduan "Siapkan Tailscale" di tab PC di HP dan di Pengaturan › Remote › Tailscale di desktop, dengan tombol Coba lagi / Periksa lagi.
- Relay bawaan (yang tidak pernah aktif) dimatikan; relay hanya jalan dengan URL relay sendiri.

### Koneksi Wi-Fi

- Linux: desktop mendeteksi ufw/firewalld dan membuka port gateway hanya untuk alamat LAN privat lewat satu prompt pkexec. Periksa koneksi kini jujur.
- Windows: aturan firewall berlaku juga di Wi-Fi berprofil Publik, aturan blokir lama untuk Python dihapus, timeout LAN di HP 4 detik.

### Tempest

- Tempest jadi otak bawaan: prompt ramping, pemeriksaan lint/tes sebelum selesai, dan checkpoint yang bisa dipulihkan.
- Prompt diet: prompt pertama 11.388 → 5.473 token (−52%), skema alat jarang dipakai dibuka saat dibutuhkan.
- Fase 2: pencarian sesi lama, pengingat memori, skill dari pengalaman, gerbang klaim, dan /rewind di obrolan.
- Perbaikan: Stop saat pemeriksaan berjalan, proses latar belakang ikut dimatikan, tanpa pytest = tanpa vonis, tes yang sudah merah tidak memicu rollback, checkpoint aman untuk folder besar, pesan berisi lampiran saja tetap membawa konteks, dan bytecode basi tidak lagi terbaca saat verifikasi.

### Chat

- Beberapa gambar/berkas dalam satu pesan (maks. 10 lampiran, 25 MB per berkas).
- Stop membatalkan model, alat, dan proses yang sedang berjalan di PC; status Dihentikan sama di HP dan desktop.
- Antrean pesan: kirim saat agen bekerja, pesan masuk antrean yang bisa diedit, dihapus, atau dikirim sekarang.
- Batas langkah berbasis kemajuan dan penjelasan berhenti yang jelas dengan satu tombol aksi.
- Pemakaian token: konteks % di header chat, Profil › Pemakaian token, dan Token monitor di desktop.
- Tabel Markdown satu baris dirender sebagai tabel; avatar maskot Neovarch; HP membuka chat terakhir saat dibuka lagi.
- MiMo bisa membaca gambar; HP menyambung ulang sendiri saat PC restart; mic Android tidak lagi salah melapor izin ditolak.

### Agen & CLI

- Chat interaktif di terminal (neovarch), agen yang bisa memperbaiki dirinya (/perbaiki, /undo), 26 skill bawaan, dan vision fallback.

### Kualitas

- Tes penjaga versi: versi PC yang tampil di HP selalu sama dengan versi aplikasi.
- Tes desktop flaky diperbaiki dan 9 berkas tes kembali menjaga CI.

## [1.4.6] — 2026-10-11

Pemasangan HP yang lebih aman, remote dari mana saja lewat relay terenkripsi, pilihan bahasa di Android, agen bisa mengirim berkas ke obrolan, Tempest Fase 1 (opsional), pembaruan langsung dari aplikasi, dan PowerPoint dari HP.
Berisi pekerjaan PR #2 (`fix-obsidian-vault-settings`), PR #3 (`ppt-master`), PR #4 (`fix-chat-attachments`), PR #6 (`cloud-relay`), PR #10 (`pairing-session-expiry`), PR #11 (`android-language-picker`), dan PR #12 (`tempest-prototype`).

**Penting saat memperbarui:** perbarui aplikasi desktop dan aplikasi HP bersamaan. Setelah memperbarui, tekan **Buat token baru** sekali di Pengaturan › Remote agar QR dan token akses lama tidak berlaku lagi.

### Keamanan pemasangan HP (PR #10)

- QR pemasangan sekarang sekali pakai dan berlaku 10 menit; QR baru muncul otomatis setelah dipindai atau menjelang kedaluwarsa. Kode pemasangan relay juga 10 menit dan sekali pakai.
- Setiap HP mendapat token sesi sendiri (core hanya menyimpan hash-nya). Memasangkan ulang mengganti token lama, dan HP yang sudah terpasang otomatis pindah ke token sesi saat tersambung lewat LAN.
- HP yang tidak aktif 30 hari dilepas otomatis (`remote.pairing_idle_days` di config.yaml, `0` = tidak pernah) dengan pesan "Sesi kedaluwarsa, pasangkan ulang".
- Pengaturan › Remote › Perangkat terpasang di desktop menampilkan **Terakhir aktif** dan kapan perangkat kedaluwarsa bila tidak dipakai. Tombol Cabut tetap ada.

### Remote dari mana saja (PR #6)

- HP tersambung ke PC lewat relay cloud terenkripsi ujung-ke-ujung saat tidak satu jaringan: LAN dulu, lalu otomatis lewat relay, dan kembali ke LAN saat terjangkau lagi. Relay tidak bisa membaca isi pesan dan tidak menyimpan apa pun.
- Pengaturan › Remote di desktop: Relay URL dan daftar perangkat terpasang.
- **Jalankan di latar belakang**: gateway PC dan relay tetap jalan setelah jendela ditutup.

### Bahasa di Android (PR #11)

- Pilihan bahasa di Profil › Bahasa: Bahasa Indonesia, English, atau Ikuti sistem (bawaan). Bahasa langsung berganti tanpa restart.
- Langkah "Pilih bahasa" jadi layar pertama di intro.
- Di Android 13+ pilihan yang sama juga ada di Setelan › Aplikasi › Neovarch › Bahasa; widget dan notifikasi Hey Neo ikut bahasa yang dipilih.
- Sebagian layar (Chat, Kantor, PC, Tugas, Vault, dll.) masih berbahasa Indonesia.

### Lampiran dari agen (PR #4)

- Agen bisa mengirim berkas dan screenshot ke obrolan dengan alat `send_file`: lampiran tampil di HP dan desktop dan bisa diunduh (maks. 25 MB per berkas; kunci dan kredensial ditolak).
- Agen tahu OS PC-nya (Windows: cmd.exe/PowerShell), dan keluaran shell Windows tidak lagi rusak.
- Windows: QR tidak lagi memilih adaptor virtual (vEthernet/VirtualBox/VMware), aturan Windows Firewall untuk port HP lewat UAC, dan pesan jelas bila HP terblokir.

### Tempest Fase 1 (PR #12, opsional)

- Harness agen baru yang bisa diaktifkan dengan `agent.harness_mode: tempest` di config.yaml. Harness legacy tetap bawaan dan tidak berubah.
- Isinya: cache prompt v2 (lebih hemat), compaction di 50% konteks, gerbang lint delta di akhir giliran, checkpoint shadow-git dengan rollback otomatis dan perintah `neovarch rewind`, serta `update_plan` (mati secara bawaan).
- Hasil bench masih dari replay skrip, belum diuji dengan model live.

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
- Profil & Teman di HP sinkron otomatis dari akun GitHub di PC.

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
