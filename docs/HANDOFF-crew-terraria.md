# Handoff: Crew bergaya game pixel (Terraria-like) — branch `nva-crew-terraria`

Base: `main` @ eccd9eb. Antrean v1.4.9 sesudahnya: [HANDOFF-v1.4.9.md](HANDOFF-v1.4.9.md).

Base info: Pengguna merasa ruang pixel Crew dari PR #63 terlalu polos ("gak kayak game pixel Terraria").
Tujuan: ulang ruang Crew jadi adegan game pixel side-view di desktop (Electron/React) dan HP (Flutter).

## Status
- DONE 487bff5/f148118: generator tool/crew_pixel/gen_crew_pixel.py (+ generated crew-pixel-data.ts, lib/remote/ui/crew_pixel_data.dart — the Dart file was dart-formatted after generation), desktop crew-pixel.tsx (crewPose, spritePixels(avatar,pose,tick), crewLayout, CrewScene, solo CrewStation), crew.tsx CrewRoom = CrewScene + roster, CSS, sceneLabel in 10 locales + types.ts. Vitest crew.test.tsx 13/13 green (run: cd desktop/apps/desktop && vitest run -c vt-local.config.ts --pool=forks --maxWorkers=1 --no-isolate src/components/neovarch/crew.test.tsx; vt-local.config.ts is git-excluded, copy at /workspace/work/nva-crew-terraria-patch/vt-local.config.ts, needed because main vite.config wants @rolldown/plugin-babel absent from shared node_modules).
- DONE 96279c8/5b27631: Dart port lib/remote/ui/crew_pixel.dart (CrewScene + CrewScenePainter + solo CrewStation, keys crew-station-<status> per figure, crew-fig/tag-<id>), CrewRoomGrid = scene + roster (crew-room, crew-seat-<id> kept), en string, tests. flutter test remote_crew_test 9/9, remote_crew_shots_test + remote_company_test 34/34 green (need NO_PROXY=localhost,127.0.0.1,::1). dart analyze clean on changed files.
- NOT RUN: desktop tsc full (too slow here; CI will check). _keys.desktop.json regen not done yet.
## Aturan kerja
- Commit identity: `Maftuuh1922 <145763168+Maftuuh1922@users.noreply.github.com>`, tanpa trailer/co-author.
- PR berbahasa Indonesia. Squash-merge hanya bila semua CI hijau. Tanpa release/tag/deploy.
- Gratis saja: tanpa API/aset berbayar. Semua seni orisinal (sprite sebagai kode / dihasilkan di repo), jangan salin aset Terraria.
- Jangan ubah RPC/API, identifier, alur usulan/persetujuan. String baru di semua locale desktop + regenerasi
  `desktop/locales/_keys.desktop.json` (`desktop/apps/desktop/scripts/i18n-keys.mjs`), dan Flutter id/en (`lib/remote/l10n/strings.dart`).
- CI: desktop = `desktop-electron.yml` (workflow_dispatch di branch), APK = `build-apk.yml` (jalan di PR; daftar flutter test di baris ~47).

## File yang disentuh (Crew saat ini, PR #63)
- Desktop: `desktop/apps/desktop/src/components/neovarch/crew-pixel.tsx` (CrewStation 22x19, ganti),
  `crew.tsx` (CrewRoom memakai CrewStation; CrewIntro memakai 3 CrewStation), `styles/neovarch.css` (`.nv-crew-room`, `.nv-crew-station`, ~baris 4051-4165),
  `crew.test.tsx` (describe "pixel sprite": perbarui).
- Flutter: `lib/remote/ui/crew_pixel.dart` (pertahankan global `crewPixelAnimate` dan key `ValueKey('crew-station-<status>')`),
  `lib/remote/ui/remote_crew_screen.dart` (CrewRoomGrid: key `crew-room`, `crew-seat-<id>`; baris intro),
  `test/remote_crew_test.dart`, `test/remote_crew_shots_test.dart` (screenshot 392 px gelap/terang, `--update-goldens`, env `NV_SHOTS_DIR`).

## Rencana desain
- Generator `tool/crew_pixel/gen_crew_pixel.py` = satu sumber peta sprite + palet -> menghasilkan `crew-pixel-data.ts` dan `lib/remote/ui/crew_pixel_data.dart`.
- Adegan: potongan gedung side-view. Langit (gelap: malam, bintang, bulan; terang: siang, matahari, awan), 2 lapis bukit parallax bergerak pelan
  (terlihat di atas atap dan lewat jendela), dinding luar bata batu, dinding belakang papan kayu dengan jendela, lantai papan, atap, tanah rumput/tanah.
- Layout: scale = w>=900?4 : w>=330?3 : 2; lebar logis = floor(w/scale); dinding 4; tiap meja (bay) 40 logis; kolom = min(6, floor((interior-28)/40));
  lantai = ceil(n/kolom); tinggi lantai 44 + pelat 4; atap 14; tanah 12; kolom utilitas (rak server LED berkedip, mesin kopi beruap, rak buku, tanaman,
  tangga antar lantai); bay kosong = meja kosong/dekor. HP 392 -> konten 360 -> skala 3 -> 120 logis -> 2 meja per lantai. Desktop ~644 px -> 4 meja.
- Karakter 12x21 tampak samping (rambut, kulit, mata putih+pupil, baju, celana, sepatu), 10 palet avatar.
  Pose: type (duduk mengetik, 2 frame), walk (siklus 4 frame, bolak-balik, flip), wait (angkat tangan), cheer (selesai), think (usulan), slump (galat), idle (kedip).
- Pemetaan `crewPose(memberStatus, crewStatus)`: crew proposed->think; working->type; reviewing->walk+papan klip; waiting->wait; done->cheer; error->slump;
  idle saat crew running->walk; lainnya idle. Tes unit untuk pemetaan ini di kedua platform.
- Gelembung (overlay HTML/Widget, bukan pixel font): working = activity atau judul tugas berjalan; waiting = perintah izin; done = label status;
  usulan = peran (gelembung pikiran). Papan nama di atas kepala (+ lencana manajer). Strip roster di bawah adegan tetap memuat nama/peran/status.
- Satu timer 8 fps; reduce motion (`prefers-reduced-motion` / `reduceMotion(context)`) -> diam di frame 0.
- Desktop: SVG `shape-rendering: crispEdges`, `image-rendering: pixelated`, skala bilangan bulat, tile lewat `<pattern>`, lapisan statis di-memo.
  Flutter: CustomPaint `isAntiAlias=false`, painter statis + painter animasi, overlay Positioned.

## Sisa pekerjaan (urut)
1. Generator + adegan TS + CSS; iterasi visual dengan harness React (esbuild + Playwright, lebar ~760, gelap/terang).
2. Port Dart + widget. 3. Tes: vitest + tsc + eslint (file berubah), flutter test + dart analyze; tes pemetaan pose & layout.
4. String + regenerasi `_keys.desktop.json`. 5. Screenshot: desktop ~760 px & Flutter 392 px (gelap/terang): bekerja/mengetik, berjalan,
   usulan menunggu, kosong/onboarding + GIF/strip frame animasi per platform; periksa clipping, blur, tumpang tindih, tema.
6. PR (Indonesia), dispatch Desktop (Electron), pastikan Build APK jalan, semua hijau -> squash-merge. Tanpa rilis.

## Perintah
- Desktop (dari `desktop/apps/desktop`): `../../node_modules/.bin/vitest run --pool=forks --maxWorkers=1 src/components/neovarch/crew.test.tsx`;
  `../../node_modules/.bin/tsc -p . --noEmit`; `../../node_modules/.bin/eslint <file berubah>`.
- Flutter (root): `flutter test test/remote_crew_test.dart test/remote_crew_shots_test.dart test/remote_company_test.dart`;
  `dart analyze lib/remote test/remote_crew_test.dart`; `dart format --line-length 160`.
- Shot HP: `NV_SHOTS_DIR=build/shots flutter test --update-goldens test/remote_crew_shots_test.dart`.
