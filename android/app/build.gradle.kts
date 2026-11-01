import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
}

// The release's version and build id come from the tag through scripts/app_version.py
// (release.yml passes them as -P properties: `./gradlew assembleRelease $(python3 ../scripts/app_version.py v0.1.0 --gradle)`).
// A build without them is a dev build, 0.0.0-dev at versionCode 1, which every tagged APK upgrades.
val caelzaVersion = (findProperty("caelzaVersion") as String?)?.takeIf { it.isNotBlank() } ?: "0.0.0-dev"
val caelzaVersionCode = (findProperty("caelzaVersionCode") as String?)?.toIntOrNull() ?: 1
val caelzaBuildId = (findProperty("caelzaBuildId") as String?)?.takeIf { it.isNotBlank() } ?: "dev"
// The release keystore, when the environment names one (release.yml decodes it from the repo's secrets).
// Without it the release build type signs with the debug key, so `assembleRelease` still yields an
// installable APK; release.yml names that one -debug-signed so nobody mistakes it for the real thing.
val releaseKeystore = System.getenv("CAELZA_KEYSTORE")?.takeIf { it.isNotBlank() }

android {
    namespace = "tech.enlightenedrepublic.caelza"
    compileSdk = 36

    defaultConfig {
        applicationId = "tech.enlightenedrepublic.caelza"
        minSdk = 28
        // 28 on purpose, as Termux does: from 29 on, Android refuses to execute
        // a binary the app wrote into its own files dir (W^X), and the whole
        // point of the guard is pulling a new Runtime release without a new
        // APK. docs/design/android-app.md weighs the alternatives.
        targetSdk = 28
        versionCode = caelzaVersionCode
        versionName = caelzaVersion
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        buildConfigField("String", "RELEASE_REPO", "\"Enlightened-Republic/Caelza\"")
        // The tag (v0.1.0) or `dev`: shown in the bug report's header beside the version.
        buildConfigField("String", "BUILD_ID", "\"$caelzaBuildId\"")
    }

    signingConfigs {
        if (releaseKeystore != null) {
            create("release") {
                storeFile = file(releaseKeystore)
                storePassword = System.getenv("CAELZA_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("CAELZA_KEY_ALIAS")
                keyPassword = System.getenv("CAELZA_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = if (releaseKeystore != null) signingConfigs.getByName("release") else signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        viewBinding = true
        buildConfig = true
    }

    testOptions {
        unitTests.isReturnDefaultValues = true
    }

    lint {
        // The build is the gate; lint findings are read, not blocking (yet).
        abortOnError = false
        // targetSdk 28 is deliberate (see defaultConfig).
        disable += setOf("ExpiredTargetSdkVersion", "OldTargetApi")
    }

    packaging {
        resources.excludes += setOf("META-INF/LICENSE*", "META-INF/NOTICE*", "META-INF/DEPENDENCIES")
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.material)
    implementation(libs.androidx.lifecycle.service)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.shizuku.api)
    implementation(libs.shizuku.provider)
    implementation(libs.commons.compress)

    testImplementation(libs.junit)
    testImplementation(libs.json)
    testImplementation(libs.kotlinx.coroutines.test)
}
