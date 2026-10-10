package com.neovarch.agent

import android.Manifest
import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.ActivityNotFoundException
import android.content.ComponentName
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import android.os.BatteryManager
import android.os.Build
import android.os.Bundle
import android.graphics.Color
import android.graphics.drawable.ColorDrawable
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.os.StatFs
import android.provider.CalendarContract
import android.provider.ContactsContract
import android.provider.OpenableColumns
import android.provider.Settings
import android.util.Base64
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import java.util.Locale
import java.util.TimeZone

/**
 * "neovarch/device": the on-device agent's bridge to Android. Every call is
 * read-only or launches a system UI the user completes themselves (dialer,
 * SMS composer, share sheet); nothing here acts inside other apps.
 * Runtime permissions are requested on first use.
 */
class MainActivity : FlutterActivity() {
    private val channelName = "neovarch/device"
    private val permRequests = HashMap<Int, MethodChannel.Result>()
    private val docRequests = HashMap<Int, MethodChannel.Result>()
    private val uploadRequests = HashMap<Int, MethodChannel.Result>()
    private var nextCode = 4100
    /** Where a tapped notification wants the app to go ("approvals"); taken once by Dart. */
    private var pendingRoute: String? = null

    /**
     * Cold start in the user's theme: the Dart side stores the resolved
     * background (`nv.boot.bg`, `nv.boot.dark`) in the plugin's
     * FlutterSharedPreferences; paint it as the window background before
     * Flutter's first frame so the intro opens without a colour jump. On
     * Android 13+ also pick the matching (neutral) system splash for next time.
     */
    override fun onCreate(savedInstanceState: Bundle?) {
        try {
            val p = getSharedPreferences("FlutterSharedPreferences", Context.MODE_PRIVATE)
            val bg = p.getString("flutter.nv.boot.bg", null)
            if (bg != null) window.setBackgroundDrawable(ColorDrawable(Color.parseColor(bg)))
            if (Build.VERSION.SDK_INT >= 33) {
                val light = p.getString("flutter.nv.boot.dark", "1") == "0"
                splashScreen.setSplashScreenTheme(if (light) R.style.LaunchThemeLight else R.style.LaunchTheme)
            }
        } catch (e: Exception) {
            // keep the neutral default
        }
        super.onCreate(savedInstanceState)
        pendingRoute = intent?.getStringExtra(EXTRA_ROUTE) ?: pendingRoute
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        intent.getStringExtra(EXTRA_ROUTE)?.let { pendingRoute = it }
    }

    // ------------------------------------------------------ launcher icon --
    /** Launcher icon colour: one enabled <activity-alias> (AndroidManifest). */
    private fun aliasName(id: String) = "$packageName.Launcher" + id.replaceFirstChar { it.uppercase() }

    private fun launcherIcon(): String {
        val pm = packageManager
        for (id in ICON_IDS) {
            val st = pm.getComponentEnabledSetting(ComponentName(this, aliasName(id)))
            if (st == PackageManager.COMPONENT_ENABLED_STATE_ENABLED) return id
            // DEFAULT = the manifest value: only Merah is enabled there
            if (st == PackageManager.COMPONENT_ENABLED_STATE_DEFAULT && id == ICON_IDS[0]) {
                val others = ICON_IDS.drop(1).any {
                    pm.getComponentEnabledSetting(ComponentName(this, aliasName(it))) == PackageManager.COMPONENT_ENABLED_STATE_ENABLED
                }
                if (!others) return id
            }
        }
        return ICON_IDS[0]
    }

    /** Enables [id]'s alias, then disables every other one, so the launcher never sees zero entries. */
    private fun setLauncherIcon(id: String): String {
        if (id !in ICON_IDS) throw IllegalArgumentException("ikon tidak dikenal: $id")
        val pm = packageManager
        val on = ComponentName(this, aliasName(id))
        val flags = PackageManager.DONT_KILL_APP
        if (Build.VERSION.SDK_INT >= 33) {
            val list = ArrayList<PackageManager.ComponentEnabledSetting>()
            list.add(PackageManager.ComponentEnabledSetting(on, PackageManager.COMPONENT_ENABLED_STATE_ENABLED, flags))
            for (other in ICON_IDS) if (other != id) list.add(PackageManager.ComponentEnabledSetting(
                ComponentName(this, aliasName(other)), PackageManager.COMPONENT_ENABLED_STATE_DISABLED, flags))
            pm.setComponentEnabledSettings(list)
        } else {
            pm.setComponentEnabledSetting(on, PackageManager.COMPONENT_ENABLED_STATE_ENABLED, flags)
            for (other in ICON_IDS) if (other != id) pm.setComponentEnabledSetting(
                ComponentName(this, aliasName(other)), PackageManager.COMPONENT_ENABLED_STATE_DISABLED, flags)
        }
        return id
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, channelName).setMethodCallHandler { call, result ->
            try {
                handle(call, result)
            } catch (e: SecurityException) {
                result.error("permission", e.message ?: "izin ditolak", null)
            } catch (e: Exception) {
                result.error("failed", e.message ?: e.toString(), null)
            }
        }
    }

    private fun handle(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "deviceInfo" -> result.success(deviceInfo())
            "checkPermissions" -> {
                val perms = call.argument<List<String>>("permissions") ?: emptyList()
                result.success(perms.associateWith { granted(it) })
            }
            "requestPermissions" -> {
                val perms = (call.argument<List<String>>("permissions") ?: emptyList()).filter { needsRuntime(it) }
                val missing = perms.filter { !granted(it) }
                if (missing.isEmpty()) {
                    result.success(perms.associateWith { true })
                } else {
                    val code = nextCode++
                    permRequests[code] = result
                    requestPermissions(missing.toTypedArray(), code)
                }
            }
            "storageStatus" -> result.success(storageStatus())
            "openAppSettings" -> {
                startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName"))
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                result.success(true)
            }
            "sdkInt" -> result.success(Build.VERSION.SDK_INT)
            "requestAllFiles" -> {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                    if (Environment.isExternalStorageManager()) {
                        result.success(true)
                    } else {
                        val i = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION, Uri.parse("package:$packageName"))
                        try {
                            startActivity(i)
                        } catch (e: ActivityNotFoundException) {
                            startActivity(Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION))
                        }
                        result.success(false)
                    }
                } else {
                    result.success(granted(Manifest.permission.WRITE_EXTERNAL_STORAGE))
                }
            }
            "pickDocument" -> {
                val i = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                    addCategory(Intent.CATEGORY_OPENABLE)
                    type = call.argument<String>("mime") ?: "*/*"
                }
                val code = nextCode++
                docRequests[code] = result
                @Suppress("DEPRECATION")
                startActivityForResult(i, code)
            }
            // Chat attachments: copy a picked document into the app cache (no size
            // clipping below the 25 MB upload limit) and hand Dart its path.
            "pickFileForUpload" -> {
                val i = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                    addCategory(Intent.CATEGORY_OPENABLE)
                    type = call.argument<String>("mime") ?: "*/*"
                }
                val code = nextCode++
                uploadRequests[code] = result
                @Suppress("DEPRECATION")
                startActivityForResult(i, code)
            }
            // An image on the clipboard (copied from a browser / gallery / screenshot).
            "clipboardImage" -> Thread {
                val out = try { clipboardImage() } catch (e: Exception) { null }
                Handler(Looper.getMainLooper()).post { result.success(out) }
            }.start()
            "hasClipboardImage" -> result.success(hasClipboardImage())
            "shareImage" -> {
                val f = java.io.File(call.argument<String>("path") ?: "")
                val share = java.io.File(cacheDir, "share").apply { mkdirs() }
                val target = if (f.parentFile?.canonicalPath == share.canonicalPath) f else java.io.File(share, f.name).also { f.copyTo(it, true) }
                val uri = Uri.parse("content://$packageName.nvshare/${Uri.encode(target.name)}")
                result.success(shareImage(uri, call.argument<String>("mime") ?: "image/png", call.argument<String>("text"),
                    call.argument<String>("title") ?: "Bagikan", call.argument<String>("package"), call.argument<String>("mode") ?: "send"))
            }
            // Kartu Neovarch: which of the given share targets are installed
            // (each package is listed in the manifest's <queries>).
            "installedPackages" -> result.success((call.argument<List<String>>("packages") ?: emptyList()).filter { isInstalled(it) })
            "saveImageToGallery" -> Thread {
                val out = try { saveToGallery(java.io.File(call.argument<String>("path") ?: ""), call.argument<String>("name") ?: "neovarch.png") } catch (e: Exception) { null }
                Handler(Looper.getMainLooper()).post { result.success(out) }
            }.start()
            "openIntent" -> result.success(openIntent(call))
            "notify" -> result.success(notify(call.argument<String>("title") ?: "Neovarch", call.argument<String>("body") ?: "", call.argument<String>("route")))
            "location" -> location(result)
            "contacts" -> result.success(contacts(call.argument<String>("query") ?: "", call.argument<Int>("limit") ?: 20))
            "calendar" -> result.success(calendar(call.argument<Int>("days") ?: 7, call.argument<Int>("limit") ?: 40))
            "apps" -> result.success(apps(call.argument<String>("query") ?: ""))
            "launcherIcon" -> result.success(launcherIcon())
            // home-screen widgets: Kantor snapshot + "is one placed" (NvWidgets.kt)
            "saveWidgetSnapshot", "widgetsPlaced" -> result.success(NvWidgets.handle(this, call.method, call.arguments))
            "setLauncherIcon" -> result.success(setLauncherIcon(call.argument<String>("id") ?: ""))
            "takeRoute" -> { result.success(pendingRoute); pendingRoute = null }
            "wakeWord" -> {
                NvWakeService.setEnabled(this, call.argument<Boolean>("enable") == true)
                result.success(NvWakeService.status(this))
            }
            "wakeStatus" -> result.success(NvWakeService.status(this))
            "wakeHoldMic" -> result.success(NvWakeService.holdMic(call.argument<Boolean>("hold") == true))
            "wakeBackground" -> result.success(openBackgroundSettings(call.argument<String>("kind") ?: "autostart"))
            "updateWidget" -> {
                NvHomeWidget.save(this, (call.arguments as? Map<*, *>) ?: emptyMap<String, Any?>())
                result.success(true)
            }
            else -> result.notImplemented()
        }
    }

    // ---------------------------------------------------------- permissions --
    private fun needsRuntime(p: String): Boolean = when (p) {
        Manifest.permission.POST_NOTIFICATIONS -> Build.VERSION.SDK_INT >= 33
        Manifest.permission.READ_EXTERNAL_STORAGE -> Build.VERSION.SDK_INT <= 32
        Manifest.permission.WRITE_EXTERNAL_STORAGE -> Build.VERSION.SDK_INT <= 29
        "android.permission.READ_MEDIA_IMAGES", "android.permission.READ_MEDIA_VIDEO",
        "android.permission.READ_MEDIA_AUDIO" -> Build.VERSION.SDK_INT >= 33
        "android.permission.READ_MEDIA_VISUAL_USER_SELECTED" -> Build.VERSION.SDK_INT >= 34
        else -> true
    }

    private fun granted(p: String): Boolean =
        !needsRuntime(p) || checkSelfPermission(p) == PackageManager.PERMISSION_GRANTED

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        val r = permRequests.remove(requestCode) ?: return
        val out = HashMap<String, Boolean>()
        for (i in permissions.indices) out[permissions[i]] = grantResults.getOrNull(i) == PackageManager.PERMISSION_GRANTED
        r.success(out)
    }

    private val uploadLimit = 25L * 1024 * 1024

    /** Copy a content:// URI into cache/uploads; {path, name, mime, size} or {error, size}. */
    private fun copyForUpload(uri: Uri, fallbackName: String): Map<String, Any?> {
        var name = uri.lastPathSegment?.substringAfterLast('/') ?: fallbackName
        var size = -1L
        contentResolver.query(uri, null, null, null, null)?.use { c ->
            if (c.moveToFirst()) {
                val ni = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                val si = c.getColumnIndex(OpenableColumns.SIZE)
                if (ni >= 0) name = c.getString(ni) ?: name
                if (si >= 0 && !c.isNull(si)) size = c.getLong(si)
            }
        }
        val mime = contentResolver.getType(uri) ?: "application/octet-stream"
        if (size > uploadLimit) return mapOf("error" to "too_big", "size" to size, "name" to name)
        val dir = java.io.File(cacheDir, "uploads").apply { mkdirs() }
        val safe = name.replace(Regex("[^A-Za-z0-9._ -]"), "_").ifEmpty { fallbackName }
        val f = java.io.File(dir, "${System.currentTimeMillis()}-$safe")
        var copied = 0L
        contentResolver.openInputStream(uri)?.use { input ->
            f.outputStream().use { out ->
                val buf = ByteArray(64 * 1024)
                while (true) {
                    val n = input.read(buf)
                    if (n < 0) break
                    copied += n
                    if (copied > uploadLimit) {
                        out.close(); f.delete()
                        return mapOf("error" to "too_big", "size" to copied, "name" to name)
                    }
                    out.write(buf, 0, n)
                }
            }
        } ?: return mapOf("error" to "unreadable", "name" to name)
        return mapOf("path" to f.absolutePath, "name" to name, "mime" to mime, "size" to copied)
    }

    @Suppress("DEPRECATION")
    private fun isInstalled(pkg: String): Boolean = try {
        if (Build.VERSION.SDK_INT >= 33) packageManager.getPackageInfo(pkg, PackageManager.PackageInfoFlags.of(0))
        else packageManager.getPackageInfo(pkg, 0)
        true
    } catch (e: Exception) {
        false
    }

    /**
     * Share an image from cache/share. With [pkg] the intent goes straight to
     * that app ("ig-story" = Instagram's ADD_TO_STORY with the image as the
     * story background); if the app can't take it, the system chooser opens
     * instead. Returns "shared", "chooser" (fell back) or an error string.
     */
    private fun shareImage(uri: Uri, mime: String, text: String?, title: String, pkg: String?, mode: String): String {
        val send = Intent(Intent.ACTION_SEND).apply {
            type = mime
            putExtra(Intent.EXTRA_STREAM, uri)
            text?.let { putExtra(Intent.EXTRA_TEXT, it) }
            clipData = android.content.ClipData.newRawUri("kartu", uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        val chooser = Intent.createChooser(send, title).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        if (pkg.isNullOrEmpty()) {
            startActivity(chooser)
            return "chooser"
        }
        val direct = if (mode == "ig-story") Intent("com.instagram.share.ADD_TO_STORY").apply {
            setDataAndType(uri, mime)
            putExtra("source_application", packageName)
            setPackage(pkg)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        } else Intent(send).apply { setPackage(pkg) }
        return try {
            grantUriPermission(pkg, uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
            if (direct.resolveActivity(packageManager) == null) throw ActivityNotFoundException(pkg)
            startActivity(direct)
            "shared"
        } catch (e: Exception) {
            try { startActivity(chooser); "chooser" } catch (e2: Exception) { "gagal: ${e2.message}" }
        }
    }

    /** Copy a PNG into Pictures/Neovarch via MediaStore (no permission on API 29+). */
    private fun saveToGallery(src: java.io.File, name: String): String? {
        if (!src.isFile) return null
        if (Build.VERSION.SDK_INT >= 29) {
            val values = ContentValues().apply {
                put(android.provider.MediaStore.Images.Media.DISPLAY_NAME, name)
                put(android.provider.MediaStore.Images.Media.MIME_TYPE, "image/png")
                put(android.provider.MediaStore.Images.Media.RELATIVE_PATH, Environment.DIRECTORY_PICTURES + "/Neovarch")
                put(android.provider.MediaStore.Images.Media.IS_PENDING, 1)
            }
            val uri = contentResolver.insert(android.provider.MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values) ?: return null
            contentResolver.openOutputStream(uri)?.use { out -> src.inputStream().use { it.copyTo(out) } }
            values.clear()
            values.put(android.provider.MediaStore.Images.Media.IS_PENDING, 0)
            contentResolver.update(uri, values, null, null)
            return uri.toString()
        }
        @Suppress("DEPRECATION")
        val dir = java.io.File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_PICTURES), "Neovarch").apply { mkdirs() }
        val f = java.io.File(dir, name)
        src.copyTo(f, true)
        android.media.MediaScannerConnection.scanFile(this, arrayOf(f.absolutePath), arrayOf("image/png"), null)
        return f.absolutePath
    }

    private fun clipItemUri(): Uri? {
        val cm = getSystemService(Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager
        val clip = cm.primaryClip ?: return null
        for (i in 0 until clip.itemCount) {
            val uri = clip.getItemAt(i).uri ?: continue
            val type = contentResolver.getType(uri) ?: ""
            if (type.startsWith("image/")) return uri
        }
        return null
    }

    private fun hasClipboardImage(): Boolean {
        val cm = getSystemService(Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager
        val d = cm.primaryClipDescription ?: return false
        for (i in 0 until d.mimeTypeCount) if (d.getMimeType(i).startsWith("image/")) return true
        return false
    }

    private fun clipboardImage(): Map<String, Any?>? {
        val uri = clipItemUri() ?: return null
        return copyForUpload(uri, "tempel.png")
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        val up = uploadRequests.remove(requestCode)
        if (up != null) {
            val uri = data?.data
            if (resultCode != Activity.RESULT_OK || uri == null) { up.success(null); return }
            Thread {
                try {
                    val out = copyForUpload(uri, "berkas")
                    Handler(Looper.getMainLooper()).post { up.success(out) }
                } catch (e: Exception) {
                    Handler(Looper.getMainLooper()).post { up.error("failed", e.message, null) }
                }
            }.start()
            return
        }
        val r = docRequests.remove(requestCode) ?: return
        val uri = data?.data
        if (resultCode != Activity.RESULT_OK || uri == null) {
            r.success(null)
            return
        }
        Thread {
            try {
                var name = uri.lastPathSegment ?: "berkas"
                var size = -1L
                contentResolver.query(uri, null, null, null, null)?.use { c ->
                    if (c.moveToFirst()) {
                        val ni = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                        val si = c.getColumnIndex(OpenableColumns.SIZE)
                        if (ni >= 0) name = c.getString(ni) ?: name
                        if (si >= 0) size = c.getLong(si)
                    }
                }
                val mime = contentResolver.getType(uri) ?: "application/octet-stream"
                val limit = 4 * 1024 * 1024
                val bytes = contentResolver.openInputStream(uri)?.use { it.readBytes() } ?: ByteArray(0)
                val clipped = if (bytes.size > limit) bytes.copyOf(limit) else bytes
                val map = hashMapOf<String, Any?>(
                    "name" to name, "mime" to mime, "size" to (if (size >= 0) size else bytes.size.toLong()),
                    "uri" to uri.toString(), "truncated" to (bytes.size > limit),
                    "base64" to Base64.encodeToString(clipped, Base64.NO_WRAP)
                )
                Handler(Looper.getMainLooper()).post { r.success(map) }
            } catch (e: Exception) {
                Handler(Looper.getMainLooper()).post { r.error("failed", e.message, null) }
            }
        }.start()
    }

    // ---------------------------------------------------------------- info --
    private fun deviceInfo(): Map<String, Any?> {
        val bm = getSystemService(Context.BATTERY_SERVICE) as BatteryManager
        val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val caps = cm.getNetworkCapabilities(cm.activeNetwork)
        val net = when {
            caps == null -> "offline"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "seluler"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "ethernet"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN) -> "vpn"
            else -> "lainnya"
        }
        val st = StatFs(Environment.getDataDirectory().path)
        val dm = resources.displayMetrics
        return mapOf(
            "manufacturer" to Build.MANUFACTURER,
            "model" to Build.MODEL,
            "android" to Build.VERSION.RELEASE,
            "sdk" to Build.VERSION.SDK_INT,
            "batteryPercent" to bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY),
            "charging" to bm.isCharging,
            "network" to net,
            "metered" to cm.isActiveNetworkMetered,
            "storageFreeGb" to st.availableBytes / 1e9,
            "storageTotalGb" to st.totalBytes / 1e9,
            "locale" to Locale.getDefault().toLanguageTag(),
            "timezone" to TimeZone.getDefault().id,
            "screen" to "${dm.widthPixels}x${dm.heightPixels} @${dm.densityDpi}dpi",
        )
    }

    private fun storageStatus(): Map<String, Any?> {
        val all = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) Environment.isExternalStorageManager()
        else granted(Manifest.permission.WRITE_EXTERNAL_STORAGE)
        @Suppress("DEPRECATION")
        val root = Environment.getExternalStorageDirectory().absolutePath
        return mapOf("allFiles" to all, "root" to root, "sdk" to Build.VERSION.SDK_INT)
    }

    // -------------------------------------------------------------- intents --
    private fun openIntent(call: MethodCall): String {
        val kind = call.argument<String>("kind") ?: "url"
        val target = call.argument<String>("target") ?: ""
        val text = call.argument<String>("text") ?: ""
        val intent: Intent = when (kind) {
            "url" -> Intent(Intent.ACTION_VIEW, Uri.parse(target))
            "share" -> Intent.createChooser(Intent(Intent.ACTION_SEND).apply {
                type = "text/plain"; putExtra(Intent.EXTRA_TEXT, text.ifEmpty { target })
            }, "Bagikan")
            "dial" -> Intent(Intent.ACTION_DIAL, Uri.parse("tel:" + Uri.encode(target)))
            "sms" -> Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:" + Uri.encode(target))).apply { putExtra("sms_body", text) }
            "email" -> Intent(Intent.ACTION_SENDTO, Uri.parse("mailto:" + target)).apply { putExtra(Intent.EXTRA_TEXT, text) }
            "maps" -> Intent(Intent.ACTION_VIEW, Uri.parse("geo:0,0?q=" + Uri.encode(target)))
            "app" -> packageManager.getLaunchIntentForPackage(target) ?: return "aplikasi $target tidak ditemukan"
            "settings" -> Intent(if (target.isNotEmpty()) target else Settings.ACTION_SETTINGS)
            "alarm" -> Intent("android.intent.action.SET_ALARM").apply {
                putExtra("android.intent.extra.alarm.MESSAGE", text)
                val parts = target.split(":")
                if (parts.size == 2) {
                    putExtra("android.intent.extra.alarm.HOUR", parts[0].toIntOrNull() ?: 7)
                    putExtra("android.intent.extra.alarm.MINUTES", parts[1].toIntOrNull() ?: 0)
                }
            }
            else -> return "jenis intent tidak dikenal: $kind"
        }
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        return try {
            startActivity(intent); "dibuka"
        } catch (e: ActivityNotFoundException) {
            "tidak ada aplikasi yang bisa membuka ini"
        }
    }

    private fun notify(title: String, body: String, route: String?): String {
        if (!granted(Manifest.permission.POST_NOTIFICATIONS)) return "izin notifikasi belum diberikan"
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val id = "neovarch_agent"
        val b = if (Build.VERSION.SDK_INT >= 26) {
            nm.createNotificationChannel(NotificationChannel(id, "Neovarch Agent", NotificationManager.IMPORTANCE_DEFAULT))
            Notification.Builder(this, id)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this)
        }
        val n = b.setSmallIcon(R.mipmap.ic_launcher_foreground)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(Notification.BigTextStyle().bigText(body))
            .setAutoCancel(true)
            .setContentIntent(android.app.PendingIntent.getActivity(this, if (route != null) 1 else 0,
                Intent(this, MainActivity::class.java).apply {
                    if (route != null) putExtra(EXTRA_ROUTE, route)
                    addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP)
                }, android.app.PendingIntent.FLAG_IMMUTABLE or android.app.PendingIntent.FLAG_UPDATE_CURRENT))
            .build()
        nm.notify((System.currentTimeMillis() % 100000).toInt(), n)
        return "terkirim"
    }

    private fun location(result: MethodChannel.Result) {
        if (!granted(Manifest.permission.ACCESS_FINE_LOCATION) && !granted(Manifest.permission.ACCESS_COARSE_LOCATION)) {
            result.error("permission", "izin lokasi belum diberikan", null); return
        }
        val lm = getSystemService(Context.LOCATION_SERVICE) as LocationManager
        fun out(l: Location?) = if (l == null) null else mapOf(
            "lat" to l.latitude, "lng" to l.longitude, "accuracyM" to l.accuracy.toDouble(),
            "ageS" to (System.currentTimeMillis() - l.time) / 1000, "provider" to l.provider
        )
        var best: Location? = null
        for (p in lm.getProviders(true)) {
            val l = try { lm.getLastKnownLocation(p) } catch (e: SecurityException) { null }
            if (l != null && (best == null || l.time > best.time)) best = l
        }
        val fresh = best != null && System.currentTimeMillis() - best.time < 10 * 60 * 1000
        if (fresh || Build.VERSION.SDK_INT < 30) { result.success(out(best)); return }
        val provider = when {
            lm.isProviderEnabled("fused") -> "fused"
            lm.isProviderEnabled(LocationManager.NETWORK_PROVIDER) -> LocationManager.NETWORK_PROVIDER
            lm.isProviderEnabled(LocationManager.GPS_PROVIDER) -> LocationManager.GPS_PROVIDER
            else -> null
        }
        if (provider == null) { result.success(out(best)); return }
        var done = false
        val h = Handler(Looper.getMainLooper())
        h.postDelayed({ if (!done) { done = true; result.success(out(best)) } }, 15000)
        lm.getCurrentLocation(provider, null, mainExecutor) { l ->
            if (!done) { done = true; result.success(out(l ?: best)) }
        }
    }

    private fun contacts(query: String, limit: Int): List<Map<String, Any?>> {
        val out = ArrayList<Map<String, Any?>>()
        val uri = ContactsContract.CommonDataKinds.Phone.CONTENT_URI
        val proj = arrayOf(ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME, ContactsContract.CommonDataKinds.Phone.NUMBER)
        val sel = if (query.isBlank()) null else "${ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME} LIKE ?"
        val args = if (query.isBlank()) null else arrayOf("%$query%")
        contentResolver.query(uri, proj, sel, args, "${ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME} ASC")?.use { c ->
            while (c.moveToNext() && out.size < limit) out.add(mapOf("name" to c.getString(0), "phone" to c.getString(1)))
        }
        return out
    }

    private fun calendar(days: Int, limit: Int): List<Map<String, Any?>> {
        val out = ArrayList<Map<String, Any?>>()
        val now = System.currentTimeMillis()
        val b = CalendarContract.Instances.CONTENT_URI.buildUpon()
        android.content.ContentUris.appendId(b, now - 60 * 60 * 1000)
        android.content.ContentUris.appendId(b, now + days.toLong() * 86400000L)
        val proj = arrayOf(CalendarContract.Instances.TITLE, CalendarContract.Instances.BEGIN, CalendarContract.Instances.END,
            CalendarContract.Instances.EVENT_LOCATION, CalendarContract.Instances.ALL_DAY)
        contentResolver.query(b.build(), proj, null, null, "${CalendarContract.Instances.BEGIN} ASC")?.use { c ->
            while (c.moveToNext() && out.size < limit) out.add(mapOf(
                "title" to c.getString(0), "begin" to c.getLong(1), "end" to c.getLong(2),
                "location" to c.getString(3), "allDay" to (c.getInt(4) == 1)))
        }
        return out
    }

    private fun apps(query: String): List<Map<String, Any?>> {
        val pm = packageManager
        val main = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        @Suppress("DEPRECATION")
        val list = pm.queryIntentActivities(main, 0)
        val q = query.lowercase()
        return list.map { mapOf("label" to it.loadLabel(pm).toString(), "package" to it.activityInfo.packageName) }
            .filter { q.isEmpty() || (it["label"] as String).lowercase().contains(q) || (it["package"] as String).contains(q) }
            .distinctBy { it["package"] }
            .sortedBy { (it["label"] as String).lowercase() }
    }

    companion object {
        private const val EXTRA_ROUTE = "nv_route"
        /** Order = the Dart picker (lib/remote/app_icon.dart); first is the manifest default. */
        private val ICON_IDS = listOf("merah", "biru", "ungu", "toska", "hijau", "oranye", "monokrom")
    }

    /** MIUI autostart / battery / overlay pages so Hey Neo can run and open the app from the background. */
    private fun openBackgroundSettings(kind: String): String {
        val pkg = Uri.parse("package:$packageName")
        val tries = mutableListOf<Pair<String, Intent>>()
        if (kind == "overlay") {
            tries += "overlay" to Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, pkg)
            tries += "miui-perms" to Intent("miui.intent.action.APP_PERM_EDITOR").setClassName("com.miui.securitycenter", "com.miui.permcenter.permissions.PermissionsEditorActivity").putExtra("extra_pkgname", packageName)
        } else {
            tries += "miui-autostart" to Intent().setComponent(ComponentName("com.miui.securitycenter", "com.miui.permcenter.autostart.AutoStartManagementActivity"))
            tries += "battery" to Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)
        }
        tries += "app-details" to Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, pkg)
        for ((name, i) in tries) {
            try {
                startActivity(i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                return name
            } catch (_: Exception) {}
        }
        return "none"
    }
}
