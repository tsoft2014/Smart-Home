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
source.include_exts = py,png,jpg,kv,atlas,json,mdl,conf,txt

# (list) Явно разрешаем включить всю папку модели и её содержимое
#source.include_patterns = model/*,model/vosk-model-small-ru-0.22/*,model/vosk-model-small-ru-0.22/**/*
#source.include_patterns = model/*,model/vosk-model-small-ru-0.22/*,model/vosk-model-small-ru-0.22/**/*
# Пример: включаем всю папку model с ее подпапками и бинарниками
source.include_patterns = model/*, *.py

# (str) Версия приложения
version = 1.0.0

# (list) Зависимости проекта
#requirements = python3,kivy,requests,urllib3,chardet,idna,certifi,plyer,pyjnius,cffi,vosk,hostpython3
#requirements = python3,kivy,requests,urllib3,chardet,idna,certifi,plyer,pyjnius,cffi,vosk,hostpython3,srt
#requirements = python3,kivy,requests,urllib3,chardet,idna,certifi,plyer,pyjnius,cffi,vosk,hostpython3,srt,tqdm,charset-normalizer
requirements = python3,kivy,requests,urllib3,chardet,idna,certifi,plyer,pyjnius,cffi,hostpython3,srt,tqdm,charset-normalizer

# (str) Ориентация экрана
orientation = portrait

# (bool) Показывать статус-бар телефона (0 - показывать)
fullscreen = 0

# --- Настройки Android ---

# (list) Разрешения Android для работы сети и микрофона
android.permissions = INTERNET, RECORD_AUDIO, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE, WRITE_EXTERNAL_STORAGE, READ_EXTERNAL_STORAGE

android.add_libs_out_dir = libs/

# (int) Target Android API
android.api = 33

# (int) Минимальная поддерживаемая версия Android API (Android 5.0+)
android.minapi = 21

# (list) Поддерживаемые архитектуры процессоров
android.archs = arm64-v8a#, armeabi-v7a

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