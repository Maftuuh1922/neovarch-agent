package com.neovarch.agent

import android.app.LocaleManager
import android.content.Context
import android.content.res.Configuration
import android.os.Build
import android.os.LocaleList
import java.util.Locale

/**
 * App language (Profil › Bahasa): "" = follow the system, "id" or "en".
 *
 * Android 13+: handed to the system's per-app language (LocaleManager, see
 * res/xml/locales_config.xml), so every Context of the app (widgets,
 * notifications) resolves values-en/ or the Indonesian default by itself.
 * Older Android: the choice lives only in the app's shared_preferences
 * (`flutter.app.language`, written by the Flutter side) and [ctx] wraps a
 * Context in that locale for native strings.
 */
object NvLocale {
    private const val PREFS = "FlutterSharedPreferences"
    private const val KEY = "flutter.app.language"

    /** Saved choice: "", "id" or "en". */
    fun saved(c: Context): String {
        val v = c.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY, null) ?: ""
        return if (v == "id" || v == "en") v else ""
    }

    /** Android 13+: apply the choice system-wide for this app ("" = follow the system). */
    fun apply(c: Context, language: String) {
        if (Build.VERSION.SDK_INT < 33) return
        val lm = c.getSystemService(LocaleManager::class.java) ?: return
        lm.applicationLocales = if (language.isEmpty()) LocaleList.getEmptyLocaleList() else LocaleList.forLanguageTags(language)
    }

    /** Android 13+: the per-app language set in system settings ("" = none); null below 13. */
    fun system(c: Context): String? {
        if (Build.VERSION.SDK_INT < 33) return null
        val lm = c.getSystemService(LocaleManager::class.java) ?: return ""
        val l = lm.applicationLocales
        return if (l.isEmpty) "" else l[0].toLanguageTag()
    }

    /** A Context whose resources use the app language (needed below Android 13 only). */
    fun ctx(c: Context): Context {
        if (Build.VERSION.SDK_INT >= 33) return c
        val lang = saved(c)
        if (lang.isEmpty()) return c
        val conf = Configuration(c.resources.configuration)
        conf.setLocale(Locale.forLanguageTag(lang))
        return c.createConfigurationContext(conf)
    }

    fun str(c: Context, id: Int): String = ctx(c).getString(id)
}
