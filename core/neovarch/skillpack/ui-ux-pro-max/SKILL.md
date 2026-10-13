---
name: ui-ux-pro-max
description: Kecerdasan desain UI/UX - cari gaya, palet per jenis produk, pasangan font, 119 aturan UX, chart, ikon, aturan per stack (React, Flutter, Next, Vue, Tailwind…) dan generator design system lewat skrip lokal / Searchable UI/UX design intelligence and design-system generator.
---
# UI/UX Pro Max

Dipakai untuk keputusan desain berbasis data: memilih gaya/palet/font untuk jenis produk, mengecek aturan UX
dan aksesibilitas, atau aturan khusus stack. Cocok dipakai di langkah "kunci arah" Mode Desain (`desain`).

## Cara pakai
1. Baca panduan asli: `read_file SKILL_DIR/upstream/SKILL.md` (aturan prioritas, kontrak query) dan bila perlu
   `SKILL_DIR/upstream/references/quick-reference.md` / `pro-rules.md`.
2. Jalankan skrip pencarian (Python 3, tanpa dependensi). Di perintah upstream, ganti
   `${CLAUDE_PLUGIN_ROOT}/.claude/skills/ui-ux-pro-max` dengan `SKILL_DIR/upstream`:
   - Design system: `python3 SKILL_DIR/upstream/scripts/search.py "<produk> <industri> <kata kunci>" --design-system -p "<Nama>"`
   - Satu domain: `python3 SKILL_DIR/upstream/scripts/search.py "<query>" --domain ux|style|color|typography|chart|landing|product`
   - Stack: `python3 SKILL_DIR/upstream/scripts/search.py "<query>" --stack react|flutter|nextjs|vue|html-tailwind|shadcn…`
   Di Windows pakai `py -3` atau `python`.
3. Hasil design system → petakan ke token bersama Neovarch (`--bg --surface --fg --muted --border --accent
   --font-display --font-body`) dan simpan dengan `design action=save_system`. Jangan menyimpan hasil yang
   tidak cocok dengan brief (lihat "Query Contract" upstream).

## Catatan
- Opsi upstream `--persist` (menulis MASTER.md) tidak perlu: design system Neovarch ada di `.neovarch/design/`.
- Data katalog Google Fonts lengkap ikut; berkas lisensi font per keluarga dan katalog ikon Phosphor mentah tidak
  dibundel (hanya dipakai validator upstream). Satu baris di `data/stacks/react-native.csv` (nama mesin JS
  bawaan React Native) dihapus.

Sumber: nextlevelbuilder/ui-ux-pro-max-skill (MIT, Copyright (c) 2024 Next Level Builder), folder
`.claude/skills/ui-ux-pro-max` commit 7246805. Lihat `LICENSE`.
