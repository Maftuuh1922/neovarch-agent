# Codemode: satu panggilan model, banyak alat

Terinspirasi dari [Reason Agent 1.1](https://reasonmachines.com/blog/introducing-reason-agent-1-1) ("codemode"):
alih-alih memanggil model sekali per alat, model menulis **satu program Python pendek** yang memanggil alat
lain (beberapa sekaligus) lalu hanya mencetak yang penting. Cari + baca 5 file + jalankan tes = satu
panggilan model, dan konteks hanya bertambah sebesar ringkasan yang dicetak program.

Kode: `core/neovarch/codemode.py`, dipasang di loop agent (`Agent._codemode`, `Agent._codemode_call`).

## Cara pakai (oleh model)

```python
reads = tools.parallel([("read_file", {"path": p}) for p in ["a.py", "b.py", "c.py"]])
hits = tools.grep(pattern="def total")
run = tools.shell(command="python -m pytest -q tests/test_cart.py")
print(hits)
print(run.strip().splitlines()[-1])
```

- `tools.<nama>(**args)` / `tools.call(nama, **args)` → teks hasil satu alat.
- `tools.parallel([(nama, {args}), ...])` → daftar hasil, urutan sama.
- `tools.list()` → semua alat termasuk alat tambahan (deferred); `tools.describe(nama)` → schema.

## Aturan & batas

- Setiap panggilan alat dari program lewat jalur yang sama dengan panggilan langsung: persetujuan perintah
  berbahaya, perintah di luar folder kerja, mode `/rencana` (hanya baca), cek sintaks `write_file`/`edit_file`
  /`apply_patch` + checkpoint, hooks, daftar alat yang dimatikan, dedup memori, dan ledger bukti (gerbang klaim
  "selesai" melihat tes yang dijalankan di dalam program).
- Di satu `parallel`: alat baca-saja (dan perintah shell yang tidak butuh persetujuan) berjalan bersamaan;
  alat yang mengubah sesuatu berjalan berurutan.
- Program berjalan di proses Python terpisah (`python -I`), folder kerja = folder chat, environment minimal,
  timeout (default 60 s, maks 300 s), dan di Linux/macOS batas CPU, memori (1 GB) dan ukuran file (0 = tidak
  boleh menulis file). Program tidak boleh membuka jaringan (kecuali `network=true` **dan**
  `agent.tempest_codemode_network: true`), menjalankan proses, atau menulis/menghapus/memindah file langsung.
  Ini pagar, bukan batas keamanan penuh: batas sebenarnya adalah semua efek samping lewat `tools`.
- Maks 64 panggilan alat per program, 16 per `parallel`, output dipotong 12.000 karakter.
- `codemode` dan `extra_tool` tidak bisa dipanggil dari dalam program.

## Pengaturan

| Kunci (`config.yaml`) | Default | Arti |
|---|---|---|
| `agent.tempest_codemode` | `true` | tampilkan alat `codemode` (Tempest) |
| `agent.tempest_codemode_network` | `false` | izinkan program membuka socket bila model meminta `network=true` |

Cache: schema `codemode` adalah teks statis dan ikut daftar alat inti, jadi daftar alat dan system prompt
tetap byte-identik antar giliran (hanya pesan baru yang ditambahkan). Alat jarang dipakai tetap di balik
`extra_tool` / `tools.list()`.

Binary beku (tanpa interpreter Python) → alat tidak ditampilkan (`codemode.available()`).

## Bench (`core/bench/codemode_bench.py`)

Replay deterministik lewat loop Agent asli: alat, file, pytest dan seluruh harness Tempest berjalan nyata;
hanya pilihan model yang di-skrip (lintasan tulisan tangan di `core/bench/codemode_tasks.py`, kerja yang
sama di tiap arm). Jadi ini mengukur **biaya harness** (panggilan model, token, waktu), **bukan** kualitas
model. Token: tiktoken cl100k_base pada request persis (tools + messages); cache = estimasi exact-prefix
ala OpenAI (≥1024 token, kelipatan 128).

```
python3 core/bench/codemode_bench.py all out.jsonl
python3 core/bench/codemode_bench.py report out.jsonl --latency 2.5
```

Hasil 2026-10-14 (10 tugas, 1 run per arm, `core/bench/results/codemode-2026-10-14.jsonl`):

| Arm | Lulus | Panggilan model | Token prompt | Token prompt tak-ter-cache | Token output | Waktu alat (s) | +2,5 s/panggilan (s) |
|---|---|---|---|---|---|---|---|
| per-call (1 alat per pesan) | 10/10 | 57 | 271.819 | 54.603 | 1.920 | 5,2 | 147,7 |
| parallel (baca paralel bawaan) | 10/10 | 38 | 183.668 | 53.236 | 1.882 | 7,1 | 102,1 |
| codemode | 10/10 | 23 | 108.389 | 49.509 | 2.136 | 7,4 | 64,9 |

Lulus = tes nyata pada repo setelah run (6 tugas kode) / jawaban skrip (4 tugas QnA, hanya sanity).

- vs per-call: panggilan model −60%, token prompt −60%, tak-ter-cache −9%, output +11%.
- vs parallel: panggilan model −39%, token prompt −41%, tak-ter-cache −7%, output +13%.
- Waktu alat praktis sama (model instan di replay; spawn proses program ±0,1–0,2 s); kolom terakhir
  menambahkan latensi model asumsi 2,5 s per panggilan.
- Schema codemode menambah ±650 token ke tiap request (lihat `qna-todos`, tugas satu-alat: sedikit lebih mahal).
- Dengan cache prefix, biaya input tak-ter-cache turun kecil (−7…−9%); penghematan terbesar ada di jumlah
  panggilan/round-trip dan total token yang dikirim (penting untuk provider tanpa cache dan untuk kuota gratis
  yang dihitung per request).

Belum diukur: model asli (tidak ada model gratis yang bisa diakses dari sandbox saat bench: OpenCode Free
lewat 9Router menjawab 403 FreeTierError / 429; tidak ada key OpenRouter), Harbor/Terminal-Bench/DeepSWE/
SWE-Atlas (butuh Docker), Pi/Codex CLI. Angka Reason Agent 1.1 (Index 65,1 dst.) **tidak** dibandingkan
karena setup-nya berbeda total.
