# Handoff: sisa antrean v1.4.9 (setelah Crew Terraria)

Kerjakan setelah [Crew Terraria](HANDOFF-crew-terraria.md) selesai dan di-merge.

## Aturan untuk setiap item
- Satu PR per item, deskripsi PR berbahasa Indonesia.
- Hanya model/layanan gratis (tanpa API berbayar).
- Lampirkan screenshot desktop + HP di PR.
- Squash-merge hanya bila semua CI hijau (Desktop Electron via workflow_dispatch di branch, Build APK di PR).
- Commit identity `Maftuuh1922 <145763168+Maftuuh1922@users.noreply.github.com>`, tanpa trailer/co-author.

## Antrean (urut)
1. **Voice command dari HP / mic.** Push-to-talk di HP dengan transkripsi langsung; STT lokal gratis di PC (faster-whisper atau whisper.cpp)
   di balik `/api/audio/transcribe` (sekarang selalu `stt_unavailable`); fallback rekam-lalu-kirim ke core bila Android SpeechRecognizer tidak ada;
   balasan suara opsional. Sudah ada dari PR #45 (squash 55cff25): strip status composer, alasan izin, `micPermission`/`requestMic`/`openSpeechServices`,
   watchdog; transkrip masuk ke kolom teks, tidak terkirim otomatis. Mic sebelumnya dilaporkan tidak berfungsi sama sekali di HP asli — wajib diverifikasi.
2. **Agen proaktif ala Claude Duet.** Feed di HP + brief pagi (CI gagal, PR menunggu, Kantor/Crew selesai/macet, cron); menyiapkan pekerjaan saat
   pengguna pergi, tapi selalu bertanya sebelum bertindak.
3. **Import satu klik** dari Claude Code/Codex/Cursor/OpenClaw (memori, rules, skills, MCP) ke `~/.neovarch`; CLI + tombol desktop; dry-run dulu.
4. **Uji ulang Tempest** pada benchmark sulit, hanya model gratis.
5. **Rilis v1.4.9** hanya setelah semua di atas di-merge dan CI hijau: catatan rilis berbahasa Indonesia di `docs/release-notes/v1.4.9.md`,
   APK release-signed (APK dari CI debug-signed; workflow rilis menolak melampirkannya).
