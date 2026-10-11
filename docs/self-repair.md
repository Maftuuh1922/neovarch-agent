# Perbaikan diri & cara kerja agen / Self-repair and how the agent works

> Bahasa Indonesia di atas, English below.

## Bahasa Indonesia

Neovarch Agent bisa memperbaiki dan meningkatkan dirinya sendiri langsung dari obrolan — di desktop maupun dari
aplikasi HP (HP hanya meneruskan obrolan ke PC; semua perubahan terjadi di PC).

### Perintah di obrolan

| Perintah | Fungsi |
| --- | --- |
| `/perbaiki` atau `/fix` | Diagnosis: membaca log core (`~/.neovarch/logs`), log desktop bila ada, panggilan alat yang gagal di obrolan terakhir, dan pengaturan. Menjelaskan masalah dalam bahasa Indonesia, mengusulkan perbaikan, dan langsung menerapkan perbaikan pengaturan/skill yang aman. Tetap jalan walau model sedang rusak. |
| `/perbaiki <gejala>` | Sama, lalu agen menelusuri gejala itu dengan alat dan memperbaikinya. |
| `/undo` atau "Pulihkan versi sebelumnya" | Membatalkan perubahan terakhir yang dibuat agen (skill, memori, pengaturan, persona, patch kode). |

### Apa yang bisa diubah agen sendiri

- **Skill** (`skill_manage`): membuat, mengedit, mem-patch, menghapus skill di `~/.neovarch/skills`.
- **Memori** (`memory_update`): catatan di `~/.neovarch/memory`.
- **Pengaturan** (`settings_update`): model bawaan, instruksi tambahan, persona (SOUL.md), alat yang dimatikan,
  tingkat penalaran, "Naik ke model lebih kuat saat buntu", dan beberapa lainnya. Kunci API dan rahasia **tidak**
  bisa diubah lewat jalur ini.
- **Kode aplikasi** (`self_diagnose` → `prepare_patch` / `apply_patch`): hanya untuk instalasi dari kode sumber
  (git checkout). Patch disiapkan di branch git lokal baru dalam worktree terpisah, tes dijalankan, dan baru
  diterapkan (cherry-pick ke branch aktif) setelah kamu menekan **Setujui** di desktop atau HP. Aplikasi terpaket
  (biner, app.asar) tidak pernah diubah.

Setiap perubahan dicadangkan dulu ke `~/.neovarch/self/backups/<id>/` dan dicatat di `~/.neovarch/self/journal.jsonl`
(log perubahan). Undo mengembalikan cadangan; versi yang diganti dipindahkan ke samping, tidak dihapus. Patch kode
dibatalkan dengan `git revert`.

### Keamanan

- Selalu minta persetujuan (meski mode persetujuan "off"): perubahan kode, perintah shell di luar folder kerja,
  menghapus data (skill, memori, jadwal, pegawai), mematikan persetujuan, dan restart core.
- Rahasia tidak pernah ditampilkan: log dan pengaturan disamarkan (API key, token, password, nilai dari `.env`).
- Alat perbaikan diri tidak bisa dimatikan oleh agen, supaya ia selalu bisa memulihkan diri.

### Memuat ulang tanpa memutus obrolan

`core_reload` action `soft` membaca ulang skill, pengaturan, dan daftar model di tempat. Action `restart`
(dengan persetujuan) memulai ulang proses core setelah giliran berjalan selesai, di port yang sama; obrolan tetap
tersimpan, dan hasil restart muncul sebagai pesan di obrolan yang memintanya.

### Agen utama sebagai pengatur

Alat `manage` merutekan permintaan ke: Kantor (rekrut, beri tugas, jeda, lanjutkan, berhentikan), pengaturan, model,
skill, memori, jadwal, perangkat yang dipasangkan, dan perbaikan diri. Pegawai Kantor tidak mendapat alat ini.

### Cara kerja bawaan (selalu aktif, untuk semua model)

Tidak ada saklar: setiap agen bekerja dengan cara ini, dan model kecil/gratis paling merasakan manfaatnya.

1. **Rencana dulu** untuk tugas bertahap: daftar periksa singkat (`plan_update`) yang diperbarui saat bekerja.
2. **Periksa sebelum menjawab**: klaim "sudah selesai" harus didukung hasil alat di giliran itu; setelah mengubah
   kode, agen diminta menjalankan tes/lint; file yang ditulis harus ada. Kalau pemeriksaan gagal, agen mendapat satu
   koreksi singkat (maksimal 2 kali) sebelum jawaban dikirim.
3. **Bantuan konteks**: memori, catatan Obsidian yang relevan, `AGENTS.md`/`NEOVARCH.md` proyek, dan skill yang
   cocok dengan permintaan dimasukkan otomatis.
4. **Perbaikan panggilan alat**: JSON argumen yang rusak diperbaiki bila bisa; kalau tidak, model diminta mengulang
   dengan skema alat. Nama alat yang mirip (`read-file`) dipetakan ke yang benar.
5. **Konteks kecil**: riwayat panjang dipadatkan dengan ringkasan langkah sebelumnya.
6. **Naik ke model lebih kuat saat buntu** (opsional, default mati, Pengaturan ▸ Agen): setelah 2 kegagalan
   berturut-turut, satu langkah memakai model kuat yang kamu pilih, lalu kembali ke model bawaan.
7. **Laporan berbukti**: hasil yang substansial ditutup dengan **Temuan → Bukti → Batasan → Langkah berikutnya**.
   Bukti harus konkret (file:baris, perintah + output, potongan log, file yang diubah). Di obrolan, bagian ini tampil
   sebagai bagian **Bukti** yang bisa dilipat.

## English

Neovarch Agent can repair and improve itself from the chat, on the desktop or from the phone app (the phone only
relays chats to the PC; every change happens on the PC).

### Chat commands

| Command | What it does |
| --- | --- |
| `/perbaiki` or `/fix` | Diagnosis: reads the core logs, the desktop logs when present, failed tool calls in recent chats and the configuration; explains the problem in Indonesian, proposes fixes and applies safe settings/skill fixes right away. Works even when the model itself is broken. |
| `/perbaiki <symptom>` | Same, then the agent investigates that symptom with its tools and fixes it. |
| `/undo` or "Pulihkan versi sebelumnya" | Reverts the agent's newest change (skill, memory, setting, persona, code patch). |

### What the agent can change

- **Skills** (`skill_manage`), **memory notes** (`memory_update`), **settings** (`settings_update`: default model,
  extra instructions, persona, disabled tools, reasoning level, escalation; never API keys or secrets).
- **App code** (`self_diagnose` → `prepare_patch` / `apply_patch`), source installs only: the patch is built on a new
  local git branch in a separate worktree, tests run, and it is cherry-picked onto the active branch only after the
  user taps **Setujui** (Approve). Packaged installs are never modified.

Every change is backed up to `~/.neovarch/self/backups/<id>/` and logged in `~/.neovarch/self/journal.jsonl`.
Undo restores the backup (the replaced version is moved aside, not deleted); code patches are undone with `git revert`.

### Safety

Approval is always required — even with approvals switched off — for code changes, shell commands outside the
working folder, deleting data, switching approvals off and restarting the core. Secrets are redacted from logs and
settings and are never printed. The self-repair tools cannot be disabled by the agent.

### Reload without dropping the chat

`core_reload` `soft` re-reads skills, settings and the model list in place; `restart` (approved) re-executes the
core on the same port after the running turn finishes and reports the result back into the chat.

### The main agent as orchestrator

The `manage` tool routes to the Kantor (hire, assign, pause, resume, fire), settings, models, skills, memory,
schedules, paired devices and self-repair. Kantor employees do not get it.

### Default working method (always on, every model)

Plan multi-step work as a checklist; verify before answering (claims of finished work need tool evidence from the
same turn, code edits need a test/lint run, written files must exist; at most two short corrections); automatic
context (memory, relevant vault notes, project `AGENTS.md`/`NEOVARCH.md`, matching skills); tool-call repair
(malformed JSON repaired or re-asked with the schema, near-miss tool names mapped); transcript compaction for small
context windows; optional escalation to a stronger model for one step after two consecutive failures (Settings ▸
Agent, off by default); and evidence-backed reports: **Findings → Evidence → Unknowns/Limitations → Next action**,
shown in chat as a collapsible **Bukti** section. Attribution for adapted ideas is in NOTICE.

### API

- JSON-RPC: `self.changes`, `self.undo` (`change_id?`), `self.diagnose` (`apply?`); `commands.catalog` lists
  `/perbaiki`, `/fix`, `/undo`.
- REST: `GET /api/self/changes`, `POST /api/self/undo`, `GET|POST /api/self/diagnose`.
- Events: `plan.update` (`steps`), `status.update` kinds `plan`, `verify`, `escalation`; `message.complete` may carry
  `evidence` (`findings`, `evidence`, `unknowns`, `next`) and `files_changed`; `core.restarting` before a restart.
