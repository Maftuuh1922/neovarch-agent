# HANDOFF: voice command HP + STT lokal gratis (v1.4.9, item "voice HP")

Branch: `nva-voice-stt` (dari main f21772c). Commit author/committer: `Maftuuh1922 <145763168+Maftuuh1922@users.noreply.github.com>`, tanpa trailer.
Tanpa rilis/tag/deploy. Hanya model gratis (faster-whisper / whisper.cpp lokal).

## Status
- [x] 1. Core STT: `core/neovarch/stt.py` + `/api/audio/transcribe` (faster-whisper → whisper.cpp → `stt_unavailable` + install hint),
      `GET /api/audio/stt/status`, `stt-lease.available`; extra `pip install "neovarch[stt]"`. Test: `core/tests/test_audio.py` (engine dipalsukan).
- [ ] 2. Flutter: rekam di HP (MediaRecorder native, m4a) → kirim ke core → transkrip ke composer (tanpa kirim otomatis kecuali setelan).
- [ ] 3. Desktop: sudah memanggil `/api/audio/transcribe` (data_url webm) → otomatis jalan bila core punya engine. Cek pesan error.
- [ ] 4. String locale (semua locale, regen keys).
- [ ] 5. Screenshot desktop + HP → `/workspace/work/nva-voice-stt-shots`.
- [ ] 6. PR berbahasa Indonesia, CI (desktop-electron.yml workflow_dispatch + Build APK), squash-merge hanya bila hijau.

## Konfigurasi STT (config.yaml `stt:`; env menang)
engine auto|faster-whisper|whisper.cpp|off (NEOVARCH_STT_ENGINE), model small (NEOVARCH_STT_MODEL), language auto (NEOVARCH_STT_LANGUAGE),
device cpu, compute_type int8, whisper_cpp_bin, whisper_cpp_model (NEOVARCH_WHISPER_CPP_MODEL; butuh ffmpeg).

## Cara melanjutkan
`git clone … && git checkout nva-voice-stt`; `cd core && pip install -e ".[test]" && pytest -q tests/test_audio.py`.
Belum diuji di HP fisik.
