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

1. ~~Diet prompt~~ **Selesai** (lihat bagian 6): prompt pertama ~5,5K token, tanpa kehilangan lulus. Berikutnya: bench penalaran yang lebih sulit supaya arm bisa dibedakan.
2. Tampilkan `verification` dan statistik skill di UI desktop/Android (badge "terverifikasi / belum terverifikasi").
3. Siklus hidup skill buatan Tempest (stale/archive berbasis uses/fails, tanpa LLM) dan halaman review skill.
4. Bench live yang lebih besar: ≥20 tugas × 3 seed, termasuk tugas multi-sesi untuk session search dan memori dengan model sungguhan. Tujuannya mengganti asumsi policy dengan data.
5. Subagent/folding untuk eksplorasi (roadmap 2.3), baru setelah diet prompt.

## 6. Prompt diet + benchmark ulang (12 Okt 2026)

### 6a. Apa yang diubah (`core/neovarch/tempest_diet.py`, saklar `agent.tempest_prompt_diet`)

Hanya berlaku di mode Tempest (tetap opt-in; `legacy` tetap default aplikasi). Default `true` di dalam Tempest; `tempest_prompt_diet: false` mengembalikan prompt Fase 2 persis.

| Bagian prompt pertama | Fase 2 (main) | Diet |
|---|---|---|
| Indeks skill | ~30 skill + deskripsi (4.481 char) | hanya nama skill (897 char). Deskripsi skill yang cocok dengan pesan tetap ikut di ekor pesan user (`skillpack.hint_block`, sudah ada sejak Fase 1); `skill` tanpa `name` menampilkan semua deskripsi. |
| Skema alat | 29 alat (~16.000 char JSON) | 10 alat inti (shell, read/write/edit_file, skill, memory, web_fetch, send_file, plan_update, session_search) + 1 alat `extra_tool` (~6.000 char). 19 alat lain (manage, Kantor, laporan, PPT, Obsidian, diagram, image_ask, …) hanya disebut nama + satu baris di deskripsi `extra_tool`. |
| Teks aplikasi + orkestrator | 2.527 + 1.676 char | 1.143 + 946 char, aturan yang sama (send_file, office_status, jalur dokumen/diagram, aksi berisiko). |
| Total system + tools (char) | ~27.600 | ~12.000 |

Cara kerja `extra_tool`: `action=describe` mengembalikan skema lengkap sebagai *hasil alat*; `action=run` + `arguments` menjalankannya. Agent membuka bungkus panggilan `run` menjadi alat aslinya sebelum apa pun (persetujuan, checkpoint, gate, ledger, log), jadi perilakunya sama dengan panggilan langsung. Alat tertunda yang dipanggil langsung dengan namanya juga tetap jalan (model sering memanggil `diagram_save` / `memory_update` langsung karena disebut di teks aplikasi).

Cache: array tools tidak pernah berubah dalam satu sesi (skema yang dimuat belakangan masuk sebagai pesan, append-only). Baris nama skill berubah hanya bila skill dipasang/dihapus, dan itu ditangani catatan perubahan konfigurasi cache-v2 seperti bagian lain. Tes: `core/tests/test_tempest_diet.py` (tools + system prompt identik byte antar giliran, describe/run, panggilan langsung, diet off = semua alat).

Desainnya ditulis sendiri. Gagasan umumnya (memuat skema alat sesuai kebutuhan) juga ada di "Tool Search" Hermes; tidak ada kode Hermes yang dilihat atau disalin untuk ini.

### 6b. Benchmark live ulang: Hermes vs Tempest F2 vs Tempest diet vs legacy

- 12 Okt 2026 (WIB). Model `claude-haiku-5.5` lewat zRouter, sama untuk semua arm. Maks 25 panggilan, budget 300 dtk, fixture segar per run, check deterministik (pytest + tes tersembunyi / verifikasi brute-force).
- 7 tugas coding lama × 2 seed + **9 tugas penalaran baru** × 3 seed, plus 9 tugas penalaran × 1 seed dengan `reasoning_effort=high` = 50 sel × 4 arm = **200 run**, total 8542273 runs: 200 token.
- Tugas penalaran: ksatria/pembohong (instans acak, solusi unik dicek brute force), penjadwalan 7 rapat dengan batasan, peluang (pecahan), debug interval merge (3 bug, tes tersembunyi), debug LRU cache (3 bug), debug dari log tanpa tes (split tagihan), ember air jumlah langkah minimum (BFS), rute terpendek dengan syarat urutan, hitung harga bertingkat (diskon, voucher, PPN, ongkir).
- 4 arm dari satu sel jalan **bersamaan**, jadi kondisi router sama. Setiap run lewat relay lokal sendiri yang mencatat `usage` provider per panggilan untuk semua arm (Hermes juga; sama persis dengan penghitung sesi Hermes).
- Hermes @ `835c3dd` dengan toolset terminal/file/todo, memori + background review mati (sama seperti 4b). Tempest F2 = kode main dengan `tempest_prompt_diet: false`. Diet = PR ini, default. Mode effort=high: Neovarch `agent.reasoning_effort: high`, Hermes `reasoning_config={effort: high}`; keduanya terbukti mengirim `reasoning_effort: "high"` (terlihat di log relay). Router tidak mengembalikan teks reasoning, jadi efeknya hanya terlihat dari token output.

#### coding, reasoning effort=default, seeds=[0, 1]

| Arm | Pass | Prompt pertama (median tok) | Input tok | Output tok | Total tok | Rata2 wall s | Median wall s | Rata2 call | Run dgn error |
|---|---|---|---|---|---|---|---|---|---|
| Hermes Agent @ 835c3dd | 13/14 | 6,445 | 502,154 | 19,025 | 521,179 | 31.5 | 29.3 | 4.2 | 0 |
| Tempest Fase 2 (main, diet off) | 14/14 | 11,264 | 784,469 | 24,661 | 809,130 | 28.4 | 25.6 | 4.3 | 0 |
| Tempest diet (PR ini) | 14/14 | 5,349 | 386,230 | 19,818 | 406,048 | 25.9 | 23.0 | 4.0 | 0 |
| Neovarch legacy | 12/14 | 10,814 | 871,563 | 26,394 | 897,957 | 28.9 | 23.8 | 4.6 | 0 |

#### reasoning, reasoning effort=default, seeds=[0, 1, 2]

| Arm | Pass | Prompt pertama (median tok) | Input tok | Output tok | Total tok | Rata2 wall s | Median wall s | Rata2 call | Run dgn error |
|---|---|---|---|---|---|---|---|---|---|
| Hermes Agent @ 835c3dd | 27/27 | 6,509 | 737,718 | 46,393 | 784,111 | 31.5 | 30.6 | 3.7 | 0 |
| Tempest Fase 2 (main, diet off) | 27/27 | 11,428 | 1,188,123 | 61,251 | 1,249,374 | 27.1 | 23.8 | 3.4 | 0 |
| Tempest diet (PR ini) | 27/27 | 5,513 | 709,412 | 64,371 | 773,783 | 29.9 | 25.5 | 3.7 | 0 |
| Neovarch legacy | 27/27 | 10,978 | 1,441,773 | 66,368 | 1,508,141 | 31.9 | 27.6 | 4.0 | 0 |

#### reasoning, reasoning effort=high, seeds=[0]

| Arm | Pass | Prompt pertama (median tok) | Input tok | Output tok | Total tok | Rata2 wall s | Median wall s | Rata2 call | Run dgn error |
|---|---|---|---|---|---|---|---|---|---|
| Hermes Agent @ 835c3dd | 9/9 | 6,509 | 222,091 | 16,512 | 238,603 | 31.1 | 31.6 | 3.3 | 0 |
| Tempest Fase 2 (main, diet off) | 9/9 | 11,428 | 459,895 | 21,059 | 480,954 | 31.2 | 22.8 | 3.9 | 0 |
| Tempest diet (PR ini) | 9/9 | 5,513 | 250,183 | 24,530 | 274,713 | 34.3 | 32.1 | 3.8 | 0 |
| Neovarch legacy | 9/9 | 10,978 | 568,566 | 29,714 | 598,280 | 37.2 | 36.1 | 4.4 | 0 |

#### SEMUA tugas, effort default

| Arm | Pass | Prompt pertama (median tok) | Input tok | Output tok | Total tok | Rata2 wall s | Median wall s | Rata2 call | Run dgn error |
|---|---|---|---|---|---|---|---|---|---|
| Hermes Agent @ 835c3dd | 40/41 | 6,493 | 1,239,872 | 65,418 | 1,305,290 | 31.5 | 29.6 | 3.9 | 0 |
| Tempest Fase 2 (main, diet off) | 41/41 | 11,388 | 1,972,592 | 85,912 | 2,058,504 | 27.6 | 24.9 | 3.7 | 0 |
| Tempest diet (PR ini) | 41/41 | 5,473 | 1,095,642 | 84,189 | 1,179,831 | 28.5 | 23.6 | 3.8 | 0 |
| Neovarch legacy | 39/41 | 10,938 | 2,313,336 | 92,762 | 2,406,098 | 30.8 | 24.8 | 4.2 | 0 |

#### Pass per tugas (jumlah lulus / run)

| Task | effort | hermes | tempest-f2 | tempest-diet | legacy |
|---|---|---|---|---|---|
| bugfix-careless | default | 2/2 | 2/2 | 2/2 | 2/2 |
| claim-no-tests | default | 2/2 | 2/2 | 2/2 | 2/2 |
| clean-preexisting-diag | default | 2/2 | 2/2 | 2/2 | 2/2 |
| defect-missing-import | default | 1/2 | 2/2 | 2/2 | 0/2 |
| long-refactor-16-32k | default | 2/2 | 2/2 | 2/2 | 2/2 |
| r-debug-intervals | default | 3/3 | 3/3 | 3/3 | 3/3 |
| r-debug-log | default | 3/3 | 3/3 | 3/3 | 3/3 |
| r-debug-lru | default | 3/3 | 3/3 | 3/3 | 3/3 |
| r-jugs | default | 3/3 | 3/3 | 3/3 | 3/3 |
| r-knights | default | 3/3 | 3/3 | 3/3 | 3/3 |
| r-pricing | default | 3/3 | 3/3 | 3/3 | 3/3 |
| r-probability | default | 3/3 | 3/3 | 3/3 | 3/3 |
| r-route | default | 3/3 | 3/3 | 3/3 | 3/3 |
| r-schedule | default | 3/3 | 3/3 | 3/3 | 3/3 |
| refactor-5-files | default | 2/2 | 2/2 | 2/2 | 2/2 |
| rollback-control-good-retry | default | 2/2 | 2/2 | 2/2 | 2/2 |
| r-debug-intervals | high | 1/1 | 1/1 | 1/1 | 1/1 |
| r-debug-log | high | 1/1 | 1/1 | 1/1 | 1/1 |
| r-debug-lru | high | 1/1 | 1/1 | 1/1 | 1/1 |
| r-jugs | high | 1/1 | 1/1 | 1/1 | 1/1 |
| r-knights | high | 1/1 | 1/1 | 1/1 | 1/1 |
| r-pricing | high | 1/1 | 1/1 | 1/1 | 1/1 |
| r-probability | high | 1/1 | 1/1 | 1/1 | 1/1 |
| r-route | high | 1/1 | 1/1 | 1/1 | 1/1 |
| r-schedule | high | 1/1 | 1/1 | 1/1 | 1/1 |


**Ringkasan jujur**
- **Target tercapai:** prompt pertama Tempest turun dari median 11.388 ke **5.473 token (−52%)**, di bawah target 6K dan sekarang lebih kecil dari Hermes (6.493).
- **Tanpa kehilangan lulus:** diet 41/41 (effort default) dan 9/9 (effort high), sama dengan Tempest F2. Hermes 40/41 (gagal sekali di `defect-missing-import` seed 1), legacy 39/41 (gagal `defect-missing-import` di dua seed, pola yang sama dengan run sebelumnya: tidak menjalankan tes yang ada).
- **Token:** diet −43% vs Tempest F2 (1,18 jt vs 2,06 jt). Vs Hermes: **−22% di tugas coding**, **seri di tugas penalaran** (774K vs 784K, −1%), −10% total. Diet menulis sedikit lebih banyak token output daripada Hermes (84K vs 65K); input jauh lebih kecil.
- **Waktu:** median per run diet 23,6 dtk vs Hermes 29,6 dtk (−20%), F2 24,9, legacy 24,8. Router bersama, jadi anggap indikatif. Di tugas penalaran F2 sedikit lebih cepat dari diet (23,8 vs 25,5 dtk median).
- **Tugas penalaran tidak membedakan arm:** semua arm lulus 27/27 dan 9/9. Untuk model ini tugasnya terlalu mudah (model menulis skrip Python untuk brute force bila perlu). Kesimpulan yang sah hanya: harness tidak merusak penalaran, dan diet tidak menurunkan apa pun. Untuk membedakan kemampuan penalaran perlu tugas yang jauh lebih sulit.
- `reasoning_effort=high` tidak mengubah lulus (sudah 100%). Token output naik (9 tugas seed 0, default → high): Hermes 15,2K → 16,5K, F2 20,4K → 21,1K, diet 20,2K → 24,5K, legacy 20,5K → 29,7K. Tidak ada manfaat yang terukur di set ini.
- Alat tertunda tetap dipakai dengan benar secara live (cek kecil terpisah, diet vs F2, 1 run per kasus): "simpan diagram" → `skill diagram` + `diagram_save` (dipanggil langsung), "status Kantor?" → `extra_tool` run `office_status` lalu `manage`, "ingat preferensiku" → `memory` (F2 memakai `memory_update`; keduanya tersimpan). Token per kasus diet ≈ setengah F2 (20,0K vs 37,5K; 17,4K vs 34,6K; 11,4K vs 22,9K).

**Catatan & batasan**
- n per sel kecil (1–3 run). Selisih lulus 1–2 run tidak bermakna secara statistik; selisih token konsisten di hampir semua sel.
- Satu soal (`r-pricing`) awalnya ambigu: status member pelanggan tidak disebut, sehingga Tempest F2 dan diet menganggap bukan member (asumsi disebut terang di jawaban) dan dinilai gagal. Prompt diperbaiki ("Pelanggan ini MEMBER") dan **semua arm** dijalankan ulang; hasil lama disimpan terpisah, tidak masuk tabel.
- Satu sel (`refactor-5-files` seed 1) kena gangguan router (HTTP 504, Hermes ter-kill 360 dtk); seluruh sel (4 arm) dijalankan ulang setelah router pulih. Router juga sempat 503; tidak ada run yang dihitung di masa itu.
- Router tidak melaporkan `cached_tokens` pada run ini, jadi efek cache tidak bisa diukur; "input tok" adalah total prompt termasuk bagian yang mungkin ter-cache.
- Toolset tidak identik: Hermes dibatasi terminal/file/todo (8 alat, tapi ~14K char skema); Neovarch memakai toolset bawaan penuh (F2: 29 alat; diet: 10 + `extra_tool`).
- Harness live ada di workspace pengembang (`tempest-diet-live/`), sengaja tidak masuk repo karena menjalankan Hermes.
