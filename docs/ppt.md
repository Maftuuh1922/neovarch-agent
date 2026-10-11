# PowerPoint (.pptx) / Presentasi PPT

Neovarch Agent membuat presentasi PowerPoint yang bisa diedit (.pptx) dengan
[PPT Master](https://github.com/hugohe3/ppt-master) karya Hugo He (lisensi MIT).
Neovarch Agent makes editable PowerPoint decks (.pptx) with PPT Master by Hugo He (MIT).

## Cara pakai / How to use

**Di PC / On the PC (desktop):** ketik di obrolan, misalnya
`buatin PPT dari catatan rapat ini, 8 slide` atau pilih skill `/ppt`.
Type a request in the chat (e.g. "make a 10-slide deck about …") or pick the `/ppt` skill.

**Di HP / On the phone (Android remote):** ketik permintaan yang sama di Obrolan.
HP hanya meneruskan obrolan ke PC; agen di PC yang membuat file-nya. Setelah selesai,
baris alat `ppt_export` menampilkan tombol **Unduh deck.pptx**; file diunduh dari PC
lewat `GET /api/fs/download` dengan token pasangan, sama seperti laporan Word.
The phone relays the chat to the PC agent; the finished .pptx shows an **Unduh** (download)
button that fetches it from the PC, like the Word reports.

## Yang terjadi / What happens

1. `ppt_setup` (sekali / first use):
   - cek Python 3.10+ di PC. Jika tidak ada, agen menampilkan pesan jelas (ID/EN) dengan
     tautan https://www.python.org/downloads/ (Windows: centang "Add python.exe to PATH").
   - unduh rilis resmi *skill-only* PPT Master (v6.7.0, ±22 MB), cek SHA-256 yang dipatok,
     ekstrak **tanpa diubah** ke `~/.neovarch/skills/ppt-master` (LICENSE dan berkas atribusi
     tetap utuh; gerbang `attribution_guard.py` dijalankan dan harus lulus).
   - buat venv pribadi `~/.neovarch/ppt-master/venv` dan pasang paket inti
     (python-pptx, PyYAML, XlsxWriter, skia-pathops, uharfbuzz, Pillow, numpy, mammoth,
     markdownify, openpyxl, requests, beautifulsoup4). Python sistem pengguna tidak disentuh.
2. Agen membaca skill `ppt-master`, membuat proyek di `~/.neovarch/presentations`
   (alur Quick untuk permintaan obrolan biasa), menulis SVG tiap slide, menjalankan pemeriksa kualitas.
3. `ppt_export` menjalankan pengekspor PPT Master (`svg_to_pptx.py`) dan mengembalikan
   jalur `.pptx`. Desktop membukanya dari daftar Artefak / tautan file (PowerPoint / LibreOffice);
   HP mengunduhnya.

## Input PDF dan lisensi AGPL / PDF input and AGPL

Konversi sumber PDF di PPT Master memakai **PyMuPDF (AGPL-3.0)**. Neovarch **tidak** memasangnya
secara default dan tidak pernah mendistribusikannya. Ia dipasang hanya bila pengguna meminta sumber PDF
(`ppt_setup` dengan `pdf: true`; agen diminta bertanya dulu). Sumber lain (Markdown, teks, .docx, .xlsx,
web) tidak butuh PyMuPDF.
PDF sources need PyMuPDF (AGPL-3.0). It is only installed on the user's PC when they ask for PDF input.

## Batasan / Limitations

- Kualitas deck bergantung pada model AI yang dipakai; alur PPT Master panjang (banyak langkah alat).
- Pratinjau .pptx di dalam aplikasi belum ada (Word/PDF sudah); .pptx dibuka dengan aplikasi bawaan PC.
- Butuh internet saat pemasangan pertama (GitHub release + PyPI).
- Fitur PPT Master lain (gambar AI, narasi audio/video, editor SVG) butuh paket tambahan yang tidak
  dipasang otomatis.

## Atribusi / Attribution

PPT Master — Copyright (c) 2025-2026 Hugo He — MIT License — https://github.com/hugohe3/ppt-master.
Teks lisensi lengkap ada di `NOTICE` dan di `~/.neovarch/skills/ppt-master/LICENSE` setelah dipasang.
