package com.neovarch.agent

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.Log
import org.json.JSONObject
import org.vosk.Model
import org.vosk.Recognizer
import org.vosk.android.RecognitionListener
import org.vosk.android.SpeechService
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.zip.ZipInputStream

/**
 * "Hey Neo" wake word (opt-in, Profil → Hey Neo). A microphone foreground
 * service runs Vosk offline with a two-entry grammar ("hey neo" / [unk]), so
 * nothing leaves the phone and nothing but the phrase is recognised. The small
 * English model (~40 MB) is downloaded the first time it is switched on. On a
 * match the app opens on the Chat dictation route (`nv_route=voice`); when
 * Android blocks the activity start from the background a heads-up
 * notification does the same on tap.
 *
 * Boot: a microphone foreground service may not be started from
 * BOOT_COMPLETED on Android 14+, and since Android 11 one started from the
 * background gets no microphone access, so [NvBootReceiver] posts a
 * notification ("ketuk untuk menyalakan lagi") instead; tapping it opens the
 * app (`nv_route=wake`), which restarts the service from the foreground.
 */
class NvWakeService : Service(), RecognitionListener {
    private var speech: SpeechService? = null
    private var model: Model? = null
    private val main = Handler(Looper.getMainLooper())
    private var lastHit = 0L
    @Volatile private var stopped = false
    /** The app's own dictation holds the microphone (see [holdMic]). */
    @Volatile private var held = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        stopped = false
        try {
            startInForeground("Hey Neo menyiapkan…")
        } catch (e: Exception) {
            // Android 12+/14: a microphone service may not start from the background.
            Log.w(TAG, "startForeground refused: ${e.message}")
            setState(this, "stopped")
            notifyUser(this, NvLocale.str(this, R.string.nv_wake_stopped), NvLocale.str(this, R.string.nv_wake_tap_restart), "wake", BOOT_ID)
            stopSelf()
            return START_NOT_STICKY
        }
        // Restarted by the system after MIUI/Android killed it (intent == null):
        // since Android 11 a background start gets a silent microphone, so the
        // service would run "deaf". Ask the user to reopen it instead.
        if (intent == null && Build.VERSION.SDK_INT >= 30) {
            Log.w(TAG, "sticky restart from background: microphone would be silenced")
            setState(this, "stopped")
            notifyUser(this, NvLocale.str(this, R.string.nv_wake_killed), NvLocale.str(this, R.string.nv_wake_tap_restart), "wake", BOOT_ID)
            stopSelf()
            return START_NOT_STICKY
        }
        current = this
        if (speech == null) Thread { prepareAndListen() }.start()
        return START_STICKY
    }

    private fun startInForeground(text: String) {
        val n = ongoing(text)
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(NOTIF_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        } else {
            startForeground(NOTIF_ID, n)
        }
    }

    private fun prepareAndListen() {
        try {
            val dir = modelDir(this)
            if (!File(dir, "am").exists() && !File(dir, "conf").exists()) {
                setState(this, "downloading:0:0")
                update("Mengunduh model suara…", 0, 0)
                download(dir)
            }
            if (stopped) return
            Log.i(TAG, "loading model from ${dir.absolutePath}")
            val m = Model(dir.absolutePath)
            model = m
            val rec = Recognizer(m, 16000f, GRAMMAR)
            val s = SpeechService(rec, 16000f)
            speech = s
            s.startListening(this)
            Log.i(TAG, "listening, grammar=$GRAMMAR")
            setState(this, "listening")
            update("Mendengarkan \"Hey Neo\"")
        } catch (e: Exception) {
            Log.e(TAG, "prepare failed", e)
            setState(this, "error:" + (e.message ?: e.toString()))
            update("Hey Neo gagal: ${e.message ?: e}")
        }
    }

    private fun download(dir: File) {
        val tmp = File(cacheDir, "vosk-model.zip")
        var lastUi = 0L
        ModelDownloader(MODEL_URLS).fetch(tmp, { stopped }) { ev ->
            val now = System.currentTimeMillis()
            when (ev) {
                is ModelDownloader.Event.Progress -> if (now - lastUi >= 700 || ev.done == ev.total) {
                    lastUi = now
                    setState(this, "downloading:${ev.done}:${ev.total}")
                    update(ModelDownloader.progressText(ev.done, ev.total), ev.done, ev.total)
                }
                is ModelDownloader.Event.Retry -> {
                    setState(this, "retrying:${ev.attempt}:${ev.reason}")
                    update("Unduhan macet, mencoba lagi… (${ev.attempt}/${ModelDownloader.ATTEMPTS})")
                }
            }
        }
        if (stopped) return
        val staging = File(filesDir, "vosk-staging").apply { deleteRecursively(); mkdirs() }
        ZipInputStream(tmp.inputStream()).use { z ->
            var e = z.nextEntry
            while (e != null) {
                // drop the zip's top folder (vosk-model-small-en-us-0.15/...)
                val rel = e.name.substringAfter('/', "")
                if (rel.isNotEmpty() && !rel.contains("..")) {
                    val f = File(staging, rel)
                    if (e.isDirectory) f.mkdirs() else {
                        f.parentFile?.mkdirs()
                        FileOutputStream(f).use { z.copyTo(it) }
                    }
                }
                e = z.nextEntry
            }
        }
        tmp.delete()
        dir.deleteRecursively()
        if (!staging.renameTo(dir)) throw IllegalStateException("model tidak bisa dipasang")
    }

    private var lastHeardAt = 0L

    /** "Tes Hey Neo": the last thing the recogniser heard, for the panel. */
    private fun heard(text: String) {
        if (text.isBlank()) return
        val now = System.currentTimeMillis()
        if (now - lastHeardAt < 250) return
        val p = getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        // only while "Tes Hey Neo" runs (no constant disk writes otherwise)
        if (now >= p.getLong("testUntil", 0)) return
        lastHeardAt = now
        p.edit().putString("heard", text).putLong("heardAt", now).apply()
        Log.d(TAG, "heard: $text")
    }

    private fun hit(text: String) {
        heard(text)
        if (!matches(text)) return
        Log.i(TAG, "wake phrase matched: $text")
        val now = System.currentTimeMillis()
        if (now - lastHit < 4000) return
        lastHit = now
        // Let the app's dictation have the microphone for a while.
        speech?.setPause(true)
        main.postDelayed({ if (!held) speech?.setPause(false) }, 20000)
        val open = Intent(this, MainActivity::class.java)
            .putExtra(EXTRA_ROUTE, "voice")
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        var opened = false
        // Background activity starts are allowed with "Tampil di atas aplikasi lain".
        if (Build.VERSION.SDK_INT < 29 || android.provider.Settings.canDrawOverlays(this)) {
            try {
                startActivity(open)
                opened = true
            } catch (e: Exception) {
                Log.w(TAG, "activity start blocked: ${e.message}")
            }
        }
        // Otherwise (or as well): heads-up notification with a full-screen intent,
        // which Android shows over the lock screen / opens directly when allowed.
        notifyUser(this, "Hey Neo", NvLocale.str(this, R.string.nv_wake_tap_talk), "voice", HIT_ID, fullScreen = !opened)
    }

    override fun onPartialResult(hypothesis: String?) {
        hypothesis?.let { hit(JSONObject(it).optString("partial")) }
    }

    override fun onResult(hypothesis: String?) {
        hypothesis?.let { hit(JSONObject(it).optString("text")) }
    }

    override fun onFinalResult(hypothesis: String?) {}
    override fun onError(exception: Exception?) {
        Log.e(TAG, "recognizer error", exception)
        setState(this, "error:" + (exception?.message ?: "mikrofon"))
        update("Hey Neo berhenti: ${exception?.message ?: "mikrofon"}")
    }
    override fun onTimeout() {}

    override fun onDestroy() {
        stopped = true
        if (current === this) current = null
        main.removeCallbacksAndMessages(null)
        speech?.stop()
        speech?.shutdown()
        speech = null
        model?.close()
        model = null
        if (enabled(this)) setState(this, "stopped") else setState(this, "off")
        super.onDestroy()
    }

    private fun update(text: String, done: Long = -1, total: Long = -1) {
        (getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager).notify(NOTIF_ID, ongoing(text, done, total))
    }

    private fun ongoing(text: String, done: Long = -1, total: Long = -1): Notification {
        val b = builder(this, CHANNEL_QUIET, "Hey Neo", NotificationManager.IMPORTANCE_LOW)
        if (done >= 0) {
            if (total > 0) b.setProgress(1000, (done * 1000 / total).toInt(), false) else b.setProgress(0, 0, true)
        }
        return b.setSmallIcon(R.mipmap.ic_launcher_foreground)
            .setContentTitle("Hey Neo")
            .setContentText(text)
            .setOnlyAlertOnce(true)
            .setOngoing(true)
            .setContentIntent(openApp(this, "profile", 50))
            .build()
    }

    companion object {
        const val EXTRA_ROUTE = "nv_route"
        private const val NOTIF_ID = 7301
        private const val HIT_ID = 7302
        const val BOOT_ID = 7303
        private const val CHANNEL_QUIET = "nv_wake"
        private const val CHANNEL_ALERT = "nv_wake_alert"
        private const val PREFS = "nv_wake"
        const val MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
        /** GitHub mirror first (fast CDN, range requests), then the original. */
        const val MIRROR_URL = "https://raw.githubusercontent.com/Maftuuh1922/neovrach_Agent/assets-vosk/vosk-model-small-en-us-0.15.zip"
        val MODEL_URLS = listOf(MIRROR_URL, MODEL_URL)
        private const val TAG = "NeovarchWake"
        /** Only the phrase (in-vocabulary sound-alikes) and "unknown"; see [WakePhrase]. */
        val GRAMMAR = WakePhrase.GRAMMAR

        fun matches(text: String?): Boolean = WakePhrase.matches(text)

        /** "Tes Hey Neo": log what is heard for the next 60 s (also shown in the panel). */
        fun startTest(c: Context) = c.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putLong("testUntil", System.currentTimeMillis() + 60000).remove("heard").remove("heardAt").apply()

        @Volatile private var current: NvWakeService? = null

        /**
         * Give the microphone to the app's dictation (or take it back). Two
         * recognisers on one mic made dictation fail with an audio error
         * while "Hey Neo" was listening. No-op when the service is not running.
         */
        fun holdMic(on: Boolean): Boolean {
            val s = current ?: return false
            s.main.post {
                s.held = on
                try {
                    s.speech?.setPause(on)
                } catch (e: Exception) {
                    // the recogniser is shutting down
                }
            }
            return true
        }

        fun modelDir(c: Context) = File(c.filesDir, "vosk-model-en")
        fun enabled(c: Context) = c.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean("enabled", false)
        fun setState(c: Context, s: String) = c.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString("state", s).apply()

        fun status(c: Context): Map<String, Any?> {
            val p = c.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            val d = modelDir(c)
            return mapOf(
                "enabled" to p.getBoolean("enabled", false),
                "state" to p.getString("state", "off"),
                "modelReady" to (File(d, "am").exists() || File(d, "conf").exists()),
                "heard" to p.getString("heard", null),
                "heardAt" to p.getLong("heardAt", 0),
                "testUntil" to p.getLong("testUntil", 0),
                "matched" to matches(p.getString("heard", null)),
            )
        }

        /** Switch on/off (from the app, in the foreground). */
        fun setEnabled(c: Context, on: Boolean) {
            c.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean("enabled", on).apply()
            val i = Intent(c, NvWakeService::class.java)
            if (on) {
                if (Build.VERSION.SDK_INT >= 26) c.startForegroundService(i) else c.startService(i)
            } else {
                c.stopService(i)
                setState(c, "off")
            }
        }

        fun openApp(c: Context, route: String, code: Int): PendingIntent = PendingIntent.getActivity(
            c, code,
            Intent(c, MainActivity::class.java).putExtra(EXTRA_ROUTE, route)
                .setAction("com.neovarch.agent.wake.$route")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)

        private fun builder(c: Context, channel: String, name: String, importance: Int): Notification.Builder =
            if (Build.VERSION.SDK_INT >= 26) {
                (c.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager)
                    .createNotificationChannel(NotificationChannel(channel, name, importance))
                Notification.Builder(c, channel)
            } else {
                @Suppress("DEPRECATION")
                Notification.Builder(c)
            }

        fun notifyUser(c: Context, title: String, body: String, route: String, id: Int, fullScreen: Boolean = false) {
            val b = builder(c, CHANNEL_ALERT, "Hey Neo (panggilan)", NotificationManager.IMPORTANCE_HIGH)
                .setSmallIcon(R.mipmap.ic_launcher_foreground)
                .setContentTitle(title)
                .setContentText(body)
                .setAutoCancel(true)
                .setCategory(Notification.CATEGORY_CALL)
                .setContentIntent(openApp(c, route, id))
            if (fullScreen) b.setFullScreenIntent(openApp(c, route, id + 1), true)
            val n = b.build()
            try {
                (c.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager).notify(id, n)
            } catch (e: SecurityException) {
                // notifications not allowed
            }
        }
    }
}

/** After a reboot: restart Hey Neo where Android allows it, else ask with a notification. */
class NvBootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED || !NvWakeService.enabled(context)) return
        if (Build.VERSION.SDK_INT >= 30) {
            // Android 14+: no microphone foreground service from BOOT_COMPLETED;
            // Android 11-13: it would start without microphone access.
            NvWakeService.setState(context, "stopped")
            NvWakeService.notifyUser(context, "Hey Neo berhenti setelah HP dinyalakan ulang",
                "Ketuk untuk menyalakan lagi", "wake", NvWakeService.BOOT_ID)
        } else {
            try {
                NvWakeService.setEnabled(context, true)
            } catch (e: Exception) {
                NvWakeService.notifyUser(context, NvLocale.str(context, R.string.nv_wake_stopped), NvLocale.str(context, R.string.nv_wake_tap_restart), "wake", NvWakeService.BOOT_ID)
            }
        }
    }
}
