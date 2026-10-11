---
name: finalisasi-akademik
description: Finalisasi naskah akademik - format kampus/jurnal, daftar pustaka, cek konsistensi, cek kemiripan/plagiarisme, ekspor DOCX/PDF / Final formatting, reference and consistency checks before submission.
---
# Finalisasi Akademik

Gunakan saat naskah hampir dikumpulkan: "rapikan format skripsi", "cek daftar pustaka", "siap submit jurnal".

## Daftar periksa akhir
1. **Format** - ikuti pedoman kampus/jurnal bila diberikan; default kampus: Times New Roman 12, spasi 1,5,
   margin 4-3-3-3 cm, nomor bab/subbab, daftar isi, daftar tabel/gambar. `report_export` sudah memakai default ini.
2. **Daftar pustaka** - setiap sitasi di teks ada di daftar pustaka dan sebaliknya; satu gaya (APA 7 / IEEE);
   cek ulang DOI/URL dengan `web_fetch`; hapus sumber yang tidak bisa diverifikasi atau tandai untuk pengguna.
3. **Konsistensi** - istilah, singkatan (didefinisikan saat pertama muncul), angka di abstrak = hasil, penomoran
   tabel/gambar dan rujukannya, tahun dan nama penulis.
4. **Kemiripan/plagiarisme** - tandai kalimat yang tampak disalin tanpa kutipan, kutipan langsung tanpa halaman,
   dan parafrase yang terlalu dekat. Sarankan pengguna mengecek dengan alat resmi kampus (mis. Turnitin);
   jangan mengklaim persentase kemiripan yang tidak diukur.
5. **Kelengkapan** - abstrak (+ abstract), kata kunci, lampiran, halaman pengesahan/pernyataan bila diwajibkan.
6. Ekspor dengan `report_export` (docx/pdf) dan berikan jalur absolut agar bisa dibuka di PC atau diunduh di HP.

Ditulis orisinal untuk Neovarch Agent; inspired by the workflow of Imbad0202/academic-research-skills (tidak ada teks yang disalin).
