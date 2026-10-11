---
name: review-sejawat
description: Telaah sejawat (peer review) naskah akademik dengan daftar periksa - kebaruan, metode, data, argumen, sitasi, bahasa / Peer-review checklist for a paper or thesis draft.
---
# Review Sejawat

Gunakan saat pengguna minta naskahnya ditinjau, "cek skripsiku", "review jurnal ini", atau mau simulasi reviewer.

## Daftar periksa
1. **Kontribusi & kebaruan** - masalah jelas? celah penelitian nyata dan didukung literatur?
2. **Kesesuaian** - judul, rumusan masalah, tujuan, metode, hasil, dan kesimpulan saling cocok.
3. **Metodologi** - desain, sampel, instrumen, validitas/reliabilitas, analisis sesuai pertanyaan; bisa direplikasi.
4. **Hasil** - angka konsisten antar tabel/teks, statistik dilaporkan lengkap, tidak melebihi bukti.
5. **Pembahasan** - dibandingkan dengan literatur, keterbatasan diakui, implikasi masuk akal.
6. **Sitasi** - setiap klaim penting bersumber; cek acak beberapa DOI/URL dengan `web_fetch`; format APA/IEEE konsisten.
7. **Bahasa & format** - EYD, istilah konsisten, struktur sesuai pedoman.
8. **Etika** - persetujuan responden, konflik kepentingan, potensi plagiarisme (paragraf yang gayanya berubah drastis).

## Keluaran
Ringkasan penilaian (terima / revisi minor / revisi mayor / tolak, beserta alasan), lalu daftar temuan bernomor:
lokasi (bab/halaman/paragraf), masalah, saran perbaikan konkret, prioritas (wajib/disarankan). Kritik tegas tapi sopan.
Lanjutkan ke skill `revisi-akademik` bila pengguna ingin memperbaiki.

Ditulis orisinal untuk Neovarch Agent; inspired by the workflow of Imbad0202/academic-research-skills (tidak ada teks yang disalin).
