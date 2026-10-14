/**
 * Strings for Settings ▸ Tentang ▸ "Perbarui" (git pull update ala `hermes update`,
 * falling back to the GitHub Releases updater). One block per bundled locale; each
 * locale file layers its block under `nvPull`. `{branch}`, `{head}`, `{old}`, `{new}`
 * are filled in by the UI. Step and error ids match core/neovarch/pull_update.py.
 */
import type { Translations } from "./types";

export type NvPullTranslations = Translations["nvPull"];

export const nvPullEn: NvPullTranslations = {
  title: "Update from source",
  description:
    "Git installs pull the latest commits (fast-forward only), reinstall dependencies, check optional extras and restart. Other installs use the latest release.",
  button: "Update",
  detecting: "Checking how Neovarch is installed…",
  gitInstall: "Git install: {branch} @ {head}",
  releaseInstall: "Not a git install — using the latest release from GitHub.",
  running: "Updating…",
  upToDate: "Already up to date.",
  updated: "Updated {old} → {new}. Restart to use the new version.",
  restartNow: "Restart now",
  later: "Later",
  failed: "Update failed",
  rolledBack:
    "The repository was restored to the previous commit; nothing changed.",
  log: "Log",
  retry: "Try again",
  releaseManual:
    "This install cannot update itself. Download the new version from the release page.",
  openRelease: "Open release page",
  steps: {
    detect: "Detect install",
    clean: "Check local changes",
    fetch: "git fetch",
    pull: "git pull (fast-forward)",
    deps: "Reinstall dependencies",
    check: "Check latest release",
    install: "Run release installer",
    extras: "Check extras (Obsidian)",
    restart: "Restart",
  },
  errors: {
    dirty:
      "There are uncommitted local changes. Commit or stash them, then try again.",
    detached: "The repository is on a detached HEAD. Check out a branch first.",
    no_upstream: "This branch has no upstream to pull from.",
    diverged:
      "The local branch has commits that are not on the remote; a fast-forward is not possible.",
    fetch_failed: "git fetch failed. Check your internet connection.",
    merge_failed: "The fast-forward merge failed.",
    deps_failed: "Installing dependencies failed.",
    git_missing: "git was not found on this computer.",
    release_failed: "Updating from the latest release failed.",
    busy: "An update is already running.",
    aborted: "The update was cancelled.",
    internal: "Something went wrong while updating.",
    unreachable: "The Neovarch core is not reachable.",
  },
};

export const nvPullId: NvPullTranslations = {
  title: "Perbarui dari sumber",
  description:
    "Instalasi git menarik commit terbaru (hanya fast-forward), memasang ulang dependensi, memeriksa ekstra opsional, lalu memulai ulang. Instalasi lain memakai rilis terbaru.",
  button: "Perbarui",
  detecting: "Memeriksa cara Neovarch dipasang…",
  gitInstall: "Instalasi git: {branch} @ {head}",
  releaseInstall: "Bukan instalasi git — memakai rilis terbaru dari GitHub.",
  running: "Memperbarui…",
  upToDate: "Sudah versi terbaru.",
  updated: "Diperbarui {old} → {new}. Mulai ulang untuk memakai versi baru.",
  restartNow: "Mulai ulang sekarang",
  later: "Nanti",
  failed: "Pembaruan gagal",
  rolledBack: "Repo dipulihkan ke commit sebelumnya; tidak ada yang berubah.",
  log: "Log",
  retry: "Coba lagi",
  releaseManual:
    "Instalasi ini tidak bisa memperbarui dirinya sendiri. Unduh versi baru dari halaman rilis.",
  openRelease: "Buka halaman rilis",
  steps: {
    detect: "Deteksi instalasi",
    clean: "Cek perubahan lokal",
    fetch: "git fetch",
    pull: "git pull (fast-forward)",
    deps: "Pasang ulang dependensi",
    check: "Cek rilis terbaru",
    install: "Jalankan installer rilis",
    extras: "Cek ekstra (Obsidian)",
    restart: "Mulai ulang",
  },
  errors: {
    dirty:
      "Ada perubahan lokal yang belum di-commit. Commit atau stash dulu, lalu coba lagi.",
    detached: "Repo dalam keadaan detached HEAD. Checkout sebuah branch dulu.",
    no_upstream: "Branch ini tidak punya upstream untuk ditarik.",
    diverged:
      "Branch lokal punya commit yang tidak ada di remote; fast-forward tidak mungkin.",
    fetch_failed: "git fetch gagal. Periksa koneksi internet.",
    merge_failed: "Merge fast-forward gagal.",
    deps_failed: "Pemasangan dependensi gagal.",
    git_missing: "git tidak ditemukan di komputer ini.",
    release_failed: "Pembaruan dari rilis terbaru gagal.",
    busy: "Pembaruan sedang berjalan.",
    aborted: "Pembaruan dibatalkan.",
    internal: "Terjadi kesalahan saat memperbarui.",
    unreachable: "Core Neovarch tidak bisa dihubungi.",
  },
};

export const nvPullDe: NvPullTranslations = {
  title: "Aus der Quelle aktualisieren",
  description:
    "Git-Installationen holen die neuesten Commits (nur Fast-Forward), installieren Abhängigkeiten neu, prüfen optionale Extras und starten neu. Andere Installationen nutzen das neueste Release.",
  button: "Aktualisieren",
  detecting: "Installationsart wird geprüft…",
  gitInstall: "Git-Installation: {branch} @ {head}",
  releaseInstall:
    "Keine Git-Installation — es wird das neueste Release von GitHub verwendet.",
  running: "Wird aktualisiert…",
  upToDate: "Bereits auf dem neuesten Stand.",
  updated:
    "Aktualisiert {old} → {new}. Neu starten, um die neue Version zu nutzen.",
  restartNow: "Jetzt neu starten",
  later: "Später",
  failed: "Aktualisierung fehlgeschlagen",
  rolledBack:
    "Das Repository wurde auf den vorherigen Commit zurückgesetzt; nichts wurde geändert.",
  log: "Protokoll",
  retry: "Erneut versuchen",
  releaseManual:
    "Diese Installation kann sich nicht selbst aktualisieren. Laden Sie die neue Version von der Release-Seite.",
  openRelease: "Release-Seite öffnen",
  steps: {
    detect: "Installation erkennen",
    clean: "Lokale Änderungen prüfen",
    fetch: "git fetch",
    pull: "git pull (Fast-Forward)",
    deps: "Abhängigkeiten neu installieren",
    check: "Neuestes Release prüfen",
    install: "Release-Installer ausführen",
    extras: "Extras prüfen (Obsidian)",
    restart: "Neu starten",
  },
  errors: {
    dirty:
      "Es gibt nicht committete lokale Änderungen. Committen oder stashen Sie sie und versuchen Sie es erneut.",
    detached:
      "Das Repository ist im Zustand „detached HEAD“. Checken Sie zuerst einen Branch aus.",
    no_upstream: "Dieser Branch hat keinen Upstream.",
    diverged:
      "Der lokale Branch hat Commits, die nicht auf dem Remote sind; Fast-Forward ist nicht möglich.",
    fetch_failed:
      "git fetch ist fehlgeschlagen. Prüfen Sie die Internetverbindung.",
    merge_failed: "Der Fast-Forward-Merge ist fehlgeschlagen.",
    deps_failed: "Die Installation der Abhängigkeiten ist fehlgeschlagen.",
    git_missing: "git wurde auf diesem Computer nicht gefunden.",
    release_failed:
      "Die Aktualisierung aus dem neuesten Release ist fehlgeschlagen.",
    busy: "Eine Aktualisierung läuft bereits.",
    aborted: "Die Aktualisierung wurde abgebrochen.",
    internal: "Beim Aktualisieren ist ein Fehler aufgetreten.",
    unreachable: "Der Neovarch-Core ist nicht erreichbar.",
  },
};

export const nvPullEs: NvPullTranslations = {
  title: "Actualizar desde el código fuente",
  description:
    "Las instalaciones git descargan los últimos commits (solo fast-forward), reinstalan dependencias, revisan los extras opcionales y reinician. Las demás instalaciones usan la última versión publicada.",
  button: "Actualizar",
  detecting: "Comprobando cómo está instalado Neovarch…",
  gitInstall: "Instalación git: {branch} @ {head}",
  releaseInstall:
    "No es una instalación git: se usa la última versión de GitHub.",
  running: "Actualizando…",
  upToDate: "Ya está actualizado.",
  updated: "Actualizado {old} → {new}. Reinicia para usar la nueva versión.",
  restartNow: "Reiniciar ahora",
  later: "Más tarde",
  failed: "La actualización falló",
  rolledBack: "El repositorio se restauró al commit anterior; no cambió nada.",
  log: "Registro",
  retry: "Reintentar",
  releaseManual:
    "Esta instalación no puede actualizarse sola. Descarga la nueva versión desde la página de versiones.",
  openRelease: "Abrir página de versiones",
  steps: {
    detect: "Detectar instalación",
    clean: "Revisar cambios locales",
    fetch: "git fetch",
    pull: "git pull (fast-forward)",
    deps: "Reinstalar dependencias",
    check: "Comprobar última versión",
    install: "Ejecutar instalador",
    extras: "Revisar extras (Obsidian)",
    restart: "Reiniciar",
  },
  errors: {
    dirty:
      "Hay cambios locales sin commit. Haz commit o stash y vuelve a intentarlo.",
    detached:
      "El repositorio está en detached HEAD. Cambia primero a una rama.",
    no_upstream: "Esta rama no tiene upstream.",
    diverged:
      "La rama local tiene commits que no están en el remoto; no es posible un fast-forward.",
    fetch_failed: "git fetch falló. Revisa la conexión a internet.",
    merge_failed: "El merge fast-forward falló.",
    deps_failed: "La instalación de dependencias falló.",
    git_missing: "No se encontró git en este equipo.",
    release_failed: "La actualización desde la última versión falló.",
    busy: "Ya hay una actualización en curso.",
    aborted: "La actualización se canceló.",
    internal: "Algo salió mal al actualizar.",
    unreachable: "No se puede conectar con el núcleo de Neovarch.",
  },
};

export const nvPullFr: NvPullTranslations = {
  title: "Mettre à jour depuis la source",
  description:
    "Les installations git récupèrent les derniers commits (fast-forward uniquement), réinstallent les dépendances, vérifient les extras optionnels puis redémarrent. Les autres installations utilisent la dernière version publiée.",
  button: "Mettre à jour",
  detecting: "Vérification du type d’installation…",
  gitInstall: "Installation git : {branch} @ {head}",
  releaseInstall:
    "Pas une installation git — utilisation de la dernière version GitHub.",
  running: "Mise à jour…",
  upToDate: "Déjà à jour.",
  updated:
    "Mis à jour {old} → {new}. Redémarrez pour utiliser la nouvelle version.",
  restartNow: "Redémarrer maintenant",
  later: "Plus tard",
  failed: "Échec de la mise à jour",
  rolledBack: "Le dépôt a été restauré au commit précédent ; rien n’a changé.",
  log: "Journal",
  retry: "Réessayer",
  releaseManual:
    "Cette installation ne peut pas se mettre à jour seule. Téléchargez la nouvelle version depuis la page des versions.",
  openRelease: "Ouvrir la page des versions",
  steps: {
    detect: "Détecter l’installation",
    clean: "Vérifier les modifications locales",
    fetch: "git fetch",
    pull: "git pull (fast-forward)",
    deps: "Réinstaller les dépendances",
    check: "Vérifier la dernière version",
    install: "Lancer l’installateur",
    extras: "Vérifier les extras (Obsidian)",
    restart: "Redémarrer",
  },
  errors: {
    dirty:
      "Des modifications locales ne sont pas commitées. Faites un commit ou un stash, puis réessayez.",
    detached: "Le dépôt est en HEAD détachée. Passez d’abord sur une branche.",
    no_upstream: "Cette branche n’a pas d’upstream.",
    diverged:
      "La branche locale contient des commits absents du distant ; un fast-forward est impossible.",
    fetch_failed: "git fetch a échoué. Vérifiez la connexion internet.",
    merge_failed: "La fusion fast-forward a échoué.",
    deps_failed: "L’installation des dépendances a échoué.",
    git_missing: "git est introuvable sur cet ordinateur.",
    release_failed: "La mise à jour depuis la dernière version a échoué.",
    busy: "Une mise à jour est déjà en cours.",
    aborted: "La mise à jour a été annulée.",
    internal: "Un problème est survenu pendant la mise à jour.",
    unreachable: "Le cœur Neovarch est injoignable.",
  },
};

export const nvPullJa: NvPullTranslations = {
  title: "ソースから更新",
  description:
    "git インストールでは最新のコミットを取得し（fast-forward のみ）、依存関係を再インストールし、オプションの追加機能を確認してから再起動します。その他のインストールでは最新リリースを使います。",
  button: "更新",
  detecting: "インストール方法を確認しています…",
  gitInstall: "git インストール: {branch} @ {head}",
  releaseInstall:
    "git インストールではありません — GitHub の最新リリースを使います。",
  running: "更新しています…",
  upToDate: "すでに最新です。",
  updated:
    "{old} → {new} に更新しました。新しいバージョンを使うには再起動してください。",
  restartNow: "今すぐ再起動",
  later: "後で",
  failed: "更新に失敗しました",
  rolledBack: "リポジトリを以前のコミットに戻しました。変更はありません。",
  log: "ログ",
  retry: "再試行",
  releaseManual:
    "このインストールは自動更新できません。リリースページから新しいバージョンをダウンロードしてください。",
  openRelease: "リリースページを開く",
  steps: {
    detect: "インストールを検出",
    clean: "ローカルの変更を確認",
    fetch: "git fetch",
    pull: "git pull (fast-forward)",
    deps: "依存関係を再インストール",
    check: "最新リリースを確認",
    install: "リリースのインストーラーを実行",
    extras: "追加機能を確認 (Obsidian)",
    restart: "再起動",
  },
  errors: {
    dirty:
      "コミットされていないローカルの変更があります。コミットまたは stash してから再試行してください。",
    detached:
      "リポジトリが detached HEAD です。先にブランチをチェックアウトしてください。",
    no_upstream: "このブランチには upstream がありません。",
    diverged:
      "ローカルブランチにリモートにないコミットがあるため、fast-forward できません。",
    fetch_failed:
      "git fetch に失敗しました。インターネット接続を確認してください。",
    merge_failed: "fast-forward マージに失敗しました。",
    deps_failed: "依存関係のインストールに失敗しました。",
    git_missing: "このコンピューターで git が見つかりません。",
    release_failed: "最新リリースからの更新に失敗しました。",
    busy: "更新はすでに実行中です。",
    aborted: "更新はキャンセルされました。",
    internal: "更新中に問題が発生しました。",
    unreachable: "Neovarch コアに接続できません。",
  },
};

export const nvPullRu: NvPullTranslations = {
  title: "Обновить из исходников",
  description:
    "Git-установки получают последние коммиты (только fast-forward), переустанавливают зависимости, проверяют дополнительные компоненты и перезапускаются. Остальные установки используют последний релиз.",
  button: "Обновить",
  detecting: "Проверяем способ установки…",
  gitInstall: "Git-установка: {branch} @ {head}",
  releaseInstall:
    "Это не git-установка — используется последний релиз с GitHub.",
  running: "Обновление…",
  upToDate: "Уже последняя версия.",
  updated:
    "Обновлено {old} → {new}. Перезапустите, чтобы использовать новую версию.",
  restartNow: "Перезапустить сейчас",
  later: "Позже",
  failed: "Не удалось обновить",
  rolledBack:
    "Репозиторий восстановлен на предыдущий коммит; ничего не изменилось.",
  log: "Журнал",
  retry: "Повторить",
  releaseManual:
    "Эта установка не может обновиться сама. Скачайте новую версию со страницы релизов.",
  openRelease: "Открыть страницу релизов",
  steps: {
    detect: "Определить установку",
    clean: "Проверить локальные изменения",
    fetch: "git fetch",
    pull: "git pull (fast-forward)",
    deps: "Переустановить зависимости",
    check: "Проверить последний релиз",
    install: "Запустить установщик",
    extras: "Проверить компоненты (Obsidian)",
    restart: "Перезапуск",
  },
  errors: {
    dirty:
      "Есть незакоммиченные локальные изменения. Сделайте commit или stash и повторите.",
    detached:
      "Репозиторий в состоянии detached HEAD. Сначала переключитесь на ветку.",
    no_upstream: "У этой ветки нет upstream.",
    diverged:
      "В локальной ветке есть коммиты, которых нет на удалённом; fast-forward невозможен.",
    fetch_failed: "git fetch не удался. Проверьте подключение к интернету.",
    merge_failed: "Fast-forward слияние не удалось.",
    deps_failed: "Не удалось установить зависимости.",
    git_missing: "git не найден на этом компьютере.",
    release_failed: "Не удалось обновиться из последнего релиза.",
    busy: "Обновление уже выполняется.",
    aborted: "Обновление отменено.",
    internal: "Во время обновления что-то пошло не так.",
    unreachable: "Ядро Neovarch недоступно.",
  },
};

export const nvPullAr: NvPullTranslations = {
  title: "التحديث من المصدر",
  description:
    "تسحب تثبيتات git أحدث الإيداعات (تقديم سريع فقط)، وتعيد تثبيت الاعتماديات، وتتحقق من الإضافات الاختيارية، ثم تعيد التشغيل. تستخدم التثبيتات الأخرى أحدث إصدار.",
  button: "تحديث",
  detecting: "جارٍ التحقق من طريقة تثبيت Neovarch…",
  gitInstall: "تثبيت git: {branch} @ {head}",
  releaseInstall: "ليس تثبيت git — يُستخدم أحدث إصدار من GitHub.",
  running: "جارٍ التحديث…",
  upToDate: "أنت على أحدث إصدار.",
  updated: "تم التحديث {old} ← {new}. أعد التشغيل لاستخدام الإصدار الجديد.",
  restartNow: "إعادة التشغيل الآن",
  later: "لاحقًا",
  failed: "فشل التحديث",
  rolledBack: "أُعيد المستودع إلى الإيداع السابق؛ لم يتغير شيء.",
  log: "السجل",
  retry: "إعادة المحاولة",
  releaseManual:
    "لا يمكن لهذا التثبيت تحديث نفسه. نزّل الإصدار الجديد من صفحة الإصدارات.",
  openRelease: "فتح صفحة الإصدارات",
  steps: {
    detect: "اكتشاف التثبيت",
    clean: "فحص التغييرات المحلية",
    fetch: "git fetch",
    pull: "git pull (تقديم سريع)",
    deps: "إعادة تثبيت الاعتماديات",
    check: "التحقق من أحدث إصدار",
    install: "تشغيل مثبّت الإصدار",
    extras: "فحص الإضافات (Obsidian)",
    restart: "إعادة التشغيل",
  },
  errors: {
    dirty:
      "توجد تغييرات محلية غير مودعة. أودعها أو خبّئها (stash) ثم أعد المحاولة.",
    detached: "المستودع في حالة detached HEAD. انتقل إلى فرع أولًا.",
    no_upstream: "لا يوجد upstream لهذا الفرع.",
    diverged:
      "يحتوي الفرع المحلي على إيداعات غير موجودة في البعيد؛ التقديم السريع غير ممكن.",
    fetch_failed: "فشل git fetch. تحقق من اتصال الإنترنت.",
    merge_failed: "فشل الدمج بالتقديم السريع.",
    deps_failed: "فشل تثبيت الاعتماديات.",
    git_missing: "لم يُعثر على git في هذا الحاسوب.",
    release_failed: "فشل التحديث من أحدث إصدار.",
    busy: "يوجد تحديث قيد التشغيل بالفعل.",
    aborted: "أُلغي التحديث.",
    internal: "حدث خطأ أثناء التحديث.",
    unreachable: "لا يمكن الوصول إلى نواة Neovarch.",
  },
};

export const nvPullZh: NvPullTranslations = {
  title: "从源码更新",
  description:
    "git 安装会拉取最新提交（仅快进）、重新安装依赖、检查可选扩展，然后重启。其他安装方式使用最新发布版本。",
  button: "更新",
  detecting: "正在检查 Neovarch 的安装方式…",
  gitInstall: "git 安装：{branch} @ {head}",
  releaseInstall: "不是 git 安装 — 使用 GitHub 上的最新发布版本。",
  running: "正在更新…",
  upToDate: "已是最新版本。",
  updated: "已更新 {old} → {new}。重启以使用新版本。",
  restartNow: "立即重启",
  later: "稍后",
  failed: "更新失败",
  rolledBack: "仓库已恢复到之前的提交，没有任何改动。",
  log: "日志",
  retry: "重试",
  releaseManual: "此安装无法自行更新。请从发布页面下载新版本。",
  openRelease: "打开发布页面",
  steps: {
    detect: "检测安装",
    clean: "检查本地改动",
    fetch: "git fetch",
    pull: "git pull（快进）",
    deps: "重新安装依赖",
    check: "检查最新发布",
    install: "运行发布安装程序",
    extras: "检查扩展（Obsidian）",
    restart: "重启",
  },
  errors: {
    dirty: "存在未提交的本地改动。请先提交或 stash，然后重试。",
    detached: "仓库处于 detached HEAD 状态。请先切换到一个分支。",
    no_upstream: "此分支没有上游分支。",
    diverged: "本地分支有远端没有的提交，无法快进。",
    fetch_failed: "git fetch 失败。请检查网络连接。",
    merge_failed: "快进合并失败。",
    deps_failed: "依赖安装失败。",
    git_missing: "在此电脑上找不到 git。",
    release_failed: "从最新发布版本更新失败。",
    busy: "已有更新正在进行。",
    aborted: "更新已取消。",
    internal: "更新时出错。",
    unreachable: "无法连接 Neovarch 核心。",
  },
};

export const nvPullZhHant: NvPullTranslations = {
  title: "從原始碼更新",
  description:
    "git 安裝會拉取最新提交（僅快轉）、重新安裝相依套件、檢查選用擴充功能，然後重新啟動。其他安裝方式使用最新發行版本。",
  button: "更新",
  detecting: "正在檢查 Neovarch 的安裝方式…",
  gitInstall: "git 安裝：{branch} @ {head}",
  releaseInstall: "不是 git 安裝 — 使用 GitHub 上的最新發行版本。",
  running: "正在更新…",
  upToDate: "已是最新版本。",
  updated: "已更新 {old} → {new}。重新啟動以使用新版本。",
  restartNow: "立即重新啟動",
  later: "稍後",
  failed: "更新失敗",
  rolledBack: "儲存庫已還原到先前的提交，沒有任何變更。",
  log: "記錄",
  retry: "重試",
  releaseManual: "此安裝無法自行更新。請從發行頁面下載新版本。",
  openRelease: "開啟發行頁面",
  steps: {
    detect: "偵測安裝",
    clean: "檢查本機變更",
    fetch: "git fetch",
    pull: "git pull（快轉）",
    deps: "重新安裝相依套件",
    check: "檢查最新發行",
    install: "執行發行安裝程式",
    extras: "檢查擴充功能（Obsidian）",
    restart: "重新啟動",
  },
  errors: {
    dirty: "有尚未提交的本機變更。請先提交或 stash，然後重試。",
    detached: "儲存庫處於 detached HEAD 狀態。請先切換到一個分支。",
    no_upstream: "此分支沒有上游分支。",
    diverged: "本機分支有遠端沒有的提交，無法快轉。",
    fetch_failed: "git fetch 失敗。請檢查網路連線。",
    merge_failed: "快轉合併失敗。",
    deps_failed: "相依套件安裝失敗。",
    git_missing: "在這台電腦上找不到 git。",
    release_failed: "從最新發行版本更新失敗。",
    busy: "已有更新正在進行。",
    aborted: "更新已取消。",
    internal: "更新時發生錯誤。",
    unreachable: "無法連線到 Neovarch 核心。",
  },
};
