package com.neovarch.agent

import androidx.core.content.FileProvider

/**
 * FileProvider for downloaded update APKs (cache/updates/, see
 * res/xml/nv_update_paths.xml). Its own class so the manifest entry never
 * collides with a plugin's androidx FileProvider.
 */
class NvUpdateProvider : FileProvider()
