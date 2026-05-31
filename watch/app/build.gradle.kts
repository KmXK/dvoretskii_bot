plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "com.dvoretskii.watch"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.dvoretskii.watch"
        minSdk = 30          // Wear OS 3+ (Galaxy Watch 5 Pro = Wear OS 4 / API 34)
        targetSdk = 34
        versionCode = 1
        versionName = "0.1"

        // Базовый URL бота. Переопредели в local.properties (BOT_BASE_URL=...)
        // или прямо здесь. Должен быть https и без хвостового слэша.
        val baseUrl = (project.findProperty("BOT_BASE_URL") as String?)
            ?: "https://tg.kmxk.ru"
        buildConfigField("String", "BOT_BASE_URL", "\"$baseUrl\"")
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2024.09.02"))
    implementation("androidx.compose.runtime:runtime")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.activity:activity-compose:1.9.2")
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.6")

    // Wear-specific Compose
    implementation("androidx.wear.compose:compose-material:1.4.0")
    implementation("androidx.wear.compose:compose-foundation:1.4.0")
    // Ввод текста на часах (системный экран ввода через RemoteInput)
    implementation("androidx.wear:wear-input:1.1.0")

    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")

    // HTTP. JSON парсим через org.json (встроен в Android), без лишних зависимостей.
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
}
