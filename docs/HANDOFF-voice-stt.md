# HANDOFF: voice command HP + STT lokal gratis (v1.4.9, item "voice HP")

Branch: `nva-voice-stt` (dari main f21772c). Commit author/committer: `Maftuuh1922 <145763168+Maftuuh1922@users.noreply.github.com>`, tanpa trailer.
Tanpa rilis/tag/deploy. Hanya model gratis (faster-whisper / whisper.cpp lokal).

## Status
- [x] 1. Core STT: `core/neovarch/stt.py` + `/api/audio/transcribe` (faster-whisper → whisper.cpp → `stt_unavailable` + install hint),
      `GET /api/audio/stt/status`, `stt-lease.available`; extra `pip install "neovarch[stt]"`. Test: `core/tests/test_audio.py` (engine dipalsukan).
- [x] 2. Flutter: rekam di HP (MainActivity.kt `recordStart/recordStop/recordCancel/recordLevel`, MediaRecorder AAC m4a 16 kHz)
      → `RemoteGateway.transcribeAudio` (POST /api/audio/transcribe {audio_base64, mime_type, language}) → transkrip ke composer.
      Urutan `auto`: SpeechRecognizer → dialog sistem → PC → Vosk (EN). Setelan Profil → Dikte suara: Otomatis / Lewat PC,
      "Kirim otomatis" (default mati), tombol Cek PC (GET /api/audio/stt/status). Test: test/voice_pc_stt_test.dart
      (+ dictation_test, voice_fallback_test, app_language_test hijau).
- [x] 3. Desktop: sudah memanggil `/api/audio/transcribe` (data_url webm) → jalan begitu core punya engine. `checkedTranscription`:
      `stt_failed/bad_audio/too_large` jadi error biasa dengan pesan core (bukan "tidak tersedia"); test di transcription-error.test.ts.
- [~] 4. String locale: HP (enStrings) + desktop `transcriptionUnavailable` di semua locale (en/id/de/es/fr/ja/ru/zh/zh-hant/ar) diperbarui
      dengan petunjuk `pip install faster-whisper`. Tidak ada key baru → `npm run i18n:keys -- --check` harus tetap sama (belum dijalankan lokal).
- [ ] 5. Screenshot desktop + HP → `/workspace/work/nva-voice-stt-shots`.
- [ ] 6. PR berbahasa Indonesia, CI (desktop-electron.yml workflow_dispatch + Build APK), squash-merge hanya bila hijau.

## Konfigurasi STT (config.yaml `stt:`; env menang)
engine auto|faster-whisper|whisper.cpp|off (NEOVARCH_STT_ENGINE), model small (NEOVARCH_STT_MODEL), language auto (NEOVARCH_STT_LANGUAGE),
device cpu, compute_type int8, whisper_cpp_bin, whisper_cpp_model (NEOVARCH_WHISPER_CPP_MODEL; butuh ffmpeg).

## Catatan uji nyata
faster-whisper 1.2.1 + av 19 gagal (`open() got an unexpected keyword argument 'metadata_errors'`); sedang diuji `av<16` (lihat /workspace/work/nvv_real*.log).

## Cara melanjutkan
`git clone … && git checkout nva-voice-stt`; `cd core && pip install -e ".[test]" && pytest -q tests/test_audio.py`.
Belum diuji di HP fisik.
