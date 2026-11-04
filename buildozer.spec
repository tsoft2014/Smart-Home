[app]

# (str) Название приложения на экране смартфона
title = Управление освещением

# (str) Имя пакета (латиницей, без пробелов)
package.name = smarthome

# (str) Домен организации (обратный домен)
package.domain = org.smarthome

# (str) Директория с исходным кодом
source.dir = .

# (list) Расширения файлов для включения в APK
#source.include_exts = py,png,jpg,kv,atlas,json
# Добавили расширения файлов модели (mdl, conf, txt и т.д.)
#source.include_exts = py,png,jpg,kv,atlas,json,mdl,conf,txt
#source.include_exts = py,png,jpg,kv,atlas,mdl,fst,int,dubm,ie,mat,conf,stats,txt
# (list) Расширения файлов для включения в APK
#source.include_exts = py,png,jpg,kv,atlas,json,so,mdl,fst,int,dubm,ie,mat,conf,stats,txt
source.include_exts = py,png,jpg,kv,atlas,json,so,mdl,fst,int,dubm,ie,mat,conf,stats,txt,zip
#source.include_exts = py,png,jpg,kv,atlas,zip

# (list) Явно разрешаем включить всю папку модели и её содержимое
#source.include_patterns = model/*,model/vosk-model-small-ru-0.22/*,model/vosk-model-small-ru-0.22/**/*
#source.include_patterns = model/*,model/vosk-model-small-ru-0.22/*,model/vosk-model-small-ru-0.22/**/*
# Пример: включаем всю папку model с ее подпапками и бинарниками
#source.include_patterns = model/*, *.py
#source.include_patterns = model/*, model/**/*
#source.include_patterns = model/*, model/**/*', vosk/*, vosk/**/*
#source.include_patterns = model/**
#source.include_patterns = vosk-model-small-ru-0.22.zip, vosk.zip, libs/*, libs/**/*
source.include_patterns = model/*, model/**, vosk.zip, libs/*, libs/**/*

# (str) Версия приложения
version = 1.0.0

# (list) Зависимости проекта
#requirements = python3,kivy,requests,urllib3,chardet,idna,certifi,plyer,pyjnius,cffi,vosk,hostpython3
#requirements = python3,kivy,requests,urllib3,chardet,idna,certifi,plyer,pyjnius,cffi,vosk,hostpython3,srt
#requirements = python3,kivy,requests,urllib3,chardet,idna,certifi,plyer,pyjnius,cffi,vosk,hostpython3,srt,tqdm,charset-normalizer
#requirements = python3, kivy, requests, urllib3, chardet, idna, certifi, plyer, pyjnius, cffi, hostpython3, srt, tqdm, charset-normalizer, vosk, opencv
#requirements = python3, kivy, requests, urllib3, chardet, idna, certifi, plyer, pyjnius, cffi, hostpython3, srt, tqdm, charset-normalizer, vosk, opencv, numpy, google-genai
#requirements = python3, kivy, requests, urllib3, chardet, idna, certifi, plyer, pyjnius, cffi, hostpython3, srt, tqdm, charset-normalizer, vosk, opencv, numpy, httpx, websockets, pillow
#requirements = python3, kivy, requests, urllib3, chardet, idna, certifi, plyer, pyjnius, cffi, hostpython3, srt, tqdm, charset-normalizer, vosk, opencv, numpy, httpx, httpcore, h11, websockets, pillow
#requirements = python3, kivy, requests, urllib3, chardet, idna, certifi, plyer, pyjnius, cffi, hostpython3, srt, tqdm, charset-normalizer, vosk, opencv, numpy, pillow, websockets, httpx, httpcore, h11, anyio
requirements = python3, kivy, requests, urllib3, chardet, idna, certifi, plyer, pyjnius, cffi, hostpython3, srt, tqdm, charset-normalizer, vosk, opencv, numpy, pillow, websockets
# (str) Ориентация экрана
orientation = portrait

# (bool) Показывать статус-бар телефона (0 - показывать)
fullscreen = 0

# --- Настройки Android ---

# (list) Разрешения Android для работы сети и микрофона
#android.permissions = INTERNET, RECORD_AUDIO, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE, WRITE_EXTERNAL_STORAGE, READ_EXTERNAL_STORAGE
android.permissions = INTERNET, RECORD_AUDIO, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE, WRITE_EXTERNAL_STORAGE, READ_EXTERNAL_STORAGE, CAMERA

android.add_libs_out_dir = libs/
# Указываем сборщику, где искать ваши дополнительные библиотеки
android.add_libs = libs/armeabi-v7a, libs/arm64-v8a

# Разрешаем включить содержимое этих папок в APK
#source.include_patterns = libs/**

# (int) Target Android API
android.api = 33

# (int) Минимальная поддерживаемая версия Android API (Android 5.0+)
android.minapi = 21

# Жесткая фиксация версий инструментов, чтобы Buildozer не искал их наугад
#android.sdk = 33
#android.ndk = 25b

# (list) Поддерживаемые архитектуры процессоров
android.archs = arm64-v8a

# (bool) Запрашивать разрешения при запуске приложения
android.grant_permissions = True

# (bool) Разрешить резервное копирование
android.allow_backup = True

# (str) Тема приложения
android.theme = @android:style/Theme.NoTitleBar

# --- Настройки python-for-android (Фиксация стабильной версии) ---
p4a.fork = kivy
p4a.branch = v2024.01.21


[buildozer]

# (int) Уровень логов (2 = подробный вывод)
log_level = 2

# (int) Предупреждение при запуске от root
warn_on_root = 1
