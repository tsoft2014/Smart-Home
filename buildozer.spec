[app]

# (str) Title of your application
title = Управление освещением

# (str) Package name
package.name = lightingcontrol

# (str) Package domain (needed for android packaging)
package.domain = org.smarthome

# (str) Path to the main source code
source.dir = .

# (str) Application versioning
version = 0.1

# (list) Source files to include
source.include_exts = py,png,jpg,kv,atlas,json

# (list) Application requirements
requirements = python3,kivy,requests,pyjnius,plyer

# (str) Supported orientations (landscape, sensor, portrait or all)
orientation = portrait

# (list) Permissions
android.permissions = INTERNET,ACCESS_NETWORK_STATE,RECORD_AUDIO

# (int) Target Android API
android.api = 33

# (int) Minimum API your APK will support
android.minapi = 21

# (bool) Use AndroidX support
android.androidx = True

[buildozer]

# (int) Log level (0 = error only, 1 = info, 2 = debug)
log_level = 2

# (int) Display warning if buildozer is run as root
warn_on_root = 1
