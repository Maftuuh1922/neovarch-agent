---
name: visual-inline
description: Gambar penjelasan langsung di obrolan sebagai kartu vektor (blok ```visual) - graf, alur, batang, timeline, perbandingan berdampingan ✓/✗ / Draw crisp inline visuals in chat with a ```visual block.
---
# Visual inline (blok ```visual)

Aplikasi desktop dan HP menggambar blok ```visual di jawabanmu sebagai **kartu vektor tajam** (bukan gambar
tempelan, bukan file): judul di atas, gambar, caption di bawah. Pengguna bisa layar penuh, lihat kode, simpan PNG/SVG.

## Kapan menggambar
- Konsep yang lebih cepat dilihat daripada dibaca: struktur graf/pohon, alur/proses, perbandingan angka,
  urutan waktu, "A vs B" (mana yang benar, mana yang salah).
- Saat pengguna minta "gambarin", "visualkan", "jelaskan pakai gambar", atau saat kamu menjelaskan konsep yang
  punya bentuk (graf bintang, BFS, stack vs queue, arsitektur kecil).
- **Jangan** menggambar untuk jawaban satu kalimat, daftar biasa, atau data yang lebih jelas sebagai tabel teks.
- Satu visual = satu gagasan. Tulis 1-3 kalimat penjelasan di luar blok; jangan ulangi isi caption.
- Diagram besar yang perlu disimpan sebagai file/halaman: pakai skill `diagram` + `diagram_save`.

## Format
Satu blok ```visual berisi SALAH SATU dari:
1. **Spec deklaratif JSON** (utama, paling rapi, tata letak otomatis): `graph`, `flow`, `bar`, `timeline`, `compare`.
2. **SVG mentah** untuk bentuk bebas: wajib `viewBox`, lebar ≤ 720 (idealnya ≤ 420: di HP kolomnya ~360px dan SVG
   mentah hanya diperkecil, tidak ditata ulang), tanpa skrip/foreignObject/tautan luar. Spec menyesuaikan lebar sendiri.
3. **HTML+CSS** kecil (tabel/kartu): tanpa skrip, form, iframe, atau sumber eksternal.

SVG/HTML boleh diawali baris `title: …` dan `caption: …` lalu `---`. Spec memakai field `"title"` dan `"caption"`.

### Spec
- `graph`: `nodes` (string, atau `{id, label?, highlight?, color?, sub?}`), `edges` (`["A","B"]`, `["A","B","label"]`,
  atau `{from, to, label?, highlight?, color?, dashed?}`), `directed?`, `layout?` (`auto` | `star` | `circle` |
  `tree` | `force` | `grid` | `line`), `hub?`, `root?`, `highlightEdges?` (sorot sisi antar simpul yang disorot).
  Label ≤ 3 huruf jadi lingkaran berhuruf; label panjang jadi kotak.
- `flow`: `steps` (`{id, label, shape?: box|decision|start|end, highlight?, color?, note?}`), `edges?`
  (tanpa edges = berurutan), `direction?` (`down` | `right`). Panah balik digambar memutar di samping.
- `bar`: `data` (`{label, value, highlight?, color?, note?, display?}`), `unit?`, `prefix?`, `sort?` (`desc`/`asc`),
  `orientation?` (`horizontal` default | `vertical`), `thousands?` (`.` untuk format Indonesia).
- `timeline`: `events` (`{date, label, note?, highlight?}`), `direction?` (otomatis: ≤ 5 mendatar, lebih tegak).
- `compare`: `panels` (2-4) berisi `{title?, visual: <spec graph/flow/bar/timeline>, caption, verdict: good|bad}`.
  Digambar berdampingan; caption diawali ✓ hijau (good) atau ✗ merah (bad) otomatis - jangan ketik ✓/✗ sendiri.

## Cara menggambar rapi
- **Palet**: netral untuk semuanya; **biru = yang penting** (`highlight: true`). Merah hanya untuk yang salah/
  bermasalah, hijau untuk hasil/berhasil. Maksimal 1-2 warna sorot per visual. Nama warna: blue, green, red, amber,
  purple, teal, pink, gray (otomatis ikut tema terang/gelap). Jangan menulis kode warna latar.
- **Sorot sedikit**: 1-4 simpul/batang/peristiwa yang ingin dilihat pembaca. Kalau semuanya biru, tidak ada yang penting.
- **Label**: pendek (≤ 3 kata di simpul/langkah); detail taruh di `note`/`sub` atau di caption. Huruf (A, B, C)
  untuk graf teori; nama asli untuk sistem/proses.
- **Ukuran**: graf ≤ 12 simpul, alur ≤ 10 langkah, batang 3-10, timeline ≤ 8. Lebih dari itu: pecah.
- **Perbandingan berdampingan**: struktur sama di kedua panel (simpul sama, posisi sama: pakai `layout` dan `hub`
  yang sama), bedanya disorot (sisi merah, simpul biru). Caption menyebut alasannya: `"Star: A ke semua simpul"` /
  `"Bukan star: B–C menghubungkan dua daun"`.
- **Judul** = pertanyaan/klaimnya ("Star vs graf kamu"); **caption** = satu kalimat apa yang harus dilihat.
- SVG mentah: pakai kelas bawaan supaya ikut tema - `nv-t` (teks), `nv-m` (teks redup), `nv-b` (tebal), `nv-node`
  (kotak/lingkaran), `nv-edge` (garis), `nv-on` (teks di atas warna sorot); warna lewat
  `style="fill:var(--nv-blue)"`, `var(--nv-red)`, `var(--nv-green)`, `var(--nv-fg)`, `var(--nv-muted)`.
  font-size ≥ 11, semua elemen di dalam viewBox, beri jarak ≥ 8px antar label.

## Wajib: cek dulu sebelum kirim
Panggil `extra_tool` → `run` `visual_check` dengan `code` = isi blok (atau blok lengkap). Perbaiki semua **error**
dan saran yang masuk akal, cek ulang, baru tulis blok ```visual di jawaban. Jangan simpan ke file kecuali diminta.

## Contoh (lihat `SKILL_DIR/examples/`)
1. `01-star-vs-graph.visual` - perbandingan dua graf kecil berdampingan, simpul huruf, pusat biru, caption ✓/✗.
2. `02-flow-login.visual` - alur dengan keputusan, langkah baru disorot, panah balik "tidak".
3. `03-bar-bundle.visual` - batang mendatar, versi sekarang biru, satuan " KB".
4. `04-timeline-release.visual` - timeline mendatar, tonggak berikutnya disorot.
5. `05-tree-search.visual` - pohon terarah, jalur pencarian biru (`highlightEdges`).
6. `06-stack-vs-queue.visual` - SVG mentah dengan kelas tema (judul/caption lewat header).
Bonus: `07-html-bigo.visual` - kartu tabel HTML+CSS.

Contoh 1 (patokan kualitas):

```visual
{
  "type": "compare",
  "title": "Star vs graf kamu",
  "caption": "Graf bintang: satu pusat terhubung ke semua simpul lain, dan daun tidak saling terhubung.",
  "panels": [
    {"title": "Star", "verdict": "good", "caption": "Star: A terhubung ke semua simpul, daun tidak saling terhubung",
     "visual": {"type": "graph", "layout": "star", "nodes": [{"id": "A", "highlight": true}, "B", "C", "D", "E"],
                "edges": [["A", "B"], ["A", "C"], ["A", "D"], ["A", "E"]]}},
    {"title": "Graf kamu", "verdict": "bad", "caption": "Bukan star: B–C menghubungkan dua daun, E tidak ke A",
     "visual": {"type": "graph", "layout": "star", "hub": "A", "nodes": [{"id": "A", "highlight": true}, "B", "C", "D", "E"],
                "edges": [["A", "B"], ["A", "C"], ["A", "D"], {"from": "B", "to": "C", "color": "red"},
                          {"from": "D", "to": "E", "color": "red"}]}}
  ]
}
```
