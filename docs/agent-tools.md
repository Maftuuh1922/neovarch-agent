# Alat agen tambahan: apply_patch, repo_map, task, hooks, /rencana

Semua alat ini ada di core (`core/neovarch`). Di Tempest (otak bawaan) skemanya tidak dikirim di setiap prompt;
agen melihatnya sebagai satu baris di katalog `extra_tool` dan memuatnya saat perlu (prompt pertama bertambah ±80 token).

## apply_patch

Patch banyak file dalam satu panggilan, format V4A (Codex CLI). Semua atau tidak sama sekali.

```
*** Begin Patch
*** Add File: src/baru.py
+print("halo")
*** Update File: src/app.py
*** Move to: src/main.py
@@ def handler():
 baris konteks
-baris lama
+baris baru
*** Delete File: lama.txt
*** End Patch
```

- Diff unified (`--- a/x` / `+++ b/x`) juga diterima, begitu juga `apply_patch <<'EOF' … EOF` yang diketik ke `shell`.
- Konteks dicari persis dulu, lalu dengan mengabaikan spasi di akhir baris, lalu mengabaikan indentasi.
- Di Tempest, setiap file yang disentuh dicek sintaksnya; satu file rusak = semua file dikembalikan. Patch ikut checkpoint
  (`/rewind`).

## repo_map

Peta simbol repo (kelas/fungsi + nomor baris), file yang paling banyak dirujuk file lain tampil dulu, dibatasi anggaran
token (bawaan 1500). `focus` menaikkan file yang cocok dengan kata/path tugas. Tanpa dependensi (regex, bukan
tree-sitter): Python, JS/TS, Dart, Go, Rust, Java/Kotlin/C#/Swift, Ruby, PHP, C/C++. Berhenti setelah 8 detik di repo
sangat besar dan menyarankan subfolder.

## task (sub-agen paralel)

Sampai 4 pertanyaan independen dijalankan bersamaan oleh sub-agen baca-saja (read_file, grep, glob, repo_map,
web_search, web_fetch), masing-masing dengan konteks baru dan maksimal 8 langkah. Hanya laporan ringkas (bukti file:baris
atau URL) yang masuk ke konteks agen utama. Sub-agen tidak bisa menulis file, menjalankan shell, atau memanggil sub-agen
lain. Memakai model obrolan yang sama dengan penalaran rendah; tokennya dihitung di pemakaian.

## Hooks (`~/.neovarch/hooks.json`)

```json
{
  "pre_tool":  [{"match": "shell", "command": "python3 ~/guard.py", "timeout": 20}],
  "post_tool": [{"match": "write_file|edit_file|apply_patch", "command": "ruff format -q ."}]
}
```

- `match` = regex nama alat (kosong = semua). Hook menerima JSON di stdin (`event`, `tool`, `args`, `cwd`, `result`
  untuk post) dan env `NEOVARCH_HOOK_EVENT`, `NEOVARCH_TOOL`; berjalan di folder kerja obrolan.
- `pre_tool` keluar dengan kode 2 = panggilan diblokir, stderr jadi alasannya untuk agen. Kode lain diabaikan.
- Output `post_tool` ditempel ke hasil alat (misalnya temuan linter).
- Hanya file milik pengguna di `~/.neovarch` yang dibaca. File hooks di dalam repo tidak pernah dijalankan.

## /rencana (mode rencana)

`/rencana <tugas>` (alias `/plan`): satu giliran yang hanya membaca dan menyusun rencana bernomor; alat yang mengubah
apa pun ditolak. Balas "lanjut" untuk mengerjakan.

## File instruksi proyek

Dimuat otomatis ke prompt: `~/.neovarch/AGENTS.md` (atau `NEOVARCH.md`) untuk semua proyek, lalu per folder dari root
git sampai folder kerja yang pertama ada dari `NEOVARCH.md`, `.neovarch/NEOVARCH.md`, `AGENTS.md`, `CLAUDE.md`.
Folder yang lebih dalam dimuat terakhir sehingga aturannya yang menang.
