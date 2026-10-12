# Neovarch Tempest Fase 2 vs Hermes Agent (dokumen internal)

Dokumen perbandingan internal untuk pengembang. Hermes Agent (NousResearch/hermes-agent, MIT) hanya dipakai sebagai acuan desain dan pembanding benchmark. **Tidak ada kode Hermes yang disalin ke Neovarch**, dan aplikasi (UI, runtime, path, port) tidak punya koneksi apa pun ke Hermes. Nama Hermes hanya muncul di dokumen ini.

Ditulis 2026-10-12. Tempest = `harness_mode: tempest` (opt-in; `legacy` tetap default aplikasi).

## 1. Hermes terbaru: fitur "learning loop" (riset web, 12 Okt 2026)

Sumber yang dibuka:
- README: https://github.com/NousResearch/hermes-agent
- Memory: https://hermes-agent.nousresearch.com/docs/user-guide/features/memory
- Curator: https://hermes-agent.nousresearch.com/docs/user-guide/features/curator
- Rilis v0.21.6 (8 Okt 2026): https://newreleases.io/project/github/NousResearch/hermes-agent/release/v0.21.6

| Fitur Hermes | Cara kerjanya (menurut docs) |
|---|---|
| Memori terkurasi | `MEMORY.md` (2.200 char) + `USER.md` (1.375 char). Dimuat sebagai snapshot beku di system prompt saat sesi mulai, supaya prefix cache aman. Tidak auto-compact: kalau penuh, tool mengembalikan error dan agen harus merapikan sendiri. Duplikat persis ditolak. Isi dipindai untuk prompt-injection. Ada `write_approval` (staging + `/memory approve`). |
| Memory/skill nudge | Setelah giliran, sebuah *fork* agen berjalan di latar ("background review"), memutar ulang percakapan (memakai prefix cache yang sama), lalu memutuskan apakah perlu menyimpan memori atau membuat/memperbarui skill. Interval diatur `memory.nudge_interval` / `skills.creation_nudge_interval` (review skill disebut ~tiap 10 giliran). Ini **panggilan LLM tambahan**; docs menyebut review bisa "burn a meaningful share of total tokens", sehingga ada `max_input_tokens`, opsi model lebih murah, dan `enabled: false`. |
| Skill otomatis | Skill dibuat dari pengalaman setelah tugas kompleks; skill bisa diperbaiki saat dipakai. Standar agentskills.io, Skills Hub. |
| Curator | Pemeliharaan latar untuk skill buatan agen: hitung view/use/patch, `active → stale (14 hari) → archived (30 hari)`, tidak pernah menghapus. Konsolidasi LLM (umbrella skill) **opt-in**, 50–100 panggilan API per sapuan. Ada ledger audit + rollback per mutasi. |
| Session search | Semua sesi CLI/messaging di SQLite (`state.db`) dengan FTS5. Alat `session_search` dengan tiga bentuk (discovery / scroll / browse). Docs memory menyebut hasilnya pesan asli tanpa ringkasan LLM; README menyebut "FTS5 session search with LLM summarization". |
| Subagent | `delegate_task`: konteks terisolasi, paralel, hanya ringkasan yang kembali. |
| Lainnya | Honcho user modeling, Bot Mode (bot bernama dengan memori/skill sendiri), cron dengan memori, tool search, 7 backend terminal, gateway Telegram/Discord/dll. |

## 2. Yang dibangun di Tempest Fase 2

Semua ditulis dari nol di core Neovarch. Prinsipnya: **nol panggilan LLM tambahan dan aman untuk prefix cache.** Catatan dari harness selalu menumpang di pesan user berikutnya (`wire_tail`), tidak pernah mengedit system prompt.

| Fitur | Modul | Status |
|---|---|---|
| a. Rename tempa → tempest | `tempest.py` (alias `harness_mode: tempa` dan `agent.tempa_*` tetap diterima) | Sudah ada di main sebelum Fase 2. Fase 2 menambah tes bahwa key `tempa_*` baru juga terpetakan. |
| b. Session search | `tempest_search.py` | **Jalan.** Indeks SQLite FTS5 (`unicode61 remove_diacritics`, prefix match) di `~/.neovarch/session_index.sqlite`, diperbarui inkremental per mtime tepat sebelum mencari. Pesan feedback harness yang tersembunyi tidak diindeks. Ada fallback `LIKE` bila sqlite tanpa FTS5. Alat `session_search`: cari (`query`, `days`, `limit`, sesi sekarang dikecualikan) dan baca (`session_id` + `around`). |
| c. Auto-memory | `tempest_memory.py` | **Jalan.** Pengingat muncul tiap `memory_nudge_every` (6) giliran tanpa penulisan memori, atau tepat setelah tugas yang mengubah file selesai tanpa gagal. Dedup sebelum `memory`/`memory_update` append: baris yang sama persis atau hampir sama (≥0,9) dengan baris di catatan mana pun dibuang. Kalau semuanya duplikat, penulisan dilewati. |
| d. Skill dari pengalaman | `tempest_skills.py` | **Jalan.** Tugas dengan ≥`skill_min_steps` (5) panggilan alat yang lolos verifikasi menjadi kandidat. `skill_learn: offer` (default) memberi tawaran di pesan berikutnya; `auto` menulis draf skill sendiri (lewat `selfedit.skill_manage`, bisa /undo) kecuali skill serupa sudah ada; `off` mematikannya. Penghitung uses/passes/fails per skill ada di `skills/.tempest_stats.json`. Skill yang dibaca di giliran yang gagal verifikasi memunculkan petunjuk perbaikan di prompt retry dan di pesan berikutnya; di mode `auto` juga ada baris bertanggal di "## Catatan kegagalan (Tempest)". |
| e. Verify gate untuk klaim | `tempest_claims.py` | **Jalan.** Klaim "selesai / sudah diperbaiki / tes lulus" tanpa eksekusi sukses setelah edit kode terakhir mendapat 1 koreksi tersembunyi (berbagi anggaran retry dengan verify/lint gate). Kalau tetap tanpa bukti, jawaban diberi catatan "⚠️ Belum terverifikasi". Setiap giliran Tempest mengirim `verification` (`verified` harness/execution, `unverified`, `failed`, `none`) di `message.complete`. Gate ini menutup celah Fase 1: self-check scaffold dimatikan di Tempest, dan verify gate hanya jalan kalau ada perintah tes. |
| e. Rewind terintegrasi | `agent.py` + `tempest_ckpt.py` | **Jalan.** `/rewind` (atau `/rewind <sha>`) di obrolan Tempest memulihkan checkpoint hijau terakhir tanpa menyentuh git pengguna. Catatan rollback otomatis kini menyebut `/rewind`. |

Yang **belum** ada (bukan stub; memang tidak dibuat di Fase 2):
- UI desktop/Android untuk `verification`, statistik skill, atau browsing session search. Datanya sudah dikirim di event, tetapi belum ditampilkan.
- Review di latar dengan LLM, konsolidasi skill ala Curator, siklus stale/archive skill, staging write-approval, user modeling, subagent.

## 3. Di mana Tempest berbeda dari Hermes

| | Hermes | Tempest Fase 2 |
|---|---|---|
| Kapan menyimpan memori/skill | Fork LLM di latar setelah giliran (token tambahan, dapat dibatasi) | Pengingat deterministik di pesan berikutnya; model yang memutuskan dalam giliran normal. 0 panggilan tambahan. |
| Dedup memori | Duplikat persis ditolak | Persis + hampir sama (normalisasi + SequenceMatcher), lintas semua catatan |
| Klaim "selesai" | `verify_on_stop` berupa nudge, default off (dari studi kode 11 Okt) | Verify gate yang dijalankan harness (Fase 1) + claim gate (Fase 2), selalu aktif di Tempest |
| Sinyal kualitas skill | Hitungan view/use/patch (Curator) | uses/passes/fails yang terikat hasil verifikasi nyata |
| Rollback | Shadow-git checkpoint, `/rollback`, opt-in | Checkpoint hijau/merah terikat status verifikasi, rollback otomatis ke hijau terakhir, `/rewind` |
| Pengukuran | Eval kompresi | Replay bench A/B deterministik di repo + bench kecil `scripts/tempest_bench` |

## 4. Hasil benchmark (angka apa adanya)

### 4a. Replay deterministik (`scripts/tempest_bench`, tanpa jaringan)

12 tugas × 3 seed × 3 arm = 108 run. Model disimulasikan dengan skrip yang hanya bereaksi pada apa yang ditunjukkan harness; alat, pytest, git, dan harness berjalan sungguhan. Token dihitung dengan tiktoken cl100k pada wire yang persis.

| arm | lulus | panggilan model | input tok | cache_read_ratio | est. biaya USD |
|---|---|---|---|---|---|
| legacy (default aplikasi) | 21/36 | 435 | 4.675.862 | 0,757 | 0,4641 |
| Tempest Fase 1 | 27/36 | 402 | 4.780.858 | 0,857 | 0,3458 |
| Tempest Fase 2 | **36/36** | 414 | 4.969.399 | 0,854 | 0,3642 |

- Pada 8 tugas lama, Fase 2 lulus sama dengan Fase 1 (24/24). Ongkosnya +0,7% sampai +4% token per tugas, terutama dari skema alat `session_search` yang ikut di setiap panggilan.
- 4 tugas "learn" baru adalah sumber semua kenaikan lulus. **Tugas-tugas ini dirancang untuk fitur Fase 2**, dan policy-nya mengandung asumsi tentang perilaku model (lihat docstring `core/bench/tempest_tasks_f2.py`). Angka 36/36 membuktikan mekanismenya jalan dari ujung ke ujung, bukan bahwa model sungguhan akan berperilaku begitu.
- `claim-no-tests`: legacy juga lulus, karena self-check scaffold legacy sudah menegur. Fase 1 gagal karena self-check itu dimatikan di Tempest. Fase 2 memulihkannya lewat claim gate.
- `skill-reuse-2sessions`: 20 panggilan (Fase 2) vs 23 (Fase 1) vs 27 (legacy), dan −10% token vs Fase 1.
- Pada 18 run yang lulus di ketiga arm: Fase 2 294 panggilan / $0,2743, Fase 1 303 / $0,2689, legacy 306 / $0,3654.

### 4b. Live: Hermes vs Tempest Fase 2 vs Fase 1 vs legacy

- 7 tugas × 4 arm × 1 run = 28 run, 12 Okt 2026. Semua selesai: tanpa timeout, tanpa error.
- Model `claude-haiku-5.5` lewat zRouter, sama untuk semua arm. Maksimal 25 panggilan, budget 300 dtk.
- Hermes @ `835c3dd` (main 11 Okt 2026) dengan toolset terminal/file/todo, memori dan background review dimatikan. Neovarch dengan toolset bawaan penuh.
- Harness ada di workspace: `/workspace/work/tempest-f2-live`. Sengaja tidak dimasukkan ke repo karena menjalankan Hermes.

| arm | lulus | input tok | output tok | total tok | rata-rata wall dtk | rata-rata panggilan |
|---|---|---|---|---|---|---|
| Hermes Agent @ 835c3dd | 7/7 | 257.986 | 9.484 | **267.470** | 33,7 | 4,6 |
| Tempest Fase 2 | 7/7 | 391.137 | 11.925 | 403.062 | **26,5** | 4,3 |
| Tempest Fase 1 | 7/7 | 376.368 | 12.115 | 388.483 | 28,0 | 4,3 |
| legacy | 7/7 | 413.304 | 11.950 | 425.254 | 30,4 | 4,4 |

- **Tidak ada klaim "mengalahkan Hermes".** Tingkat lulus seri (7/7 semua arm).
- Hermes memakai **~34% token lebih sedikit** daripada Tempest Fase 2. Tempest ~21% lebih cepat (wall time; latensi router bersama, jadi anggap indikatif).
- Penyebab utama selisih token: prompt panggilan pertama Neovarch sekarang ~10,8–11,3 ribu token (persona, aturan, indeks ~30 skill dari skill pack, dan skema puluhan alat). Pada run live 11 Okt di commit 1508ee6, angkanya ~4,2 ribu dan Tempest saat itu memakai 1,7× lebih sedikit token daripada Hermes @ 97a9ae8. Main sudah tumbuh sejak itu, dan Hermes terbaru lebih hemat.
- Fase 2 vs Fase 1: +3,8% token pada run ini (satu sampel; sebagian besar dari skema `session_search`, ~400 token per panggilan). Claim gate tidak pernah terpicu live, karena model sudah menjalankan skripnya sendiri. Itu perilaku yang benar: gate hanya bertindak pada klaim tanpa bukti.
- n = 7, satu seed, satu run per sel. Perbedaan token berasal dari sampel tunggal.
- Satu koreksi pengecekan: check awal `claim-no-tests` terlalu sempit (mewajibkan output `spread=0`), sehingga keempat arm awalnya tercatat gagal. Padahal semuanya memperbaiki crash dengan benar (`avg=n/a spread=n/a`). Check diperbaiki (penanganan apa pun yang tidak crash diterima, laporan normal tidak boleh berubah) dan keempat run dinilai ulang: semua lulus.

## 5. Langkah berikut yang disarankan

1. **Diet prompt (dampak terbesar pada token).** Muat indeks skill secara lazy (nama saja, atau hanya skill yang cocok dengan pesan) dan pakai tool search untuk alat yang jarang dipakai (Kantor, PPT, laporan, Obsidian, diagram). Targetkan prompt pertama di bawah 6 ribu token, lalu ulangi run live.
2. Tampilkan `verification` dan statistik skill di UI desktop/Android (badge "terverifikasi / belum terverifikasi").
3. Siklus hidup skill buatan Tempest (stale/archive berbasis uses/fails, tanpa LLM) dan halaman review skill.
4. Bench live yang lebih besar: ≥20 tugas × 3 seed, termasuk tugas multi-sesi untuk session search dan memori dengan model sungguhan. Tujuannya mengganti asumsi policy dengan data.
5. Subagent/folding untuk eksplorasi (roadmap 2.3), baru setelah diet prompt.
