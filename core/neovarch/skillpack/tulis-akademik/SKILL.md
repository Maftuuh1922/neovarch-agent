---
name: tulis-akademik
description: Tulis naskah akademik - kerangka lalu draf skripsi, tesis, makalah, artikel jurnal, atau proposal penelitian dengan sitasi nyata / Outline and draft a thesis, paper or journal article.
---
# Tulis Akademik

Gunakan saat pengguna minta "bantu bikin skripsi", "tulis bab 2", "buat artikel jurnal/makalah/proposal penelitian".

## Alur
1. Tanyakan hanya yang mengubah hasil: jenis naskah (skripsi/tesis/jurnal/makalah), bidang & topik, gaya sitasi
   (APA/IEEE), dan pedoman kampus/jurnal bila ada. Sisanya pakai default yang wajar.
2. Pastikan ada bahan dari skill `riset-akademik` (referensi terverifikasi). Tanpa referensi, kerjakan riset dulu.
3. Kerangka dulu, minta persetujuan singkat:
   - Skripsi/tesis: BAB I Pendahuluan (latar belakang, rumusan masalah, tujuan, manfaat, batasan), BAB II Tinjauan
     Pustaka, BAB III Metodologi, BAB IV Hasil dan Pembahasan, BAB V Kesimpulan dan Saran.
   - Artikel jurnal: Judul, Abstrak (+ kata kunci), Pendahuluan, Metode, Hasil, Pembahasan, Kesimpulan, Referensi.
4. Draf per bagian. Setiap klaim faktual diberi sitasi `[@key]` dari referensi yang ada; jangan menambah sumber baru
   tanpa verifikasi. Data/hasil penelitian tidak boleh dikarang: pakai data pengguna atau beri placeholder jelas
   seperti [DATA HASIL UJI].
5. Bahasa: Indonesia baku (PUEBI/EYD) kecuali diminta Inggris; paragraf runtut, kalimat aktif bila wajar.
6. Simpan dengan `report_create`, ekspor .docx/.pdf dengan `report_export`, dan berikan jalur absolutnya.

Etika: bantu pengguna menulis dan memahami karyanya; ingatkan aturan integritas akademik kampusnya bila relevan.

Ditulis orisinal untuk Neovarch Agent; inspired by the workflow of Imbad0202/academic-research-skills (tidak ada teks yang disalin).
