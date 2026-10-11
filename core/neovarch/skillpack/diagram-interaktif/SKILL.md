---
name: diagram-interaktif
description: Diagram interaktif (arsitektur, workflow, sequence, data-flow, siklus/state) sebagai HTML mandiri dengan SVG, tema gelap/terang, dan zoom; juga merapikan Mermaid / Interactive standalone-HTML architecture and workflow diagrams.
---
# Diagram Interaktif

Gunakan saat pengguna ingin diagram yang bisa dijelajahi (zoom, klik, tema gelap/terang), visualisasi
arsitektur dari repositori, alur request API, pipeline data/ETL, mesin state, atau "rapikan Mermaid ini".
Untuk bagan statis biasa, skill `diagram` sudah cukup.

## Alur kerja (semua model)
1. Baca `SKILL_DIR/upstream/SKILL.md` (panduan asli Archify) lalu hanya referensi yang perlu:
   `references/authoring-defaults.md` dan `references/authoring-contract.md`; `references/repository-authoring.md`
   bila diagram harus mencerminkan kode nyata.
2. Kumpulkan fakta dulu (baca kode / tanya pengguna). Jangan menebak nama layanan atau alur.
3. Hasilkan **satu file HTML mandiri** berisi SVG inline + sedikit JavaScript untuk zoom/geser dan toggle
   tema. Tanpa CDN wajib, tanpa build step, supaya terbuka offline di PC dan di HP.
   Jika pengguna memasang runtime Archify lengkap (Node.js), ikuti alur `bin/`/renderer di panduan upstream;
   bila tidak ada, jangan mencoba memasangnya tanpa izin.
4. Simpan dengan `diagram_save` (`format: html`) dan akhiri jawaban dengan jalur absolutnya supaya desktop
   membuka dan HP mengunduhnya.

Sumber: tt-a1i/archify (MIT, Copyright (c) 2026 tt-a1i (Archify), Copyright (c) 2025 Cocoon AI). Lihat `LICENSE`
dan `upstream/THIRD_PARTY_NOTICES.md`.
