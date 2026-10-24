plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.rohan.upinetwork.ble"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.rohan.upinetwork.ble"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
    }
}
