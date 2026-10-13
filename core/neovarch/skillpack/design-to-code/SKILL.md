---
name: design-to-code
description: Terapkan design system proyek (.neovarch/design DESIGN.md + tokens) ke kode React/Next/Vue/Svelte/HTML/Tailwind/Flutter dengan token yang konsisten, lalu cek konsistensi / Turn the project's design system into consistent UI code.
---
# Design → kode

Dipakai setelah "Pakai untuk coding" di Mode Desain, atau saat pengguna minta mengimplementasikan desain/mockup
ke aplikasinya. Sumber kebenaran: `<proyek>/.neovarch/design/` (`DESIGN.md`, `tokens.css`, `tokens.json`,
`artifacts/*.html`). Lihat isinya dengan `design action=status` dan `read_file`.

## Alur
1. **Kenali stack** dari file proyek (package.json, pubspec.yaml, tailwind.config, vite/next config). Jangan
   menambah framework baru tanpa diminta.
2. **Pasang token sekali, di satu tempat**:
   - CSS/HTML/React/Vue/Svelte biasa: salin `tokens.css` ke folder style proyek (mis. `src/styles/tokens.css`)
     dan import sekali di entry (main.tsx / layout / App.vue).
   - Tailwind v4: `design action=export format=tailwind` → import `tailwind-theme.css`; pakai kelas `bg-bg`,
     `text-fg`, `bg-accent`… Tailwind v3: petakan `theme.extend.colors` ke `var(--bg)` dst.
   - Flutter: `design action=export format=dart` → salin `neovarch_tokens.dart` ke `lib/design/`, pakai
     `NvTokens.theme()` di MaterialApp dan `NvTokens.accent`, `NvTokens.radiusMd`… di widget. Font kustom harus
     ada di pubspec; bila tidak, biarkan fontFamily default dan beri tahu pengguna.
3. **Bangun komponen dari artifact**: artifact HTML adalah acuan visual (struktur, jarak, hierarki). Terjemahkan
   ke komponen idiomatis stack itu; jangan menempel HTML mentah ke React/Flutter.
4. **Aturan token**: tidak ada hex/rgb/font mentah di komponen. Semua warna `var(--…)` / `NvTokens.*`;
   radius/jarak dari skala token. Nilai baru → tambahkan dulu ke design system (`design action=save_system`),
   jangan diam-diam.
5. **Status & aksesibilitas**: hover/focus/disabled/loading/empty/error untuk komponen interaktif; kontras teks
   ≥ 4.5:1; target sentuh ≥ 44px di mobile; fokus terlihat.
6. **Verifikasi**: jalankan build/test proyek seperti biasa, lalu `design action=check` (atau `/desain cek`).
   Perbaiki semua temuan `off-palette`, `off-font`, `ai-indigo`; `hardcoded` (nilai token ditulis mentah) ganti
   dengan var/konstanta tokennya. Ulangi sampai bersih atau jelaskan sisa temuan yang sengaja dibiarkan.

## Batasan
- Jangan mengubah file di `.neovarch/design/` saat coding kecuali pengguna mengubah desainnya.
- Kode yang dihasilkan generator (`*.g.dart`, `dist/`, `build/`) tidak dicek dan jangan diedit.

Original Neovarch skill (MIT, Copyright (c) NeovarchLabs). Token names follow the OpenDesign shared token
contract (nexu-io/open-design, Apache-2.0).
