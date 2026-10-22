# Visual inline di chat (blok ```visual)

Agen bisa menjelaskan sesuatu dengan **gambar vektor langsung di jawaban**, bukan gambar tempelan atau file.
Contoh: graf bintang vs graf yang salah, alur login, perbandingan ukuran bundel, rencana rilis, stack vs queue.
Desktop dan HP memakai **renderer yang sama**, jadi hasilnya identik di kedua aplikasi.

## Cara kerja singkat

1. Agen memuat skill `visual-inline` saat konsep lebih cepat dilihat daripada dibaca (atau saat pengguna minta
   "gambarin", "visualkan").
2. Agen menulis blok kode berbahasa `visual`, lalu **wajib** mengeceknya dulu dengan alat `visual_check`
   (lewat `extra_tool` → `run`). Alat ini memeriksa JSON/SVG/HTML, elemen terlarang, teks di luar `viewBox`,
   ukuran huruf terlalu kecil, judul/caption yang hilang, dll.
3. Aplikasi menggambar blok itu sebagai **kartu**: judul di atas, gambar, caption di bawah. Selama blok masih
   mengalir (streaming) kartu menampilkan "Menggambar…".

## Format isi blok

Satu blok berisi **salah satu** dari:

| Jenis | Kapan dipakai | Catatan |
|---|---|---|
| **Spec JSON** (`graph`, `flow`, `bar`, `timeline`, `compare`) | Pilihan utama | Tata letak otomatis dan **menyesuaikan lebar layar** |
| **SVG mentah** | Bentuk bebas | Wajib `viewBox`; lebar idealnya ≤ 420 supaya tetap terbaca di HP |
| **HTML+CSS kecil** | Tabel/kartu sederhana | Tanpa skrip, form, iframe, atau sumber luar |

SVG/HTML boleh diawali baris `title: …` dan `caption: …` lalu `---`. Spec memakai field `"title"` dan `"caption"`.

Contoh spec:

````
```visual
{"type": "timeline", "title": "Rencana rilis", "caption": "Titik biru = tonggak berikutnya.",
 "events": [{"date": "1 Nov", "label": "Beta tertutup"},
            {"date": "1 Des", "label": "Rilis publik", "highlight": true}]}
```
````

Contoh lengkap ada di `core/neovarch/skillpack/visual-inline/examples/` (graf, alur, batang, timeline, pohon,
SVG mentah, HTML).

## Menyesuaikan lebar (desktop & HP)

Renderer menerima lebar ruang kartu: `prepareVisual(code, { width })`.

- **Desktop**: `embeds/visual-embed.tsx` mengukur lebar badan kartu (ResizeObserver), mengurangi padding kartu,
  dan membulatkannya ke kelipatan 24px agar tidak menggambar ulang di setiap piksel saat jendela diubah.
- **HP**: `assets/diagram/host.html` memakai `p.width` jika dikirim aplikasi, atau lebar konten `#out` di WebView.
  Layar penuh tetap memakai tata letak lebar (bisa digeser/zoom).

Yang berubah jika ruang sempit:

- **timeline** berubah dari mendatar menjadi tegak bila tiap peristiwa tidak kebagian ±132px;
- **compare** menumpuk panel ke bawah bila berdampingan akan mengecilkan isi di bawah ±85%;
- **bar** menyempitkan kolom label dan panjang batang agar angka tidak terpotong.

SVG mentah hanya diperkecil (tidak ditata ulang). Karena itu `visual_check` memberi saran bila `viewBox` lebih
lebar dari 480.

## Keamanan

- Markup dibersihkan dengan DOMPurify; desktop menampilkannya di `<iframe sandbox="">` tanpa skrip dan CSP yang
  memblokir semua unduhan. HP memakai shadow root di WebView lokal (offline, tanpa jaringan).
- Elemen seperti `<script>`, `<foreignObject>`, atribut `on*`, dan tautan luar dibuang.

## Menu kartu

Layar penuh, lihat kode, simpan PNG, simpan SVG, salin gambar, salin kode.

## Pengembangan

- Kode renderer: `desktop/apps/desktop/src/lib/visual/` (parse, render, sanitize, theme).
- Bundel HP: `assets/diagram/visual.js`, dibangun ulang dengan
  `node desktop/apps/desktop/scripts/build-visual-bundle.mjs`. Tes `bundle.test.ts` gagal jika bundel lupa
  dibangun ulang.
- Sisi agen: `core/neovarch/visuals.py` (pemeriksa) dan alat `visual_check`; tes di `core/tests/test_visuals.py`.
