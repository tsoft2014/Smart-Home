[app]

# (str) Title of your application
title = Управление освещением

# (str) Package name
package.name = lightingcontrol

# (str) Package domain (needed for android packaging)
package.domain = org.smarthome

# (list) Source files to include (letting .json and .png for icons/config)
source.include_exts = py,png,jpg,kv,atlas,json

# (list) Application requirements
# Specify 'python3', 'kivy', 'requests', 'pyjnius', 'plyer'
requirements = python3,kivy,requests,pyjnius,plyer

# (str) Supported orientations (landscape, sensor, portrait or all)
orientation = portrait

# (list) Permissions
android.permissions = INTERNET,ACCESS_NETWORK_STATE,RECORD_AUDIO

# (int) Target Android API, should be as high as possible.
android.api = 33

# (int) Minimum API your APK will support.
android.minapi = 21

# (bool) Use AndroidX support
android.androidx = True

# (str) Icon of the application (optional, if you have icon.png)
#icon.filename = %(source.dir)s/icon.png

[buildozer]

# (int) Log level (0 = error only, 1 = info, 2 = debug (with command output))
log_level = 2

# (int) Display warning if buildozer is run as root (0 = False, 1 = True)
warn_on_root = 1
