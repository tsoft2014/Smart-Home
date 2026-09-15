[app]
title = Smart Home Assistant
package.name = smarthome
package.domain = org.mysmarthome
source.dir = .
source.include_exts = py,png,jpg,kv,json,mdl,fst,txt,int
version = 1.0.0
android.accept_sdk_license = True

# Строго без srt и без версий с точками внутри списка requirements:
requirements = python3, kivy, pyjnius, requests, websockets, vosk

# Жестко фиксируем рабочую версию Python для p4a, чтобы сборщик не брал Python 3.14
p4a.python_version = 3.11

android.permissions = INTERNET,RECORD_AUDIO
android.archs = arm64-v8a,armeabi-v7a
android.api = 33
android.minapi = 21
orientation = portrait
fullscreen = 0
android.presplash_color = #1c1c1c

[buildozer]
log_level = 2
warn_root = 1
bin_dir = ./bin
p4a.branch = master
