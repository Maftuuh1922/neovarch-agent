# Memperbarui Neovarch (`neovarch update` dan tombol "Perbarui")

Neovarch bisa memperbarui dirinya sendiri di Windows dan Linux tanpa mengunduh installer secara
manual, mirip `hermes update`. Ada dua jalur; Neovarch memilih sendiri sesuai cara ia dipasang.
Android tidak termasuk (aplikasi HP diperbarui lewat Play Store / APK rilis).

## Cara memakai

**Terminal**

```sh
neovarch update             # perbarui, pasang ulang dependensi, cek ekstra, mulai ulang gateway
neovarch update --check     # hanya cek apakah ada pembaruan
neovarch update --rollback  # instalasi git: kembali ke commit sebelum pembaruan terakhir
neovarch update --json      # keluaran mesin (untuk skrip)
```

Opsi lain: `--no-deps` (lewati pemasangan ulang dependensi), `--no-extras` (lewati cek ekstra),
`--no-restart` (jangan minta gateway yang berjalan untuk mulai ulang).

**Aplikasi desktop**: Pengaturan ▸ Tentang ▸ kartu **Perbarui dari sumber** ▸ tombol **Perbarui**.
Kartu menampilkan tiap langkah (✓ selesai, – dilewati, ✗ gagal), log, dan pesan kesalahan dalam
bahasa antarmuka. Setelah berhasil, tombol **Mulai ulang sekarang** memulai ulang aplikasi (core
ikut dimulai ulang). Kartu disembunyikan saat desktop tersambung ke gateway jarak jauh.

## Jalur 1: instalasi git

Dipakai bila core berjalan dari clone repo ini (mis. `git clone … && pip install -e core`).
Clone dikenali lewat `git rev-parse --show-toplevel` dari folder paket, dan hanya dihitung bila
folder itu memang berisi `core/neovarch` (core yang kebetulan berada di dalam repo git lain tidak
akan ikut "diperbarui"). `NEOVARCH_REPO_DIR` bisa menunjuk ke clone secara eksplisit.

Langkah:

1. **Cek perubahan lokal** — `git status --porcelain --untracked-files=no`. Bila ada berkas
   terlacak yang berubah, pembaruan **ditolak** dengan pesan jelas (commit atau `git stash` dulu).
   Detached HEAD dan branch tanpa upstream juga ditolak.
2. **git fetch** dari remote upstream branch.
3. **git pull (hanya fast-forward)** — `git merge --ff-only @{u}`. Bila branch lokal punya commit
   yang tidak ada di remote (diverged), pembaruan ditolak; tidak ada merge/rebase otomatis.
4. **Pasang ulang dependensi** — core Python (`uv pip install -e core` bila `uv` ada, selain itu
   `python -m pip install -e core`, memakai Python yang menjalankan Neovarch). Dependensi desktop
   (`npm install` di `desktop/`) hanya dipasang ulang bila `desktop/node_modules` ada dan
   `desktop/package.json` / `package-lock.json` berubah di antara commit lama dan baru.
5. **Cek ekstra** — lihat di bawah.
6. **Mulai ulang** — lihat di bawah.

### Pemulihan (rollback) dan pembatalan

Commit sebelum pembaruan dicatat di `<home>/update/last.json` (`prev`, `new`, `status`).
Bila pemasangan dependensi gagal **atau dibatalkan (Ctrl+C)**, clone di-reset ke commit
sebelumnya (`git reset --keep <prev>`, aman karena tree sudah dipastikan bersih) dan dependensi
lama dipasang ulang (usaha terbaik). Pesan kesalahan menyebut bahwa repo sudah dipulihkan.
Bila reset itu sendiri gagal, pesan menyebut perintah `git reset --hard <prev>` yang harus
dijalankan. Kegagalan fetch/merge tidak mengubah apa pun, jadi tidak perlu pemulihan.

`neovarch update --rollback` kembali ke `prev` dari pembaruan terakhir yang berhasil, hanya bila
HEAD masih commit hasil pembaruan itu dan tree bersih.

## Jalur 2: bukan instalasi git (fallback rilis)

Untuk instalasi lewat `scripts/install.sh` / `install.ps1`, paket NSIS, AppImage, .deb, atau pip:

* **CLI**: rilis terbaru dicek lewat API publik GitHub Releases dengan logika versi yang sama
  dengan cek pembaruan yang sudah ada (`neovarch.updates`). Instalasi installer menjalankan ulang
  installer resmi untuk tag itu (`NEOVARCH_VERSION=<tag>`; Linux `install.sh`, Windows
  `install.ps1`, yang mengunduh aset rilis dan memperbarui core + aplikasi desktop). Installer
  menyiapkan versi baru di folder sementara dan baru menukarnya di akhir, jadi bila gagal versi
  lama tetap dipakai. AppImage/.deb/pip tidak bisa memperbarui dirinya tanpa root, jadi CLI
  menampilkan halaman rilis dan tautan aset yang cocok.
* **Desktop**: tombol "Perbarui" tidak menduplikasi updater rilis; ia memanggil updater GitHub
  Releases yang sudah ada (PR #38: Linux install.sh menjalankan ulang installer, Windows mengunduh
  dan menjalankan `neovarch-agent-windows-x64-setup.exe`, AppImage/.deb membuka halaman rilis).
  Progresnya sama dengan kartu "Pembaruan Neovarch".

## Ekstra opsional setelah setiap pembaruan

Setelah setiap pembaruan (juga bila sudah terbaru), `neovarch update` menjalankan pemeriksa
ekstra dari PR #52/#53 (`extras.ensure_all(reason="update")`): ekstra yang belum ada (Obsidian)
dipasang diam-diam dari rilis resminya (Windows `/S`, Linux AppImage), yang sudah ada dilewati,
dan kegagalan tidak membuat pembaruan gagal (hanya ditandai "!"). `extras.auto_install` dan
`NEOVARCH_EXTRAS_AUTO=0` tetap dihormati. Pada jalur rilis, installer juga menjalankan
`neovarch extras ensure`, dan gateway versi baru memeriksa ekstra saat pertama kali start.

## Mulai ulang

* **CLI**: menulis `<home>/update/restart-request.json`. Setiap gateway (`neovarch serve`) yang
  berjalan untuk home ini memantau berkas itu dan memulai ulang dirinya sendiri setelah giliran
  yang aktif selesai (mekanisme yang sama dengan restart self-repair; port tetap sama, jadi desktop
  dan HP tersambung lagi). Aplikasi desktop perlu dibuka ulang untuk memuat antarmuka baru.
  Pemantauan bisa dimatikan dengan `NEOVARCH_UPDATE_WATCH=0`.
* **Desktop**: "Mulai ulang sekarang" memulai ulang aplikasi (backend dimatikan dulu, lalu
  dijalankan lagi dengan kode baru).

## API (untuk desktop)

* `GET /api/update/pull` → `{install, job, last}`; `install.kind` = `git` | `installer` |
  `installer-windows` | `package` (git juga memberi `branch`, `head`, `upstream`, `dirty`).
* `POST /api/update/pull` `{restart?: bool, check_only?: bool}` → `202 {job}`; `409 {code: "busy"}`
  bila sudah berjalan. `job` = `{state: running|done|failed, steps: {<id>: {status, detail}},
  lines, result, error, code, rolled_back}`. Event `update.progress` dikirim untuk tiap langkah.

Kode kesalahan yang stabil: `dirty`, `detached`, `no_upstream`, `diverged`, `fetch_failed`,
`merge_failed`, `deps_failed`, `aborted`, `git_missing`, `release_failed`, `no_rollback`, `busy`.

## Batasan

* Hanya Windows dan Linux yang diuji lewat tes otomatis (git, subprocess, dan jaringan di-mock);
  belum dijalankan pada mesin Windows/Linux sungguhan.
* macOS tidak punya jalur rilis otomatis (sama seperti updater rilis desktop).
* Tidak ada layanan berbayar: hanya git, GitHub Releases publik, pip/uv dan npm.
