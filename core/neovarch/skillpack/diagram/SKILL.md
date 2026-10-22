---
name: diagram
description: Buat diagram rapi (arsitektur, flowchart, sequence, ER, timeline, org chart, swimlane, Gantt, dsb.) sebagai SVG/HTML yang bisa dibuka di PC dan HP / Make clean diagrams as SVG/HTML that open on desktop and phone.
---
# Diagram

Gunakan saat pengguna minta diagram, bagan, flowchart, skema, peta alur, arsitektur sistem, ERD, timeline,
org chart, atau "gambarin alurnya". Use when the user asks for any diagram or chart of a structure or flow.

Untuk penjelasan singkat langsung di obrolan (tanpa file), pakai skill `visual-inline` (blok ```visual).

## Alur kerja (semua model)
1. Tentukan jenis diagram yang paling cocok (arsitektur, flowchart, sequence, state, ER, timeline, swimlane,
   pohon/org chart, quadrant, Gantt, Venn, piramida). Jika ragu, tanya satu pertanyaan singkat.
2. Buka panduan aslinya di `SKILL_DIR/upstream/SKILL.md` dengan `read_file`, lalu hanya file referensi
   jenis yang dipilih, misalnya `SKILL_DIR/upstream/references/type-flowchart.md` dan
   `SKILL_DIR/upstream/references/style-guide.md`. Jangan membaca semua referensi sekaligus.
3. Tulis diagram sebagai **SVG inline dalam satu file HTML mandiri** (tanpa file eksternal, tanpa build).
   Untuk diagram sederhana boleh Mermaid; `diagram_save` membungkusnya jadi HTML yang bisa dibuka.
4. Simpan dengan alat `diagram_save` (`name`, `format`: svg | html | mermaid, `content`). Alat itu menulis ke
   `~/.neovarch/diagrams/` dan mengembalikan jalur absolut.
5. Akhiri jawaban dengan jalur absolut file itu. Desktop membukanya di peramban; HP mengunduhnya lewat
   remote dan membukanya di peramban HP. Tambahkan `open: true` hanya bila pengguna ada di depan PC.

## Aturan
- Label harus terbaca (kontras cukup, tidak saling tumpuk), maksimal ±12 kotak per diagram; pecah bila lebih.
- Jangan mengarang komponen sistem pengguna; bila diagram harus mencerminkan kode, baca kodenya dulu.
- Langkah upstream yang memakai skrip/CLI khusus (ekspor PNG, import drawio) bersifat opsional; jika alatnya
  tidak ada di PC ini, cukup kirim HTML/SVG.

Sumber: cathrynlavery/diagram-design (MIT, Copyright (c) 2025 Cathryn Lavery). Lihat `LICENSE`.
