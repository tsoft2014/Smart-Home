[app]

# (str) Title of your application
title = Smart Home Assistant

# (str) Package name
package.name = smarthome

# (str) Package domain (needed for android packaging)
package.domain = org.mysmarthome

# (str) Source files where the relevent code is (relative to directory of spec)
source.dir = .

# (list) Source files to include
source.include_exts = py,png,jpg,kv,json,mdl,fst,txt,int

# (str) Версия приложения
version = 1.0.0

# Принимать лицензии SDK автоматически
android.accept_sdk_license = True

# (list) Application requirements
# Фиксируем совместимые версии библиотек, исключая попытки скачать битые сборки под Python 3.14
requirements = python3, kivy==2.3.0, pyjnius, requests, websockets, vosk

# Жестко задаем рабочую версию Python для p4a
p4a.python_version = 3.11

# (list) Permissions
android.permissions = INTERNET,RECORD_AUDIO

# (list) Target architectures
android.archs = arm64-v8a,armeabi-v7a

# (int) Target Android API
android.api = 33

# (int) Minimum API your APK will support
android.minapi = 21

# (str) Supported orientations
orientation = portrait

# (bool) Indicate if the application should be fullscreen or not
fullscreen = 0

# (string) Presplash background color
android.presplash_color = #1c1c1c


[buildozer]

log_level = 2
warn_root = 1
bin_dir = ./bin

# Прямое указание стабильного архива python-for-android (обход любых багов бранчей)
p4a.url = https://github.com/kivy/python-for-android/archive/refs/tags/v2024.09.0.zip
p4a.bootstrap = sdl2
