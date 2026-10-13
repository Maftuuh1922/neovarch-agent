---
name: taste
description: Selera desain anti-template untuk landing page, portfolio dan redesign - baca brief, tentukan bahasa desain, atur dial variance/motion/density, cek aturan keras sebelum kirim; plus audit redesign proyek lama / Anti-template frontend taste and redesign audit.
---
# Taste

Dipakai saat hasil desain harus terasa "dibuat desainer", bukan template: landing page, portfolio, halaman
produk, atau saat pengguna bilang desainnya "AI banget", "generik", "kurang wah", atau minta redesign.

## Cara pakai
- Desain baru: `read_file SKILL_DIR/upstream/taste-skill/SKILL.md` lalu ikuti inferensi brief, tiga dial
  (VARIANCE / MOTION / DENSITY), dan pre-flight "hard rules" sebelum mengirim.
- Redesign proyek yang sudah ada: `read_file SKILL_DIR/upstream/redesign-skill/SKILL.md` (audit dulu, baru ubah).
- Di Mode Desain: token proyek (`.neovarch/design/tokens.css`) tetap menang untuk nilai warna/font; skill ini
  mengatur cara memakainya (layout, ritme, tipografi, motion).
- Contoh kode upstream yang memakai GSAP/CDN bersifat opsional; artifact Mode Desain harus tetap satu file
  dan tampil tanpa internet bila memungkinkan.

Sumber: Leonxlnx/taste-skill (MIT, Copyright (c) 2026 Leonxlnx), `skills/taste-skill` dan
`skills/redesign-skill` commit d237dd3. Satu frasa yang menyebut merek mewah diganti kata umum. Lihat `LICENSE`.
