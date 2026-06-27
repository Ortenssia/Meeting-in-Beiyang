[app]

# (str) Title of your application
title = Beiyang Social

# (str) Package name
package.name = beiyangsocial

# (str) Package domain (needed for android/ios packaging)
package.domain = org.beiyangsocial

# (str) Source code where the main.py live
source.dir = core

# (list) Source files to include (let empty to include all the files)
source.include_exts = py,png,jpg,kv,atlas,ttf,otf

# (str) Application versioning (method 1)
version = 3.0.0

# (list) Application requirements
# comma separated e.g. requirements = sqlite3,kivy
requirements = python3,kivy,plyer,sqlite3

# (str) Supported orientation (landscape, sensorLandscape, portrait or all)
orientation = portrait

# (bool) Indicate if the application should be fullscreen or not
fullscreen = 0

# (list) Permissions
android.permissions = INTERNET,ACCESS_WIFI_STATE,CHANGE_WIFI_STATE,CHANGE_WIFI_MULTICAST_STATE,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE

# (int) Target Android API, should be as high as possible.
android.api = 33

# (int) Minimum API your APK will support.
android.minapi = 21

# (str) Android NDK version to use
android.ndk = 25b

# (bool) Use --private data storage (True) or --dir public storage (False)
android.private_storage = True

# (str) Android logcat filters to use
android.logcat_filters = *:S python:D

# (bool) Copy library instead of making a libpymodules.so
android.copy_libs = 1

# (bool) Auto-accept Android SDK licenses
android.accept_sdk_license = True

# (str) The Android arch to build for, arm64-v8a covers all modern phones
android.archs = arm64-v8a

[buildozer]

# (int) Log level (0 = error only, 1 = info, 2 = debug (with command output))
log_level = 2

# (int) Display warning if buildozer is run as root (0 = False, 1 = True)
warn_on_root = 0

# (str) Path to build artifact storage, absolute or relative to spec file
build_dir = /home/user/.buildozer_build

# (str) Path to build output (i.e. .apk, .ipa) storage
bin_dir = ./bin
