// The Caelza Android app (vision §3.3, M7): the native companion that hosts
// the Runtime binary and shows the dashboard. `android/README.md` explains the
// layout; `docs/design/android-app.md` the slices.
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "caelza"
include(":app")
