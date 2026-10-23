# Crew

Crew adalah tim kecil agen yang disusun oleh agen utama Neovarch untuk **satu tujuan**.
Kamu cukup menulis tujuannya. Agen utama merancang anggota, tugas, dan alurnya, lalu
menunjukkan rancangan itu kepadamu. Tidak ada yang berjalan sebelum kamu menyetujuinya.

Crew ada di:

- **Desktop**: menu rail **Crew** (`/crew`), dengan tiga tab: **Crew**, **Riwayat**, **Lanjutan**.
  Kartu kecil **Crew** di panel konteks kanan (samping percakapan) membuka halaman yang sama.
- **HP (Flutter)**: tab **Crew** dengan tiga bagian: **Crew**, **Tugas**, **Lanjutan**.

## Alur

1. **Tulis tujuan.** Contoh: "bandingkan 3 laptop di bawah 15 juta" atau "perbaiki bug login".
   Kamu juga bisa langsung memilih salah satu template.
2. **Agen utama merancang crew.** Ia menyusun maksimal 5 anggota (nama, peran, tujuan, alat,
   model) dan maksimal 8 tugas, plus alurnya. Kalau agen utama tidak menjawab, jawabannya tidak
   terbaca, atau rancangannya tidak valid, Crew memakai template yang paling cocok dengan tujuanmu
   dan memberi catatan kenapa. Label di kartu menunjukkan asal rancangan: "Dirancang agen utama"
   atau "Dari template".
3. **Tinjau usulan.** Kartu usulan menampilkan anggota, tugas, alur (berurutan atau dipimpin
   manajer), dan peringatan bila crew bisa mengubah file atau menjalankan perintah.
4. **Setujui & mulai.** Ruang pixel menampilkan tiap anggota di mejanya dengan status:
   santai, bekerja, memeriksa, butuh kamu, selesai, atau galat. Progres tugas terlihat sebagai
   `selesai/total`.
5. **Hasil.** Begitu selesai, hasil akhir tampil di kartu. Crew yang sudah selesai tersimpan di
   **Riwayat** dan bisa dijalankan lagi.

Agen utama juga bisa membuat usulan crew dari Chat lewat alat `crew` (`action=propose`). Usulan
itu tetap muncul di menu Crew dan tetap menunggu persetujuanmu; agen tidak boleh menganggap crew
sudah berjalan.

### Alur kerja (process)

- **`sequential` (berurutan)**: tugas dikerjakan satu per satu sesuai urutan. Tiap anggota melihat
  hasil anggota sebelumnya. Hasil akhir = hasil tugas terakhir.
- **`hierarchical` (dipimpin manajer)**: satu anggota menjadi manajer. Setelah tiap tugas,
  manajer memeriksa hasilnya sekali (`OK` atau `REVISI: ...`). Bila diminta revisi, anggota
  mengerjakan ulang satu kali dengan catatan manajer. Di akhir, manajer menulis jawaban akhir
  dari semua hasil tim.

## Template

Template dipakai saat kamu memilihnya langsung, atau sebagai cadangan saat rancangan agen utama
gagal. Bila tidak memilih, Crew menebak template dari kata kunci tujuanmu.

| Template | Alur | Anggota | Cocok untuk |
| --- | --- | --- | --- |
| **Riset** (`riset`) | berurutan | Peneliti, Analis | Cari sumber, cek fakta, rangkum temuan |
| **Konten** (`konten`) | berurutan | Perencana konten, Penulis, Editor | Kerangka, draf, lalu sunting satu konten |
| **Coding** (`coding`) | dipimpin manajer | Manajer teknis, Perancang, Programmer, Penguji | Rencana perubahan kode, implementasi, uji |
| **Riset + Laporan** (`riset_laporan`) | berurutan | Peneliti, Analis, Penulis laporan | Riset lalu laporan Markdown (`laporan-crew.md`) |

## Alat dan persetujuan

Tiap anggota hanya mendapat kelompok alat yang ada di rancangannya:

| Kelompok | Alat | Efek samping |
| --- | --- | --- |
| `web` | `web_search`, `web_fetch` | tidak |
| `files` | `read_file`, `grep`, `glob`, `repo_map` | tidak |
| `write` | `write_file`, `edit_file`, `apply_patch` | **ya** |
| `shell` | `shell`, `shell_job` | **ya** |

Persetujuan berlapis:

1. **Menyetujui rancangan.** Crew tidak jalan sebelum kamu menekan "Setujui & mulai".
2. **Izin efek samping.** Bila ada anggota dengan `write` atau `shell`, kamu harus mencentang izin
   tambahan. Tanpa centang itu, core menolak memulai (`needs_consent`).
3. **Perintah berisiko tetap bertanya.** Walau izin efek samping diberikan, perintah yang butuh
   persetujuan tetap memunculkan permintaan izin. Anggota yang menunggu tampil dengan status
   "butuh kamu" beserta perintahnya, dan kamu bisa **Izinkan** atau **Tolak** langsung dari kartu
   Crew (desktop maupun HP).
4. **Izin berlaku untuk rancangan yang kamu lihat.** Setiap perubahan di Lanjutan mengembalikan
   crew ke status usulan dan mencabut izin efek samping, jadi kamu menyetujui ulang.

### Hanya model gratis

Crew hanya memakai model gratis. Model anggota yang tidak gratis ditolak saat rancangan disimpan
(`paid_model`). Saat berjalan, anggota tanpa model memakai model default PC bila gratis, dan bila
tidak, memakai model gratis bawaan. Crew tidak pernah jatuh ke model berbayar.

## Lanjutan

Tab **Lanjutan** untuk yang ingin mengatur sendiri:

- ubah judul, alur (`sequential` / `hierarchical`) dan manajer;
- tambah, hapus, atau ubah anggota: nama, peran, tujuan, alat, model (hanya model gratis);
- tambah, hapus, atau ubah tugas dan siapa yang mengerjakannya;
- simpan: perubahan divalidasi dengan aturan yang sama seperti rancangan agen utama
  (maksimal 5 anggota, 8 tugas, manajer harus salah satu anggota, alat harus dikenal).

Crew yang sedang bekerja tidak bisa diubah; hentikan dulu. Di bagian bawah Lanjutan ada tautan
ke tampilan **Kantor & Perusahaan** lama (3D, organisasi, tiket) yang tetap tersedia di `/office`.

## Penyimpanan

Crew disimpan di `<home Neovarch>/crew/crews.json` (30 crew terakhir). Bila core dimulai ulang
saat crew sedang bekerja, crew itu ditandai gagal dengan catatan "dihentikan karena core dimulai
ulang". Tiap giliran anggota berjalan sebagai sesi tersembunyi (`source="crew"`).

## RPC dan API

Semua metode tersedia lewat WebSocket RPC (`/api/ws`, dipakai desktop dan HP) maupun REST.

| RPC | REST | Kegunaan |
| --- | --- | --- |
| `crew.templates` | ikut di `GET /api/crew` | Daftar template dan kelompok alat |
| `crew.list` | `GET /api/crew` | Ringkasan semua crew (terbaru dulu) |
| `crew.get` `{id}` | `POST /api/crew/get` | Detail satu crew |
| `crew.propose` `{goal, template?}` | `POST /api/crew/propose` | Buat usulan (agen utama, atau template bila `template` diisi) |
| `crew.update` `{id, patch}` | `POST /api/crew/update` | Ubah usulan dari Lanjutan |
| `crew.approve` `{id, allow_side_effects}` | `POST /api/crew/approve` | Setujui dan mulai (`crew.start` adalah alias) |
| `crew.cancel` `{id}` | `POST /api/crew/cancel` | Hentikan crew yang sedang bekerja |
| `crew.delete` `{id}` | `POST /api/crew/delete` | Hapus crew (bukan yang sedang bekerja) |

Perubahan dikirim sebagai event push **`crew.update`** berisi crew lengkap, atau
`{id, deleted: true}` setelah dihapus.

Kode galat:

| Kode | RPC | HTTP | Arti |
| --- | --- | --- | --- |
| `invalid` | -32602 | 400 | Rancangan atau parameter tidak valid |
| `paid_model` | -32602 | 400 | Model anggota tidak gratis |
| `not_found` | -32004 | 404 | Crew tidak ada |
| `busy` | -32009 | 409 | Crew sedang bekerja |
| `needs_consent` | -32011 | 409 | Butuh izin efek samping |
| `unavailable` | -32010 | 503 | Core ini belum bisa menjalankan crew |
| `unknown` | -32601 | 404 | Metode tidak dikenal |

### Kompatibilitas

- RPC lama **`office.*`** dan **`company.*`** serta `/api/company` tidak berubah. Halaman Kantor
  dan Perusahaan lama tetap jalan di `/office` dan dibuka dari Crew ▸ Lanjutan.
- Crew punya penyimpanan sendiri dan tidak menyentuh data Kantor/Perusahaan.
- Klien lama yang belum mengenal `crew.*` tetap bekerja; event `crew.update` cukup diabaikan.
