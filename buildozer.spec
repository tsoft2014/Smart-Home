[app]

# (str) Название приложения
title = Управление освещением

# (str) Имя пакета (без пробелов и спецсимволов)
package.name = smarthome

# (str) Домен организации (обратный домен)
package.domain = org.smarthome

# (str) Исходный код находится в текущей директории
source.dir = .

# (list) Расширения файлов, которые нужно включить в APK (ОБЯЗАТЕЛЬНО картинки и json!)
source.include_exts = py,png,jpg,kv,atlas,json

# (str) Версия приложения
version = 1.0.0

# (list) Зависимости проекта
requirements = python3,kivy,requests,urllib3,chardet,idna,certifi,plyer,pyjnius

# (str) Ориентация экрана (вертикальная)
orientation = portrait

# (bool) Показывать статус-бар телефона
fullscreen = 0

# --- Настройки Android ---

# (list) Системные разрешения Android
android.permissions = INTERNET, RECORD_AUDIO

# (int) Target Android API (33 — стандарт для modern Android)
android.api = 33

# (int) Минимальная поддерживаемая версия Android API (21 = Android 5.0)
android.minapi = 21

# (list) Архитектуры процессоров (поддержка большинства современных смартфонов)
android.archs = arm64-v8a, armeabi-v7a

# (bool) Запрашивать разрешения при первом запуске
android.grant_permissions = True

# (bool) Разрешить резервное копирование
android.allow_backup = True

# (str) Тема приложения (стандартная с заголовком)
android.theme = @android:style/Theme.NoTitleBar


[buildozer]

# (int) Уровень логов (2 = подробный вывод при сборке)
log_level = 2

# (int) Отображение предупреждений
warn_on_root = 1
