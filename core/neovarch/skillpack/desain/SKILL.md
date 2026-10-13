---
name: desain
description: Mode Desain ala OpenDesign - brief, template (landing/dashboard/deck/mobile), kunci arah (5 arah kurasi, design system bawaan, atau impor brand dari URL/screenshot), DESIGN.md + tokens.css, artifact HTML satu file dengan pratinjau, kritik 5 dimensi, lalu "Pakai untuk coding" / Design mode - brief to design system to previewed HTML artifact to code handoff.
---
# Mode Desain

Dipakai saat pengguna mengetik `/desain`, minta "desain", "mockup", "landing page", "dashboard", "UI aplikasi",
"slide/deck", "design system", "brand kit", atau "bikin tampilan yang bagus". Semua lewat alat `design`
(di Tempest: `extra_tool` name=design). Simpanan ada di proyek: `.neovarch/design/`.

Alur ini diadaptasi dari OpenDesign (nexu-io/open-design, Apache-2.0). Tidak ada daemon Node; Neovarch
menjalankan alurnya sendiri. Kerjakan berurutan, tandai tiap langkah di rencana (plan_update) bila tersedia.

## 1. Brief (maks. 2 pertanyaan)
Pastikan tahu: **apa** (landing, dashboard, deck, aplikasi mobile, docs…), **untuk siapa / produk apa**, dan
**rasa visual atau brand** (ada URL/screenshot brand? warna wajib?). Jika brief sudah jelas, jangan bertanya.
Cek dulu `design action=status`: bila proyek sudah punya design system, pakai itu kecuali pengguna minta arah baru.
Catatan memori "desain-preferensi" berisi selera pengguna dari sesi lalu; patuhi.

## 2. Pilih template
`design action=catalog kind=templates`, lalu `design action=template id=<id>` (atau grup: landing, dashboard,
deck, mobile, docs, prototype). Baca SKILL.md template + contoh HTML-nya sebagai kerangka. Frontmatter `od:`
hanyalah metadata OpenDesign; abaikan perintah daemon `od`.

## 3. Kunci arah (pilih satu jalur)
- **5 arah kurasi**: `design action=catalog kind=directions`, tawarkan 2-3 yang cocok dengan brief dalam satu
  kalimat masing-masing (atau pilih sendiri jika pengguna menyerahkan), lalu `design action=use_direction
  direction=<id> name=<nama produk> brief=<ringkas>`; aksen bisa diganti `overrides={"--accent":"#…"}`.
- **Design system bawaan** (22 sistem kurasi OpenDesign): `design action=catalog kind=systems` →
  `design action=use_system system=<id>`. Nama merek hanya acuan gaya; jangan pakai logo/aset merek itu.
- **Impor brand**: `design action=import_brand url=<https://…>` (warna, font, theme-color dari HTML+CSS) atau
  `image=<path screenshot>` (palet dominan; tanpa Pillow → baca dengan `image_ask`). Hasilnya DRAFT: periksa,
  tulis DESIGN.md 9 bagian (Visual Theme, Color Palette & Roles, Typography, Components, Layout, Depth, Do's &
  Don'ts, Responsive, Agent Prompt Guide), lalu `design action=save_system design_md=… tokens={…}`.
  Jangan menebak token brand tanpa sumber; bila tidak ada sumber, minta URL/screenshot.

## 4. Design system
Hasil langkah 3 = `DESIGN.md` + `tokens.css` + `tokens.json` dengan nama token bersama: `--bg --surface --fg
--muted --border --accent --accent-on --success --warn --danger --font-display --font-body --font-mono
--radius-* --space-* --text-*`. Ini kontraknya; artifact dan kode mengikutinya.

## 5. Artifact + pratinjau
Tulis **satu file HTML utuh** (`<!doctype html>` … `</html>`, CSS di `<style>`, tanpa build, tanpa CDN wajib):
- Blok `:root{…}` pertama = isi `tokens.css` (read_file), lalu SEMUA warna/font lewat `var(--…)`.
- Ikuti kerangka template + aturan kerajinan di `SKILL_DIR/upstream/craft/` (baca `anti-ai-slop.md`,
  `color.md`, `typography.md`; `accessibility-baseline.md` untuk form/aplikasi). Copy nyata dan spesifik untuk
  brief, bukan lorem/isian generik. Tanpa emoji sebagai ikon (pakai SVG garis), tanpa indigo Tailwind default.
- Simpan: `design action=artifact name=<slug> html=<…>`. Alat itu menyimpan di `.neovarch/design/artifacts/` dan
  langsung mengirim berkasnya ke chat (kartu Pratinjau | Kode di HP, berkas di desktop). Bila perlu tangkapan
  layar, pakai perintah screenshot di bagian "This PC" lalu `send_file`.

## 6. Kritik diri 5 dimensi + tweak
Nilai 1-5 dengan jujur: philosophy (sesuai arah?), hierarchy (satu titik fokus?), execution (tipografi, jarak,
kontras), specificity (spesifik untuk brief?), restraint (aksen ≤ 2x, satu flourish). Simpan:
`design action=critique scores={…} notes=… artifact=<slug>`. Dimensi < 3 → perbaiki yang terlemah, simpan
artifact lagi, nilai ulang (maks. 2 putaran). Lalu tawarkan 2-3 tweak konkret (mis. aksen lebih tegas, kepadatan,
mode gelap) — lihat `SKILL_DIR/upstream/templates/tweaks/SKILL.md`.

## 7. Handoff "Pakai untuk coding"
Saat pengguna setuju (atau minta langsung diimplementasikan): `design action=handoff`. Mulai saat itu design
system ini otomatis ada di konteks agent utama untuk setiap perubahan UI di proyek ini. Lanjutkan dengan skill
`design-to-code` (React/Next/Vue/HTML/Tailwind/Flutter) dan akhiri dengan `design action=check`.

## 8. Ingat preferensi
Bila pengguna menyatakan selera yang berlaku umum ("jangan pernah pakai gradient", "suka sudut membulat",
"warna kami merah #EE1C1C"), simpan satu kalimat: `design action=remember text=…`. Jangan simpan detail sekali pakai.

## Referensi tambahan (baca hanya bila perlu)
- `ui-ux-pro-max` — pencarian gaya/palet/font/aturan UX + generator design system (skrip Python lokal).
- `taste` — arahan anti-template untuk landing/portfolio; `impeccable` — audit/kritik UX mendalam.
- `frontend-design` — prinsip desain frontend yang khas.

Sumber: nexu-io/open-design (Apache-2.0, Copyright the OpenDesign authors) — alur, `directions.json` (diadaptasi
dari apps/daemon/src/prompts/directions.ts), `upstream/design-systems/` (subset kurasi), `upstream/templates/`,
`upstream/craft/`. Lihat `LICENSE` dan THIRD_PARTY_SKILLS.md.
