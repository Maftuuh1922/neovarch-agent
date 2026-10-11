---
name: investigasi
description: Investigasi teknis berbasis bukti - membedah aplikasi/biner/APK/Electron, melacak crash, membandingkan versi, memverifikasi rekonstruksi / Evidence-first reverse engineering and crash investigation.
---
# Investigasi

Gunakan saat pengguna minta "kenapa aplikasi ini crash", "fitur X di app ini kerjanya bagaimana",
membandingkan dua versi build, membongkar APK/Electron/biner miliknya, atau menelusuri perilaku dari artefak.
Bukan untuk sekadar membaca arsitektur repo sumber biasa.

## Batas penggunaan (wajib)
- Hanya untuk perangkat lunak milik pengguna, yang ia berhak analisis, atau riset keamanan yang diizinkan.
  Tolak membobol DRM, lisensi, akun orang lain, atau malware untuk menyerang. Jika kepemilikan tidak jelas, tanya.

## Alur kerja (semua model)
1. Tetapkan pertanyaan yang bisa dijawab dan target (file, versi, platform). Catat apa yang sudah diketahui.
2. Kumpulkan bukti dari artefak (strings, manifest, bundle JS, log, stack trace) sebelum menyimpulkan.
   Tandai setiap klaim: **terbukti** (ada bukti), **dugaan**, atau **belum diketahui**.
3. Pilih pola dari `SKILL_DIR/upstream/mcp-prompts.md`: investigasi fitur, bandingkan versi, verifikasi
   rekonstruksi, telusuri crash, audit hal yang belum diketahui, atau tangkapan proses terbatas.
4. Panduan per jenis target ada di `SKILL_DIR/upstream/references/` (android-applications, javascript-applications,
   native-and-artifacts, runtime-observation, evidence-workflows). Baca hanya yang relevan.
5. Jika alat REA (https://github.com/morluto/rea) terpasang, ikuti `SKILL_DIR/upstream/SKILL.md`. Jika tidak, pakai
   alat bawaan (shell, read_file) dengan perintah sempit dan timeout pendek; jangan memasang alat tanpa izin.
6. Laporkan: jawaban singkat, bukti (jalur file/offset/baris), hal yang masih belum diketahui, langkah berikutnya.

Sumber: morluto/rea (MIT, Copyright (c) 2026 morluto). Lihat `LICENSE`.
