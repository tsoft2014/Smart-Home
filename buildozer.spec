[app]

# (str) Title of your application
title = Smart Home Assistant

# (str) Package name
package.name = smarthome

# (str) Package domain (needed for android packaging)
package.domain = org.mysmarthome

# (str) Source files where the relevent code is (relative to directory of spec)
source.dir = .

# (list) Source files to include (let it include json and png/icons)
source.include_exts = py,png,jpg,kv,json,mdl,fst,txt,int

# (str) Версия приложения
version = 1.0.0

# Принимать лицензии SDK автоматически
android.accept_sdk_license = True

# (list) Application requirements
# Оставляем чистые требования без жесткой привязки к минорным версиям, чтобы не ломать pip внутри сборщика
requirements = python3, kivy, pyjnius, requests, websockets, vosk

# Указываем версию Python для p4a
p4a.python_version = 3.11

# (list) Permissions
android.permissions = INTERNET,RECORD_AUDIO

# (list) Target architectures
android.archs = arm64-v8a,armeabi-v7a

# (int) Target Android API, should be as high as possible.
android.api = 33

# (int) Minimum API your APK will support.
android.minapi = 21

# (str) Supported orientations
orientation = portrait

# (bool) Indicate if the application should be fullscreen or not
fullscreen = 0

# (string) Presplash background color
android.presplash_color = #1c1c1c


[buildozer]

# (int) Log level (0 = error, 1 = info, 2 = debug (with command output))
log_level = 2

# (int) Display warning if buildozer is run as root (0 = False, 1 = True)
warn_root = 1

# (str) Path to build artifact
bin_dir = ./bin

# Переходим на актуальную ветку p4a, которая поддерживает Python 3.11 и современные рецепты
p4a.branch = master
