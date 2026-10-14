/**
 * Neovarch's Indonesian strings, layered over the English catalog.
 *
 * Neovarch's interface language is Indonesian. Rather than ship a separate
 * locale the user has to pick, the base catalog (`en`, the fallback every
 * other language resolves through) is merged with these strings, so anything
 * translated here shows in Indonesian by default. Keys not listed stay as the
 * upstream English until they are translated.
 */
import type { TranslationOverrides } from './define-locale'
import { nvPamerkanId } from './nv-pamerkan'
import { nvPullId } from './nv-pull'

export const NEOVARCH_ID = {
  "nvPamerkan": nvPamerkanId,
  "nvPull": nvPullId,
  "common": {
    "apply": "Terapkan",
    "back": "Kembali",
    "save": "Simpan",
    "saving": "Menyimpan…",
    "cancel": "Batal",
    "change": "Ubah",
    "choose": "Pilih",
    "clear": "Bersihkan",
    "close": "Tutup",
    "collapse": "Ciutkan",
    "confirm": "Konfirmasi",
    "connect": "Hubungkan",
    "connecting": "Menghubungkan",
    "continue": "Lanjut",
    "bots": "Bot",
    "copied": "Tersalin",
    "copy": "Salin",
    "copyFailed": "Gagal menyalin",
    "delete": "Hapus",
    "docs": "Dokumentasi",
    "done": "Selesai",
    "error": "Galat",
    "expand": "Bentangkan",
    "failed": "Gagal",
    "formatJson": "Rapikan JSON",
    "free": "Gratis",
    "loading": "Memuat…",
    "notSet": "Belum diatur",
    "refresh": "Muat ulang",
    "remove": "Lepas",
    "replace": "Ganti",
    "retry": "Coba lagi",
    "run": "Jalankan",
    "send": "Kirim",
    "set": "Atur",
    "skip": "Lewati",
    "update": "Perbarui",
    "on": "Nyala",
    "off": "Mati"
  },
  "cron": {
    "close": "Tutup jadwal",
    "title": "Jadwal tugas",
    "search": "Cari jadwal…",
    "loading": "Memuat jadwal…",
    "states": {
      "enabled": "aktif",
      "scheduled": "terjadwal",
      "running": "berjalan",
      "paused": "dijeda",
      "disabled": "nonaktif",
      "error": "jalan terakhir gagal",
      "completed": "selesai"
    },
    "lastRunFailed": "Jalan terakhir gagal:",
    "editJob": "Ubah jadwal",
    "runAgain": "Jalankan lagi",
    "deliveryLabels": {
      "local": "PC ini"
    },
    "scheduleLabels": {
      "daily": "Harian",
      "weekdays": "Hari kerja",
      "weekly": "Mingguan",
      "monthly": "Bulanan",
      "hourly": "Tiap jam",
      "every-15-minutes": "Tiap 15 menit",
      "custom": "Kustom"
    },
    "scheduleHints": {
      "daily": "Setiap hari pukul 09.00",
      "weekdays": "Senin sampai Jumat pukul 09.00",
      "weekly": "Setiap Senin pukul 09.00",
      "monthly": "Tanggal 1 setiap bulan pukul 09.00",
      "hourly": "Di awal setiap jam",
      "every-15-minutes": "Tiap 15 menit",
      "custom": "Ekspresi cron (0 9 * * 1-5), interval (30m, every 2h) atau daily 08:00"
    },
    "days": {
      "0": "Minggu",
      "1": "Senin",
      "2": "Selasa",
      "3": "Rabu",
      "4": "Kamis",
      "5": "Jumat",
      "6": "Sabtu",
      "7": "Minggu"
    },
    "topOfHour": "Di awal setiap jam",
    "newCron": "Jadwal baru",
    "emptyDescNew": "Jadwalkan prompt agar dijalankan otomatis. Neovarch menjalankannya di sesi baru di PC ini.",
    "emptyDescSearch": "Coba kata kunci yang lebih umum.",
    "emptyTitleNew": "Belum ada jadwal",
    "emptyTitleSearch": "Tidak ada yang cocok",
    "last": "Terakhir:",
    "next": "Berikutnya:",
    "overdueSince": "Terlambat sejak:",
    "noRuns": "Belum pernah jalan",
    "queuedRun": "Antre jalan",
    "manage": "Kelola",
    "showRuns": "Lihat riwayat",
    "hideRuns": "Sembunyikan riwayat",
    "runHistory": "Riwayat jalan",
    "actionsTitle": "Aksi jadwal",
    "resume": "Lanjutkan jadwal",
    "pause": "Jeda jadwal",
    "resumeTitle": "Lanjutkan",
    "pauseTitle": "Jeda",
    "triggerNow": "Jalankan sekarang",
    "edit": "Ubah jadwal",
    "deleteTitle": "Hapus jadwal?",
    "deleteDescPrefix": "Ini akan menghapus ",
    "deleteDescSuffix": " secara permanen. Jadwal langsung berhenti.",
    "deleting": "Menghapus…",
    "resumed": "Jadwal dilanjutkan",
    "paused": "Jadwal dijeda",
    "triggered": "Jadwal dijalankan",
    "deleted": "Jadwal dihapus",
    "created": "Jadwal dibuat",
    "updated": "Jadwal diperbarui",
    "failedLoad": "Gagal memuat jadwal",
    "failedUpdate": "Gagal memperbarui jadwal",
    "failedTrigger": "Gagal menjalankan jadwal",
    "failedDelete": "Gagal menghapus jadwal",
    "failedSave": "Gagal menyimpan jadwal",
    "editTitle": "Ubah jadwal",
    "createTitle": "Jadwal baru",
    "editDesc": "Ubah jadwal atau prompt. Perubahan berlaku pada jalan berikutnya.",
    "createDesc": "Jadwalkan prompt agar berjalan otomatis. Pakai ekspresi cron, interval seperti \"every 2h\", atau \"daily 08:00\".",
    "nameLabel": "Nama",
    "namePlaceholder": "Ringkasan pagi",
    "promptLabel": "Prompt",
    "promptPlaceholder": "Rangkum berita teknologi hari ini dalam 5 poin…",
    "frequencyLabel": "Frekuensi",
    "deliverLabel": "Kirim ke",
    "modelLabel": "Model",
    "modelDefault": "Bawaan (model global)",
    "customScheduleLabel": "Jadwal kustom",
    "customPlaceholder": "0 9 * * 1-5 atau daily 08:00",
    "customHint": "Ekspresi cron, interval (30m, every 2h) atau daily HH:MM.",
    "optional": "Opsional",
    "promptRequired": "Prompt wajib diisi.",
    "promptScheduleRequired": "Prompt dan jadwal wajib diisi.",
    "scheduleRequired": "Jadwal wajib diisi.",
    "saveChanges": "Simpan perubahan",
    "createAction": "Buat jadwal",
    "tabs": {
      "jobs": "Jadwal",
      "blueprints": "Templat"
    },
    "blueprints": {
      "tab": "Templat",
      "emptyTitle": "Belum ada templat",
      "emptyDesc": "Neovarch core belum punya templat otomasi.",
      "loading": "Memuat templat…",
      "failedLoad": "Gagal memuat templat"
    }
  },
  "artifacts": {
    "search": "Cari artefak…",
    "refresh": "Muat ulang artefak",
    "refreshing": "Memuat ulang artefak",
    "indexing": "Mengindeks artefak sesi terbaru",
    "tabAll": "Semua",
    "tabImages": "Gambar",
    "tabFiles": "File",
    "tabLinks": "Tautan",
    "noArtifactsTitle": "Belum ada artefak",
    "noArtifactsDesc": "Gambar dan file yang dibuat agen akan muncul di sini.",
    "failedLoad": "Gagal memuat artefak",
    "openFailed": "Gagal membuka",
    "itemsImage": "gambar",
    "itemsLink": "tautan",
    "itemsFile": "file",
    "itemsGeneric": "item",
    "colTitleLink": "Judul tautan",
    "colTitleFile": "Nama",
    "colTitleDefault": "Judul / nama",
    "colLocationFile": "Lokasi",
    "colLocationDefault": "Lokasi",
    "colSession": "Sesi",
    "kindImage": "gambar",
    "kindFile": "file",
    "kindLink": "tautan",
    "chat": "Obrolan",
    "copyUrl": "Salin URL",
    "copyPath": "Salin path"
  },
  "composer": {
    "message": "Pesan",
    "followUpPlaceholders": {
      "0": "Kirim lanjutan",
      "1": "Tambah konteks",
      "2": "Perjelas permintaan",
      "3": "Lalu apa?",
      "4": "Lanjutkan",
      "5": "Kembangkan lagi",
      "6": "Ubah atau lanjutkan"
    },
    "startVoice": "Mulai percakapan suara",
    "openDirective": "Buka",
    "queueMessage": "Antrekan pesan",
    "steer": "Arahkan jalan yang sedang berlangsung",
    "stop": "Berhenti",
    "send": "Kirim",
    "speaking": "Berbicara",
    "transcribing": "Mentranskripsi",
    "thinking": "Berpikir",
    "muted": "Dibisukan",
    "listening": "Mendengarkan",
    "lookupLoading": "Mencari…",
    "lookupNoMatches": "Tidak ada yang cocok.",
    "lookupTry": "Coba",
    "lookupOr": "atau",
    "commonCommands": "Perintah umum",
    "hotkeys": "Pintasan",
    "helpFooter": "membuka panel lengkap · backspace menutup",
    "commandDescs": {
      "/help": "Tampilkan perintah garis miring",
      "/clear": "mulai sesi baru",
      "/resume": "Lanjutkan sesi tersimpan",
      "/new": "Mulai obrolan baru",
      "/title": "Ganti nama sesi ini",
      "/stop": "Hentikan giliran yang sedang berjalan",
      "/status": "Tampilkan status sesi",
      "/model": "Ganti model untuk sesi ini",
      "/quit": "keluar dari neovarch",
      "/version": "Tampilkan versi Neovarch Agent",
      "/plan": "Tulis rencana implementasi markdown ke .neovarch/plans/ tanpa menjalankan apa pun",
      "/retry": "Kirim ulang pesan terakhir",
      "/copy": "salin pilihan atau balasan terakhir",
      "/subscription": "Lihat paket langganan di browser",
      "/topup": "Lihat saldo dan kelola tagihan"
    },
    "hotkeyDescs": {
      "composer": {
        "mention": "rujuk file, folder, URL, git",
        "slash": "palet perintah garis miring",
        "help": "bantuan singkat ini (hapus untuk menutup)",
        "sendNewline": "kirim · Shift+Enter untuk baris baru",
        "sendQueued": "kirim giliran antre berikutnya",
        "cancel": "tutup popover · batalkan jalan",
        "history": "ganti popover / riwayat"
      },
      "keybinds": {
        "openPanel": "semua pintasan keyboard"
      }
    },
    "attachUrlTitle": "Lampirkan URL",
    "attachUrlDesc": "Neovarch akan mengambil halaman itu sebagai konteks giliran ini.",
    "urlPlaceholder": "https://contoh.com/artikel",
    "urlHintPre": "Tulis URL lengkap, mis. ",
    "attach": "Lampirkan",
    "attachmentOnly": "Hanya lampiran",
    "emptyTurn": "Giliran kosong",
    "hiddenQueued": "Catatan",
    "editingInComposer": "Sedang diedit di kolom ketik",
    "restoredDraftNotice": "Pesan yang belum terkirim dipulihkan",
    "restoredDraftUndo": "Urungkan",
    "queueEdit": "Ubah",
    "queueExpand": "Bentangkan",
    "queueCollapse": "Ciutkan",
    "queueSendNext": "Berikutnya",
    "queueSend": "Kirim",
    "queueDelete": "Hapus",
    "queueResume": "Lanjutkan",
    "previewUnavailable": "Pratinjau tidak tersedia",
    "attachLabel": "Lampirkan",
    "files": "File…",
    "folder": "Folder…",
    "images": "Gambar…",
    "pasteImage": "Tempel gambar",
    "url": "URL…",
    "promptSnippets": "Cuplikan prompt…",
    "tipPre": "Tips: ketik ",
    "tipPost": " untuk merujuk file.",
    "snippetsTitle": "Cuplikan prompt",
    "snippetsDesc": "Pilih prompt awal untuk dimasukkan ke kolom ketik.",
    "dropFiles": "Lepas file untuk melampirkan",
    "dropSession": "Lepas untuk menautkan obrolan ini",
    "cronSuggestions": {
      "label": "Jadwalkan ini",
      "prefix": "Jadikan ini tugas terjadwal:",
      "done": "Ditandai untuk dijadwalkan"
    },
    "snippets": {
      "codeReview": {
        "label": "Tinjau kode",
        "description": "Periksa perubahan ini untuk regresi, kasus tepi, dan tes yang kurang.",
        "text": "Tolong tinjau ini untuk bug, regresi, dan tes yang kurang."
      },
      "implementationPlan": {
        "label": "Rencana implementasi",
        "description": "Susun pendekatan sebelum mengubah kode.",
        "text": "Tolong buat rencana implementasi singkat sebelum mengubah kode."
      },
      "explainThis": {
        "label": "Jelaskan ini",
        "description": "Jelaskan cara kerja kode ini dan file pentingnya.",
        "text": "Tolong jelaskan cara kerja ini dan tunjukkan file-file pentingnya."
      }
    }
  },
  "fileMenu": {
    "revealFileManager": "Buka folder berisi",
    "revealInSidebar": "Tampilkan di pohon file",
    "copyPath": "Salin path",
    "copyRelativePath": "Salin path relatif",
    "download": "Unduh",
    "downloadSaved": "Tersimpan",
    "downloadFailed": "Gagal mengunduh",
    "rename": "Ganti nama…",
    "delete": "Hapus",
    "renameTitle": "Ganti nama",
    "renameLabel": "Nama baru",
    "deleteBody": "File dipindah ke Tempat Sampah — bisa dipulihkan dari sana.",
    "pathCopied": "Path tersalin"
  },
  "titlebar": {
    "hideSidebar": "Sembunyikan panel samping",
    "showSidebar": "Tampilkan panel samping",
    "search": "Cari",
    "searchTitle": "Cari sesi, halaman, dan aksi",
    "hideRightSidebar": "Sembunyikan panel kanan",
    "showRightSidebar": "Tampilkan panel kanan",
    "openSettings": "Buka pengaturan",
    "layoutEditor": "Editor tata letak"
  },
  "language": {
    "label": "Bahasa",
    "description": "Pilih bahasa antarmuka desktop.",
    "saving": "Menyimpan bahasa…",
    "saveError": "Gagal mengganti bahasa",
    "switchTo": "Ganti bahasa",
    "searchPlaceholder": "Cari bahasa…",
    "noResults": "Bahasa tidak ditemukan"
  },
  "skills": {
    "tabSkills": "Skill",
    "tabToolsets": "Alat",
    "configuringProfile": "Mengatur:",
    "all": "Semua",
    "searchSkills": "Cari skill…",
    "searchToolsets": "Cari alat…",
    "refresh": "Muat ulang skill",
    "refreshing": "Memuat ulang skill",
    "loading": "Memuat kemampuan…",
    "noSkillsTitle": "Belum ada skill",
    "noSkillsDesc": "Taruh folder berisi SKILL.md di ~/.neovarch/skills, lalu muat ulang.",
    "noToolsetsTitle": "Alat tidak ditemukan",
    "noToolsetsDesc": "Coba kata kunci yang lebih umum.",
    "noDescription": "Tanpa deskripsi.",
    "configured": "Siap",
    "needsKeys": "Butuh kunci",
    "skillsLoadFailed": "Gagal memuat skill",
    "toolsetsRefreshFailed": "Gagal memuat ulang alat",
    "skillEnabled": "Skill diaktifkan",
    "skillDisabled": "Skill dinonaktifkan",
    "toolsetEnabled": "Alat diaktifkan",
    "toolsetDisabled": "Alat dinonaktifkan",
    "sortMostUsed": "Paling sering",
    "sortAlpha": "A–Z",
    "enableAll": "Aktifkan semua",
    "disableAll": "Nonaktifkan semua",
    "disableUnused": "Nonaktifkan yang tak dipakai",
    "bulkNoChange": "Tidak ada yang berubah.",
    "changesApplyNewSessions": "Perubahan berlaku untuk sesi baru.",
    "skillUpdated": "Skill diperbarui",
    "edit": "Ubah",
    "archive": "Arsipkan",
    "skillArchivedTitle": "Skill diarsipkan",
    "skillArchivedMessage": "Bisa dipulihkan dari folder skill.",
    "tabPlugins": "Plugin",
    "officialCatalog": "Tersedia untuk dipasang",
    "officialPill": "Resmi",
    "plugins": {
      "deepLinkCatalogUnavailable": "Katalog plugin tidak bisa dimuat. Periksa koneksi dan buka tautannya lagi."
    }
  },
  "sidebar": {
    "filter": {
      "grouping": "Pengelompokan",
      "ordering": "Urutan",
      "show": "Tampilkan",
      "filters": "Filter",
      "status": "Status",
      "project": "Proyek",
      "archived": "Diarsipkan",
      "resetToDefaults": "Kembalikan bawaan",
      "expandAll": "Bentangkan semua",
      "collapseAll": "Ciutkan semua",
      "updated": "Diperbarui",
      "created": "Dibuat",
      "tokens": "Token",
      "cost": "Biaya",
      "manual": "Manual",
      "preview": "Pratinjau",
      "needsInput": "Butuh jawaban",
      "working": "Bekerja",
      "unread": "Belum dibaca",
      "draft": "Draf",
      "idle": "Santai",
      "open": "Terbuka",
      "closed": "Ditutup"
    },
    "nav": {
      "new-session": "Sesi baru",
      "capabilities": "Skill & alat",
      "messaging": "Pesan",
      "artifacts": "Artefak",
      "cron": "Jadwal"
    },
    "searchAria": "Cari sesi",
    "searchPlaceholder": "Cari sesi…",
    "clearSearch": "Bersihkan pencarian",
    "results": "Hasil",
    "pinned": "Disematkan",
    "sessions": "Sesi",
    "terminal": "Terminal",
    "files": "File",
    "review": "Tinjauan",
    "logs": "Log",
    "cronJobs": "Jadwal",
    "showProjects": "Tampilkan proyek",
    "showSessions": "Tampilkan sesi",
    "groupTitleGrouped": "Pisahkan sesi",
    "groupTitleUngrouped": "Kelompokkan per folder kerja",
    "allPinned": "Semua di sini disematkan. Lepas sematan agar muncul di terbaru.",
    "shiftClickHint": "Shift-klik obrolan untuk menyematkan",
    "noWorkspace": "Tanpa folder kerja",
    "projectEmpty": "Belum ada sesi",
    "projectLoadFailed": "Gagal memuat sesi",
    "noSessions": "Belum ada sesi",
    "noFilterMatches": "Tidak ada sesi yang cocok dengan filter",
    "projects": {
      "showAllSessions": "Tampilkan semua sesi",
      "sectionLabel": "Proyek",
      "home": "Beranda",
      "newButton": "Proyek baru",
      "createTitle": "Proyek baru",
      "createDesc": "Beri nama dan tambahkan satu atau lebih folder.",
      "renameTitle": "Ganti nama proyek",
      "addFolderTitle": "Tambah folder",
      "namePlaceholder": "mis. Skripsi",
      "foldersLabel": "Folder",
      "noFolders": "Belum ada folder.",
      "addFolder": "Tambah folder",
      "removeFolder": "Lepas",
      "create": "Buat",
      "menu": "Aksi",
      "menuRename": "Ganti nama…",
      "menuAppearance": "Tampilan",
      "noColor": "Tanpa warna",
      "menuAddFolder": "Tambah folder",
      "menuSetActive": "Jadikan aktif",
      "menuDelete": "Hapus",
      "reveal": "Buka foldernya",
      "copyPath": "Salin path",
      "back": "Semua proyek"
    },
    "loading": "Memuat…",
    "loadMore": "Muat lebih banyak",
    "row": {
      "pin": "Sematkan",
      "unpin": "Lepas sematan",
      "markUnread": "Tandai belum dibaca",
      "markRead": "Tandai sudah dibaca",
      "copyId": "Salin ID",
      "export": "Ekspor",
      "branchFrom": "Cabangkan",
      "rename": "Ganti nama…",
      "archive": "Arsipkan",
      "unarchive": "Keluarkan dari arsip",
      "newWindow": "Jendela baru",
      "openInTerminal": "Buka di terminal",
      "openInNewTab": "Buka di tab baru",
      "openInSplit": "Buka berdampingan",
      "copyIdFailed": "Gagal menyalin ID sesi",
      "sessionActions": "Aksi sesi",
      "sessionRunning": "Sesi berjalan",
      "needsInput": "Butuh jawabanmu",
      "waitingForAnswer": "Menunggu jawabanmu",
      "finishedUnread": "Selesai — belum dibaca",
      "backgroundRunning": "Tugas latar berjalan",
      "draftSession": "Draf — belum ada yang dikirim",
      "renamed": "Nama diganti",
      "renameFailed": "Gagal mengganti nama",
      "renameTitle": "Ganti nama sesi",
      "renameDesc": "Kosongkan untuk menghapus nama.",
      "untitledPlaceholder": "Sesi tanpa judul",
      "deleteTitle": "Hapus sesi?",
      "deleting": "Menghapus…",
      "deleted": "Sesi dihapus",
      "todoProgress": "Tugas selesai",
      "ageNow": "baru",
      "ageDay": "h",
      "ageHour": "j",
      "ageMin": "m"
    },
    "dateDivider": {
      "today": "Tadi",
      "yesterday": "Kemarin",
      "thisWeek": "Minggu ini",
      "lastWeek": "Minggu lalu",
      "thisMonth": "Bulan ini"
    },
    "statusDivider": {
      "working": "Bekerja",
      "done": "Selesai"
    },
    "markAllRead": "Tandai semua dibaca"
  },
  "shell": {
    "windowControls": "Kontrol jendela",
    "paneControls": "Kontrol panel",
    "appControls": "Kontrol aplikasi",
    "modelMenu": {
      "search": "Cari model",
      "noModels": "Model tidak ditemukan",
      "editModels": "Atur model…",
      "followDefault": "Pakai bawaan Pengaturan",
      "refreshModels": "Muat ulang model",
      "favorites": "Favorit",
      "addFavorite": "Tambah ke favorit",
      "removeFavorite": "Hapus dari favorit",
      "fast": "Cepat",
      "free": "gratis"
    },
    "modelOptions": {
      "noOptions": "Model ini tidak punya opsi",
      "options": "Opsi",
      "thinking": "Berpikir",
      "fast": "Cepat",
      "effort": "Usaha",
      "minimal": "Minimal",
      "low": "Rendah",
      "medium": "Sedang",
      "high": "Tinggi",
      "xhigh": "Sangat tinggi",
      "max": "Maks",
      "updateFailed": "Gagal mengubah opsi model"
    },
    "gatewayMenu": {
      "gateway": "Core",
      "connected": "Terhubung",
      "connecting": "Menghubungkan",
      "offline": "Luring",
      "inferenceReady": "Model siap",
      "inferenceNotReady": "Model belum siap",
      "checkingInference": "Memeriksa model",
      "disconnected": "Terputus",
      "reconnectGateway": "Sambungkan ulang core",
      "recentActivity": "Aktivitas terbaru",
      "viewAllLogs": "Lihat semua log →"
    },
    "approvalMode": {
      "title": "Mode persetujuan",
      "manual": "Manual",
      "manualDescription": "Tanya sebelum aksi yang butuh persetujuan",
      "smart": "Pintar",
      "smartDescription": "Nilai aksi otomatis dan tanya bila perlu",
      "off": "Mati",
      "offDescription": "Jalan tanpa minta persetujuan"
    },
    "statusbar": {
      "unknown": "tidak diketahui",
      "restart": "mulai ulang",
      "update": "pembaruan",
      "updateInProgress": "Sedang memperbarui",
      "showTerminal": "Tampilkan terminal",
      "hideTerminal": "Sembunyikan terminal"
    }
  },
  "zones": {
    "newSessionTab": "Tab sesi baru"
  },
  "keybinds": {
    "title": "Pintasan keyboard",
    "search": "Cari pintasan…",
    "rebind": "Ubah tombol",
    "reset": "Kembalikan bawaan",
    "resetAll": "Kembalikan semua",
    "clear": "Kosongkan",
    "pressKey": "Tekan tombol…",
    "set": "atur",
    "categories": {
      "composer": "Kolom ketik",
      "profiles": "Profil",
      "session": "Sesi",
      "navigation": "Navigasi",
      "view": "Tampilan"
    }
  },
  "commandCenter": {
    "close": "Tutup pusat perintah",
    "paletteTitle": "Palet perintah",
    "back": "Kembali",
    "searchPlaceholder": "Cari sesi, halaman, dan aksi",
    "goTo": "Buka",
    "goToSession": "Buka sesi",
    "branches": "Cabang",
    "projects": "Proyek",
    "openFolder": "Buka folder sebagai proyek…",
    "commands": "Perintah",
    "commandCenter": "Pusat perintah",
    "appearance": "Tampilan",
    "settings": "Pengaturan",
    "changeTheme": "Ganti tema",
    "changeColorMode": "Ganti mode warna…",
    "settingsFields": "Kolom pengaturan",
    "archivedChats": "Obrolan diarsipkan",
    "sections": {
      "maintenance": "Perawatan",
      "sessions": "Sesi",
      "system": "Sistem",
      "usage": "Pemakaian"
    },
    "providerNavigate": "Navigasi",
    "providerSessions": "Sesi",
    "refresh": "Muat ulang",
    "refreshing": "Memuat ulang…",
    "noResults": "Tidak ada hasil yang cocok.",
    "pinSession": "Sematkan sesi",
    "unpinSession": "Lepas sematan sesi",
    "exportSession": "Ekspor sesi",
    "deleteSession": "Hapus sesi",
    "noSessions": "Belum ada sesi.",
    "reloadWindow": "Muat ulang jendela",
    "updateHermes": "Perbarui Neovarch",
    "actionRunning": "berjalan",
    "actionDone": "selesai",
    "actionFailed": "gagal",
    "loadingStatus": "Memuat status…",
    "recentLogs": "Log terbaru",
    "noLogs": "Belum ada log.",
    "statSessions": "Sesi",
    "statApiCalls": "Panggilan API",
    "statTokens": "Token masuk/keluar",
    "statCost": "Perkiraan biaya",
    "loadingUsage": "Memuat pemakaian…",
    "retry": "Coba lagi",
    "dailyTokens": "Token harian",
    "input": "masuk",
    "output": "keluar",
    "noDailyActivity": "Belum ada aktivitas harian.",
    "topModels": "Model teratas",
    "noModelUsage": "Belum ada pemakaian model.",
    "topSkills": "Skill teratas",
    "noSkillActivity": "Belum ada aktivitas skill.",
    "logFile": "File log",
    "logLevel": "Level",
    "logSearchPlaceholder": "Cari baris log…",
    "maintenance": {
      "runOps": "Diagnostik"
    }
  },
  "onboarding": {
    "headerTitle": "Mari siapkan Neovarch Agent",
    "headerDesc": "Hubungkan penyedia model untuk mulai mengobrol. Kebanyakan cukup satu klik.",
    "preparingInstall": "Neovarch sedang menyelesaikan pemasangan. Biasanya kurang dari semenit pada jalan pertama.",
    "starting": "Memulai Neovarch…",
    "setupSlowTitle": "Penyiapan lebih lama dari biasanya.",
    "setupSlowBody": "Neovarch masih dimulai di latar belakang.",
    "continueWithoutSetup": "Lanjut tanpa penyiapan",
    "lookingUpProviders": "Mencari penyedia…",
    "collapse": "Ciutkan",
    "otherProviders": "Penyedia lain",
    "haveApiKey": "Saya punya API key",
    "chooseLater": "Pilih penyedia nanti",
    "recommended": "Disarankan",
    "connected": "Terhubung",
    "featuredPitch": "Satu langganan, 300+ model terdepan — cara yang disarankan untuk menjalankan Neovarch",
    "fireworksPitch": "API model langsung — model terdepan yang dihosting Fireworks",
    "localModelsTitle": "Jalankan model lokal",
    "localModelsPitch": "Tanpa akun — unduh model dan jalankan di komputer ini",
    "openRouterPitch": "Satu key, ratusan model — pilihan awal yang aman",
    "apiKeyOptions": {
      "fireworks": {
        "short": "API model langsung",
        "description": "Akses langsung ke model yang dihosting Fireworks AI."
      },
      "openrouter": {
        "short": "satu key, banyak model",
        "description": "Ratusan model di balik satu key. Pilihan awal yang baik untuk pemasangan baru."
      },
      "openai": {
        "short": "model kelas GPT",
        "description": "Akses langsung ke model OpenAI."
      },
      "gemini": {
        "short": "model Gemini",
        "description": "Akses langsung ke model Google Gemini."
      },
      "xai": {
        "short": "model Grok",
        "description": "Akses langsung ke model xAI Grok."
      },
      "local": {
        "short": "dihosting sendiri",
        "description": "Arahkan Neovarch ke endpoint lokal atau yang Anda hosting sendiri yang kompatibel OpenAI (vLLM, llama.cpp, Ollama, dll.)."
      }
    },
    "backToSignIn": "Kembali ke masuk",
    "getKey": "Ambil key",
    "replaceCurrent": "Ganti nilai sekarang",
    "pasteApiKey": "Tempel API key",
    "localApiKeyPlaceholder": "API key (opsional — hanya bila endpoint memintanya)",
    "localModelNamePlaceholder": "Nama model (mis. qwen3-8b)",
    "couldNotSave": "Kredensial tidak bisa disimpan.",
    "connecting": "Menghubungkan",
    "update": "Perbarui",
    "flowSubtitles": {
      "pkce": "Membuka browser untuk masuk, lalu lanjut di sini",
      "device_code": "Membuka halaman verifikasi di browser — Neovarch terhubung otomatis",
      "external": "Masuk sekali di terminal, lalu kembali untuk mengobrol"
    },
    "signInFailed": "Gagal masuk. Coba lagi.",
    "signInExpired": "Halaman masuk kedaluwarsa sebelum selesai. Coba lagi dan selesaikan langkah di browser dalam beberapa menit, atau pakai API key.",
    "tryAgain": "Coba lagi",
    "useApiKeyInstead": "Pakai API key",
    "errorDetails": "Detail",
    "pickDifferentProvider": "Pilih penyedia lain",
    "authorizeThere": "Izinkan Neovarch di sana.",
    "copyAuthCode": "Salin kode otorisasi lalu tempel di bawah.",
    "pasteAuthCode": "Tempel kode otorisasi",
    "reopenAuthPage": "Buka lagi halaman otorisasi",
    "waitingAuthorize": "Menunggu Anda memberi izin…",
    "signedIn": "Saya sudah masuk",
    "reopenVerification": "Buka lagi halaman verifikasi",
    "copy": "Salin",
    "defaultModel": "Model bawaan",
    "freeTier": "Paket gratis",
    "pro": "Pro",
    "free": "Gratis",
    "change": "Ubah",
    "startChatting": "Mulai"
  },
  "assistant": {
    "thread": {
      "loadingSession": "Memuat sesi",
      "showEarlier": "Tampilkan pesan sebelumnya",
      "loadingResponse": "Neovarch sedang memuat jawaban",
      "processingPrompt": "Memproses prompt",
      "thinking": "Berpikir",
      "thought": "Berpikir",
      "thoughtBriefly": "Berpikir sebentar",
      "copy": "Salin",
      "refresh": "Ulangi",
      "moreActions": "Aksi lain",
      "branchNewChat": "Cabangkan ke obrolan baru",
      "react": "Beri reaksi",
      "dismissError": "Tutup galat",
      "responseStopped": "Jawaban dihentikan",
      "errorLayers": {
        "auth": "Masalah masuk",
        "billing": "Kredit habis",
        "disk": "Disk penuh",
        "endpoint": "Server model tidak terjangkau",
        "gateway": "Neovarch mengalami masalah",
        "generic": "Neovarch tidak bisa menyelesaikan jawaban ini",
        "provider": "Layanan AI mengembalikan galat",
        "runtime": "Neovarch mengalami masalah",
        "streaming": "Jawaban terputus"
      },
      "errorLayerBodies": {
        "auth": "Layanan AI menolak kredensial Anda. Periksa kredensial penyedia ini, lalu kirim lagi pesan Anda.",
        "billing": "Kredit akun Anda di penyedia ini habis. Isi ulang atau ganti penyedia, lalu kirim lagi.",
        "disk": "Disk penuh sehingga Neovarch tidak bisa menyimpan percakapan ini. Kosongkan ruang, lalu coba lagi.",
        "endpoint": "Neovarch tidak bisa menjangkau server model kustom Anda. Pastikan server berjalan, lalu kirim lagi.",
        "gateway": "Neovarch mengalami masalah internal saat memulai jawaban. Kirim lagi; bila terus terjadi, kirim diagnostik.",
        "generic": "Ada yang salah saat Neovarch menjawab. Coba lagi, atau salin detailnya bila terus terjadi.",
        "provider": "Layanan AI tidak bisa menyelesaikan permintaan ini. Coba lagi sebentar lagi atau ganti penyedia.",
        "runtime": "Neovarch mengalami masalah internal saat memulai jawaban. Kirim lagi; bila terus terjadi, kirim diagnostik.",
        "streaming": "Koneksi terputus sebelum jawaban selesai. Coba lagi untuk mengirim ulang."
      },
      "errorCodes": {
        "billing": {
          "title": "Kredit habis"
        },
        "rate_limit": {
          "title": "Layanan AI sedang sibuk"
        },
        "upstream_rate_limit": {
          "title": "Layanan AI sedang sibuk"
        },
        "overloaded": {
          "title": "Layanan AI kelebihan beban"
        },
        "server_error": {
          "title": "Layanan AI mengalami masalah"
        },
        "timeout": {
          "title": "Layanan AI tidak terjangkau"
        },
        "stream_drop": {
          "title": "Jawaban terputus",
          "body": "Koneksi terputus sebelum jawaban selesai. Coba lagi untuk mengirim ulang."
        },
        "no_reply": {
          "title": "Jawaban tidak selesai",
          "body": "Neovarch mengakhiri giliran ini tanpa jawaban. Coba lagi untuk mengirim ulang."
        },
        "upstream_blocked": {
          "title": "Permintaan diblokir firewall"
        },
        "ssl_cert_verification": {
          "title": "Koneksi aman gagal"
        },
        "context_overflow": {
          "title": "Percakapan ini terlalu panjang",
          "body": "Percakapan tidak lagi muat di model. Padatkan atau mulai obrolan baru, lalu kirim lagi."
        },
        "payload_too_large": {
          "title": "Pesan ini terlalu besar",
          "body": "Permintaan terlalu besar untuk model. Padatkan percakapan atau mulai obrolan baru, lalu kirim lagi."
        },
        "model_not_found": {
          "title": "Model ini tidak tersedia"
        },
        "provider_policy_blocked": {
          "title": "Model ini diblokir oleh pengaturan akun Anda"
        },
        "content_policy_blocked": {
          "title": "Layanan AI menolak permintaan ini"
        },
        "format_error": {
          "title": "Layanan AI menolak format permintaan"
        },
        "truncated": {
          "title": "Jawaban terpotong",
          "body": "Model berhenti sebelum selesai. Coba lagi untuk jawaban lengkap."
        },
        "invalid_response": {
          "title": "Layanan AI mengirim jawaban yang tidak terbaca"
        },
        "empty_response": {
          "title": "Layanan AI mengirim jawaban kosong"
        },
        "loop_error": {
          "title": "Neovarch terjebak dalam putaran",
          "body": "Jawaban terus mengulang langkah yang sama, jadi Neovarch menghentikannya. Coba lagi, atau mulai obrolan baru bila terulang."
        },
        "SESSION_NOT_OWNED": {
          "title": "Obrolan ini terbuka di tempat lain",
          "body": "Obrolan ini sedang terbuka di jendela atau terminal Neovarch lain. Tutup di sana lalu kirim lagi, atau mulai obrolan baru di sini."
        },
        "disk_full": {
          "title": "Disk penuh",
          "body": "Disk penuh sehingga Neovarch tidak bisa menyimpan percakapan ini. Kosongkan ruang, lalu coba lagi."
        },
        "free_tier_disabled": {
          "title": "Pemakaian tanpa masuk sedang dimatikan",
          "body": "Masuk dengan akun penyedia untuk lanjut mengobrol."
        },
        "free_tier_rate_limited": {
          "title": "Jatah obrolan tanpa masuk sudah habis",
          "body": "Jatah segera diisi ulang. Masuk dengan akun untuk jatah lebih besar."
        },
        "free_tier_at_capacity": {
          "title": "Obrolan tanpa masuk sedang sangat ramai",
          "body": "Masuk untuk melewati antrean, atau coba lagi sebentar lagi."
        },
        "free_tier_model_not_free": {
          "title": "Model itu tidak tersedia tanpa masuk",
          "body": "Neovarch memakai model gratis untuk sementara. Masuk untuk model lain."
        },
        "free_tier_route": {
          "title": "Neovarch tidak bisa menjangkau model gratis di rute ini",
          "body": "Masuk dengan akun, atau periksa pengaturan alamat inferensi."
        },
        "free_tier_outage": {
          "title": "Model gratis sedang bermasalah",
          "body": "Coba kirim lagi pesan Anda dalam semenit."
        },
        "free_tier_refused": {
          "title": "Neovarch tidak bisa mengirim itu tanpa masuk",
          "body": "Masuk dengan akun penyedia."
        }
      },
      "errorDetails": "Detail",
      "errorGenericProvider": "Layanan AI",
      "errorToastTitle": "Neovarch tidak bisa menyelesaikan jawaban",
      "errorRetry": "Coba lagi",
      "errorRetryScheduledCancel": "Batal",
      "errorStartNewSession": "Mulai sesi baru",
      "errorSwitchProvider": "Ganti penyedia",
      "errorChooseModel": "Pilih model",
      "errorCompressConversation": "Padatkan percakapan",
      "errorCompressFailed": "Percakapan tidak bisa dipadatkan",
      "errorOpenHermesFolder": "Buka folder Neovarch",
      "errorOpenHermesFolderFailed": "Folder Neovarch tidak bisa dibuka",
      "errorUpdateApiKey": "Perbarui API key",
      "errorSignInFreeTier": "Masuk dengan akun",
      "errorOpenLogs": "Buka log",
      "errorOpenLogsFailed": "Folder log tidak bisa dibuka",
      "errorOpenDesktopLogs": "Buka log desktop",
      "errorCopyDiagnostics": "Salin detail galat",
      "errorSendDiagnostics": "Kirim diagnostik",
      "reviewChanges": "Tinjau",
      "readAloudFailed": "Gagal membacakan",
      "preparingAudio": "Menyiapkan audio…",
      "stopReading": "Berhenti membaca",
      "readAloud": "Bacakan",
      "copyFullResponse": "Salin jawaban lengkap",
      "readAloudFullResponseHint": "Shift-klik: bacakan jawaban lengkap",
      "editMessage": "Ubah pesan",
      "expandMessage": "Bentangkan pesan",
      "scrollToBottom": "Gulir ke bawah",
      "stop": "Berhenti",
      "restorePrevious": "Pulihkan checkpoint sebelumnya",
      "restoreCheckpoint": "Pulihkan checkpoint",
      "restoreFromHere": "Pulihkan checkpoint — jalankan ulang dari prompt ini",
      "restoreTitle": "Pulihkan ke checkpoint ini?",
      "restoreBody": "Semua setelah prompt ini dihapus dari percakapan, dan prompt dijalankan lagi dari sini.",
      "restoreConfirm": "Pulihkan & jalankan ulang",
      "restoreNext": "Pulihkan checkpoint berikutnya",
      "goForward": "Maju",
      "sendEdited": "Kirim pesan yang diubah",
      "attachingFile": "Melampirkan…"
    },
    "approval": {
      "gatewayDisconnected": "Neovarch sedang offline. Perintah masih menunggu jawaban Anda (sampai batas waktu persetujuan). Sambungkan lagi, lalu kirim ulang.",
      "sendFailed": "Jawaban Anda tidak terkirim",
      "reconnect": "Sambungkan lagi",
      "timedOutSystemLine": "Persetujuan kedaluwarsa — perintah tidak dijalankan. Minta Neovarch mencoba lagi, atau naikkan batasnya di Pengaturan → Keamanan → Batas waktu persetujuan.",
      "openSafetySettings": "Buka pengaturan Keamanan",
      "run": "Jalankan",
      "command": "Perintah",
      "commandDetails": "Detail perintah",
      "moreOptions": "Opsi persetujuan lain",
      "allowSession": "Izinkan di sesi ini",
      "alwaysAllowMenu": "Selalu izinkan…",
      "jumpToApproval": "Perlu persetujuan",
      "reject": "Tolak",
      "alwaysTitle": "Selalu izinkan perintah ini?",
      "alwaysAllow": "Selalu izinkan"
    },
    "clarify": {
      "notReady": "Pertanyaan belum siap",
      "gatewayDisconnected": "Neovarch sedang offline. Sambungkan lagi, lalu kirim ulang.",
      "sendFailed": "Jawaban tidak terkirim",
      "loadingQuestion": "Memuat pertanyaan…",
      "other": "Lainnya (ketik jawaban)",
      "placeholder": "Ketik jawaban…",
      "skip": "Lewati",
      "skipped": "Dilewati",
      "noAnswer": "Tanpa jawaban",
      "confirmAndContinueLabel": "Konfirmasi dan lanjut",
      "singleSelectHint": "Pilih satu",
      "multiSelectHint": "Pilih semua yang sesuai",
      "oneQuestion": "1 pertanyaan",
      "notDelivered": "Pertanyaan ini tidak sampai ke aplikasi, jadi tidak bisa dijawab di sini. Tekan Berhenti untuk mengakhiri giliran, lalu balas di obrolan."
    },
    "setupChoose": {
      "kinds": {
        "accent": "Warna aksen",
        "connectors": "Aplikasi",
        "layout": "Tata letak",
        "plugins": "Plugin",
        "theme": "Tampilan"
      },
      "loading": "Memuat pilihan…",
      "unavailable": "Daftar ini sedang tidak tersedia. Balas di obrolan saja.",
      "findApp": "Cari aplikasi",
      "customColor": "Warna kustom",
      "plugin": "Plugin",
      "startsLater": "Kami siapkan ini saat Anda mulai."
    },
    "startChat": {
      "startingUntitled": "Memulai obrolan…",
      "untitled": "Obrolan baru",
      "notStarted": "Obrolan itu tidak bisa dimulai.",
      "retry": "Coba lagi",
      "open": "Buka",
      "openFailed": "Obrolan tidak bisa dibuka"
    },
    "catalogInstall": {
      "preparing": "Menyiapkan pemasangan…",
      "install": "Pasang",
      "advanced": "Lanjutan",
      "skip": "Lewati",
      "installing": "Memasang…",
      "installed": "Terpasang",
      "notInstalled": "Belum terpasang",
      "failed": "Gagal",
      "showNames": "tampilkan nama",
      "hideNames": "sembunyikan nama",
      "kind": {
        "plugin": "plugin",
        "skill": "skill"
      },
      "tier": {
        "official": "resmi",
        "community": "komunitas"
      },
      "sendFailed": "Jawaban tidak terkirim. Coba lagi.",
      "commitLabel": "Commit",
      "subdirLabel": "Folder",
      "securityHeading": "Keamanan",
      "scan": {
        "passed": "Pemindaian lolos",
        "warnings": "Pemindaian menemukan peringatan",
        "failed": "Pemindaian gagal"
      },
      "requirementsLabel": "Membutuhkan",
      "credentialsHeading": "Kredensial",
      "phase": {
        "downloading": "Mengunduh…",
        "python_packages": "Memasang paket Python…",
        "loading_tools": "Memuat tool…"
      },
      "notEnabled": "Terpasang tapi belum dinyalakan",
      "alreadyInstalled": "Sudah terpasang; dibiarkan apa adanya"
    },
    "mcpSetup": {
      "installTitle": "Tambah server MCP",
      "enableTitle": "Aktifkan server MCP",
      "authorizeTitle": "Izinkan server MCP",
      "installAction": "Pasang",
      "enableAction": "Aktifkan",
      "authorizeAction": "Izinkan",
      "envRequired": "Isi dulu kredensial yang diperlukan",
      "sendFailed": "Jawaban penyiapan MCP tidak terkirim",
      "reloadFailed": "Server tersimpan, tapi memuat ulang tool MCP gagal — tool dimuat di sesi berikutnya",
      "gatewayDisconnected": "Neovarch sedang offline. Sambungkan lagi, lalu kirim ulang."
    },
    "tool": {
      "copyCode": "Salin kode",
      "renderingImage": "Menampilkan gambar",
      "copyOutput": "Salin keluaran",
      "copyCommand": "Salin perintah",
      "copyContent": "Salin isi",
      "copyUrl": "Salin URL",
      "copyResults": "Salin hasil",
      "copyQuery": "Salin kueri",
      "copyFile": "Salin file",
      "copyPath": "Salin path",
      "skillActivity": {
        "loading": "Memuat skill",
        "loaded": "Skill dimuat",
        "loadFailed": "Gagal memuat skill",
        "readingResource": "Membaca sumber skill",
        "readResource": "Sumber skill dibaca",
        "resourceFailed": "Gagal membaca sumber skill",
        "listing": "Mendaftar skill",
        "listed": "Skill didaftar",
        "listFailed": "Gagal mendaftar skill",
        "unavailable": "Hasil skill tidak tersedia"
      },
      "outputAlt": "Keluaran tool",
      "rawResponse": "Respons mentah",
      "copyActivity": "Salin aktivitas",
      "recoveredOne": "Pulih setelah 1 langkah gagal",
      "failedOne": "1 langkah gagal",
      "statusRunning": "Berjalan",
      "statusError": "Galat",
      "statusRecovered": "Pulih",
      "statusDone": "Selesai",
      "resultUnavailable": "Hasil tidak tersedia",
      "resultInterrupted": "Terhenti",
      "memoryWriteNoted": "Penulisan memori dicatat",
      "actions": {
        "read": "Dibaca",
        "reading": "Membaca",
        "opened": "Dibuka",
        "opening": "Membuka",
        "failedToOpen": "Gagal membuka",
        "searched": "Dicari",
        "searching": "Mencari",
        "ran": "Dijalankan",
        "running": "Menjalankan",
        "ranCode": "Kode dijalankan",
        "runningCode": "Menulis skrip"
      },
      "prefixes": {
        "browser": "Browser",
        "web": "Web"
      },
      "titles": {
        "browser_click": {
          "done": "Elemen halaman diklik",
          "pending": "Mengklik elemen halaman",
          "pendingAction": "Mengklik"
        },
        "browser_fill": {
          "done": "Kolom formulir diisi",
          "pending": "Mengisi kolom formulir",
          "pendingAction": "Mengisi"
        },
        "browser_navigate": {
          "done": "Halaman dibuka",
          "pending": "Membuka halaman",
          "pendingAction": "Membuka"
        },
        "browser_snapshot": {
          "done": "Cuplikan halaman diambil",
          "pending": "Mengambil cuplikan halaman",
          "pendingAction": "Mengambil"
        },
        "browser_take_screenshot": {
          "done": "Tangkapan layar diambil",
          "pending": "Mengambil tangkapan layar",
          "pendingAction": "Mengambil"
        },
        "browser_type": {
          "done": "Teks diketik di halaman",
          "pending": "Mengetik di halaman",
          "pendingAction": "Mengetik"
        },
        "clarify": {
          "done": "Mengajukan pertanyaan",
          "pending": "Mengajukan pertanyaan",
          "pendingAction": "Bertanya"
        },
        "cronjob": {
          "done": "Jadwal tugas",
          "pending": "Menjadwalkan tugas",
          "pendingAction": "Menjadwalkan"
        },
        "edit_file": {
          "done": "File diubah",
          "pending": "Mengubah file",
          "pendingAction": "Mengubah"
        },
        "execute_code": {
          "done": "Kode dijalankan",
          "pending": "Menulis skrip",
          "pendingAction": "Menulis skrip"
        },
        "image_generate": {
          "done": "Gambar dibuat",
          "pending": "Membuat gambar",
          "pendingAction": "Membuat"
        },
        "list_files": {
          "done": "File didaftar",
          "pending": "Mendaftar file",
          "pendingAction": "Mendaftar"
        },
        "memory": {
          "done": "Disimpan ke memori",
          "pending": "Menyimpan ke memori",
          "pendingAction": "Menyimpan"
        },
        "patch": {
          "done": "File ditambal",
          "pending": "Menambal file",
          "pendingAction": "Menambal"
        },
        "read_file": {
          "done": "File dibaca",
          "pending": "Membaca file",
          "pendingAction": "Membaca"
        },
        "search_files": {
          "done": "File dicari",
          "pending": "Mencari file",
          "pendingAction": "Mencari"
        },
        "session_search_recall": {
          "done": "Riwayat sesi dicari",
          "pending": "Mencari riwayat sesi",
          "pendingAction": "Mencari"
        },
        "setup_choose": {
          "done": "Mengajukan pertanyaan penyiapan",
          "pending": "Mengajukan pertanyaan penyiapan",
          "pendingAction": "Bertanya"
        },
        "start_chat": {
          "done": "Obrolan dimulai",
          "pending": "Memulai obrolan",
          "pendingAction": "Memulai"
        },
        "terminal": {
          "done": "Perintah dijalankan",
          "pending": "Menjalankan perintah",
          "pendingAction": "Menjalankan"
        },
        "todo": {
          "done": "Daftar tugas diperbarui",
          "pending": "Memperbarui daftar tugas",
          "pendingAction": "Memperbarui"
        },
        "vision_analyze": {
          "done": "Gambar dianalisis",
          "pending": "Menganalisis gambar",
          "pendingAction": "Menganalisis"
        },
        "web_extract": {
          "done": "Halaman web dibaca",
          "pending": "Membaca halaman web",
          "pendingAction": "Membaca"
        },
        "web_search": {
          "done": "Web dicari",
          "pending": "Mencari di web",
          "pendingAction": "Mencari"
        },
        "write_file": {
          "done": "File diubah",
          "pending": "Mengubah file",
          "pendingAction": "Mengubah"
        }
      }
    }
  },
  "settings": {
    "subpages": {
      "appearanceTheme": "Tema",
      "appearanceTypography": "Tipografi",
      "appearanceWindowLayout": "Jendela & tata letak",
      "appearanceChatDisplay": "Tampilan obrolan",
      "appearancePet": "Peliharaan",
      "appearanceGeneral": "Umum",
      "modelMain": "Model utama",
      "modelAuxiliary": "Model pembantu",
      "modelMoa": "Gabungan agen (MoA)",
      "modelFallbacks": "Model cadangan",
      "chatBehavior": "Perilaku",
      "chatAttachments": "Lampiran",
      "workspaceProjects": "Proyek & penemuan",
      "workspaceShell": "Lingkungan shell",
      "workspaceFiles": "File & eksekusi",
      "agentBrain": "Otak agen",
      "agentEscalation": "Naik model saat buntu",
      "safetyApprovals": "Persetujuan",
      "safetyPrivacy": "Privasi & jaringan",
      "safetyCheckpoints": "Checkpoint",
      "browserProfile": "Profil browser",
      "browserNetwork": "URL lokal & privat",
      "memoryPersistent": "Memori permanen",
      "memoryContext": "Konteks & pemadatan",
      "voiceConversation": "Percakapan suara",
      "voiceTranscription": "Suara ke teks",
      "voiceSpeech": "Teks ke suara",
      "advancedRuntime": "Batas agen",
      "advancedTools": "Akses tool",
      "advancedTerminal": "Backend terminal",
      "advancedOutput": "Batas keluaran",
      "advancedDelegation": "Subagen",
      "advancedDesktop": "Desktop & startup",
      "gatewayConnection": "Jendela ini",
      "gatewayDevices": "Koneksi tersimpan",
      "gatewayManagedUpdates": "Pembaruan jarak jauh",
      "gatewayManagedUpdatesUnavailable": "Pembaruan jarak jauh butuh versi desktop yang mendukung pembaruan SSH terkelola.",
      "gatewayManagedUpdatesEmpty": "Tambahkan koneksi SSH di Koneksi tersimpan untuk mengelola pembaruannya di sini.",
      "keyboardShortcuts": "Pintasan tombol",
      "hudGesture": "Gestur HUD",
      "screenCapture": "Tangkapan layar",
      "notificationAlerts": "Notifikasi desktop",
      "notificationSounds": "Suara",
      "archivedSessions": "Arsip & retensi",
      "defaultDirectory": "Folder proyek bawaan",
      "vaultCredentials": "Kredensial tersimpan",
      "vaultSources": "Pengelola kata sandi",
      "appUpdates": "Versi & pembaruan",
      "uninstall": "Copot pemasangan",
      "billingOverview": "Ringkasan",
      "billingPlans": "Paket"
    },
    "closeSettings": "Tutup pengaturan",
    "exportConfig": "Ekspor konfigurasi",
    "importConfig": "Impor konfigurasi",
    "resetToDefaults": "Kembalikan ke bawaan",
    "resetConfirm": "Kembalikan semua pengaturan ke bawaan Neovarch?",
    "exportFailed": "Ekspor gagal",
    "resetFailed": "Pengembalian gagal",
    "pluginPages": {
      "blurb": "Opsi yang ditambahkan plugin terpasang. Tiap plugin punya halamannya sendiri, dan sebagian menambah sub-halaman di bawahnya.",
      "empty": "Belum ada plugin yang punya pengaturan.",
      "manage": "Kelola plugin",
      "agentSettings": "Pengaturan agen",
      "missing": "Plugin itu tidak punya halaman pengaturan. Mungkin dinonaktifkan atau sudah dicopot."
    },
    "nav": {
      "providers": "Penyedia",
      "providerAccounts": "Akun",
      "providerApiKeys": "API key",
      "providerCustomEndpoints": "Endpoint kustom",
      "providerLocalModels": "Model lokal",
      "gateway": "Gateway",
      "apiKeys": "Tool & key",
      "keybinds": "Pintasan keyboard",
      "keysTools": "Tool",
      "keysSettings": "Pengaturan",
      "mcp": "MCP",
      "archivedChats": "Obrolan diarsipkan",
      "sessions": "Sesi",
      "about": "Tentang",
      "billing": "Tagihan",
      "notifications": "Notifikasi",
      "vault": "Kata sandi & login",
      "plugins": "Plugin"
    },
    "plugins": {
      "title": "Plugin desktop",
      "openFolder": "Buka folder plugin desktop",
      "rescan": "Pindai ulang",
      "reveal": "Tampilkan di pengelola file",
      "failed": "gagal",
      "kinds": {
        "bundled": "bawaan",
        "disk": "di disk",
        "runtime": "runtime"
      },
      "installModal": {
        "installFromGit": "Pasang dari Git",
        "reviewRepository": "Tinjau repositori",
        "repoPlaceholder": "https://github.com/owner/repo",
        "title": "Pasang plugin",
        "description": "Tinjau isi repositori ini sebelum memasang apa pun.",
        "repoLabel": "Repositori",
        "includesHeading": "Paket ini berisi",
        "agentLabel": "Plugin agen",
        "desktopLabel": "UI desktop",
        "profileLabel": "Pasang untuk profil",
        "reviewedHeading": "Entri katalog yang ditinjau",
        "reviewedIntro": "Entri ini ditinjau manusia pada commit yang dipatok. Anda tetap bisa memeriksa kodenya di bawah.",
        "nextChat": "tool tambahan tersedia di obrolan berikutnya",
        "missingEnvAction": "Siapkan",
        "desktopTarget": "Dipasang ke folder plugin desktop lokal aplikasi ini",
        "desktopTargetFromPackage": "Dimuat ke aplikasi ini dari paket di atas — sama untuk setiap profil",
        "desktopOnlyNote": "Paket khusus desktop tidak memasang plugin agen di backend.",
        "insecureWarning": "URL ini memakai skema tidak aman atau lokal. Utamakan https:// atau git@ untuk pemasangan serius.",
        "securityHeading": "Sebelum memasang",
        "securityIntro": "Pasang hanya dari sumber tepercaya — tinjau repositori di bawah bila ingin melihat apa yang akan ditambahkan.",
        "sourceHeading": "Kode sumber",
        "viewRepository": "Lihat repositori",
        "viewPluginFiles": "Lihat file plugin",
        "gitCloneLabel": "URL git clone",
        "enableAgent": "Aktifkan plugin agen setelah dipasang",
        "forceReinstall": "Paksa pasang ulang (ganti bila sudah terpasang)",
        "pinToCommit": "Patok ke commit (opsional)",
        "pinToCommitPlaceholder": "SHA commit lengkap 40 karakter",
        "pinToCommitHint": "Semua yang memasang SHA ini mendapat kode yang sama; plugin lalu menolak pembaruan sampai dipatok ulang. Kosongkan untuk commit terbaru.",
        "pinToCommitInvalid": "Harus SHA commit lengkap 40 karakter (branch dan tag tidak diterima).",
        "install": "Pasang",
        "installing": "Memasang…",
        "probing": "Memeriksa repositori…",
        "probeUnavailable": "Pemeriksaan plugin tidak tersedia di lingkungan ini.",
        "desktopUnavailable": "Pemasangan plugin desktop tidak tersedia di lingkungan ini.",
        "selectComponent": "Pilih minimal satu komponen untuk dipasang.",
        "agentFailed": "Pemasangan plugin agen gagal",
        "installUncertain": "Neovarch berhenti menunggu hasil pemasangan, tapi plugin mungkin masih dipasang. Tutup dialog ini dan pakai Pindai ulang di Plugin sebelum mencoba Pasang lagi.",
        "desktopFailed": "Pemasangan plugin desktop gagal"
      }
    },
    "vault": {
      "title": "Kata sandi & login",
      "blurb": "Katakan \"masuk ke GitHub\" dan agen masuk untuk Anda. Saat pertama bertemu halaman masuk, agen menanyakan login di tempat; setelah itu langsung jalan. Kata sandi dienkripsi di komputer ini dan diisikan langsung ke halaman — model tidak pernah melihatnya.",
      "loadFailed": "Item brankas tidak bisa dimuat",
      "empty": "Belum ada yang tersimpan",
      "emptyDesc": "Anda tidak perlu menambah apa pun di sini. Minta agen masuk ke sebuah situs dan ia akan menanyakan login sekali, di tempat. Pakai Tambah bila ingin mengisinya lebih dulu.",
      "add": "Tambah",
      "addTitle": "Tambah login, kartu, atau alamat",
      "addDescription": "Disimpan terenkripsi di komputer ini. Agen tidak pernah melihat kata sandinya.",
      "added": "Tersimpan.",
      "adding": "Menyimpan…",
      "addConfirm": "Simpan",
      "kindField": "Jenis",
      "kinds": {
        "login": "Login",
        "payment": "Kartu pembayaran",
        "address": "Alamat"
      },
      "labelField": "Label",
      "labelPlaceholder": "mis. akun GitHub kantor",
      "labelRequired": "Label wajib diisi.",
      "originField": "Asal situs",
      "originPlaceholder": "https://github.com",
      "originPlaceholderCheckout": "https://toko.contoh.com",
      "originInvalid": "Masukkan URL yang valid seperti https://contoh.com.",
      "identifierTypeField": "Jenis pengenal",
      "identifierTypes": {
        "email": "Email",
        "phone": "Telepon",
        "username": "Nama pengguna"
      },
      "identifierField": "Pengenal",
      "passwordField": "Kata sandi",
      "loginFieldsRequired": "Pengenal dan kata sandi wajib diisi.",
      "cardNumberField": "Nomor kartu",
      "cardNameField": "Nama di kartu",
      "expMonthField": "Bulan kedaluwarsa",
      "expYearField": "Tahun kedaluwarsa",
      "cvcField": "CVC",
      "postalField": "Kode pos",
      "addressLine1Field": "Alamat baris 1",
      "addressLine2Field": "Alamat baris 2",
      "cityField": "Kota",
      "stateField": "Provinsi / wilayah",
      "countryField": "Negara",
      "optional": "(opsional)",
      "deleteAction": "Hapus item tersimpan",
      "otpField": "Kunci autentikator",
      "otpPlaceholder": "Rahasia Base32 atau tautan otpauth://",
      "otpHint": "\"Kunci penyiapan\" yang ditampilkan situs saat Anda mengaktifkan 2FA. Bila tersimpan, Neovarch membuat kodenya sendiri.",
      "twoFactorBadge": "2FA otomatis",
      "deleteTitle": "Hapus item ini?",
      "deleteConfirm": "Hapus",
      "sources": {
        "title": "Pengelola kata sandi",
        "blurb": "Pengelola kata sandi yang terpasang terdeteksi otomatis. Agen meminta Anda membukanya saat pertama butuh login darinya (sekali per sesi); hanya token sesi yang disimpan di memori, dan agen tidak pernah melihat kata sandi utama atau login apa pun.",
        "toggleFailed": "Pengelola kata sandi tidak bisa diperbarui",
        "disabledDesc": "Terdeteksi tapi dimatikan untuk Neovarch.",
        "lockedDesc": "Terdeteksi. Agen akan meminta Anda membukanya saat butuh login, atau buka sekarang.",
        "unlockedDesc": "Terbuka untuk sesi ini. Terkunci otomatis setelah 30 menit diam atau saat Neovarch ditutup.",
        "statusLocked": "Terkunci",
        "statusNotDetected": "Tidak terdeteksi",
        "statusOff": "Mati",
        "statusUnlocked": "Terbuka",
        "unlock": "Buka",
        "unlocking": "Membuka…",
        "lock": "Kunci",
        "unlockDescription": "Masukkan kata sandi utama. Kata sandi diserahkan ke pengelola kata sandi di komputer ini lalu dibuang — tidak pernah disimpan, dicatat, atau diperlihatkan ke agen.",
        "masterPasswordPlaceholder": "Kata sandi utama"
      }
    },
    "notifications": {
      "title": "Notifikasi",
      "intro": "Notifikasi sistem operasi (bukan toast di aplikasi). Per perangkat.",
      "enableAll": "Aktifkan notifikasi",
      "enableAllDesc": "Bila mati, semua notifikasi di bawah dibisukan.",
      "focusedHint": "Notifikasi selesai hanya muncul saat Neovarch berada di latar belakang.",
      "kinds": {
        "approval": {
          "label": "Perlu persetujuan",
          "description": "Ada perintah yang menunggu Anda setujui atau tolak."
        },
        "input": {
          "label": "Perlu masukan",
          "description": "Neovarch mengajukan pertanyaan atau butuh kata sandi atau rahasia."
        },
        "turnDone": {
          "label": "Jawaban siap",
          "description": "Satu giliran selesai saat Neovarch di latar belakang."
        },
        "turnError": {
          "label": "Giliran gagal",
          "description": "Galat giliran di latar belakang."
        },
        "backgroundDone": {
          "label": "Tugas latar selesai",
          "description": "Perintah terminal di latar belakang selesai."
        },
        "credits": {
          "label": "Peringatan kredit",
          "description": "Akses kredit dijeda atau dipulihkan."
        },
        "plugin": {
          "label": "Notifikasi plugin",
          "description": "Plugin desktop mengirim notifikasi saat Neovarch di latar belakang."
        }
      },
      "test": "Kirim notifikasi uji",
      "testTitle": "Neovarch",
      "testBody": "Notifikasi berfungsi.",
      "testSent": "Uji terkirim. Bila tidak muncul, periksa izin notifikasi sistem dan mode Fokus/Jangan Ganggu.",
      "testUnsupported": "Sistem ini tidak mendukung notifikasi bawaan.",
      "completionSoundTitle": "Suara selesai",
      "completionSoundDesc": "Diputar saat giliran agen selesai. Pilih preset dan dengarkan di sini.",
      "completionSoundPreview": "Dengarkan"
    },
    "sections": {
      "model": "Model",
      "chat": "Obrolan",
      "agent": "Agen",
      "appearance": "Tampilan",
      "workspace": "Ruang kerja",
      "safety": "Keamanan",
      "memory": "Memori & konteks",
      "voice": "Suara",
      "advanced": "Lanjutan"
    },
    "searchPlaceholder": {
      "about": "Tentang Neovarch Agent",
      "config": "Cari pengaturan…",
      "gateway": "Koneksi gateway…",
      "keys": "Cari API key…",
      "mcp": "Cari server MCP…",
      "sessions": "Cari sesi yang diarsipkan…"
    },
    "modeOptions": {
      "light": {
        "label": "Terang",
        "description": "Permukaan desktop cerah"
      },
      "dark": {
        "label": "Gelap",
        "description": "Ruang kerja minim silau"
      },
      "system": {
        "label": "Sistem",
        "description": "Ikuti tampilan sistem operasi"
      }
    },
    "appearance": {
      "chatTextScaleTitle": "Ukuran teks obrolan",
      "chatTextScaleDesc": "Mengubah ukuran teks percakapan dan editor pesan relatif terhadap Skala UI. Sidebar dan kontrol tetap sama.",
      "title": "Tampilan",
      "intro": "Khusus desktop. Mode adalah kecerahan; tema adalah palet dan bingkai obrolan.",
      "colorMode": "Mode warna",
      "colorModeDesc": "Pilih mode tetap atau biarkan Neovarch mengikuti pengaturan sistem.",
      "toolViewTitle": "Tampilan panggilan tool",
      "toolViewDesc": "Produk menyembunyikan muatan mentah tool; Teknis menampilkan masukan/keluaran lengkap.",
      "hideCodeDiffsTitle": "Sembunyikan diff kode",
      "hideCodeDiffsDesc": "Tampilkan perubahan file sebagai baris tool dengan jumlah baris ditambah/dihapus, tanpa kodenya.",
      "hideThreadTimelineTitle": "Sembunyikan bilah linimasa",
      "hideThreadTimelineDesc": "Sembunyikan bilah navigasi di tepi kanan tiap percakapan.",
      "reasoningCollapsedTitle": "Ciutkan proses berpikir secara bawaan",
      "reasoningCollapsedDesc": "Penalaran tetap tersedia tapi tidak dibentangkan sampai Anda membukanya.",
      "uiScaleTitle": "Skala UI",
      "sessionDensityTitle": "Kepadatan daftar sesi",
      "sessionDensityDesc": "Pilih seberapa banyak konteks yang tampil di bawah judul sesi di sidebar.",
      "sessionDensityCompact": "Ringkas",
      "sessionDensityComfortable": "Nyaman",
      "sessionDensityDetailed": "Rinci",
      "tabStripTitle": "Bilah tab",
      "tabStripDesc": "Tampilkan tab di atas zona. Otomatis menyembunyikannya untuk satu panel kecuali ada obrolan atau zona lain yang terbuka.",
      "tabStripAuto": "Otomatis",
      "tabStripAlways": "Selalu",
      "tabStripNever": "Tidak pernah",
      "appActionsTitle": "Aksi aplikasi",
      "appActionsDesc": "Posisi Pengaturan, Tata letak, dan HUD di bilah judul. Kanan menyisakan ruang untuk tab di kiri.",
      "appActionsLeft": "Kiri",
      "appActionsRight": "Kanan",
      "terminalFontTitle": "Font terminal",
      "terminalFontDesc": "Pilih font terpasang untuk terminal desktop. Nerd Fonts menampilkan ikon Powerlevel10k dan shell; kosongkan untuk memakai JetBrains Mono bawaan.",
      "terminalFontPlaceholder": "MesloLGS NF atau tumpukan font CSS",
      "terminalFontPreview": "Pratinjau glif",
      "terminalFontReset": "Pakai bawaan",
      "chatFontTitle": "Font obrolan",
      "chatFontDesc": "Pilih font terpasang untuk obrolan dan seluruh aplikasi. Berguna untuk font keterbacaan seperti OpenDyslexic; kosongkan untuk memakai font tema.",
      "chatFontPlaceholder": "OpenDyslexic atau tumpukan font CSS",
      "chatFontPreview": "Pratinjau",
      "chatFontSample": "Saya suka makan nasi goreng di pinggir jalan. 0123456789",
      "chatFontReset": "Pakai font tema",
      "translucencyTitle": "Transparansi jendela",
      "translucencyDesc": "Desktop terlihat menembus seluruh jendela, termasuk teks. Diatur terpisah untuk terang dan gelap.",
      "translucencyGlassDesc": "Kaca buram: desktop terlihat sebagai blur halus sementara teks tetap tajam. Diatur terpisah untuk terang dan gelap.",
      "translucencyModeClear": "Bening",
      "translucencyModeGlass": "Kaca",
      "translucencyTintTitle": "Warna",
      "translucencyFadeTitle": "Pudar",
      "translucencyFrostTitle": "Buram",
      "translucencyFrost": {
        "under-window": "Dalam",
        "popover": "Lembut",
        "titlebar": "Terang",
        "header": "Silau"
      },
      "translucencyScopeTitle": "Area",
      "translucencyScope": {
        "window": "Seluruh jendela",
        "sidebar": "Sidebar saja"
      },
      "backdropTitle": "Latar obrolan",
      "backdropDesc": "Gambar samar di belakang percakapan.",
      "userBubbleTitle": "Gelembung pesan",
      "userBubbleDesc": "Seberapa tembus pandang pesan Anda sendiri. Padat di 0; hanya garis tepi yang tersisa di 100.",
      "textDirectionTitle": "Arah teks",
      "textDirectionDesc": "Cara pesan obrolan dan composer memilih arah. Otomatis mengikuti huruf pertama tiap paragraf; pilih arah bila teks campuran berbaris salah. Kode selalu kiri-ke-kanan.",
      "textDirection": {
        "auto": "Otomatis",
        "rtl": "Kanan-ke-kiri",
        "ltr": "Kiri-ke-kanan"
      },
      "introSplashTitle": "Layar pembuka",
      "introSplashDesc": "Sapaan yang tampil di obrolan kosong.",
      "modelPricingTitle": "Harga model",
      "modelPricingDesc": "Tampilkan harga masukan, keluaran, dan baca-cache per sejuta token di pemilih model.",
      "reactionsTitle": "Reaksi pesan",
      "reactionsDesc": "Reaksi emoji ala iMessage — beri reaksi ke pesan, dan Neovarch bisa bereaksi ke pesan Anda.",
      "tipsTitle": "Tips di aplikasi",
      "tipsDesc": "Petunjuk sesekali dari aplikasi dan Neovarch. Tiap tips muncul sekali. Mati otomatis setelah 30 hari pertama; bisa dinyalakan lagi.",
      "toursTitle": "Tur terpandu",
      "toursDesc": "Biarkan Neovarch menyorot tiap langkah saat memandu Anda di aplikasi. Mati otomatis setelah 30 hari pertama; bisa dinyalakan lagi.",
      "composerPopoutTitle": "Composer mengambang",
      "composerPopoutDesc": "Izinkan composer diseret keluar dari dok. Bila mati, composer tetap di bawah.",
      "fileBrowserTitle": "Penjelajah file",
      "fileBrowserDesc": "Tampilkan penjelajah file di samping obrolan saat ruang kerja terbuka. Tombol di bilah judul juga mengubah ini.",
      "vibeHeartsTitle": "Hati beterbangan",
      "vibeHeartsDesc": "Hati melayang saat Anda bilang terima kasih, makasih, atau mengirim hati. Terpisah dari Reaksi pesan di atas.",
      "embedsTitle": "Sematan inline",
      "embedsDesc": "Pratinjau kaya dimuat dari situs pihak ketiga (YouTube, X, …). Tanya menampilkan placeholder sampai Anda mengizinkan; Selalu memuat otomatis; Mati menampilkan tautan biasa.",
      "embedsAsk": "Tanya",
      "embedsAlways": "Selalu",
      "embedsOff": "Mati",
      "resumeLastSessionTitle": "Buka obrolan terakhir saat mulai",
      "resumeLastSessionDesc": "Bila aktif, aplikasi membuka obrolan terakhir saat dijalankan. Matikan untuk selalu mulai dengan obrolan baru.",
      "product": "Produk",
      "productDesc": "Aktivitas tool yang ramah dengan ringkasan singkat.",
      "technical": "Teknis",
      "technicalDesc": "Sertakan argumen/hasil mentah tool dan detail tingkat rendah.",
      "themeTitle": "Tema",
      "themeDesc": "Hanya palet desktop. Mode yang dipilih diterapkan di atasnya.",
      "themeSearchPlaceholder": "Cari tema Anda atau VS Code Marketplace…",
      "installTitle": "Pasang dari VS Code",
      "installDesc": "Tempel id ekstensi Marketplace (mis. dracula-theme.theme-dracula) untuk mengubah tema warnanya menjadi palet desktop.",
      "installPlaceholder": "publisher.extension",
      "installButton": "Pasang",
      "installing": "Memasang…",
      "installError": "Tema itu tidak bisa dipasang.",
      "removeTheme": "Hapus tema",
      "importedBadge": "Diimpor",
      "pet": {
        "title": "Peliharaan",
        "intro": "Adopsi maskot animasi yang melayang di atas aplikasi dan bereaksi pada kerja Neovarch — berlari saat tool berjalan, merayakan keberhasilan, cemberut saat galat.",
        "restartHint": "Peliharaan butuh mulai ulang singkat — aplikasi yang berjalan dimulai sebelum fitur ini ada. Tutup dan buka lagi Neovarch, lalu kembali ke sini.",
        "scaleTitle": "Ukuran",
        "scaleDesc": "Ubah ukuran maskot. Langsung berlaku di mana saja.",
        "roamTitle": "Berkeliaran",
        "roamDesc": "Biarkan peliharaan berkeliling jendela sendiri saat diam.",
        "chooseTitle": "Pilih peliharaan",
        "chooseDesc": "Memilih satu akan memasangnya (bila perlu) dan menjadikannya aktif.",
        "searchPlaceholder": "Cari peliharaan…",
        "unreachable": "Galeri peliharaan tidak terjangkau. Periksa koneksi dan buka lagi halaman ini.",
        "installedTag": "terpasang",
        "generatedTag": "Dibuat",
        "deleteBody": "Peliharaan ini dihapus permanen — tidak bisa dipasang lagi.",
        "deleteConfirm": "Hapus",
        "renameTitle": "Ganti nama peliharaan",
        "renamePlaceholder": "Beri nama peliharaan",
        "renameSave": "Simpan",
        "noneAvailable": "Belum ada peliharaan yang bisa dinyalakan.",
        "turnOnFailed": "Peliharaan tidak bisa dinyalakan.",
        "turnOffFailed": "Peliharaan tidak bisa dimatikan."
      }
    },
    "fieldLabels": {
      "model": "Model bawaan",
      "modelContextLength": "Jendela konteks model utama (timpa)",
      "fallbackProviders": "Model cadangan",
      "toolsets": "Toolset aktif",
      "timezone": "Zona waktu",
      "display": {
        "personality": "Kepribadian",
        "showReasoning": "Blok penalaran"
      },
      "desktop": {
        "repoScanEnabled": "Penemuan repositori otomatis",
        "repoScanRoots": "Akar penemuan repositori",
        "repoScanExcludePaths": "Path repositori yang dikecualikan"
      },
      "agent": {
        "harnessMode": "Otak agen",
        "systemPrompt": "Instruksi tambahan",
        "maxTurns": "Langkah agen maksimum",
        "imageInputMode": "Lampiran gambar",
        "apiMaxRetries": "Percobaan ulang API",
        "serviceTier": "Tingkat layanan",
        "toolUseEnforcement": "Penegakan pemakaian tool"
      },
      "terminal": {
        "cwd": "Direktori kerja",
        "backend": "Backend eksekusi",
        "timeout": "Batas waktu perintah",
        "persistentShell": "Shell persisten",
        "envPassthrough": "Variabel lingkungan yang diteruskan",
        "dockerImage": "Image Docker",
        "singularityImage": "Image Singularity",
        "modalImage": "Image Modal",
        "daytonaImage": "Image Daytona"
      },
      "fileReadMaxChars": "Batas baca file",
      "toolOutput": {
        "maxBytes": "Batas keluaran terminal",
        "maxLines": "Batas halaman file",
        "maxLineLength": "Batas panjang baris"
      },
      "codeExecution": {
        "mode": "Mode eksekusi kode"
      },
      "approvals": {
        "mode": "Mode persetujuan",
        "timeout": "Batas waktu persetujuan",
        "mcpReloadConfirm": "Konfirmasi muat ulang MCP"
      },
      "commandAllowlist": "Daftar perintah yang diizinkan",
      "security": {
        "redactSecrets": "Sensor rahasia",
        "allowPrivateUrls": "Izinkan URL privat"
      },
      "browser": {
        "allowPrivateUrls": "URL privat di browser",
        "autoLocalForPrivateUrls": "Browser lokal untuk URL privat",
        "useRealProfile": "Pakai profil browser asli saya"
      },
      "checkpoints": {
        "enabled": "Checkpoint file",
        "maxSnapshots": "Batas checkpoint"
      },
      "voice": {
        "maxRecordingSeconds": "Panjang rekaman maksimum",
        "autoTts": "Bacakan jawaban",
        "voiceChatMode": "Mode obrolan suara",
        "gptLive": {
          "voice": "Suara GPT-Live",
          "instructions": "Persona GPT-Live"
        }
      },
      "stt": {
        "enabled": "Suara ke teks",
        "echoTranscripts": "Tampilkan transkrip",
        "provider": "Penyedia suara-ke-teks",
        "streaming": "Transkripsi langsung",
        "local": {
          "model": "Model transkripsi lokal",
          "language": "Bahasa transkripsi"
        },
        "openai": {
          "model": "Model STT OpenAI",
          "streamingModel": "Model transkripsi langsung OpenAI"
        },
        "groq": {
          "model": "Model STT Groq"
        },
        "mistral": {
          "model": "Model STT Mistral"
        },
        "xai": {
          "model": "Model STT xAI"
        },
        "deepinfra": {
          "model": "Model STT DeepInfra"
        },
        "elevenlabs": {
          "modelId": "Model STT ElevenLabs",
          "languageCode": "Bahasa ElevenLabs",
          "tagAudioEvents": "Tandai peristiwa audio",
          "diarize": "Pemisahan pembicara"
        }
      },
      "tts": {
        "provider": "Penyedia teks-ke-suara",
        "edge": {
          "voice": "Suara Edge"
        },
        "openai": {
          "model": "Model TTS OpenAI",
          "voice": "Suara OpenAI"
        },
        "elevenlabs": {
          "voiceId": "Suara ElevenLabs",
          "modelId": "Model ElevenLabs"
        },
        "xai": {
          "voiceId": "Suara xAI (Grok)",
          "language": "Bahasa xAI",
          "speed": "Kecepatan putar xAI",
          "autoSpeechTags": "Tag ekspresi otomatis xAI",
          "optimizeStreamingLatency": "Optimasi latensi streaming xAI",
          "sampleRate": "Sample rate xAI",
          "bitRate": "Bit rate xAI"
        },
        "minimax": {
          "model": "Model TTS MiniMax",
          "voiceId": "Suara MiniMax"
        },
        "mistral": {
          "model": "Model TTS Mistral",
          "voiceId": "Suara Mistral"
        },
        "gemini": {
          "model": "Model TTS Gemini",
          "voice": "Suara Gemini"
        },
        "neutts": {
          "model": "Model NeuTTS",
          "device": "Perangkat NeuTTS"
        },
        "kittentts": {
          "model": "Model KittenTTS",
          "voice": "Suara KittenTTS"
        },
        "piper": {
          "voice": "Suara Piper"
        },
        "deepinfra": {
          "model": "Model TTS DeepInfra",
          "voice": "Suara DeepInfra"
        }
      },
      "memory": {
        "memoryEnabled": "Memori permanen",
        "userProfileEnabled": "Profil pengguna",
        "memoryCharLimit": "Anggaran memori",
        "userCharLimit": "Anggaran profil",
        "provider": "Penyedia memori"
      },
      "context": {
        "engine": "Mesin konteks"
      },
      "compression": {
        "enabled": "Pemadatan otomatis",
        "threshold": "Ambang pemadatan",
        "codexGpt55Autoraise": "Naikkan otomatis pemadatan Codex",
        "targetRatio": "Target pemadatan",
        "protectLastN": "Pesan terbaru yang dilindungi"
      },
      "auxiliary": {
        "compression": {
          "timeout": "Batas waktu model pemadatan (detik)"
        }
      },
      "delegation": {
        "model": "Model subagen",
        "provider": "Penyedia subagen",
        "maxIterations": "Batas giliran subagen",
        "maxConcurrentChildren": "Subagen paralel",
        "childTimeoutSeconds": "Batas waktu subagen",
        "reasoningEffort": "Upaya penalaran subagen"
      },
      "updates": {
        "nonInteractiveLocalChanges": "Perubahan lokal saat pembaruan di aplikasi"
      }
    },
    "fieldDescriptions": {
      "model": "Dipakai untuk obrolan baru kecuali Anda memilih model lain di composer.",
      "modelContextLength": "Menimpa jendela konteks terdeteksi khusus model obrolan UTAMA (token). Biarkan 0 untuk memakai nilai terdeteksi. Tidak memengaruhi model pembantu/MoA.",
      "fallbackProviders": "Entri penyedia:model cadangan yang dicoba bila model bawaan gagal.",
      "display": {
        "personality": "Gaya asisten bawaan untuk sesi baru.",
        "showReasoning": "Tampilkan bagian penalaran bila backend menyediakannya."
      },
      "desktop": {
        "repoScanEnabled": "Pindai folder lokal untuk repositori Git yang ditampilkan di Proyek.",
        "repoScanRoots": "Folder yang dipindai. Kosongkan untuk memindai folder home.",
        "repoScanExcludePaths": "Folder (beserta isinya) yang dilewati saat penemuan repositori."
      },
      "timezone": "Pengenal zona waktu IANA (mis. Asia/Jakarta). Kosong memakai zona waktu sistem.",
      "browser": {
        "useRealProfile": "Penjelajahan lokal memakai login asli Anda. Neovarch menyalin profil browser bawaan (cookie, login, preferensi) ke snapshot terkelola dan menjalankannya dengan Chromium bawaan — profil aktif Anda tidak pernah dibuka langsung, dan salinannya diperbarui setiap kali jalan. Agen juga bisa membuka sesi profil asli lokal atas permintaan meski backend browser cloud diatur. Hanya browser Chromium (Chrome, Edge, Brave, Chromium) yang didukung; browser bawaan non-Chromium gagal dengan pesan jelas. Mati secara bawaan."
      },
      "agent": {
        "harnessMode": "Tempest = Neovarch Tempest, otak baru (bawaan): prompt hemat, cek lint/tes sebelum selesai, checkpoint yang bisa dipulihkan. Legacy = loop lama, bila perlu kembali.",
        "systemPrompt": "Instruksi tambahan yang diikuti agen di setiap obrolan, setelah SOUL.md.",
        "imageInputMode": "Mengatur cara lampiran gambar dikirim ke model.",
        "maxTurns": "Batas atas giliran pemanggilan tool sebelum Neovarch menghentikan proses."
      },
      "terminal": {
        "cwd": "Folder proyek bawaan untuk kerja tool dan terminal.",
        "persistentShell": "Pertahankan status shell antarperintah bila backend mendukung.",
        "envPassthrough": "Variabel lingkungan yang diteruskan ke eksekusi tool.",
        "dockerImage": "Image kontainer yang dipakai bila backend eksekusinya Docker.",
        "singularityImage": "Image yang dipakai bila backend eksekusinya Singularity.",
        "modalImage": "Image yang dipakai bila backend eksekusinya Modal.",
        "daytonaImage": "Image yang dipakai bila backend eksekusinya Daytona."
      },
      "codeExecution": {
        "mode": "Seberapa ketat eksekusi kode dibatasi ke proyek saat ini."
      },
      "fileReadMaxChars": "Jumlah karakter maksimum yang bisa dibaca Neovarch per permintaan file.",
      "approvals": {
        "mode": "Cara Neovarch menangani perintah yang butuh persetujuan eksplisit.",
        "timeout": "Berapa lama permintaan persetujuan menunggu sebelum kedaluwarsa."
      },
      "security": {
        "redactSecrets": "Sembunyikan rahasia yang terdeteksi dari konten yang dilihat model bila memungkinkan."
      },
      "checkpoints": {
        "enabled": "Buat snapshot pemulihan sebelum mengubah file."
      },
      "memory": {
        "memoryEnabled": "Simpan memori jangka panjang yang membantu sesi berikutnya.",
        "userProfileEnabled": "Simpan profil ringkas preferensi pengguna."
      },
      "context": {
        "engine": "Strategi mengelola percakapan panjang yang mendekati batas konteks."
      },
      "compression": {
        "enabled": "Ringkas konteks lama saat percakapan membesar.",
        "codexGpt55Autoraise": "Naikkan pemadatan ke 85% untuk model ChatGPT Codex OAuth yang didukung."
      },
      "auxiliary": {
        "compression": {
          "timeout": "Detik menunggu model pemadatan pembantu per panggilan (bawaan 120). Naikkan untuk model lokal yang lambat."
        }
      },
      "voice": {
        "autoTts": "Bacakan jawaban asisten secara otomatis.",
        "voiceChatMode": "chained: suara-ke-teks → Neovarch → teks-ke-suara dengan penyedia di bawah. gpt-live: satu model suara OpenAI full-duplex (gpt-live-1) mendengar dan berbicara, lalu menyerahkan setiap permintaan nyata ke Neovarch — model yang Anda pilih menjawab dengan toolset lengkap. Butuh API key OpenAI; lapisan suara ditagih $0,05 per menit.",
        "gptLive": {
          "voice": "Suara untuk mode GPT-Live. ID suara kustom diterima.",
          "instructions": "Kalimat tambahan untuk persona suara langsung (nada, tempo, bahasa). Neovarch tetap memakai prompt sistemnya sendiri."
        }
      },
      "tts": {
        "xai": {
          "voiceId": "ID suara xAI (mis. eve) atau ID suara kustom.",
          "language": "Kode bahasa (mis. id, en) atau \"auto\" untuk deteksi otomatis.",
          "speed": "Kecepatan putar. 0,7 = lebih lambat, 1,0 = normal, 1,5 = lebih cepat.",
          "autoSpeechTags": "Biarkan LLM menyisipkan tag ekspresi audio ([tertawa], [menghela napas]) ke naskah sebelum sintesis.",
          "optimizeStreamingLatency": "Imbang latensi vs kualitas. 0 = kualitas terbaik, 2 = latensi terendah.",
          "sampleRate": "Sample rate audio dalam Hz. Lebih tinggi = kualitas lebih baik, file lebih besar.",
          "bitRate": "Bitrate MP3 dalam bps. Hanya berlaku bila codec mp3."
        },
        "neutts": {
          "device": "Perangkat inferensi lokal untuk NeuTTS."
        }
      },
      "stt": {
        "enabled": "Aktifkan transkripsi suara lokal atau lewat penyedia.",
        "echoTranscripts": "Kirim transkrip mentah 🎙️ pesan suara kembali ke obrolan.",
        "streaming": "Tampilkan teks saat Anda berbicara (OpenAI, xAI, ElevenLabs). Kembali ke rekaman bila ada kegagalan.",
        "elevenlabs": {
          "languageCode": "Kode bahasa ISO-639-3 opsional. Kosong membiarkan ElevenLabs mendeteksi otomatis."
        }
      },
      "updates": {
        "nonInteractiveLocalChanges": "Saat Neovarch memperbarui diri dari aplikasi (tanpa prompt terminal), simpan perubahan kode lokal (stash) atau buang (discard). Pembaruan dari terminal selalu bertanya."
      }
    },
    "uninstallSection": {
      "dangerZone": "Zona berbahaya",
      "checkingInstalled": "Memeriksa yang terpasang…",
      "uninstallHermes": "Copot Neovarch",
      "managedBody": "Pemasangan ini dikelola sistem, jadi Neovarch tidak bisa mencopot dirinya sendiri.",
      "openAppsSettings": "Buka pengaturan Aplikasi",
      "chooseHowMuch": "Pilih seberapa banyak yang dihapus. Aplikasi ditutup untuk menyelesaikannya; buka installer kapan saja untuk kembali.",
      "confirmUninstall": "Konfirmasi pencopotan",
      "appLabel": "Aplikasi:",
      "couldNotStart": "Pencopotan tidak bisa dimulai.",
      "uninstalling": "Mencopot…",
      "yesUninstall": "Ya, copot",
      "options": {
        "gui": {
          "title": "Copot aplikasi desktop saja",
          "description": "Hapus aplikasi desktop ini. Core Neovarch, konfigurasi, dan obrolan Anda tetap ada.",
          "consequence": "aplikasi desktop (aplikasi ini dan datanya)"
        },
        "lite": {
          "title": "Copot aplikasi + agen, simpan data saya",
          "description": "Hapus aplikasi dan core Neovarch, tapi simpan konfigurasi, obrolan, dan rahasia untuk pemasangan ulang.",
          "consequence": "aplikasi desktop dan core Neovarch (konfigurasi, obrolan, dan rahasia disimpan)"
        },
        "full": {
          "title": "Copot semuanya",
          "description": "Hapus aplikasi, agen, dan semua data pengguna — konfigurasi, obrolan, jadwal, rahasia, log.",
          "consequence": "SEMUANYA — aplikasi desktop, core Neovarch, serta semua konfigurasi, obrolan, rahasia, dan log Anda"
        }
      }
    },
    "poolLimits": {
      "warmBotBackendsAria": "Backend bot siaga",
      "warmBotBackendsTitle": "Backend bot siaga",
      "backendIdleTimeoutAria": "Batas waktu diam backend dalam milidetik",
      "backendIdleTimeoutTitle": "Batas waktu diam backend"
    },
    "customEndpoints": {
      "active": "Aktif",
      "apiKeySet": "API key diatur",
      "use": "Pakai",
      "editTitle": "Ubah endpoint",
      "addTitle": "Tambah endpoint",
      "fields": {
        "name": "Nama",
        "providerId": "ID penyedia",
        "endpointUrl": "URL endpoint",
        "defaultModel": "Model bawaan",
        "context": "Konteks",
        "apiKey": "API key",
        "apiKeyNewPlaceholder": "Kosongkan untuk mempertahankan key sekarang",
        "apiKeyPlaceholder": "Opsional",
        "useNewChats": "Pakai untuk obrolan baru",
        "discoverModels": "Ambil daftar model"
      },
      "test": "Tes koneksi",
      "save": "Simpan",
      "newEndpoint": "Endpoint baru",
      "apiMode": "Mode API",
      "autoDetect": "Deteksi otomatis",
      "couldNotLoad": "Endpoint kustom tidak bisa dimuat",
      "endpointSaved": "Endpoint kustom tersimpan.",
      "saveFailed": "Gagal menyimpan",
      "endpointReachable": "Endpoint bisa dijangkau.",
      "endpointValidationFailed": "Validasi endpoint gagal.",
      "validationFailed": "Validasi gagal",
      "activationFailed": "Aktivasi gagal",
      "deleteFailed": "Gagal menghapus",
      "title": "Endpoint kustom",
      "deleteEndpoint": "Hapus endpoint",
      "emptyDescription": "Tambahkan endpoint yang kompatibel OpenAI di bawah (https gateway atau http lokal).",
      "emptyTitle": "Belum ada endpoint kustom",
      "namePlaceholder": "9router",
      "contextPlaceholder": "Otomatis"
    },
    "computerUse": {
      "accessibility": "Aksesibilitas",
      "screenRecording": "Perekaman layar",
      "driverHealth": "Kesehatan driver"
    },
    "about": {
      "updates": "Pembaruan"
    },
    "config": {
      "minimizeToTrayTitle": "Kecilkan ke tray",
      "minimizeToTrayDesc": "Mengecilkan atau menutup jendela utama akan menyembunyikannya di system tray (bilah menu di macOS) dan Neovarch tetap berjalan. Pakai Keluar dari menu tray atau Cmd+Q untuk keluar. Mati secara bawaan; hanya untuk perangkat ini.",
      "minimizeToTrayUnavailable": "System tray tidak tersedia. Jendela akan dikecilkan dan ditutup seperti biasa. Matikan lalu nyalakan untuk mencoba lagi.",
      "none": "Tidak ada",
      "noneParen": "(tidak ada)",
      "builtinOnly": "Bawaan saja",
      "notSet": "Belum diatur",
      "commaSeparated": "nilai dipisah koma",
      "searchPlaceholder": "Cari…",
      "noResults": "Tidak ada hasil",
      "systemDefault": "Bawaan sistem",
      "loading": "Memuat konfigurasi Neovarch…",
      "emptyTitle": "Tidak ada yang perlu diatur",
      "emptyDesc": "Bagian ini tidak punya pengaturan yang bisa diubah.",
      "failedLoad": "Pengaturan gagal dimuat",
      "autosaveFailed": "Simpan otomatis gagal",
      "imported": "Konfigurasi diimpor",
      "invalidJson": "JSON konfigurasi tidak valid",
      "toolsetsWipeConfirm": "Hapus semua toolset aktif? Ini menonaktifkan memori, terminal, pencarian web, delegasi, dan sebagian besar tool lain sampai Anda mengaktifkannya lagi.",
      "keepAwakeTitle": "Jaga komputer tetap menyala",
      "keepAwakeDesc": "Cegah komputer tertidur. \"Saat bekerja\" hanya menahannya selama giliran berjalan, jadi proses semalam tetap jalan tanpa membuat laptop menyala seminggu penuh. Layar tetap bisa meredup.",
      "keepAwakeOff": "Mati",
      "keepAwakeWhileWorking": "Saat bekerja",
      "keepAwakeAlways": "Selalu",
      "disableF12Title": "Nonaktifkan DevTools F12",
      "disableF12Desc": "Cegah F12 membuka Developer Tools. Ctrl+Shift+I (atau Cmd+Opt+I di Mac) tetap berfungsi.",
      "alwaysExternalLinksTitle": "Selalu buka tautan di browser luar",
      "alwaysExternalLinksDesc": "Buka setiap tautan di browser sistem, bukan browser dalam aplikasi. \"Buka di browser aplikasi\" di menu klik kanan tetap berfungsi.",
      "developerTitle": "Pengembang",
      "resetOnboardingTitle": "Ulangi penyiapan awal",
      "resetOnboardingDesc": "Hapus obrolan penyiapan, bangun ulang profil penyiapan, dan jalankan lagi penyiapan pertama. Profil, obrolan, dan plugin Anda tetap ada.",
      "resetOnboardingAction": "Ulangi",
      "resetOnboardingFailed": "Penyiapan awal tidak bisa diulang",
      "attachmentSizeTitle": "Ukuran maks pratinjau / gambar",
      "attachmentSizeDesc": "Seberapa besar file lokal yang dimuat desktop untuk pratinjau dan lampiran gambar, dalam MB. Bawaan 16. Lampiran non-gambar jarak jauh punya batas terpisah 256 MB. Nilai yang sangat besar memuat seluruh file ke memori dan bisa membuat aplikasi macet.",
      "attachmentSizeUnit": "MB",
      "attachmentSizeLabel": "Ukuran maks pratinjau / gambar dalam megabyte",
      "voiceShortcutHintTitle": "Pintasan rekam suara",
      "voiceShortcutHintDesc": "Atur pintasan rekam suara di Pengaturan → Pintasan keyboard (\"Mulai / hentikan percakapan suara\"). Nilai konfigurasi voice.record_key hanya berlaku untuk CLI dan TUI.",
      "showOptions": "Tampilkan opsi"
    },
    "hudModifier": {
      "title": "Ketuk untuk memanggil HUD",
      "description": "Ketuk dan lepas ⌘ + Option di Mac, atau Ctrl + Alt di Windows/Linux, untuk memunculkan HUD dari aplikasi mana pun. Mati secara bawaan; hanya untuk perangkat ini.",
      "permission": "Izinkan Neovarch di Pengaturan Sistem → Privasi & Keamanan → Pemantauan Input, lalu coba lagi. Gestur ini tidak merekam ketikan atau layar.",
      "unavailable": "Pembantu gestur HUD tidak bisa dimulai atau berhenti mendadak. Coba lagi, atau mulai ulang Neovarch. Pintasan HUD biasa tetap berfungsi di dalam Neovarch.",
      "missingHelper": "Pemasangan Neovarch ini tidak punya pembantu gestur HUD. Perbarui atau pasang ulang Neovarch, lalu coba lagi.",
      "unsupportedSession": "Sesi desktop ini tidak mendukung ketukan modifier global. Linux butuh X11; Wayland tidak didukung."
    },
    "screenshot": {
      "enabledTitle": "Pintasan tangkapan layar",
      "enabledDesc": "Tekan kedua tombol Command bersamaan dari aplikasi mana pun untuk menangkap jendela terdepan dan melampirkannya ke draf Neovarch saat ini. Tidak pernah terkirim otomatis. Mati secara bawaan; hanya untuk Mac ini. Isi jendela bisa sensitif — periksa lampiran sebelum mengirim.",
      "statusTitle": "Status pintasan tangkapan layar",
      "checking": "Memeriksa pintasan tangkapan layar…",
      "disabled": "Pintasan tangkapan layar mati.",
      "starting": "Memulai pendengar pintasan. Belum siap.",
      "ready": "Pintasan siap. Tangkapan layar dilampirkan ke draf tanpa dikirim.",
      "inputPermission": "Izin Pemantauan Input membuat Neovarch bisa mendeteksi kedua tombol Command saat aplikasi lain aktif. Izinkan Neovarch di Pengaturan Sistem → Privasi & Keamanan → Pemantauan Input, lalu kembali dan coba lagi.",
      "screenPermission": "Izin Perekaman Layar membuat Neovarch bisa menangkap jendela aplikasi terdepan saat pintasan dipakai. Izinkan Neovarch di Pengaturan Sistem → Privasi & Keamanan → Perekaman Layar, lalu kembali dan coba lagi. Mulai ulang Neovarch bila macOS memintanya.",
      "openSettings": "Buka Pengaturan Sistem",
      "retry": "Coba lagi",
      "unavailable": "Pintasan tangkapan layar tidak tersedia. Coba lagi, atau matikan.",
      "errorTitle": "Galat pintasan tangkapan layar",
      "loadFailed": "Status pintasan tidak bisa dibaca. Coba lagi untuk memeriksa pengaturannya.",
      "saveFailed": "Perubahan pintasan tidak bisa dipastikan. Coba lagi untuk memeriksa pengaturannya.",
      "permissionFailed": "Pengaturan Sistem tidak bisa dibuka. Buka Privasi & Keamanan secara manual, lalu coba lagi.",
      "captureFailed": "Jendela terdepan tidak bisa ditangkap. Tidak ada yang dilampirkan atau dikirim.",
      "contextChanged": "Draf berubah saat penangkapan. Tangkapan layar tidak dilampirkan atau dikirim."
    },
    "quickEntry": {
      "enabledTitle": "Entri cepat",
      "enabledDesc": "Panggil composer kecil dari mana saja dengan pintasan global dan kirim prompt tanpa membuka Neovarch.",
      "shortcutTitle": "Pintasan entri cepat",
      "shortcutDesc": "Butuh minimal satu modifier, mis. CommandOrControl+Shift+Space.",
      "active": "Pintasan aktif.",
      "takenBy": "Aplikasi lain sudah memakai pintasan ini — pilih yang lain.",
      "invalidShortcut": "Pintasan tidak valid. Sertakan minimal satu tombol modifier."
    },
    "credentials": {
      "pasteKey": "Tempel key",
      "optional": "Opsional",
      "enterValueFirst": "Isi nilainya dulu.",
      "couldNotSave": "Kredensial tidak bisa disimpan.",
      "remove": "Hapus",
      "getKey": "Ambil key",
      "saving": "Menyimpan"
    },
    "envActions": {
      "actions": "Aksi",
      "manageInKeys": "Kelola di API key",
      "docs": "Dokumentasi",
      "hideValue": "Sembunyikan nilai",
      "revealValue": "Tampilkan nilai",
      "replace": "Ganti",
      "set": "Atur",
      "clear": "Bersihkan"
    },
    "connections": {
      "title": "Gateway terdaftar",
      "intro": "Kelola perangkat ini dan setiap gateway Neovarch yang bisa dijangkau lewat koneksi jarak jauh atau SSH.",
      "stagedNote": "Ganti gateway dari Sesi. Profil, obrolan, dan jadwal tetap di gateway masing-masing; kerja di gateway lain tetap berjalan.",
      "launchModeTitle": "Saat mulai, kembali ke Sesi di gateway terakhir",
      "launchModeDesc": "Bila mati, Sesi dibuka di gateway utama.",
      "searchPlaceholder": "Cari gateway…",
      "noSearchResults": "Tidak ada gateway yang cocok.",
      "loadFailed": "Koneksi tidak bisa dimuat",
      "currentPill": "Saat ini",
      "primaryPill": "Utama",
      "managedPill": "Dikelola aplikasi",
      "addConnection": "Tambah koneksi",
      "editConnection": "Ubah",
      "removeConnection": "Hapus",
      "removeConfirmTitle": "Hapus koneksi ini?",
      "makePrimary": "Jadikan utama",
      "testConnection": "Tes",
      "testOk": "Terjangkau",
      "testFailed": "Tes koneksi gagal",
      "saveFailed": "Koneksi tidak bisa disimpan",
      "removeFailed": "Koneksi tidak bisa dihapus",
      "updateAll": "Perbarui semua instans",
      "updateAllRunning": "Memperbarui semua instans…",
      "updateAllDone": "Pembaruan dikirim",
      "updateAllFailed": "Pengiriman pembaruan gagal",
      "updateSkippedCloud": "Dikelola cloud",
      "kindLocal": "Lokal",
      "kindRemote": "Gateway jarak jauh",
      "kindCloud": "Cloud",
      "kindSsh": "SSH",
      "kindLocalDesc": "Runtime Neovarch yang dikelola aplikasi ini.",
      "kindRemoteDesc": "Gateway Neovarch yang bisa dijangkau lewat HTTP(S) — LAN, Tailscale, atau internet.",
      "kindCloudDesc": "Instans terhosting (koneksi lama).",
      "kindSshDesc": "Pemasangan Neovarch yang dijangkau lewat SSH.",
      "labelTitle": "Nama",
      "labelDesc": "Wajib. Tampil di mana pun instans ini muncul; harus unik (mis. \"Server rumah\", \"Laptop kantor\").",
      "labelPlaceholder": "Server rumah",
      "urlTitle": "URL gateway",
      "sshHostTitle": "Host SSH",
      "headersTitle": "Header gateway tambahan",
      "headersDesc": "Dikirim bersama setiap permintaan HTTP dan WebSocket ke gateway ini — untuk proxy akses seperti Cloudflare Access (CF-Access-Client-Id / CF-Access-Client-Secret). Nilai disimpan terenkripsi. Header yang dikelola Neovarch (Authorization, Cookie, Host…) diabaikan.",
      "headerValuePlaceholder": "Nilai",
      "headerValueSaved": "Tersimpan — kosongkan untuk mempertahankan",
      "headerAdd": "Tambah header",
      "headerRemove": "Hapus",
      "duplicateLocal": "Aplikasi ini sudah mengelola koneksi lokal — hanya boleh satu.",
      "localAddHint": "Lokal tidak tersedia: koneksi lokal terkelola sudah ada (hanya ada satu).",
      "cloudAddHint": "Pakai formulir ini untuk mendaftarkan URL instans yang sudah diketahui secara manual.",
      "save": "Simpan koneksi",
      "saving": "Menyimpan…",
      "cancel": "Batal",
      "empty": "Belum ada koneksi terdaftar."
    },
    "managedUpdates": {
      "title": "Pembaruan terkelola",
      "intro": "Perbarui pemasangan SSH yang dikelola desktop secara transaksional: sesi dikosongkan, checkout jarak jauh diperbarui, dan setiap profil dipulihkan dengan tanda terima.",
      "sshConnection": "Pemasangan SSH yang dikelola desktop",
      "update": "Perbarui",
      "updating": "Memperbarui…",
      "progress": "Mengosongkan sesi, memperbarui pemasangan jarak jauh, dan memulihkan profil…",
      "updated": "Diperbarui",
      "partial": "Diperbarui — pemulihan gagal",
      "refused": "Ditolak",
      "failed": "Pembaruan gagal",
      "alreadyRunning": "Pembaruan sedang berjalan"
    },
    "gateway": {
      "loading": "Memuat pengaturan gateway…",
      "unavailableTitle": "Pengaturan gateway tidak tersedia",
      "unavailableDesc": "Pengaturan koneksi hanya bisa diubah dari aplikasi Neovarch Agent di komputer yang menjalankannya.",
      "title": "Koneksi gateway",
      "envOverride": "ditimpa env",
      "intro": "Lokal secara bawaan. Pakai jarak jauh bila aplikasi ini harus mengendalikan backend Neovarch di tempat lain. Koneksi gateway berlaku per mesin; profil ditemukan dari gateway yang terhubung.",
      "envOverrideTitle": "Koneksi ini ditetapkan oleh cara Neovarch dijalankan.",
      "envOverrideDesc": "Pengaturan startup di luar aplikasi memilih koneksi ini, jadi opsi di bawah hanya-baca. Mulai ulang Neovarch tanpa pengaturan itu — atau tanya yang menyiapkannya — untuk mengubahnya di sini.",
      "modeTitle": "Mode koneksi",
      "localTitle": "Gateway lokal",
      "localDesc": "Jalankan backend Neovarch privat di localhost. Ini bawaan dan bisa offline.",
      "remoteTitle": "Gateway jarak jauh",
      "remoteDesc": "Hubungkan aplikasi desktop ini ke backend Neovarch jarak jauh.",
      "remoteAuthHint": "Gateway terhosting memakai OAuth atau nama pengguna dan kata sandi; yang dihosting sendiri bisa memakai token sesi.",
      "cloudTitle": "Cloud (lama)",
      "cloudDesc": "Koneksi cloud lama. Pilih Lokal, Jarak jauh, atau SSH.",
      "cloudSignInTitle": "Cloud",
      "cloudSignIn": "Masuk ke cloud",
      "cloudSignedIn": "Sudah masuk ke cloud",
      "cloudNeedsSignIn": "Masuk ke cloud untuk menemukan agen di akun Anda.",
      "cloudSignedInDesc": "Anda sudah masuk. Pilih agen di bawah; sesi diperbarui otomatis.",
      "cloudAgentsTitle": "Agen Anda",
      "cloudOrgPickerTitle": "Pilih organisasi",
      "cloudOrgSelect": "Pilih",
      "cloudOrgChange": "Ganti organisasi",
      "cloudLoadingAgents": "Memuat agen Anda…",
      "cloudNoAgents": {
        "before": "Tidak ada agen di akun ini. Buat satu di ",
        "linkText": "portal",
        "after": ", lalu muat ulang."
      },
      "cloudRefresh": "Muat ulang",
      "cloudConnect": "Hubungkan",
      "cloudSavedTitle": "Gateway cloud tersimpan",
      "cloudSavedDesc": "Pakai gateway tersimpan tanpa mengubah bawaan. Kelola nama dan login di daftar koneksi tersimpan.",
      "cloudUseSaved": "Pakai gateway",
      "cloudActive": "Aktif di jendela ini",
      "cloudConnecting": "Menghubungkan…",
      "cloudDiscoverFailed": "Agen cloud tidak bisa dimuat",
      "cloudConnectFailed": "Tidak bisa terhubung ke agen itu",
      "cloudSignInFailed": "Gagal masuk ke cloud",
      "cloudSignedOutTitle": "Keluar dari cloud",
      "cloudSignedOutMessage": "Sesi cloud dihapus.",
      "cloudConnectedTitle": "Terhubung",
      "cloudConnectedPill": "Terhubung",
      "cloudAgentProvisioning": "Menyiapkan…",
      "remoteUrlTitle": "URL jarak jauh",
      "remoteUrlDesc": "URL dasar backend jarak jauh. Prefiks path didukung, mis. /neovarch.",
      "probing": "Memeriksa cara gateway ini mengautentikasi…",
      "probeError": "Neovarch tidak bisa menjangkau alamat itu. Periksa URL dan pastikan komputer lain menjalankan Neovarch — opsi masuk muncul setelah ia menjawab.",
      "signedIn": "Sudah masuk",
      "signIn": "Masuk",
      "signOut": "Keluar",
      "authTitle": "Autentikasi",
      "authSignedInPassword": "Gateway ini memakai nama pengguna dan kata sandi. Anda sudah masuk; sesi diperbarui otomatis.",
      "authSignedInOauth": "Gateway ini memakai OAuth. Anda sudah masuk; sesi diperbarui otomatis.",
      "authNeedsPassword": "Gateway ini memakai nama pengguna dan kata sandi. Masuk untuk mengizinkan aplikasi desktop ini.",
      "tokenTitle": "Token sesi",
      "tokenDesc": "Token sesi untuk akses REST dan WebSocket. Kosongkan untuk mempertahankan token tersimpan.",
      "savedToken": "tersimpan",
      "pasteSessionToken": "Tempel token sesi",
      "plainTextConfirmTitle": "Simpan token gateway sebagai teks biasa?",
      "plainTextConfirmDesc": "Layanan keyring sistem tidak ditemukan, jadi token akan disimpan tanpa enkripsi di file pengaturan koneksi aplikasi, bisa dibaca proses apa pun yang berjalan sebagai pengguna ini. Pasang atau aktifkan keychain sistem (GNOME Keyring atau KWallet di Linux) untuk penyimpanan terenkripsi.",
      "plainTextConfirmAction": "Simpan sebagai teks biasa",
      "plainTextStoredTitle": "Token disimpan sebagai teks biasa",
      "plainTextStoredDesc": "Penyimpanan aman tidak tersedia, jadi token disimpan tanpa enkripsi di file pengaturan koneksi di komputer ini. Pasang atau aktifkan keychain sistem (GNOME Keyring atau KWallet di Linux) untuk mengenkripsinya.",
      "keychainEncryptionTitle": "Enkripsi rahasia tersimpan dengan keychain sistem",
      "keychainEncryptionDesc": "Mati secara bawaan. Bila aktif, token gateway dan kredensial masuk dienkripsi dengan keychain sistem (Keychain Access, GNOME Keyring, atau Windows DPAPI) — sistem mungkin meminta izin atau kata sandi. Bila mati, disimpan sebagai file biasa yang hanya bisa dibaca akun Anda.",
      "keychainEncryptionFailed": "Enkripsi rahasia tidak bisa diubah",
      "testRemote": "Tes jarak jauh",
      "saveForRestart": "Simpan untuk mulai ulang berikutnya",
      "saveAndReconnect": "Simpan dan sambungkan ulang",
      "diagnostics": "Diagnostik",
      "diagnosticsDesc": "Tampilkan desktop.log di pengelola file — berguna bila gateway gagal dimulai.",
      "openLogs": "Buka log",
      "incompleteTitle": "Gateway jarak jauh belum lengkap",
      "incompleteSignIn": "Isi URL jarak jauh dan masuk sebelum beralih ke jarak jauh.",
      "incompleteToken": "Isi URL jarak jauh dan token sesi sebelum beralih ke jarak jauh.",
      "incompleteSignInTest": "Isi URL jarak jauh dan masuk sebelum menguji.",
      "incompleteTokenTest": "Isi URL jarak jauh dan token sesi sebelum menguji.",
      "enterUrlFirst": "Isi URL jarak jauh dulu.",
      "restartingTitle": "Koneksi gateway dimulai ulang",
      "savedTitle": "Pengaturan gateway tersimpan",
      "restartingMessage": "Neovarch Agent akan tersambung ulang dengan pengaturan tersimpan — aplikasi tetap terbuka.",
      "savedMessage": "Disimpan untuk mulai ulang berikutnya.",
      "reachableTitle": "Gateway jarak jauh terjangkau",
      "signedOutTitle": "Sudah keluar",
      "signedOutMessage": "Sesi gateway jarak jauh dihapus.",
      "failedLoad": "Pengaturan gateway gagal dimuat",
      "signInFailed": "Gagal masuk",
      "signOutFailed": "Gagal keluar",
      "testFailed": "Tes gateway jarak jauh gagal",
      "applyFailed": "Pengaturan gateway tidak bisa diterapkan",
      "saveFailed": "Pengaturan gateway tidak bisa disimpan",
      "sshTitle": "Hubungkan lewat SSH",
      "sshDesc": "Neovarch dijalankan di mesin jarak jauh lewat SSH dan disalurkan ke aplikasi ini — tidak ada yang perlu Anda jalankan atau buka sendiri. Butuh akses SSH berbasis key yang berfungsi.",
      "sshTrustHint": "Host key pertama dipercaya dan dipatok; perubahan setelahnya ditolak.",
      "sshHostTitle": "Host",
      "sshHostDesc": "user@host, atau alias Host dari ~/.ssh/config.",
      "sshHostPick": "Pilih host…",
      "sshHostPickTitle": "Host",
      "sshHostPickDesc": "Alias Host dari ~/.ssh/config, atau Kustom untuk mengetik sendiri.",
      "sshHostCustom": "Kustom (isi manual)…",
      "sshUserTitle": "Pengguna",
      "sshUserDesc": "Kosong = ~/.ssh/config atau pengguna saat ini.",
      "sshUserPlaceholder": "dari ~/.ssh/config",
      "sshPortTitle": "Port",
      "sshPortDesc": "Kosong = 22 atau port di ~/.ssh/config.",
      "sshKeyTitle": "File identitas",
      "sshKeyDesc": "Path private key. Kosong = ssh-agent atau ~/.ssh/config.",
      "sshHermesPathTitle": "Path Neovarch (opsional)",
      "sshHermesPathDesc": "Path lengkap ke program neovarch di mesin jarak jauh. Kosong = deteksi otomatis.",
      "sshHermesPathPlaceholder": "deteksi otomatis",
      "sshTestConnection": "Tes SSH",
      "sshConnect": "Hubungkan",
      "sshButtonsHint": "Simpan berlaku saat aplikasi dibuka lagi. Hubungkan menyambung ulang sekarang.",
      "sshIncompleteHost": "Isi host SSH sebelum menghubungkan.",
      "sshErrUnreachable": "Host itu tidak terjangkau lewat SSH. Periksa host, port, dan jaringan Anda.",
      "sshErrAuth": "Autentikasi SSH gagal. Muat key ke ssh-agent (ssh-add) atau atur IdentityFile di ~/.ssh/config — Neovarch menjalankan ssh tanpa interaksi.",
      "sshErrHostKey": "Host key BERUBAH sejak koneksi terakhir. Pastikan ini memang diharapkan, lalu jalankan ssh-keygen -R <host> dan sambungkan lagi.",
      "sshErrNotInstalled": "Core Neovarch belum terpasang di host jarak jauh. Pasang di sana atau atur path Neovarch.",
      "sshErrPlatform": "Platform jarak jauh tidak didukung. Mode SSH Neovarch Agent mendukung host Linux, macOS, dan Windows.",
      "sshErrTimeout": "Koneksi SSH kedaluwarsa. Host mungkin tidak terjangkau atau sedang tidur.",
      "sshErrUpdateRequired": "Perbarui Neovarch di host jarak jauh sebelum terhubung lewat SSH desktop.",
      "sshErrInteractiveAuth": "Tailscale SSH butuh pemeriksaan browser interaktif. Di terminal, jalankan `ssh <host> true`, selesaikan pemeriksaannya, lalu coba lagi — Neovarch menjalankan SSH tanpa interaksi.",
      "sshErrUnknown": "Koneksi SSH gagal."
    },
    "keys": {
      "loading": "Memuat API key dan kredensial…",
      "failedLoad": "API key gagal dimuat",
      "empty": "Belum ada yang diatur di kategori ini."
    },
    "search": {
      "placeholder": "Cari semua pengaturan…",
      "pill": "Cari"
    },
    "profileScope": {
      "appliesTo": "Berlaku untuk"
    },
    "mcp": {
      "loading": "Memuat server MCP…",
      "invalidJson": "JSON MCP tidak valid",
      "saveFailed": "Gagal menyimpan",
      "removeFailed": "Gagal menghapus",
      "reloadFailed": "Muat ulang MCP gagal",
      "savedTitle": "Server MCP tersimpan",
      "disabled": "nonaktif",
      "name": "Nama",
      "serverJson": "JSON server",
      "remove": "Hapus",
      "test": "Tes koneksi",
      "catalogLoading": "Memuat katalog MCP…",
      "catalogEnvRequired": "Isi nilai yang diperlukan sebelum memasang.",
      "statusConnecting": "Menghubungkan…",
      "statusNeedsAuth": "Perlu autentikasi",
      "statusError": "Galat",
      "statusOff": "Mati",
      "allServers": "Semua server",
      "authenticatedTitle": "Terautentikasi",
      "authenticate": "Autentikasi",
      "noOutput": "Belum ada keluaran.",
      "deepLinkTitle": "Tambah server MCP?",
      "deepLinkDescription": "Sebuah tautan meminta menambah server MCP ini ke Neovarch. Tinjau konfigurasinya di bawah — berasal dari tautan, bukan dari Neovarch.",
      "deepLinkStdioWarning": "Server ini menjalankan proses lokal di komputer Anda dengan perintah di bawah. Lanjutkan hanya bila Anda memercayai sumbernya.",
      "deepLinkConfirm": "Tambah server",
      "deepLinkNameInvalid": "Nama terdiri dari 1-64 huruf, angka, titik, tanda hubung, atau garis bawah.",
      "deepLinkErrorTitle": "Tautan pemasangan MCP ditolak",
      "deepLinkErrorName": "Nama server di tautan kosong atau tidak valid.",
      "deepLinkErrorConfig": "Konfigurasi di tautan bukan JSON berenkode base64 yang valid.",
      "deepLinkErrorShape": "Konfigurasi harus objek JSON dengan kolom string `url` atau `command`.",
      "deepLinkErrorUrl": "Hanya URL server http:// dan https:// yang diizinkan.",
      "deepLinkErrorTooLarge": "Muatan konfigurasi melebihi batas 32KB."
    },
    "model": {
      "setupProviderFallback": "penyedia",
      "staleAuxAfter": ", bukan model utama Anda.",
      "staleAuxOtherProviders": "penyedia lain",
      "moaEnabled": "Aktif",
      "moaSetDefault": "Jadikan bawaan",
      "moaNewPresetPlaceholder": "preset baru",
      "moaAddPreset": "Tambah preset",
      "customModel": "Model kustom…",
      "customModelPlaceholder": "ID model",
      "chooseFromList": "Pilih dari daftar",
      "moaDefault": "Bawaan:",
      "moaAddReference": "Tambah model referensi",
      "loading": "Memuat konfigurasi model…",
      "appliesDesc": "Berlaku untuk sesi baru. Pakai pemilih model di composer untuk mengganti model obrolan aktif.",
      "provider": "Penyedia",
      "model": "Model",
      "applying": "Menerapkan…",
      "mainAppliedTitle": "Model utama diperbarui",
      "defaultsLabel": "Bawaan",
      "reasoning": "Penalaran",
      "reasoningOff": "Mati",
      "speed": "Kecepatan",
      "speedStandard": "Standar",
      "defaultsFailed": "Gagal menyimpan bawaan model",
      "loadFailed": "Model tidak bisa dimuat",
      "restartRequired": "Backend ini menjalankan kode lama setelah pembaruan. Mulai ulang untuk memuat kode baru.",
      "restartBackend": "Mulai ulang backend",
      "restartingBackend": "Memulai ulang backend…",
      "restartFailed": "Backend tidak bisa dimulai ulang",
      "auxiliaryTitle": "Model pembantu",
      "resetAllToMain": "Kembalikan semua ke model utama",
      "staleAuxDismiss": "Jangan tampilkan lagi",
      "auxiliaryDesc": "Tugas pembantu berjalan di model utama secara bawaan. Tetapkan model khusus untuk tugas mana pun untuk menimpanya.",
      "setToMain": "Pakai model utama",
      "change": "Ubah",
      "autoUseMain": "otomatis · pakai model utama",
      "inheritMainEffort": "ikut · upaya model utama",
      "providerDefault": "(bawaan penyedia)",
      "fallbackAdd": "Tambah cadangan",
      "fallbackEmpty": "Tidak ada model cadangan — model bawaan dipakai kecuali gagal.",
      "notInCatalog": "tidak ada di daftar model penyedia ini — panggilan bisa jatuh ke cadangan.",
      "moaTitle": "Gabungan agen (MoA)",
      "moaPreset": "Preset",
      "moaDescription": "Atur preset bernama yang muncul sebagai model di bawah penyedia Gabungan agen. Agregator adalah model yang bertindak — ia menjalankan setiap langkah putaran tool, dan hampir semua biaya ditagihkan ke penyedianya. Referensi hanya memberi saran sekali per giliran secara bawaan.",
      "moaAggregator": "Agregator",
      "moaAggregatorBilled": "model yang bertindak · ditagih untuk prosesnya",
      "moaReferenceHint": "memberi saran sekali per giliran secara bawaan",
      "tasks": {
        "vision": {
          "label": "Penglihatan",
          "hint": "Analisis gambar"
        },
        "compression": {
          "label": "Pemadatan",
          "hint": "Pemadatan konteks"
        },
        "skills_hub": {
          "label": "Pusat skill",
          "hint": "Pencarian skill"
        },
        "approval": {
          "label": "Persetujuan",
          "hint": "Persetujuan otomatis cerdas"
        },
        "mcp": {
          "label": "MCP",
          "hint": "Perutean tool MCP"
        },
        "title_generation": {
          "label": "Judul",
          "hint": "Judul sesi"
        },
        "review": {
          "label": "Tinjauan",
          "hint": "Subagen peninjau /review"
        },
        "voice_chat": {
          "label": "Obrolan suara",
          "hint": "Jawaban lisan mode suara"
        },
        "triage_specifier": {
          "label": "Perinci triase",
          "hint": "Melengkapi spesifikasi Kanban"
        },
        "kanban_decomposer": {
          "label": "Pemecah Kanban",
          "hint": "Pemecahan tugas"
        },
        "profile_describer": {
          "label": "Penjelas profil",
          "hint": "Deskripsi profil otomatis"
        },
        "curator": {
          "label": "Kurator",
          "hint": "Tinjauan pemakaian skill"
        }
      }
    },
    "localModels": {
      "connectionChanged": "Koneksi model lokal berubah",
      "title": "Model lokal",
      "runtimeTitle": "Runtime lokal",
      "serverRunning": "Berjalan",
      "runtimeInstalled": "Runtime llama.cpp terpasang",
      "installTitle": "Pasang runtime lokal",
      "installDetail": "Mengunduh mesin inferensi llama.cpp (beberapa ratus MB). Model yang Anda unduh berjalan sepenuhnya di komputer ini — tanpa akun, tidak ada yang keluar dari komputer Anda.",
      "installAction": "Pasang runtime",
      "installing": "Memasang runtime…",
      "installFailed": "Pemasangan runtime gagal",
      "hardwareTitle": "Komputer ini",
      "hardwareLoading": "Memeriksa perangkat keras…",
      "unifiedMemory": "Memori terpadu",
      "modelsTitle": "Model",
      "recommended": "Disarankan",
      "recommendedReason": {
        "product-default": "Model bawaan untuk komputer ini, dipilih oleh pembuatnya.",
        "best-quality-resident": "Model berkualitas tertinggi yang berjalan sepenuhnya di GPU dengan kecepatan penuh. Pilihan menimbang kualitas terhadap perkiraan kecepatan di perangkat ini.",
        "speed-gated-quality": "Model berkualitas lebih tinggi muat di komputer ini tapi akan terlalu lambat karena bandwidth memorinya — ini model terbaik yang tetap cepat.",
        "fastest-resident": "Tidak ada model yang mencapai kecepatan penuh di perangkat ini; ini yang paling mendekati sambil berjalan sepenuhnya di memori GPU."
      },
      "noRecommendationTitle": "Tidak ada rekomendasi otomatis untuk komputer ini",
      "noRecommendationDetail": "Penyiapan otomatis butuh model kurasi yang muat sepenuhnya di GPU atau memori terpadu. Anda tetap bisa memilih model di bawah atau menjelajah model lain.",
      "noRecommendationAction": "Jelajahi model",
      "downloaded": "Terunduh",
      "downloadStatusRunning": "Mengunduh",
      "downloadPausedLabel": "Dijeda",
      "downloadPauseAction": "Jeda",
      "downloadResumeAction": "Lanjutkan",
      "installDoneToast": "Runtime lokal terpasang dan siap.",
      "quickstartTitle": "Jalankan model di komputer ini",
      "quickstartAction": "Siapkan untuk saya",
      "quickstartConfigure": "Saya pilih sendiri",
      "quickstartFailed": "Penyiapan model lokal gagal",
      "quickstartStageEngine": "Mesin",
      "quickstartStageModel": "Model",
      "quickstartStageFinish": "Selesai",
      "useAction": "Pakai",
      "activePill": "Bawaan",
      "updateTitle": "Pembaruan mesin tersedia",
      "updateAction": "Perbarui mesin",
      "updating": "Memperbarui mesin…",
      "upToDateTitle": "Mesin sudah terbaru",
      "activeDetail": "Obrolan baru memakai model ini — dimuat saat Anda mengirim pesan pertama",
      "activeNotLoaded": "Dimuat saat pesan pertama",
      "loadedPill": "Di memori",
      "placementResident": "semua di GPU",
      "placementSpilled": "sebagian di RAM",
      "placementResidentTip": "Berjalan sepenuhnya di memori GPU pada jendela konteks ini — kecepatan penuh.",
      "placementSpilledTip": "Sebagian model ini berjalan dari RAM sistem — tetap jalan, tapi lebih lambat. Versi lebih ringkas atau konteks lebih kecil akan muat penuh.",
      "loadingPill": "Memuat…",
      "ejectTip": "Bebaskan memori GPU (dimuat lagi di pesan berikutnya)",
      "ejected": "Model dilepas — memori GPU dibebaskan.",
      "ejectFailed": "Model tidak bisa dilepas",
      "stopServer": "Matikan",
      "startServer": "Nyalakan",
      "runtimeRunningDetail": "Server lokal berjalan. Mematikannya membebaskan semua memori GPU dan mencegah obrolan baru memakai model lokal sampai dinyalakan lagi.",
      "serverStopped": "Server lokal berhenti — memori GPU dibebaskan.",
      "serverStarted": "Server lokal berjalan.",
      "serverStopFailed": "Server lokal tidak bisa dihentikan",
      "serverStartFailed": "Server lokal tidak bisa dimulai",
      "activating": "Memulai…",
      "pillFitsGpu": "Muat di GPU Anda",
      "pillUsesRam": "Memakai RAM sistem",
      "pillTooBig": "Terlalu besar untuk komputer ini",
      "browseTitle": "Cari model lain",
      "browseHint": "Cari di seluruh Hugging Face. Model yang diunduh di sini disesuaikan otomatis dengan komputer Anda, tapi tidak kami uji.",
      "browsePlaceholder": "Cari model berdasarkan nama atau pembuat…",
      "browseSearching": "Mencari di Hugging Face",
      "browseListing": "Membaca file model",
      "browseShowFiles": "Tampilkan file",
      "browseRefresh": "Muat ulang",
      "browseDownloads": "unduhan",
      "browseLikes": "suka",
      "browseGated": "perlu masuk Hugging Face",
      "browseNoGguf": "Tidak ada file model yang kompatibel.",
      "browseFitUnknown": "Kecocokan tidak diketahui",
      "browseAlreadyDownloaded": "Sudah diunduh.",
      "addedByYou": "Ditambahkan oleh Anda",
      "browseDownloadStarted": "Mengunduh {name}",
      "browseDownloadAria": "Unduh {name}",
      "sideloadButton": "Tambah file model",
      "sideloadTitle": "Pilih file model GGUF",
      "sideloadDone": "{name} ditambahkan.",
      "sideloadAlreadyPresent": "Sudah ada di pustaka Anda.",
      "pillFullContextTip": "Berjalan dengan jendela konteks penuh model sejak awal",
      "pillGrowsTip": "Bertambah otomatis saat percakapan butuh ruang lebih",
      "pillVision": "Bisa melihat gambar",
      "deleteAction": "Hapus model",
      "deleteFailed": "Gagal menghapus"
    },
    "billing": {
      "freeTier": {
        "signIn": "Masuk",
        "title": "Anda memakai paket gratis",
        "message": "Masuk dengan akun untuk membuka lebih banyak model dan tool.",
        "caption": "Berjalan di model gratis dengan konektor. Masuk mempertahankan konektor dan menambah tool yang butuh akun serta model lain.",
        "name": "Paket gratis",
        "footnote": "Paket gratis tidak punya saldo dan tidak ada yang dibayar. Pembayaran dan pemakaian muncul setelah Anda masuk.",
        "plan": "Paket gratis",
        "model": "Model",
        "connectors": "Konektor",
        "included": "Termasuk"
      },
      "amountValidation": {
        "reloadTo": "Isi hingga",
        "greaterThanThreshold": "Jumlah isi ulang harus lebih besar dari ambang."
      },
      "stepUp": {
        "openVerification": "Buka halaman verifikasi",
        "dismiss": "Tutup",
        "waiting": "Menunggu tautan verifikasi…",
        "verify": "Verifikasi untuk lanjut",
        "deniedTitle": "Verifikasi tidak disetujui",
        "deniedBody": "Verifikasi selesai tanpa mengizinkan pembelanjaan jarak jauh untuk terminal ini.",
        "successTitle": "Verifikasi selesai",
        "successBody": "Pembelanjaan jarak jauh diizinkan untuk terminal ini."
      },
      "charge": {
        "failedTitle": "Penagihan gagal",
        "unconfirmedTitle": "Hasil penagihan belum pasti",
        "checkTitle": "Penagihan tidak bisa diperiksa",
        "checkBody": "Penagihan tidak bisa diperiksa.",
        "untrackedTitle": "Penagihan tidak bisa dilacak",
        "untrackedBody": "Layanan tagihan menerima permintaan tapi tidak mengembalikan ID penagihan.",
        "timeoutTitle": "Masih diproses setelah 5 menit",
        "timeoutBody": "Penagihan mungkin masih diselesaikan. Periksa portal sebelum mencoba lagi.",
        "authenticationRequired": "Bank Anda meminta verifikasi (3DS). Selesaikan di portal untuk menuntaskan pembelian ini.",
        "expired": "Kartu Anda kedaluwarsa. Perbarui di portal.",
        "declined": "Kartu Anda ditolak. Coba kartu lain di portal."
      },
      "title": "Tagihan",
      "preview": "pratinjau",
      "summary": {
        "balance": "Saldo",
        "plan": "Paket",
        "autoRefill": "Isi ulang otomatis"
      },
      "sections": {
        "invoices": "Faktur",
        "plan": "Paket",
        "paymentAndCredits": "Pembayaran & kredit",
        "usage": "Pemakaian"
      },
      "usage": {
        "title": "Pemakaian"
      },
      "buyCredits": {
        "customAmount": "Jumlah kredit kustom",
        "title": "Beli kredit sekarang",
        "buyButton": "Beli",
        "processing": "Memproses… memeriksa penyelesaian",
        "retry": "Coba lagi",
        "openPortal": "Buka portal"
      },
      "plan": {
        "title": "Paket",
        "changePlan": "Ganti paket",
        "viewPlans": "Lihat paket",
        "backAria": "Kembali ke tagihan",
        "current": "Paket saat ini",
        "scheduled": "Terjadwal",
        "empty": "Belum ada paket lain yang bisa dipilih.",
        "undo": "Urungkan",
        "undoing": "Mengurungkan…",
        "downgrade": "Turunkan",
        "confirmDowngrade": "Konfirmasi penurunan",
        "tryAgain": "Coba lagi",
        "checkingChange": "Memeriksa perubahan ini…",
        "cannotChange": "Perubahan itu tidak bisa dilakukan di sini.",
        "notScheduleable": "Perubahan ini tidak bisa dijadwalkan di sini.",
        "scheduling": "Menjadwalkan…",
        "cancel": "Batal"
      },
      "autoReload": {
        "threshold": "Ambang",
        "thresholdAria": "Ambang isi ulang otomatis",
        "reloadTo": "Isi hingga",
        "reloadToAria": "Jumlah isi ulang otomatis",
        "turnOffConfirm": "Matikan isi ulang otomatis?",
        "turnOff": "Matikan",
        "disable": "Nonaktifkan",
        "updated": "Isi ulang otomatis diperbarui.",
        "turnedOff": "Isi ulang otomatis dimatikan.",
        "manage": "Kelola",
        "save": "Simpan",
        "saving": "Menyimpan…",
        "cancel": "Batal"
      },
      "state": {
        "notice": {
          "loggedOut": {
            "title": "Hubungkan akun Anda",
            "message": "Masuk dengan akun untuk melihat saldo, paket, dan pemakaian di sini.",
            "action": "Masuk"
          },
          "openPortal": "Buka portal ↗",
          "noCard": {
            "title": "Belum ada metode pembayaran",
            "message": "Pembelian kredit dan isi ulang otomatis nonaktif sampai ada kartu tersimpan. Tambahkan di portal.",
            "action": "Tambah kartu ↗"
          }
        },
        "paymentMethod": {
          "title": "Metode pembayaran",
          "description": "Kelola kartu untuk isi ulang dan perpanjangan langganan.",
          "addAction": "Tambah metode pembayaran",
          "updateAction": "Perbarui",
          "provenance": {
            "autoRefill": "kartu isi ulang otomatis",
            "customerDefault": "bawaan pelanggan",
            "subPin": "kartu langganan"
          }
        },
        "buyCredits": {
          "description": "Satu penagihan di kartu Anda, ditambahkan ke saldo hari ini."
        },
        "autoRefill": {
          "title": "Isi ulang saat menipis",
          "genericDescription": "Jaga saldo tetap terisi saat turun di bawah ambang.",
          "offPill": "Mati",
          "enabledPill": "Aktif",
          "notAvailablePill": "—",
          "manageCaption": "Kelola isi ulang otomatis dari portal.",
          "turnOnCaption": "Nyalakan isi ulang otomatis dari portal",
          "distinctCardFallback": "kartu lain",
          "reconcileAction": "Rekonsiliasi ↗"
        },
        "usage": {
          "subscriptionCredits": {
            "title": "Kredit langganan",
            "barLabel": "Sisa kredit langganan"
          },
          "topupCredits": {
            "title": "Kredit isi ulang",
            "caption": "Tidak kedaluwarsa"
          },
          "monthlyCap": {
            "title": "Batas belanja bulanan",
            "barLabel": "Batas belanja bulanan terpakai",
            "captionDefault": "Batas bawaan",
            "captionSpending": "Belanja jarak jauh bulanan"
          }
        },
        "planCard": {
          "freeTier": "Gratis",
          "chooseAction": "Pilih ↗",
          "adjustPlanAction": "Ubah paket ↗",
          "unavailableCaption": "Detail langganan tidak tersedia; portal tetap bisa dibuka.",
          "noSubscriptionCaption": "Tidak ada langganan aktif — model berbayar memakai kredit isi ulang."
        }
      },
      "errors": {
        "consentRequired": {
          "title": "Perlu konfirmasi kartu",
          "message": "Konfirmasi kartu ini untuk penagihan terminal di portal"
        },
        "insufficientScope": {
          "title": "Pembelanjaan jarak jauh perlu persetujuan",
          "message": "Ini butuh izin pembelanjaan jarak jauh. Mulai isi ulang untuk mengizinkannya, lalu coba lagi."
        },
        "remoteSpendingRevoked": {
          "title": "Pembelanjaan jarak jauh dihentikan",
          "messageByAdmin": "Admin menghentikan pembelanjaan jarak jauh untuk terminal ini.",
          "messageBySelf": "Anda menghentikan pembelanjaan jarak jauh untuk terminal ini."
        },
        "sessionRevoked": {
          "title": "Sesi keluar",
          "message": "Sesi Anda dikeluarkan. Masuk lagi dari Pengaturan → Gateway."
        },
        "cliBillingDisabled": {
          "title": "Pembelanjaan jarak jauh mati",
          "message": "Pembelanjaan jarak jauh mati untuk akun ini — admin tagihan bisa menyalakannya dari portal."
        },
        "roleRequired": {
          "title": "Perlu peran admin",
          "message": "Menambah dana butuh admin/pemilik organisasi. Minta admin, atau kelola di portal."
        },
        "idempotencyConflict": {
          "title": "Mulai isi ulang baru",
          "message": "🔴 Kunci penagihan itu sudah dipakai untuk jumlah berbeda. Mulai isi ulang baru."
        },
        "noPaymentMethod": {
          "title": "Tidak ada kartu tersimpan",
          "message": "💳 Belum ada kartu tersimpan untuk penagihan terminal. Siapkan di portal (pembelian kredit sekali tidak menyimpan kartu)."
        },
        "orgAccessDenied": {
          "title": "Akses organisasi ditolak",
          "message": "Token ini tidak terikat ke organisasi yang bisa Anda kelola"
        },
        "monthlyCapExceeded": {
          "title": "Batas belanja bulanan tercapai",
          "messageReached": "🔴 Batas belanja bulanan tercapai."
        },
        "rateLimited": {
          "title": "Terlalu banyak penagihan saat ini"
        },
        "stripeUnavailable": {
          "title": "Stripe sedang bermasalah"
        },
        "upgradeCapExceeded": {
          "title": "Batas ganti paket harian tercapai",
          "message": "Batas ganti paket harian tercapai — coba lagi besok"
        },
        "endpointUnavailable": {
          "title": "Endpoint tagihan tidak tersedia",
          "message": "Endpoint tagihan mengembalikan respons non-JSON (mungkin tidak tersedia di instalasi ini)."
        },
        "timeout": {
          "title": "Permintaan tagihan kedaluwarsa",
          "message": "Permintaan tagihan kedaluwarsa."
        },
        "transport": {
          "title": "Koneksi tagihan gagal",
          "message": "Permintaan tagihan gagal sebelum mencapai gateway."
        },
        "default": {
          "title": "Permintaan tagihan gagal",
          "message": "Permintaan tagihan gagal."
        }
      }
    },
    "providers": {
      "connectAccount": "Hubungkan akun",
      "haveApiKey": "Punya API key?",
      "intro": "Masuk dengan langganan — tanpa menyalin API key. Neovarch menjalankan proses masuk browser untuk Anda, langsung di aplikasi.",
      "connected": "Terhubung",
      "collapse": "Ciutkan",
      "connectAnother": "Hubungkan penyedia lain",
      "otherProviders": "Penyedia lain",
      "disconnect": "Putuskan",
      "disconnectInTerminal": "Putuskan (menjalankan perintah penghapusan di terminal)",
      "removedTitle": "Akun dihapus",
      "noProviderKeys": "Tidak ada API key penyedia.",
      "searchKeys": "Cari penyedia…",
      "noKeysMatch": "Tidak ada penyedia yang cocok.",
      "localEndpoint": {
        "title": "Endpoint lokal / kustom",
        "description": "Arahkan Neovarch ke endpoint apa pun yang kompatibel OpenAI (9router, LiteLLM, vLLM, llama.cpp, Ollama, dll.)."
      },
      "loading": "Memuat penyedia…"
    },
    "sessions": {
      "loading": "Memuat sesi yang diarsipkan…",
      "archivedTitle": "Sesi diarsipkan",
      "archivedIntro": "Obrolan yang diarsipkan disembunyikan dari sidebar tapi semua pesannya tetap ada. Alt/⌥+Shift-klik obrolan di sidebar untuk mengarsipkannya.",
      "emptyArchivedTitle": "Belum ada arsip",
      "emptyArchivedDesc": "Arsipkan obrolan untuk menyimpannya di sini.",
      "unarchive": "Keluarkan dari arsip",
      "deletePermanently": "Hapus permanen",
      "restored": "Dipulihkan",
      "autoArchiveTitle": "Arsipkan otomatis obrolan lama",
      "autoArchiveDesc": "Arsipkan otomatis obrolan yang lama tidak disentuh. Obrolan yang disematkan tidak pernah diarsipkan, dan tidak ada yang dihapus — obrolan hanya dipindah ke sini.",
      "autoArchiveDaysLabel": "Arsipkan setelah",
      "autoArchiveDaysUnit": "hari tidak aktif",
      "autoArchiveFailed": "Arsip otomatis tidak bisa diperbarui",
      "defaultDirTitle": "Folder proyek bawaan",
      "defaultDirDesc": "Sesi baru dimulai di folder ini kecuali Anda memilih yang lain. Biarkan kosong untuk memakai folder home.",
      "defaultDirUpdated": "Folder proyek bawaan diperbarui — mulai obrolan baru (Ctrl/⌘+N) agar berlaku",
      "change": "Ubah",
      "choose": "Pilih",
      "clear": "Bersihkan",
      "notSet": "Belum diatur",
      "failedLoad": "Sesi yang diarsipkan tidak bisa dimuat",
      "unarchiveFailed": "Gagal mengeluarkan dari arsip",
      "deleteFailed": "Gagal menghapus",
      "updateDirFailed": "Folder bawaan tidak bisa diperbarui",
      "clearDirFailed": "Folder bawaan tidak bisa dibersihkan"
    },
    "toolsets": {
      "loadingConfig": "Memuat konfigurasi",
      "savedTitle": "Kredensial tersimpan",
      "removedTitle": "Kredensial dihapus",
      "set": "Diatur",
      "notSet": "Belum diatur",
      "selectedTitle": "Penyedia dipilih",
      "failedLoad": "Konfigurasi tool gagal dimuat",
      "noProviderOptions": "Toolset ini tidak punya opsi penyedia — aktifkan dan langsung jalan dengan pengaturan saat ini.",
      "noProviders": "Belum ada penyedia untuk toolset ini.",
      "ready": "Siap",
      "needsSignIn": "Perlu masuk",
      "needsSetup": "Perlu penyiapan",
      "activeBackend": "Aktif",
      "activeBackendHint": "Ini backend aktif Anda",
      "useBackend": "Pakai backend ini",
      "nousIncluded": "Termasuk dalam langganan — masuk dengan akun Anda untuk mengaktifkan.",
      "nousAuthNeededTitle": "Masuk dengan akun Anda",
      "nousAuthSignIn": "Masuk",
      "nousAuthDoneTitle": "Akun terhubung",
      "nousAuthDoneMessage": "Backend langganan Anda sekarang aktif.",
      "nousAuthFailed": "Proses masuk tidak selesai",
      "nousAuthFailedMessage": "Coba lagi.",
      "nousAuthTryAgain": "Coba lagi",
      "noApiKeyRequired": "Tidak perlu API key.",
      "postSetupInstalledHint": "Terpasang. Jalankan ulang penyiapan hanya bila ada yang rusak.",
      "postSetupRun": "Jalankan penyiapan",
      "postSetupRerun": "Jalankan ulang penyiapan",
      "postSetupInstalled": "Terpasang",
      "postSetupRunning": "Memasang…",
      "postSetupStarting": "Memulai…",
      "postSetupCompleteTitle": "Penyiapan selesai",
      "postSetupErrorTitle": "Penyiapan selesai dengan galat",
      "postSetupOpenLogs": "Buka log",
      "postSetupRunAgain": "Jalankan lagi",
      "webCapabilityUnset": "belum diatur",
      "webUseForSearch": "Pakai untuk pencarian",
      "webUseForExtract": "Pakai untuk ekstraksi",
      "webUsedForSearch": "Backend pencarian",
      "webUsedForExtract": "Backend ekstraksi",
      "loadingModels": "Memuat katalog model…",
      "modelSectionTitle": "Model",
      "modelInUse": "Dipakai",
      "modelDefault": "bawaan",
      "modelInactiveHint": "Pilih backend ini dulu untuk mengubah modelnya.",
      "modelSelectedTitle": "Model dipilih",
      "terminalBackend": {
        "sectionTitle": "Backend eksekusi",
        "loading": "Memeriksa backend eksekusi…",
        "failedLoad": "Backend terminal tidak bisa dimuat",
        "ready": "Siap",
        "needsSetup": "Perlu penyiapan",
        "unavailable": "Tidak tersedia",
        "inUse": "Dipakai",
        "selectedTitle": "Backend dipilih",
        "needsSetupHint": "Backend ini dipilih tanpa penyiapan lengkap — perintah akan gagal sampai penyiapan selesai.",
        "needsSetupConfirmDescriptionGeneric": "Backend ini belum disiapkan. Sesi yang dimulai setelah perubahan ini tidak punya tool terminal atau file sampai penyiapan selesai.",
        "needsSetupConfirmAction": "Tetap pilih",
        "unavailableTitle": "Perintah terminal tidak tersedia",
        "openBackendSettings": "Buka pengaturan terminal",
        "useLocal": "Pakai lokal",
        "switchedToLocal": "Perintah terminal sekarang berjalan lokal. Berlaku untuk sesi baru."
      },
      "browserRealProfile": {
        "label": "Pakai profil browser asli saya",
        "description": "Menyalin login dan cookie browser bawaan ke snapshot terkelola yang dipakai agen untuk menjelajah. Profil aktif Anda tidak pernah dibuka langsung. Berlaku untuk sesi baru.",
        "enabledTitle": "Penjelajahan profil asli aktif",
        "enabledMessage": "Sesi baru akan menjelajah dengan snapshot profil browser bawaan Anda.",
        "disabledTitle": "Penjelajahan profil asli mati",
        "disabledMessage": "Snapshot profil akan dihapus; sesi baru memakai browser bersih.",
        "failedSave": "Pengaturan profil asli tidak bisa disimpan",
        "prompt": {
          "title": "Tetap masuk di situs Anda",
          "body": "Biarkan Neovarch menjelajah dengan snapshot profil browser bawaan, sehingga situs terbuka dalam keadaan sudah masuk.",
          "bulletSnapshot": "Cookie dan login disalin ke snapshot terkelola.",
          "bulletLiveProfile": "Profil browser aktif Anda tidak pernah dibuka langsung.",
          "bulletLocal": "Tidak ada yang keluar dari komputer ini.",
          "dontShowAgain": "Jangan tampilkan lagi",
          "notNow": "Nanti saja",
          "enable": "Pakai profil saya"
        }
      }
    }
  },
  "sharedMetrics": {
    "sending": "Statistik tetap di komputer ini kecuali Anda memilih Bagikan. Neovarch tidak mengirim statistik ke layanan mana pun.",
    "share": "Bagikan",
    "sendLabel": "Bagikan statistik pemakaian",
    "sendDesc": "Neovarch tidak mengirim statistik ke luar. Statistik hanya disimpan di komputer ini.",
    "stripChoices": {
      "share": "Bagikan"
    }
  },
  "connectorsPage": {
    "card": {
      "inCatalog": "Di katalog"
    },
    "page": {
      "signInLine": "Masuk untuk memakai aplikasi terkelola.",
      "disconnectRefused": "Login ini belum bisa dihapus. Matikan aplikasinya dengan sakelar, atau coba lagi nanti."
    },
    "dialog": {
      "nousLine": "Aplikasi terkelola mengikuti akun Anda, bukan profil."
    },
    "tools": {
      "signedOutTitle": "Masuk untuk membaca daftar tool."
    }
  },
  "boot": {
    "failure": {
      "cloudDownTitle": "Agen cloud sedang mati",
      "cloudDownDescription": "Agen cloud yang dihubungi gateway ini mengembalikan galat server. Tidak bisa dimulai ulang dari sini — periksa statusnya atau beralih ke gateway lokal.",
      "cloudDownHint": "Beralih ke gateway lokal di Pengaturan → Remote / HP → Gateway."
    },
    "updateHold": {
      "recoveryHint": "Biasanya selesai dalam beberapa menit. Bila tidak: tutup Neovarch, akhiri proses git atau neovarch yang tersisa (atau mulai ulang komputer), lalu buka Neovarch lagi."
    }
  },
  "butterbar": {
    "legal": {
      "before": "Pemakaian Neovarch Agent tunduk pada "
    }
  },
  "billingBlock": {
    "titleNous": "Kredit habis"
  },
  "sendDiagnostics": {
    "title": "Simpan diagnostik",
    "privacyNotice": "Ini membuat paket debug lokal berisi info sistem (OS, versi, penyedia, API key mana yang diatur — tidak pernah key-nya) serta log agen, gateway, dan desktop. Tidak ada yang diunggah otomatis.",
    "failedHint": "Anda juga bisa menjalankan `neovarch doctor` dari terminal untuk mencetak laporan tanpa mengunggah.",
    "links": {
      "portal": "Isu di GitHub"
    }
  },
  "messaging": {
    "fieldCopy": {
      "MATRIX_USER_ID": {
        "placeholder": "@neovarch:contoh.org"
      }
    }
  },
  "profiles": {
    "fleet": {
      "localDevice": "Perangkat ini (backend lokal — memasang core Neovarch bila belum ada, lalu membuka sesi baru)",
      "installDeviceDesc": "Ini akan memasang core Neovarch di komputer ini, lalu membuka sesi baru. Tidak ada yang dipasang sampai Anda mengonfirmasi."
    },
    "remoteOverride": {
      "urlPlaceholder": "https://neovarch.contoh.com"
    }
  },
  "updates": {
    "versionDetailsDistributionSourceInstallerDesktop": "Sumber (skrip pemasangan) + Neovarch desktop",
    "versionDetailsDistributionSourceDesktop": "Sumber + Neovarch desktop"
  },
  "nvUpdate": {
    "title": "Pembaruan Neovarch",
    "installedVersion": "Versi terpasang {version}",
    "checkNow": "Periksa pembaruan",
    "checking": "Memeriksa GitHub Releases…",
    "upToDate": "Neovarch sudah versi terbaru.",
    "available": "Neovarch {version} tersedia",
    "checkFailed": "Gagal memeriksa pembaruan. Periksa koneksi lalu coba lagi.",
    "updateNow": "Update sekarang",
    "downloadInstall": "Unduh & pasang",
    "openRelease": "Buka halaman rilis",
    "fullNotes": "Catatan rilis lengkap",
    "installing": "Memasang pembaruan…",
    "downloading": "Mengunduh penginstal… {percent}",
    "installedRestart": "Pembaruan terpasang. Mulai ulang Neovarch untuk memakainya.",
    "restartNow": "Mulai ulang sekarang",
    "later": "Nanti",
    "launched": "Penginstal sudah terbuka. Neovarch akan ditutup agar pemasangan selesai.",
    "failed": "Pembaruan gagal",
    "fellBack": "Halaman rilis sudah dibuka agar bisa diunduh manual.",
    "manualHint": "Instalasi ini (AppImage atau .deb) diperbarui lewat halaman rilis.",
    "unsupportedHint": "Pembaruan untuk sistem ini lewat halaman rilis.",
    "noticeTitle": "Pembaruan tersedia",
    "noticeBody": "Neovarch {version} siap dipasang.",
    "noticeAction": "Lihat",
    "log": "Log penginstal"
  },
  "install": {
    "setupChoiceDesc": "Hubungkan aplikasi ini ke gateway Neovarch yang sudah berjalan, atau pasang core Neovarch di komputer ini.",
    "setupChoiceDescLocal": "Pasang core Neovarch di komputer ini, atau hubungkan ke gateway Neovarch yang sudah berjalan.",
    "installLocalTitle": "Pasang core Neovarch di komputer ini",
    "remoteUrlPlaceholder": "https://gateway.contoh.com/neovarch",
    "settingUpTitle": "Menyiapkan core Neovarch"
  },
  "freeTier": {
    "providerRowTitle": "Paket gratis",
    "providerRowPitch": "Masuk dengan akun untuk membuka lebih banyak model dan tool.",
    "signInInstead": "Masuk dengan akun",
    "stripTitle": "Inferensi gratis dan konektor sekarang tersedia.",
    "stripBody": "Buka pemilih model untuk mencobanya, atau masuk dengan akun.",
    "providerName": "Gratis",
    "signInHeading": "Masuk dengan akun untuk membuka lebih banyak model dan tool.",
    "rejectedBody": "Tidak masalah, Anda tetap di layanan gratis. Masuk kapan pun Anda siap.",
    "timedOutBody": "Mulai lagi kapan pun Anda siap. Anda tetap di layanan gratis.",
    "unreachableBody": "Neovarch tidak bisa menjangkau layanan untuk menyelesaikan proses masuk. Periksa koneksi internet dan coba lagi. Sesi Anda tetap ada.",
    "alreadySignedInBody": "Neovarch ini sudah masuk ke sebuah akun.",
    "offer": {
      "body": "Anda memakai jatah gratis. Bila terus dipakai, Anda akan mulai mencapai batas. Masuk dengan akun untuk jatah lebih besar."
    },
    "setupFailed": {
      "gateClosed": "Versi Neovarch ini tidak bisa dimulai tanpa akun. Masuk atau buat akun.",
      "unreachable": "Neovarch tidak bisa menjangkau layanan. Periksa koneksi internet, lalu ketuk Coba lagi. Atau hubungkan penyedia lain untuk sementara.",
      "serverError": "Layanan sedang tersendat. Ketuk Coba lagi sebentar lagi, atau hubungkan penyedia lain untuk sementara.",
      "powRequired": "Server meminta proof of work yang belum didukung. Masuk atau buat akun untuk lanjut.",
      "locked": "Sesi ini tidak bisa lanjut tanpa masuk. Masuk atau buat akun untuk lanjut.",
      "signInBelow": "Pilih penyedia di bawah."
    }
  },
  "notifications": {
    "voice": {
      "configureSpeechToText": "Atur suara-ke-teks untuk memakai mode suara.",
      "couldNotStartSession": "Sesi suara tidak bisa dimulai",
      "microphoneAccessDenied": "Akses mikrofon ditolak.",
      "microphoneConstraintsUnsupported": "Pengaturan mikrofon ini tidak didukung perangkat.",
      "microphoneFailed": "Mikrofon gagal",
      "microphoneInUse": "Mikrofon sedang dipakai aplikasi lain.",
      "microphonePermissionDenied": "Izin mikrofon ditolak.",
      "microphoneStartFailed": "Perekaman mikrofon tidak bisa dimulai.",
      "microphoneUnsupported": "Perekaman mikrofon tidak didukung di sini.",
      "noMicrophone": "Mikrofon tidak ditemukan.",
      "noSpeechDetected": "Suara tidak terdengar",
      "playbackFailed": "Pemutaran suara gagal",
      "recordingFailed": "Perekaman suara gagal",
      "transcriptionFailed": "Gagal mengubah suara jadi teks",
      "transcriptionUnavailable": "Dikte suara di PC belum tersedia. Ketik pesan, atau pakai mik di aplikasi HP.",
      "tryRecordingAgain": "Coba rekam lagi.",
      "unavailable": "Suara tidak tersedia"
    }
  },
  "modelPicker": {
    "proNeedsSubscription": "Model Pro butuh langganan berbayar."
  }
} as unknown as TranslationOverrides
