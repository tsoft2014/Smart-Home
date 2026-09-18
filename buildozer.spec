[app]
title = Управление освещением
package.name = smarthome
package.domain = org.smarthome
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json
source.include_patterns = model/*,model/**/*
version = 1.0.0

# Добавлены hostpython3 (обязательно!) и sounddevice
requirements = python3,kivy,requests,urllib3,chardet,idna,certifi,plyer,pyjnius,cffi,vosk,sounddevice,hostpython3

orientation = portrait
fullscreen = 1  # Изменено на 1 для полного экрана

android.permissions = INTERNET, RECORD_AUDIO, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE, WRITE_EXTERNAL_STORAGE, READ_EXTERNAL_STORAGE
android.api = 33
android.minapi = 21
android.archs = arm64-v8a, armeabi-v7a
android.grant_permissions = True
android.allow_backup = True
android.theme = @android:style/Theme.NoTitleBar

p4a.fork = kivy
p4a.branch = v2024.01.21
