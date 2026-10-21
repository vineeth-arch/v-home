import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.designinnsaeit.vhome.watch"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.designinnsaeit.vhome.watch"
        minSdk = 26
        targetSdk = 35
        versionCode = 9
        versionName = "0.8.1"
        // Debug log receiver on the build machine (android/tools/logsink.py); set logSink=ip:port in local.properties.
        val localProps = Properties().apply {
            rootProject.file("local.properties").takeIf { it.exists() }?.inputStream()?.use { load(it) }
        }
        buildConfigField("String", "LOG_SINK", "\"${localProps.getProperty("logSink", "")}\"")
    }
    buildFeatures { buildConfig = true }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    testOptions { unitTests.isReturnDefaultValues = true }
}

dependencies {
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.9.0")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
    testImplementation("com.squareup.okhttp3:okhttp-tls:4.12.0")
    // Android's org.json is a stub on the JVM; the real one makes JSON tests meaningful.
    testImplementation("org.json:json:20240303")
}
