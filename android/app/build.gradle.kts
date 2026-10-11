import java.io.FileInputStream
import java.util.Base64
import java.util.Properties

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// Fixed Neovarch signing key, so every APK (debug and release) carries the
// same certificate and installs over the previous one. The key is NOT in
// the repository. Sources, in order:
//   1. android/key.properties (local, git-ignored): storeFile (relative to
//      android/app/ or absolute), storePassword, keyAlias, keyPassword.
//   2. Environment (CI): NEOVARCH_KEYSTORE_BASE64 (the keystore, base64),
//      NEOVARCH_KEYSTORE_PASSWORD, NEOVARCH_KEY_ALIAS, NEOVARCH_KEY_PASSWORD;
//      the keystore is decoded to a temp file under build/.
//   3. Neither: the default Android debug key.
val keystorePropertiesFile = rootProject.file("key.properties")
val keystoreProperties = Properties().apply {
    if (keystorePropertiesFile.exists()) {
        FileInputStream(keystorePropertiesFile).use { load(it) }
    }
}

data class NeovarchSigning(val storeFile: File, val storePassword: String, val keyAlias: String, val keyPassword: String)

fun signingFromProperties(): NeovarchSigning? {
    val store = keystoreProperties.getProperty("storeFile")?.let { file(it) }?.takeIf { it.exists() } ?: return null
    val alias = keystoreProperties.getProperty("keyAlias") ?: return null
    val storePw = keystoreProperties.getProperty("storePassword") ?: return null
    return NeovarchSigning(store, storePw, alias, keystoreProperties.getProperty("keyPassword") ?: storePw)
}

fun signingFromEnv(): NeovarchSigning? {
    val b64 = System.getenv("NEOVARCH_KEYSTORE_BASE64")?.trim()?.takeIf { it.isNotEmpty() } ?: return null
    val storePw = System.getenv("NEOVARCH_KEYSTORE_PASSWORD")?.takeIf { it.isNotEmpty() } ?: return null
    val alias = System.getenv("NEOVARCH_KEY_ALIAS")?.takeIf { it.isNotEmpty() } ?: return null
    val keyPw = System.getenv("NEOVARCH_KEY_PASSWORD")?.takeIf { it.isNotEmpty() } ?: storePw
    val out = layout.buildDirectory.file("neovarch-signing/ci.keystore").get().asFile
    out.parentFile.mkdirs()
    out.writeBytes(Base64.getMimeDecoder().decode(b64))
    out.deleteOnExit()
    return NeovarchSigning(out, storePw, alias, keyPw)
}

val neovarchSigning: NeovarchSigning? = signingFromProperties() ?: signingFromEnv()

android {
    namespace = "com.neovarch.agent"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        applicationId = "com.neovarch.agent"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        // Uses the version code from pubspec.yaml. When using split APKs, 1000 * ABI_VERSION
        // is added automatically by Flutter. (https://developer.android.com/studio/build/configure-apk-splits#configure-APK-versions)
        // You can force using the value of versionCode by specifying the `-P force-version-code-ignoring-abi=true`
        // flag during build.
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    signingConfigs {
        neovarchSigning?.let { k ->
            create("neovarch") {
                storeFile = k.storeFile
                storePassword = k.storePassword
                keyAlias = k.keyAlias
                keyPassword = k.keyPassword
            }
        }
    }

    buildTypes {
        val appSigning = if (neovarchSigning != null) {
            signingConfigs.getByName("neovarch")
        } else {
            signingConfigs.getByName("debug")
        }
        debug {
            signingConfig = appSigning
        }
        release {
            signingConfig = appSigning
            // Vosk (Hey Neo) goes through JNA: keep its classes from R8.
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }
}

android {
    // Home-screen widget tests: JVM logic + Robolectric renders of the real layouts.
    testOptions {
        unitTests.isIncludeAndroidResources = true
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}

dependencies {
    // "Hey Neo" wake word: offline Vosk recogniser (Apache-2.0); JNA as an AAR
    // so its native dispatch library is packaged per ABI.
    implementation("com.alphacephei:vosk-android:0.3.47") {
        exclude(group = "net.java.dev.jna")
    }
    implementation("net.java.dev.jna:jna:5.13.0@aar")
    // In-app update: FileProvider (already in the graph via Flutter plugins)
    implementation("androidx.core:core:1.13.1")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.robolectric:robolectric:4.14.1")
    testImplementation("androidx.test:core:1.6.1")
}

// Unit-test asset packaging reads the merged assets dir that Flutter's
// copyFlutterAssets* also writes; order them so Gradle's validation passes.
tasks.configureEach {
    if (name.startsWith("package") && name.endsWith("UnitTestForUnitTest")) {
        val variant = name.removePrefix("package").removeSuffix("UnitTestForUnitTest")
        mustRunAfter("copyFlutterAssets$variant")
    }
}
