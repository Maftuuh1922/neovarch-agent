---
name: impeccable
description: Audit, kritik dan poles UI secara mendalam - hierarki visual, arsitektur informasi, beban kognitif, aksesibilitas, tipografi, warna, layout, motion, copy UX, state error/kosong, responsif / Deep UX audit, critique and polish of a frontend.
---
# Impeccable

Dipakai untuk audit atau kritik UX ("cek UX-nya", "review tampilan", "kenapa terasa berantakan", "poles UI"),
dan untuk langkah kritik/tweak Mode Desain saat butuh lebih dari skor 5 dimensi.

## Cara pakai
1. Baca `read_file SKILL_DIR/upstream/SKILL.md`. Peluncur biner `scripts/impeccable` upstream TIDAK dibundel
   (ia mengunduh biner saat dijalankan); ikuti jalur "Launcher unavailable" di panduan itu: baca DESIGN.md
   proyek (di Neovarch: `.neovarch/design/DESIGN.md`) dan PRODUCT.md bila ada, tanpa mengarang konteks.
2. Muat hanya playbook yang relevan dari `SKILL_DIR/upstream/reference/` (mis. `audit.md`, `critique.md`,
   `polish.md`, `layout.md`, `typeset.md`, `colorize.md`, `android.md`, `ios.md`) dan `craft-floor.md` sebelum
   mengedit UI.
3. Batasi verifikasi seperti aturan upstream: satu putaran periksa, perbaiki sekaligus, maksimal satu konfirmasi.
4. Bila proyek punya design system Neovarch, perbaikan tetap memakai tokennya; akhiri dengan `design action=check`.

Sumber: pbakaus/impeccable (Apache-2.0), `.claude/skills/impeccable` (SKILL.md + reference/) commit 245ad82.
Lihat `LICENSE` dan `NOTICE.md` (berkas referensi ios/android diturunkan dari ehmo/platform-design-skills, MIT).
