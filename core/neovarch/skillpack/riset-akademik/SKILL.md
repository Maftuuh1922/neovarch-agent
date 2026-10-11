---
name: riset-akademik
description: Riset akademik - cari literatur, nilai kualitas sumber, kutip APA/IEEE tanpa referensi palsu, verifikasi setiap DOI/URL / Academic literature search and source checking with verified citations.
---
# Riset Akademik

Gunakan saat pengguna minta mencari jurnal/referensi, tinjauan pustaka (literature review), state of the art,
dasar teori untuk skripsi/tesis/jurnal, atau "carikan sumber tentang ...".

## Aturan utama
- **Tidak ada referensi karangan.** Setiap sumber harus berasal dari hasil pencarian nyata (`report_search`,
  atau halaman yang benar-benar dibuka dengan `web_fetch`). Jika tidak ditemukan, katakan tidak ditemukan.
- **Verifikasi DOI/URL.** Buka `https://doi.org/<doi>` atau URL-nya dengan `web_fetch`; cocokkan judul, penulis,
  dan tahun. Sumber yang gagal diverifikasi ditandai "belum terverifikasi" dan tidak dipakai sebagai kutipan.
- Jangan mengklaim isi artikel yang hanya kamu lihat abstraknya; sebutkan bahwa itu dari abstrak.

## Alur
1. Rumuskan pertanyaan riset dan kata kunci (Indonesia + Inggris, sinonim, rentang tahun; default 5-10 tahun terakhir).
2. Cari dengan `report_search` (OpenAlex, Crossref, Semantic Scholar) beberapa kali dengan variasi kata kunci.
3. Saring: relevansi, jenis publikasi (jurnal bereputasi/prosiding/buku > blog), tahun, sitasi, metodologi jelas.
   Waspadai jurnal predator dan preprint yang belum ditelaah; beri label.
4. Buat matriks literatur: penulis-tahun, tujuan, metode, data, temuan, keterbatasan, relevansi.
5. Sintesis per tema (bukan per artikel): persamaan, perbedaan, celah penelitian (research gap).
6. Kutipan: APA 7 (default) atau IEEE sesuai permintaan; gunakan kunci `[@key]` dari `report_search`
   bila akan dilanjutkan ke `report_create`.

Lanjutkan ke skill `tulis-akademik` untuk menulis naskah.

Ditulis orisinal untuk Neovarch Agent; inspired by the workflow of Imbad0202/academic-research-skills (tidak ada teks yang disalin).
