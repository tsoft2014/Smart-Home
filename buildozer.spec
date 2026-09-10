[app]

# Название приложения
title = Smart Home

# Имя пакета
package.name = smarthome

# Домен пакета
package.domain = org.mysmarthome

# Исходная директория проекта
source.dir = .

# Расширения файлов для включения в сборку
source.include_exts = py,png,jpg,kv,atlas,json

# Папки и файлы для включения (модель Vosk)
source.include_patterns = model/*

# Версия приложения
version = 0.1

# Зависимости проекта (kivy и pyjnius подключаются автоматически внутри python-for-android)
requirements = python3,requests,plyer,cffi,vosk

# Ориентация экрана
orientation = portrait

# Разрешения Android
android.request_permissions = True
android.permissions = RECORD_AUDIO, INTERNET, FOREGROUND_SERVICE, FOREGROUND_SERVICE_MICROPHONE, WAKE_LOCK

# Архитектура процессора (современные 64-битные устройства)
android.archs = arm64-v8a

# Целевой API Android
android.api = 34

# Минимальный поддерживаемый API
android.minapi = 21

# Фиксация стабильной версии NDK для предотвращения ошибок компиляции libffi
android.ndk = 25b

# Полноэкранный режим (0 — выключен, строка состояния видна)
fullscreen = 0

[buildozer]

# Уровень детализации логов (1 — информация)
log_level = 1

# Предупреждение при запуске от root (1 — включено)
warn_on_root = 1
