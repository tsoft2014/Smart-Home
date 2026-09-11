[app]

# (str) Название приложения на экране телефона
title = Управление освещением

# (str) Имя пакета (латиницей, без пробелов)
package.name = smarthome

# (str) Домен организации (обратный домен)
package.domain = org.smarthome

# (str) Директория с исходным кодом
source.dir = .

# (list) Расширения файлов для включения в APK (ОБЯЗАТЕЛЬНО картинки и json!)
source.include_exts = py,png,jpg,kv,atlas,json

# (str) Версия приложения
version = 1.0.0

# (list) Зависимости проекта (фиксируем стабильный Python 3.11)
requirements = python3==3.11.0,kivy,requests,urllib3,chardet,idna,certifi,plyer,pyjnius

# (str) Ориентация экрана (вертикальная)
orientation = portrait

# (bool) Показывать статус-бар телефона (0 - показывать, 1 - во весь экран)
fullscreen = 0

# --- Настройки Android ---

# (list) Разрешения Android для микрофона и работы с платами по Wi-Fi
android.permissions = INTERNET, RECORD_AUDIO

# (int) Target Android API
android.api = 33

# (int) Минимальная поддерживаемая версия Android API (Android 5.0+)
android.minapi = 21

# (list) Поддерживаемые архитектуры процессоров
android.archs = arm64-v8a, armeabi-v7a

# (bool) Автоматически запрашивать разрешения при запуске
android.grant_permissions = True

# (bool) Разрешить резервное копирование
android.allow_backup = True

# (str) Тема приложения
android.theme = @android:style/Theme.NoTitleBar

# --- Фикс тулчейна python-for-android (Защита от ошибок venv/pip) ---
p4a.fork = kivy
p4a.branch = master


[buildozer]

# (int) Уровень логов (2 = подробный вывод)
log_level = 2

# (int) Предупреждения при запуске от root
warn_on_root = 1
