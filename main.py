import os
import zipfile
import json
import re
import queue
import threading
import time
import requests
import cv2  # <--- Вот этот импорт нужен для работы с камерой
import asyncio
import traceback
import numpy as np
import itertools
import websockets
import base64
import certifi
import ssl


os.environ["PYTHONIOENCODING"] = "utf-8"

from kivy.config import Config

Config.set('graphics', 'width', '400')
Config.set('graphics', 'height', '700')

from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.metrics import sp, dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.image import Image
from kivy.uix.widget import Widget
from kivy.uix.popup import Popup
from kivy.uix.textinput import TextInput
from kivy.uix.scrollview import ScrollView
from kivy.utils import platform
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.graphics import Color, RoundedRectangle, Line
from kivy.uix.floatlayout import FloatLayout
#from google import genai
#from google.genai import types
from kivy.clock import mainthread
from kivy.graphics.texture import Texture
from kivy.graphics import Color, Ellipse, Line, Rectangle
from io import BytesIO
from kivy.clock import Clock
from kivy.uix.camera import Camera  # Импортируем нативный виджет камеры
from kivy.core.window import Window  # Не забудьте убедиться, что Window импортирован в файле
from kivy.graphics import Color, Rectangle
from kivy.core.image import Texture
from kivy.graphics import Color, RoundedRectangle, Rectangle, Ellipse, Triangle
from kivy.core.clipboard import Clipboard  # <--- Убедитесь, что Clipboard импортирован в начале файла
from kivy.uix.behaviors import ButtonBehavior

# Проверки наличия модулей
try:
    from camera4kivy import Preview
    HAS_CAMERA4KIVY = True
    print("[CAMERA] Camera4Kivy успешно загружена")
except ImportError:
    HAS_CAMERA4KIVY = False
    print("[WARN] camera4kivy not found. Camera will not work on Android.")

try:
    from kivy.uix.camera import Camera
    HAS_KIVY_CAMERA = True
except ImportError:
    HAS_KIVY_CAMERA = False
    print("[WARN] kivy.uix.camera not found. Fallback camera will not work on Android.")

try:
    import cv2
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False
    print("[WARN] opencv-python not found. Camera on PC will not work.")

try:
    from PIL import Image as PilImage
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    print("[WARN] Pillow not found. Image saving/processing might fail.")


# Распаковываем vosk, если папка еще не распакована на устройстве
current_dir = os.path.dirname(os.path.abspath(__file__))
vosk_dir = os.path.join(current_dir, 'vosk')
vosk_zip = os.path.join(current_dir, 'vosk.zip')

if not os.path.exists(vosk_dir) and os.path.exists(vosk_zip):
    with zipfile.ZipFile(vosk_zip, 'r') as zip_ref:
        zip_ref.extractall(current_dir)

HAS_ANDROID_AUDIO = False
AudioRecord = AudioSource = AudioFormat = None
AudioManager = AudioTrack = None
autoclass = None

# 1. Единый блок инициализации Android-аудио и разрешений
if platform == 'android':
    try:
        from android.permissions import request_permissions, Permission

        request_permissions([
            Permission.RECORD_AUDIO,
            Permission.CAMERA,
            Permission.WRITE_EXTERNAL_STORAGE,
            Permission.READ_EXTERNAL_STORAGE,
            Permission.READ_CONTACTS,
            Permission.READ_PHONE_STATE,
            Permission.CALL_PHONE
        ])
    except Exception as e:
        print(f"[ANDROID PERMISSIONS ERROR]: {e}")

    try:
        from jnius import autoclass

        AudioRecord = autoclass('android.media.AudioRecord')
        AudioSource = autoclass('android.media.MediaRecorder$AudioSource')
        AudioFormat = autoclass('android.media.AudioFormat')
        AudioManager = autoclass('android.media.AudioManager')
        AudioTrack = autoclass('android.media.AudioTrack')
        HAS_ANDROID_AUDIO = True
    except Exception as e:
        print(f"[ANDROID AUDIO INIT ERROR]: {e}")
        HAS_ANDROID_AUDIO = False
else:
    HAS_ANDROID_AUDIO = False

if platform == 'android':
    from jnius import autoclass, java_method, PythonJavaClass
    Context = autoclass('android.content.Context')
    Intent = autoclass('android.content.Intent')
    IntentFilter = autoclass('android.content.IntentFilter')
    TelephonyManager = autoclass('android.telephony.TelephonyManager')
    PythonActivity = autoclass('org.kivy.android.PythonActivity')
    Uri = autoclass('android.net.Uri')
    KeyEvent = autoclass('android.view.KeyEvent')

    # Нативный Java-ресивер для отслеживания звонков
    class PhoneStateReceiver(PythonJavaClass):
        __javainterfaces__ = ['android/content/BroadcastReceiver']
        __javachain__ = ['java/lang/Object']

        def __init__(self, callback):
            super(PhoneStateReceiver, self).__init__()
            self.callback = callback

        @java_method('(Landroid/content/Context;Landroid/content/Intent;)V')
        def onReceive(self, context, intent):
            action = intent.getAction()
            if action == TelephonyManager.ACTION_PHONE_STATE_CHANGED:
                state = intent.getStringExtra(TelephonyManager.EXTRA_STATE)
                if state == TelephonyManager.EXTRA_STATE_RINGING:
                    incoming_number = intent.getStringExtra(TelephonyManager.EXTRA_INCOMING_NUMBER)
                    if self.callback:
                        self.callback("ringing", incoming_number)
                elif state == TelephonyManager.EXTRA_STATE_IDLE:
                    if self.callback:
                        self.callback("idle", None)
else:
    class PhoneStateReceiver:
        def __init__(self, callback):
            self.callback = callback

# Безопасный импорт sounddevice только для ПК
HAS_SOUNDDEVICE = False
sd = None
if platform != 'android':
    try:
        import sounddevice as sd
        HAS_SOUNDDEVICE = True
    except (ImportError, OSError) as e:
        print(f"[PC SOUNDDEVICE INIT ERROR]: {e}")
        sd = None
        HAS_SOUNDDEVICE = False

try:
    from vosk import Model, KaldiRecognizer
    HAS_VOSK = True
    print("[VOSK DEBUG] Модуль vosk успешно импортирован!")
except Exception as e:
    Model = None
    KaldiRecognizer = None
    HAS_VOSK = False
    print(f"[VOSK IMPORT CRITICAL ERROR] {type(e).__name__}: {e}")

current_dir = os.path.dirname(os.path.abspath(__file__))

if platform == 'android':
    possible_paths = [
        # Самый надежный вариант: рядом с текущим main.py внутри private.tar
        os.path.join(current_dir, "model", "vosk-model-small-ru-0.22"),
        # Текущая рабочая директория
        os.path.join(os.getcwd(), "model", "vosk-model-small-ru-0.22"),
    ]
    # Безопасно добавляем user_data_dir, если app уже запущен
    try:
        from kivy.app import App
        app = App.get_running_app()
        if app and app.user_data_dir:
            possible_paths.append(os.path.join(app.user_data_dir, "model", "vosk-model-small-ru-0.22"))
    except Exception:
        pass
else:
    possible_paths = ["model/vosk-model-small-ru-0.22"]

# Ищем первый существующий путь
model_path = None
for path in possible_paths:
    print(f"DEBUG_VOSK: Проверяем путь -> {path} (существует: {os.path.exists(path)})")
    if os.path.exists(path):
        model_path = path
        break

if model_path and HAS_VOSK:
    try:
        model = Model(model_path)
        print(f"[VOSK DEBUG] Модель успешно загружена из: {model_path}")
    except Exception as e:
        print(f"[VOSK LOAD ERROR] {type(e).__name__}: {e}")
else:
    print("[VOSK ERROR] Не удалось найти папку модели ни по одному из путей!")

tts_lock = threading.Lock()

# Инициализация Android TTS с правильным callback и Locale
_android_tts = None
if platform == 'android':
    try:
        from jnius import autoclass, java_method, PythonJavaClass

        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        TextToSpeech = autoclass('android.speech.tts.TextToSpeech')
        Locale = autoclass('java.util.Locale')


        class TTSListener(PythonJavaClass):
            __javainterfaces__ = ['android/speech/tts/TextToSpeech$OnInitListener']
            __javachars__ = None

            @java_method('(I)V')
            def onInit(self, status):
                global _android_tts
                if status == TextToSpeech.SUCCESS:
                    try:
                        ru_locale = Locale("ru", "RU")
                        result = _android_tts.setLanguage(ru_locale)
                        if result == TextToSpeech.LANG_MISSING_DATA or result == TextToSpeech.LANG_NOT_SUPPORTED:
                            print("[ANDROID TTS] Русский язык не поддерживается на устройстве")
                        else:
                            print("[ANDROID TTS] Движок успешно инициализирован и настроен!")
                    except Exception as e:
                        print(f"[ANDROID TTS CONFIG ERROR]: {e}")
                else:
                    print("[ANDROID TTS] Ошибка инициализации нативного движка")


        _tts_listener = TTSListener()
        _android_tts = TextToSpeech(PythonActivity.mActivity, _tts_listener)

    except Exception as e:
        print(f"[ANDROID TTS INIT ERROR]: {e}")
        _android_tts = None

_audio_play_counter = itertools.count(1)


def speak(text, on_done_callback=None):
    if not text or not str(text).strip():
        if on_done_callback:
            on_done_callback()
        return

    text = str(text).strip()

    # --- НИЗКОУРОВНЕВАЯ ЛОВУШКА СО СТРОГИМ ФИЛЬТРОМ НА "СЛУШАЮ" ---
    call_id = next(_audio_play_counter)

    if "слушаю" in text.lower():
        print(f"\n🚨 [TARGET LOCKED: 'СЛУШАЮ' #{call_id}] ФИЗИЧЕСКИЙ ЗАПРОС ЗВУКА: '{text}'")
        print("Стек вызовов для слова 'слушаю':")
        for line in traceback.format_stack()[:-1]:
            print("   ->", line.strip())
        print("=" * 60)

    # -----------------------------------------------------------

    def _say_thread():
        with tts_lock:
            if platform == 'android':
                try:
                    if _android_tts is not None:
                        print(f"🚨 [ANDROID AUDIO EXECUTE #{call_id}] Запуск нативного speak")
                        HashMap = autoclass('java.util.HashMap')
                        params = HashMap()
                        _android_tts.speak(text, 0, params)
                    else:
                        print(f"[ANDROID TTS ERROR #{call_id}]: Движок не инициализирован")
                except Exception as e:
                    print(f"[ANDROID TTS ERROR #{call_id}]: {e}")
            else:
                pythoncom_imported = False
                try:
                    try:
                        import pythoncom
                        pythoncom.CoInitialize()
                        pythoncom_imported = True
                    except ImportError:
                        pass

                    import pyttsx3
                    print(f"🚨 [PC AUDIO EXECUTE #{call_id}] Инициализация pyttsx3 и старт say()")
                    engine = pyttsx3.init()
                    engine.setProperty('rate', 170)
                    engine.say(text)
                    engine.runAndWait()
                    engine.stop()
                    print(f"🚨 [PC AUDIO EXECUTE #{call_id}] Воспроизведение завершено")
                except Exception as e:
                    print(f"[PC TTS ERROR #{call_id}]: {e}")
                finally:
                    if pythoncom_imported:
                        try:
                            import pythoncom
                            pythoncom.CoUninitialize()
                        except Exception:
                            pass

            if on_done_callback:
                on_done_callback()

    threading.Thread(target=_say_thread, daemon=True, name=f"TTS-Thread-{call_id}").start()

def format_temperature_speech(temp_value):
    try:
        temp = float(temp_value)
    except (ValueError, TypeError):
        return "Не удалось определить температуру"

    temp = round(temp, 1)
    is_negative = temp < 0
    temp_abs = abs(temp)

    int_part = int(temp_abs)
    dec_part = int(round((temp_abs - int_part) * 10))

    if dec_part == 10:
        int_part += 1
        dec_part = 0

    prefix = "минус " if is_negative else ""

    if dec_part == 0:
        if 11 <= (int_part % 100) <= 19:
            degree = "градусов"
        else:
            last = int_part % 10
            if last == 1:
                degree = "градус"
            elif last in (2, 3, 4):
                degree = "градуса"
            else:
                degree = "градусов"
        return f"Текущая температура {prefix}{int_part} {degree}"

    tenths_words = {
        1: "одна десятая", 2: "две десятых", 3: "три десятых",
        4: "четыре десятых", 5: "пять десятых", 6: "шесть десятых",
        7: "семь десятых", 8: "восемь десятых", 9: "девять десятых"
    }
    tenths_text = tenths_words.get(dec_part, f"{dec_part} десятых")

    return f"Текущая температура {prefix}{int_part} и {tenths_text} градуса"


# Ресурсы картинок
IMG_LAMP_1_OFF = "lamp_1_off.png"
IMG_LAMP_1_ON = "lamp_1_on.png"
IMG_LAMP_2_OFF = "lamp_2_off.png"
IMG_LAMP_2_ON = "lamp_2_on.png"
IMG_LAMP_3_OFF = "lamp_3_off.png"
IMG_LAMP_3_ON = "lamp_3_on.png"

IMG_SWITCH_OFF = "Switch_OFF.png"
IMG_SWITCH_ON = "Switch_ON-1.png"
IMG_WIFI = "wifi_icon.png"
IMG_PHONE = "phone_icon.png"

CONFIG_FILE = "config.json"

DEFAULT_CONFIG = {
    "device_ip": "192.168.1.39",
    "sensor_ip": "192.168.1.39",
    "tts_enabled": True,
    "wake_word_ai": "джарвис",
    "wake_word_cam": "снимок",
    "wake_word_light": "свет",
    "wake_response": "Слушаю",
    "wake_timeout_sec": 120,
    "channels": [
        {"id": 4, "name": "Лампу 1"},
        {"id": 5, "name": "Лампу 2"},
        {"id": 0, "name": "Лампу 3"}
    ],
    "voice_commands": [],
    "voice_responses": []
}
TIMEOUT = 4
# --- Константы таймеров ---
POLL_INTERVAL = 5.0             # Частота сетевых запросов к ESP8266 (реле, температура)
ASSISTANT_TICK_INTERVAL = 1.0   # Частота проверки активности и пауз речи ассистента


def get_img(filename):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, filename)


def load_config():
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return DEFAULT_CONFIG


def save_config(config_data):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, ensure_ascii=False, indent=4)


# 2. Затем вспомогательные функции (включая set_visible)
def set_visible(widget, is_visible):
    """
    Аналог свойства Visible из MIT App Inventor для Kivy.
    """
    if not hasattr(widget, '_saved_size_hint'):
        widget._saved_size_hint = list(widget.size_hint) if widget.size_hint else [None, None]
        widget._saved_size = list(widget.size) if widget.size else [100, 50]

    if is_visible:
        widget.size_hint = widget._saved_size_hint
        widget.size = widget._saved_size
        widget.opacity = 1
        widget.disabled = False
    else:
        if widget.size_hint[0] is not None:
            widget._saved_size_hint[0] = widget.size_hint[0]
        if widget.size_hint[1] is not None:
            widget._saved_size_hint[1] = widget.size_hint[1]

        widget.size_hint_y = None
        widget.height = 0
        widget.opacity = 0
        widget.disabled = True



class FixedButton(Button):
    def __init__(self, bg_color=(0.2, 0.25, 0.35, 1), **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ''
        self.background_color = (0, 0, 0, 0)
        self.color = (1, 1, 1, 1)
        self.bold = True

        with self.canvas.before:
            self.rect_color = Color(*bg_color)
            self.rect = RoundedRectangle(size=self.size, pos=self.pos, radius=[10])

        self.bind(pos=self.update_canvas, size=self.update_canvas)

    def update_canvas(self, *args):
        self.rect.pos = self.pos
        self.rect.size = self.size


class LampRow(BoxLayout):
    def __init__(self, channel_id, icon_off, icon_on, base_url_provider, app_ref=None, **kwargs):
        super().__init__(
            orientation='horizontal',
            size_hint_x=1,
            padding=[dp(15), dp(10), dp(15), dp(10)],
            size_hint_y=None,
            height=dp(110),
            **kwargs
        )
        self.channel_id = channel_id
        self.icon_off = icon_off
        self.icon_on = icon_on
        self.is_on = False
        self.get_base_url = base_url_provider
        self.app = app_ref

        self.icon_widget = Image(
            source=get_img(self.icon_off),
            size_hint=(None, None),
            size=(dp(100), dp(85)),
            allow_stretch=True,
            keep_ratio=True,
            pos_hint={'center_y': 0.5}
        )
        self.add_widget(self.icon_widget)
        self.add_widget(Widget())

        self.btn_switch = Button(
            background_normal=get_img(IMG_SWITCH_OFF),
            background_down=get_img(IMG_SWITCH_OFF),
            size_hint=(None, None),
            size=(dp(140), dp(68)),
            border=(0, 0, 0, 0),
            pos_hint={'center_y': 0.5}
        )
        self.btn_switch.bind(on_press=lambda x: self.toggle_action())
        self.add_widget(self.btn_switch)

    def turn_on(self):
        def req():
            try:
                res = requests.get(f"{self.get_base_url()}/{self.channel_id}/on", timeout=TIMEOUT)
                if res.status_code == 200:
                    self.is_on = True
                    self._update_ui()
            except Exception as e:
                print(f"[ОШИБКА РЕЛЕ ON]: {e}")

        threading.Thread(target=req, daemon=True).start()

    def turn_off(self):
        def req():
            try:
                res = requests.get(f"{self.get_base_url()}/{self.channel_id}/off", timeout=TIMEOUT)
                if res.status_code == 200:
                    self.is_on = False
                    self._update_ui()
            except Exception as e:
                print(f"[ОШИБКА РЕЛЕ OFF]: {e}")

        threading.Thread(target=req, daemon=True).start()

    def toggle_action(self):
        if self.is_on:
            self.turn_off()
        else:
            self.turn_on()

    @mainthread
    def _update_ui(self):
        if self.is_on:
            self.btn_switch.background_normal = get_img(IMG_SWITCH_ON)
            self.btn_switch.background_down = get_img(IMG_SWITCH_ON)
            self.icon_widget.source = get_img(self.icon_on)
        else:
            self.btn_switch.background_normal = get_img(IMG_SWITCH_OFF)
            self.btn_switch.background_down = get_img(IMG_SWITCH_OFF)
            self.icon_widget.source = get_img(self.icon_off)

    def check_status(self):
        def req():
            try:
                res = requests.get(f"{self.get_base_url()}/{self.channel_id}", timeout=TIMEOUT)
                if res.status_code == 200:
                    text = res.text.upper()
                    if f"GPIO{self.channel_id}ON" in text:
                        self.is_on = True
                    elif f"GPIO{self.channel_id}OFF" in text:
                        self.is_on = False
                    self._update_ui()
            except Exception:
                pass

        threading.Thread(target=req, daemon=True).start()

    def set_state(self, state: int):
        if state == 1:
            self.turn_on()
        else:
            self.turn_off()


class VoiceAssistant:
    def __init__(self, app, lamp_objects):
        self.app = app
        self.lamp_objects = lamp_objects
        self.is_speaking = False

        # Модель приходит готовой из экрана SmartHomeScreen.
        self.model = getattr(app, "model", None)

        self.q = queue.Queue(maxsize=50)
        self.listening = False
        self.is_active = False
        self.last_active_time = 0
        self._audio_needs_restart = False
        self.current_session_mode = None
        self.voice_input_target = None

        self._thread_started = False
        self._processor_running = False

        self._processor_thread = None
        self._record_thread = None
        self._audio_record = None
        self.stream = None

        self._lifecycle_lock = threading.Lock()
        # <--- ВОТ ТУТ ДОБАВЛЯЕМ АТРИБУТ ТАЙМЕРА --->
        self.assistant_event = None

        # Запускаем фоновое отслеживание таймаута каждую секунду
        self.start_activity_timer()

        self.is_speaking = False
        self.last_spoken_text = ""
        self.current_engine = None  # Ссылка на активный движок pyttsx3 для экстренной остановки

    def start_activity_timer(self):
        # Отменяем предыдущий запуск, если он был, чтобы не плодить дубликаты
        if self.assistant_event:
            self.assistant_event.cancel()

        # Запускаем проверку каждую 1 секунду
        self.assistant_event = Clock.schedule_interval(self.check_activity_timeout, 1)

    def stop_activity_timer(self):
        if self.assistant_event:
            self.assistant_event.cancel()
            self.assistant_event = None

    def stop(self):
        """Экстренная остановка речи (вызывается по кнопке Стоп)"""
        print("[TTS] Принудительный сброс движка озвучки...")

        # 1. Останавливаем pyttsx3 на ПК
        if self.current_engine:
            try:
                self.current_engine.stop()
            except Exception:
                pass
            try:
                self.current_engine.endLoop()
            except Exception:
                pass
            self.current_engine = None

        # 2. Останавливаем на Android, если поддерживается
        if platform == "android":
            try:
                global _android_tts
                if _android_tts is not None:
                    _android_tts.stop()
            except Exception:
                pass

        self.is_speaking = False

    def normalize_numbers_to_words(self, text):
        if not text:
            return ""
        import re

        ones = {
            '0': 'ноль', '1': 'один', '2': 'два', '3': 'три', '4': 'четыре',
            '5': 'пять', '6': 'шесть', '7': 'семь', '8': 'восемь', '9': 'девять',
            '10': 'десять', '11': 'одиннадцать', '12': 'двенадцать', '13': 'тринадцать',
            '14': 'четырнадцать', '15': 'пятнадцать', '16': 'шестнадцать',
            '17': 'семнадцать', '18': 'восемнадцать', '19': 'девятнадцать'
        }

        tens = {
            '2': 'двадцать', '3': 'тридцать', '4': 'сорок', '5': 'пятьдесят',
            '6': 'шестьдесят', '7': 'семьдесят', '8': 'восемьдесят', '9': 'девяносто'
        }

        def convert(match):
            num_str = match.group(0)
            if num_str in ones:
                return ones[num_str]
            if len(num_str) == 2:
                t = tens.get(num_str[0], '')
                o = ones.get(num_str[1], '') if num_str[1] != '0' else ''
                return f"{t} {o}".strip()
            return num_str

        return re.sub(r'\b\d+\b', convert, text)

    def clean_text_for_tts(self, text):
        if not text:
            return ""

        # --- СЛОВАРЬ ФОНЕТИЧЕСКИХ КОРРЕКЦИЙ ДЛЯ TTS ---
        # Здесь можно прописывать слова, которые движок читает неправильно
        pronunciation_dict = {
            r'\bкому\b': 'камý',
            r'\bтак\b': 'так',
            r'\bи\b': 'и',
            r'\bговори\b': 'говóри',
            r'\bне\b': 'не',
            r'\bправильно\b': 'прáвильно',
        }

        for pattern, replacement in pronunciation_dict.items():
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

        # Универсальная замена точек между цифрами (например, 3.5 -> 3 и 5)
        text = re.sub(r'(\d+)\.(\d+)', r'\1 и \2', text)

        # 1. Очищаем LaTeX и математические символы формулы
        text = text.replace(r'\times', ' умножить на ')
        text = text.replace(r'{,}', ',')
        text = re.sub(r'\\text\{([^}]+)\}', r'\1', text)
        text = re.sub(r'\\mathbf\{([^}]+)\}', r'\1', text)
        text = re.sub(r'[$*_\\{}]', '', text)

        # 2. Заменяем знаки операций на слова
        text = text.replace('×', ' умножить на ')
        text = text.replace('=', ' равно ')

        # 3. Очистка стандартного Markdown
        text = re.sub(r'#+\s*', '', text)
        text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
        text = re.sub(r'`{1,3}', '', text)

        # 4. Обработка знаков препинания и спецсимволов для TTS
        text = re.sub(r'\s*—\s*', ', ', text)
        text = re.sub(r'[«»„“"\'\[\]()<>|~^]', ' ', text)

        # 5. Нормализация сокращений единиц измерения
        text = re.sub(r'\bмл\b', 'миллилитров', text, flags=re.IGNORECASE)
        text = re.sub(r'\bг\b', 'грамм', text, flags=re.IGNORECASE)

        # 6. Конвертируем числа в слова
        text = self.normalize_numbers_to_words(text)

        # 7. Убираем образовавшиеся двойные пробелы
        text = re.sub(r'\s+', ' ', text)

        return text.strip()

    def speak(self, text, on_done_callback=None):
        if not text or not str(text).strip():
            if on_done_callback:
                on_done_callback()
            return

        if self.is_speaking:
            self.stop()

        # Очищаем текст прямо внутри ассистента!
        clean_text = self.clean_text_for_tts(str(text))
        self.last_spoken_text = clean_text.lower()

        def _say_thread(cb=on_done_callback):
            self.is_speaking = True
            engine = None
            pythoncom_imported = False

            try:
                if platform == "android":
                    try:
                        if _android_tts is not None:
                            HashMap = autoclass("java.util.HashMap")
                            params = HashMap()
                            _android_tts.speak(clean_text, 0, params)

                            import time
                            words = clean_text.split()
                            for _ in range(len(words) * 2):
                                if not self.is_speaking:
                                    try:
                                        _android_tts.stop()
                                    except Exception:
                                        pass
                                    break
                                time.sleep(0.3)
                    except Exception as e:
                        print(f"[ANDROID TTS ERROR]: {e}")
                else:
                    try:
                        import pythoncom
                        pythoncom.CoInitialize()
                        pythoncom_imported = True
                    except ImportError:
                        pass

                    import pyttsx3
                    engine = pyttsx3.init()
                    self.current_engine = engine
                    engine.setProperty("rate", 170)

                    # Разбиваем очищенный текст на предложения для мгновенной отмены
                    import re
                    sentences = re.split(r'(?<=[.!?])\s+', clean_text)

                    for sentence in sentences:
                        if not self.is_speaking:
                            print("[TTS] Озвучка прервана.")
                            break
                        if sentence.strip():
                            engine.say(sentence)
                            engine.runAndWait()

            except Exception as e:
                print(f"[PC TTS ERROR]: {e}")

            finally:
                if engine:
                    try:
                        engine.stop()
                        engine.endLoop()
                    except Exception:
                        pass

                if self.current_engine == engine:
                    self.current_engine = None

                if pythoncom_imported:
                    try:
                        import pythoncom
                        pythoncom.CoUninitialize()
                    except Exception:
                        pass

                self.is_speaking = False
                if cb:
                    cb()

        threading.Thread(target=_say_thread, daemon=True).start()

    def stop(self):
        print("[Assistant] Принудительная остановка...")
        self.is_speaking = False
        if hasattr(self, 'current_engine') and self.current_engine:
            try:
                self.current_engine.stop()
                self.current_engine.endLoop()
            except Exception:
                pass
            self.current_engine = None

    def set_voice_input_target(self, callback_func):
        self.voice_input_target = callback_func

    def start_listening(self):
        with self._lifecycle_lock:
            # Не запускаем новые потоки, пока старые ещё работают.
            threads = (self._processor_thread, self._record_thread)
            if any(thread and thread.is_alive() for thread in threads):
                print("[VOICE] Прослушивание уже запущено или ещё завершается.")
                return

            if not HAS_VOSK or not self.model:
                print("[VOICE] Ошибка: Vosk не готов или модель не загружена.")
                return

            self._processor_thread = None
            self._record_thread = None
            self._audio_needs_restart = False

            if platform != "android":
                if not HAS_SOUNDDEVICE:
                    self.app.update_assistant_status(
                        "Ассистент: Ошибка sounddevice",
                        color=(0.9, 0.2, 0.2, 1),
                    )
                    return

                try:
                    self.stream = sd.RawInputStream(
                        samplerate=16000,
                        blocksize=8000,
                        dtype="int16",
                        channels=1,
                        callback=self.audio_callback,
                    )
                    self.stream.start()

                except Exception as e:
                    self.stream = None
                    print(f"[PC RECORD ERROR]: {e}")
                    self.app.update_assistant_status(
                        "Ассистент: Ошибка микрофона ПК",
                        color=(0.9, 0.2, 0.2, 1),
                    )
                    return

            self.listening = True
            self._thread_started = True

            self._processor_thread = threading.Thread(
                target=self.processor_loop,
                daemon=True,
                name="ProcessorLoop-Main",
            )
            self._processor_thread.start()

            if platform == "android":
                self._record_thread = threading.Thread(
                    target=self._android_record_loop,
                    daemon=True,
                    name="AndroidRecordLoop",
                )
                self._record_thread.start()
            else:
                hint_word = self.get_current_wake_hint()
                self.app.update_assistant_status(
                    f"Ассистент: Ожидание («{hint_word}»)",
                    color=(0.6, 0.6, 0.6, 1),
                )

    def stop_listening(self):
        self.listening = False
        self._audio_needs_restart = True

        # Останавливаем микрофон ПК.
        stream = self.stream
        self.stream = None

        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass

            try:
                stream.close()
            except Exception:
                pass

        # Останавливаем Android-запись. Освобождает AudioRecord
        # сам Android-поток в блоке finally.
        audio_record = self._audio_record
        if audio_record is not None:
            try:
                if audio_record.getRecordingState() == AudioRecord.RECORDSTATE_RECORDING:
                    audio_record.stop()
            except Exception:
                pass

        # Разбудить processor_loop, если он ждёт данные из очереди.
        try:
            self.q.put_nowait(b"")
        except queue.Full:
            pass

        current_thread = threading.current_thread()
        threads = (self._processor_thread, self._record_thread)

        for thread in threads:
            if thread and thread.is_alive() and thread is not current_thread:
                thread.join(timeout=3)

        still_running = any(
            thread and thread.is_alive() and thread is not current_thread
            for thread in threads
        )

        if not still_running:
            self._thread_started = False
            self._processor_thread = None
            self._record_thread = None

        # Удаляем оставшиеся аудиоданные.
        while True:
            try:
                self.q.get_nowait()
            except queue.Empty:
                break

        print("[VOICE] Прослушивание остановлено.")

    def _android_record_loop(self):
        sample_rate = 16000
        channel_config = AudioFormat.CHANNEL_IN_MONO
        audio_format = AudioFormat.ENCODING_PCM_16BIT

        while self.listening:
            if self._audio_needs_restart:
                self._audio_needs_restart = False
                break

            audio_record = None

            try:
                min_buf_size = AudioRecord.getMinBufferSize(
                    sample_rate,
                    channel_config,
                    audio_format,
                )

                if min_buf_size <= 0:
                    min_buf_size = 4096

                buffer_size = 3200

                audio_record = AudioRecord(
                    AudioSource.VOICE_RECOGNITION,
                    sample_rate,
                    channel_config,
                    audio_format,
                    max(min_buf_size, buffer_size),
                )
                self._audio_record = audio_record

                if audio_record.getState() != AudioRecord.STATE_INITIALIZED:
                    time.sleep(1.0)
                    continue

                audio_record.startRecording()
                buf = bytearray(buffer_size)

                while self.listening:
                    if self._audio_needs_restart:
                        self._audio_needs_restart = False
                        break

                    if self.is_speaking:
                        time.sleep(0.05)
                        continue

                    read_bytes = audio_record.read(buf, 0, buffer_size)

                    if read_bytes > 0:
                        try:
                            self.q.put_nowait(bytes(buf[:read_bytes]))
                        except queue.Full:
                            pass

                    elif read_bytes == AudioRecord.ERROR_INVALID_OPERATION:
                        self._audio_needs_restart = True
                        break

                    else:
                        time.sleep(0.01)

            except Exception as e:
                if self.listening:
                    print(f"[ANDROID RECORD LOOP CRITICAL]: {e}")
                    time.sleep(1.0)

            finally:
                try:
                    if audio_record is not None:
                        if (
                            audio_record.getRecordingState()
                            == AudioRecord.RECORDSTATE_RECORDING
                        ):
                            audio_record.stop()

                        audio_record.release()
                except Exception:
                    pass

                if self._audio_record is audio_record:
                    self._audio_record = None

    def audio_callback(self, indata, frames, time_info, status):
        if self.is_speaking or not self.listening:
            return

        try:
            self.q.put_nowait(bytes(indata))
        except queue.Full:
            pass

    def processor_loop(self):
        if not HAS_VOSK or not self.model:
            print("[LOOP DEBUG] Vosk или модель не инициализированы.")
            return

        if self._processor_running:
            print("[LOOP DEBUG] Повторный запуск processor_loop отклонён.")
            return

        self._processor_running = True
        print(
            f"[LOOP DEBUG] === Поток processor_loop СТАРТОВАЛ "
            f"({threading.current_thread().name}) ==="
        )

        try:
            recognizer = KaldiRecognizer(self.model, 16000)

            while self.listening:
                try:
                    data = self.q.get(timeout=0.5)

                    if not data or self.is_speaking:
                        continue

                    if recognizer.AcceptWaveform(data):
                        result = json.loads(recognizer.Result())
                        text = result.get("text", "").lower().strip()

                        if text:
                            recognizer.Reset()

                            while True:
                                try:
                                    self.q.get_nowait()
                                except queue.Empty:
                                    break

                            self.process_command(text)

                except queue.Empty:
                    continue

                except Exception as e:
                    print(f"[VOSK PROCESSOR ERROR]: {e}")
                    time.sleep(0.05)

        except Exception as e:
            print(f"[VOSK INITIALIZATION ERROR]: {e}")

        finally:
            self._processor_running = False
            print("[LOOP DEBUG] === Поток processor_loop ОСТАНОВЛЕН ===")

    def set_active_wake_word(self, word):
        self.active_wake_word = word.lower().strip() if word else None
        wake_word = word.capitalize() if word else "Джарвис"

        self.app.update_assistant_status(
            f"Ассистент: Ожидание («{wake_word}»)",
            color=(0.6, 0.6, 0.6, 1),
        )

    def check_activity_timeout(self, dt=None):
        app_instance = App.get_running_app()

        # --- ЖЁСТКИЙ ПЕРХВАТ ДЛЯ LIVE-ДИАЛОГА ---
        is_live = (
                getattr(self, "is_live_active", False)
                or getattr(self, "app", None) and getattr(self.app, "is_live_active", False)
                or (app_instance and getattr(app_instance, "is_live_active", False))
        )

        if is_live:
            # Пока идет Live-диалог, полностью замораживаем таймер неактивности
            self.last_active_time = time.time()
            self.speech_buffer = ""
            return
        # ----------------------------------------

        if not self.is_active:
            return

        current_mode = getattr(self, "current_session_mode", None)

        if getattr(self, "speech_buffer", ""):
            try:
                pause_sec = float(
                    self.app.config_data.get("pause_timer", 5)
                )
            except (ValueError, TypeError):
                pause_sec = 5.0

            last_speech = getattr(self, "last_speech_time", time.time())

            if time.time() - last_speech > pause_sec:
                final_query = self.speech_buffer.strip()
                self.speech_buffer = ""

                if final_query:
                    try:
                        if (
                            app_instance
                            and app_instance.root
                            and hasattr(app_instance.root, "current")
                        ):
                            screen_manager = app_instance.root

                            if screen_manager.has_screen(screen_manager.current):
                                screen = screen_manager.get_screen(
                                    screen_manager.current
                                )

                                if screen and hasattr(screen, "receive_voice_query"):
                                    screen.receive_voice_query(final_query)
                                    return

                    except Exception as e:
                        print(f"[PAUSE FORWARD ERROR]: {e}")

        config = getattr(getattr(self, "app", None), "config_data", {}) or {}

        try:
            if current_mode == "light":
                timeout_sec = int(config.get("activity_timer_light", 30))
            elif current_mode == "cam":
                timeout_sec = int(config.get("activity_timer_cam", 30))
            else:  # Для "ai" и остальных режимов по умолчанию
                timeout_sec = int(config.get("activity_timer", 30))
        except (ValueError, TypeError):
            timeout_sec = 30

        last_active = getattr(self, "last_active_time", time.time())

        if time.time() - last_active > timeout_sec:
            self.is_active = False
            self.current_session_mode = None
            self.speech_buffer = ""

            hint_word = self.get_current_wake_hint()
            idle_text = f"Ассистент: Ожидание («{hint_word}»)"
            idle_color = (0.6, 0.6, 0.6, 1)

            try:
                if app_instance:
                    if hasattr(app_instance, "update_current_screen_status"):
                        app_instance.update_current_screen_status(idle_text, color=idle_color)

                    if hasattr(app_instance, "update_assistant_status"):
                        app_instance.update_assistant_status(idle_text, color=idle_color)
            except Exception as e:
                print(f"[TIMEOUT ERROR]: {e}")

    def activate(self):
        """Оригинальный метод активации с очисткой очереди и корректным обновлением таймера."""
        # Очищаем очередь распознавания Vosk от старого мусора
        if hasattr(self, 'q'):
            while True:
                try:
                    self.q.get_nowait()
                except queue.Empty:
                    break

        # БЕЗУСЛОВНО обновляем время старта таймера при каждом включении!
        self.last_active_time = time.time()

        self.is_active = True
        self.current_session_mode = "light"

        # Безопасное обновление визуального статуса на всех экранах
        app_inst = getattr(self, 'app', None) or App.get_running_app()
        if app_inst:
            status_text = "Ассистент: Слушаю команды..."
            status_color = (0.2, 0.85, 0.3, 1)

            if hasattr(app_inst, 'update_current_screen_status'):
                app_inst.update_current_screen_status(status_text, color=status_color)

            if hasattr(app_inst, 'update_assistant_status'):
                app_inst.update_assistant_status(status_text, color=status_color)

    def get_custom_response(self, sub_action, channel_id=None):
        responses = self.app.config_data.get("voice_responses", [])

        for response in responses:
            if (
                response.get("sub_action") == sub_action
                and response.get("channel_id") == channel_id
            ):
                value = (response.get("response_text") or "").strip()
                if value:
                    return value

        return ""

    def get_current_wake_hint(self):
        current_screen_name = ""

        if hasattr(self.app, "root") and self.app.root:
            current_screen_name = getattr(self.app.root, "current", "")

        if current_screen_name in ("main", "smarthome") or not current_screen_name:
            raw = self.app.config_data.get("wake_word_light", "зал")
        elif current_screen_name == "ai_camera":
            raw = self.app.config_data.get("wake_word_cam", "снимок")
        else:
            raw = self.app.config_data.get("wake_word_ai", "алиса")

        return raw.split(",")[0].strip().capitalize()

    def process_command(self, raw_command):
        # --- ЖЕСТКАЯ ЗАЩИТА ОТ ЭХА (ИГНОРИРУЕМ ГОЛОС АССИСТЕНТА) ---
        if getattr(self, 'is_speaking', False):
            return

        norm_command = raw_command.lower().strip()
        if not norm_command:
            return

        # --- 1. ПЕРЕХВАТЧИК ДЛЯ НАСТРОЕК (ПРОВЕРЯЕМ И В APP, И В СЕБЕ) ---
        app = App.get_running_app()
        target = getattr(self, 'voice_input_target', None) or (app and getattr(app, 'voice_input_target', None))

        if target:
            print(f"[DEBUG SUCCESS] Перехвачена фраза для настроек: '{norm_command}'")
            self.voice_input_target = None
            if app:
                app.voice_input_target = None

            Clock.schedule_once(lambda dt: target(norm_command), 0)
            return

        # --- 2. БЛОКИРОВКА VOSK ЕСЛИ АКТИВЕН LIVE-ДИАЛОГ ---
        is_live = (
                getattr(self, "is_live_active", False)
                or (getattr(self, "app", None) and getattr(self.app, "is_live_active", False))
                or (app and getattr(app, "is_live_active", False))
        )
        if is_live:
            return

        # --- 3. ЗАЩИТА ОТ ДВОЙНОГО ВЫЗОВА (Дебаунс 3 сек) ---
        current_time = time.time()
        if hasattr(self, '_last_cmd_text') and norm_command == self._last_cmd_text:
            if hasattr(self, '_last_cmd_time') and (current_time - self._last_cmd_time) < 3.0:
                print(f"[ASSISTANT DEBUG] Отсечен дубликат по времени: '{norm_command}'")
                return

        self._last_cmd_text = norm_command
        self._last_cmd_time = current_time

        try:
            print(f"\n[ASSISTANT DEBUG] >>> Вход в process_command с текстом: '{norm_command}'")

            # Безопасное получение настроек
            config_data = getattr(self, 'app', None) and getattr(self.app, 'config_data', None)
            if not config_data and app and hasattr(app, 'config_data'):
                config_data = app.config_data
            config_data = config_data or {}

            wake_response = config_data.get("wake_response")

            # Объявляем списки ключевых слов
            ai_words = [w.strip() for w in config_data.get("wake_word_ai", "алиса").lower().replace(';', ',').split(',')
                        if w.strip()]
            live_words = [w.strip() for w in
                          config_data.get("wake_word_live", "давай поговорим").lower().replace(';', ',').split(',') if
                          w.strip()]
            light_words = [w.strip() for w in
                           config_data.get("wake_word_light", "зал").lower().replace(';', ',').split(',') if w.strip()]
            cam_words = [w.strip() for w in
                         config_data.get("wake_word_cam", "снимок").lower().replace(';', ',').split(',') if w.strip()]

            # Ключевые слова телефонии
            answer_words = [w.strip() for w in
                            config_data.get("wake_word_answer", "алло").lower().replace(';', ',').split(',') if
                            w.strip()]
            reject_words = [w.strip() for w in
                            config_data.get("wake_word_reject", "сброс").lower().replace(';', ',').split(',') if
                            w.strip()]
            call_words = [w.strip() for w in
                          config_data.get("wake_word_call", "позвони").lower().replace(';', ',').split(',') if
                          w.strip()]
            cancel_words = [w.strip() for w in
                            config_data.get("wake_word_call_cancel", "отмена").lower().replace(';', ',').split(',') if
                            w.strip()]

            current_mode = getattr(self, 'current_session_mode', None)

            # Проверяем таймауты для активных режимов
            if self.is_active and current_mode:
                now = time.time()
                last_time = getattr(self, 'last_active_time', 0)

                if current_mode == "light":
                    timeout = float(config_data.get("activity_timer_light", config_data.get("activity_timer", 10)))
                elif current_mode == "ai":
                    timeout = float(config_data.get("activity_timer_ai", config_data.get("activity_timer", 10)))
                elif current_mode == "cam":
                    timeout = float(config_data.get("activity_timer_cam", config_data.get("activity_timer", 10)))
                else:
                    timeout = float(config_data.get("activity_timer", 10))

                if now - last_time > timeout:
                    self.is_active = False
                    self.current_session_mode = None
                    print(f"[ASSISTANT DEBUG] Таймер сессии истек для режима: {current_mode}")

                    try:
                        if app and hasattr(app, 'update_current_screen_status'):
                            hint = self.get_current_wake_hint()
                            app.update_current_screen_status(f"Ассистент: Ожидание («{hint}»)",
                                                             color=(0.6, 0.6, 0.6, 1))
                    except Exception as e:
                        print(f"[TIMEOUT STATUS ERROR]: {e}")

            # Предварительные флаги
            has_ai_word = any(w in norm_command for w in ai_words)
            is_ai_session = (getattr(self, 'current_session_mode', None) in ["ai",
                                                                             "text_dictation"] and self.is_active) or (
                                    getattr(self, 'current_mode', None) in ["ai", "text_dictation"] and self.is_active)

            raw_text_words = getattr(app, 'config_data', {}).get('mode_word_text',
                                                                 'запрос, текст') if app else 'запрос, текст'
            text_words = [w.strip().lower() for w in raw_text_words.split(',') if w.strip()]

            has_live_word = any(w in norm_command for w in
                                ["поговорим", "диалог", "live"] + (live_words if 'live_words' in locals() else []))
            has_text_word = any(w in norm_command for w in text_words)

            is_light_session = (getattr(self, 'current_mode', None) == "light" and self.is_active) or (
                    getattr(self, 'current_session_mode', None) == "light" and self.is_active)
            has_light_word = any(w in norm_command for w in (light_words if 'light_words' in locals() else []))

            is_cam_session = (getattr(self, 'current_mode', None) == "cam" and self.is_active)
            has_cam_word = any(w in norm_command for w in (cam_words if 'cam_words' in locals() else []))

            # --- А. ПРИОРИТЕТ 1: УПРАВЛЕНИЕ ТЕЛЕФОНИЕЙ И ДИАЛОГАМИ ---
            if app and hasattr(app, 'telephony'):
                # 1. Проверка ожидания выбора конкретного номера из нескольких
                if getattr(app.telephony, 'is_waiting_for_number_choice', False):
                    if app.telephony.handle_voice_command(norm_command):
                        return

                # 2. Управление входящим вызовом
                if getattr(app.telephony, 'is_incoming_active', False):
                    if any(w in norm_command for w in answer_words):
                        print("[TELEPHONY] Голосовая команда: Принять входящий вызов")
                        app.telephony.answer_incoming_call()
                        if hasattr(app, 'start_call_timer') and hasattr(app, 'call_status_lbl'):
                            app.start_call_timer(app.call_status_lbl)
                        return

                    if any(w in norm_command for w in reject_words) or any(w in norm_command for w in cancel_words):
                        print("[TELEPHONY] Голосовая команда: Сбросить входящий вызов")
                        app.telephony.reject_incoming_call()
                        if hasattr(app, 'hide_incoming_call_ui'):
                            app.hide_incoming_call_ui()
                        return

                # 3. Глобальная отмена
                if any(w in norm_command for w in cancel_words):
                    print(f"[TELEPHONY DEBUG] Распознана команда отмены: '{norm_command}'")
                    app.telephony.cancel_call_waiting()
                    self.is_waiting_for_call_target = False
                    self.is_active = False
                    self.current_session_mode = None

                    if hasattr(app, 'update_current_screen_status'):
                        app.update_current_screen_status("Ассистент: Действие отменено", color=(0.8, 0.4, 0.4, 1))

                        def reset_to_idle(dt):
                            hint = app.get_current_wake_hint() if hasattr(app, 'get_current_wake_hint') else "алиса"
                            app.update_current_screen_status(f"Ассистент: Ожидание («{hint}»)",
                                                             color=(0.6, 0.6, 0.6, 1))

                        Clock.schedule_once(reset_to_idle, 1.5)
                    return

                # 4. Если ассистент ждал имя абонента для исходящего вызова
                if getattr(self, 'is_waiting_for_call_target', False):
                    print(f"[TELEPHONY DEBUG] Получено имя для исходящего вызова: '{norm_command}'")
                    self.is_waiting_for_call_target = False
                    app.telephony.execute_outgoing_call(norm_command)
                    return

                # 5. Триггер команды «позвони»
                if any(w in norm_command for w in call_words):
                    target_part = norm_command
                    for w in call_words:
                        target_part = target_part.replace(w, "").strip()

                    if target_part:
                        print(f"[TELEPHONY DEBUG] Исходящий вызов для: '{target_part}'")
                        app.telephony.execute_outgoing_call(target_part)
                    else:
                        print("[TELEPHONY DEBUG] Ожидание имени абонента...")
                        self.is_waiting_for_call_target = True

                        if hasattr(app, 'update_current_screen_status'):
                            app.update_current_screen_status("Кому позвонить? (Имя или «Отмена»)",
                                                             color=(1.0, 0.6, 0.2, 1))

                        if hasattr(app.telephony, 'speak_text'):
                            app.telephony.speak_text("Кому позвонить?")
                    return

            # ==========================================
            # ПРИОРИТЕТ 3: УПРАВЛЕНИЕ СВЕТОМ И УМНЫМ ДОМОМ
            # ==========================================
            # (Ваша дальнейшая логика освещения, камеры и ассистента остается здесь)

            if has_light_word or is_light_session:
                print(f"[ASSISTANT DEBUG] -> ПОПАЛИ В ВЕТКУ: АССИСТЕНТ 2 (Свет)")
                if 'light_words' in locals():
                    for w in light_words:
                        norm_command = norm_command.replace(w, "").strip()

                # Вызываем activate без аргументов
                if hasattr(self, 'activate'):
                    self.activate()
                else:
                    if not self.is_active or self.current_session_mode != "light":
                        self.last_active_time = time.time()
                    self.current_session_mode = "light"
                    self.is_active = True

                print(f"[LIGHT ASSISTANT] Режим Света активен. Команда: '{norm_command}'")

                # ЕСЛИ СКАЗАЛИ ТОЛЬКО КЛЮЧЕВОЕ СЛОВО (пустая команда):
                if not norm_command:
                    # ОБЯЗАТЕЛЬНО обновляем таймер, чтобы отсчет пошел с текущей секунды активации!
                    self.last_active_time = time.time()

                    if not is_light_session and 'wake_response' in locals() and wake_response:
                        self.speak(wake_response)
                    return

                # ЕСЛИ ЕСТЬ РЕАЛЬНАЯ КОМАНДА (обновляем таймер активности):
                self.last_active_time = time.time()

                try:
                    app_instance = App.get_running_app()
                    if app_instance and hasattr(app_instance, 'update_current_screen_status'):
                        app_instance.update_current_screen_status(f"Свет: {norm_command}",
                                                                  color=(0.2, 0.85, 0.3, 1))
                except Exception as e:
                    print(f"[LIGHT STATUS ERROR]: {e}")

                # --- ВЫПОЛНЕНИЕ КОМАНД СВЕТА ---
                voice_cmds = getattr(self.app, 'config_data', {}).get("voice_commands", []) if getattr(self, 'app',
                                                                                                       None) else []
                for cmd in voice_cmds:
                    phrase = (cmd.get("phrase") or "").strip().lower()
                    if phrase and phrase in norm_command:
                        action = cmd.get("action")
                        chid = cmd.get("channel_id")
                        print(f"[ASSISTANT DEBUG] Найдена голосовая команда света: action={action}, chid={chid}")
                        if action == "temp":
                            if getattr(self, 'app', None):
                                self.app.fetch_temperature(speak_result=True)
                            return
                        elif action == "all_on":
                            if getattr(self, 'app', None):
                                self.app.turn_all_on()
                            resp = self.get_custom_response("all_on") if hasattr(self,
                                                                                 'get_custom_response') else "Включаю весь свет"
                            self.speak(resp or "Включаю весь свет")
                            return
                        elif action == "all_off":
                            if getattr(self, 'app', None):
                                self.app.turn_all_off()
                            resp = self.get_custom_response("all_off") if hasattr(self,
                                                                                  'get_custom_response') else "Выключаю весь свет"
                            self.speak(resp or "Выключаю весь свет")
                            return
                        elif action == "toggle" and chid is not None:
                            for lamp in getattr(self, 'lamp_objects', []):
                                if lamp.channel_id == chid:
                                    if lamp.is_on:
                                        lamp.turn_off()
                                        resp = self.get_custom_response("off", chid) if hasattr(self,
                                                                                                'get_custom_response') else "Выключаю"
                                    else:
                                        lamp.turn_on()
                                        resp = self.get_custom_response("on", chid) if hasattr(self,
                                                                                               'get_custom_response') else "Включаю"
                                    self.speak(resp or "Готово")
                                    return

                import re
                num_replacements = {
                    r'\b(одна|одно|одну|первая|первую)\b': '1',
                    r'\b(две|два|вторая|вторую)\b': '2',
                    r'\b(три|третья|третью)\b': '3'
                }
                for pattern, repl in num_replacements.items():
                    norm_command = re.sub(pattern, repl, norm_command)

                if "температур" in norm_command:
                    print("[ASSISTANT DEBUG] Запрос температуры по ключевому слову 'температура'")
                    if getattr(self, 'app', None):
                        self.app.fetch_temperature(speak_result=True)
                    return

                has_off = any(w in norm_command for w in ["выключ", "погаси", "отключи"])
                has_on = any(w in norm_command for w in ["включ", "зажги", "вруби"])

                if "все" in norm_command or "всё" in norm_command:
                    if has_off:
                        if getattr(self, 'app', None):
                            self.app.turn_all_off()
                        resp = self.get_custom_response("all_off") if hasattr(self,
                                                                              'get_custom_response') else "Выключаю весь свет"
                        self.speak(resp or "Выключаю весь свет")
                    elif has_on:
                        if getattr(self, 'app', None):
                            self.app.turn_all_on()
                        resp = self.get_custom_response("all_on") if hasattr(self,
                                                                             'get_custom_response') else "Включаю весь свет"
                        self.speak(resp or "Включаю весь свет")
                    return

                target_idx = None
                if "1" in norm_command or "перв" in norm_command:
                    target_idx = 0
                elif "2" in norm_command or "втор" in norm_command:
                    target_idx = 1
                elif "3" in norm_command or "трет" in norm_command:
                    target_idx = 2

                lamp_list = getattr(self, 'lamp_objects', [])
                if target_idx is not None and target_idx < len(lamp_list):
                    lamp = lamp_list[target_idx]
                    if has_off:
                        lamp.turn_off()
                        resp = self.get_custom_response("off", lamp.channel_id) if hasattr(self,
                                                                                           'get_custom_response') else "Выключаю"
                    elif has_on:
                        lamp.turn_on()
                        resp = self.get_custom_response("on", lamp.channel_id) if hasattr(self,
                                                                                          'get_custom_response') else "Включаю"
                    else:
                        if lamp.is_on:
                            lamp.turn_off()
                            resp = self.get_custom_response("off", lamp.channel_id) if hasattr(self,
                                                                                               'get_custom_response') else "Выключаю"
                        else:
                            lamp.turn_on()
                            resp = self.get_custom_response("on", lamp.channel_id) if hasattr(self,
                                                                                              'get_custom_response') else "Включаю"
                    self.speak(resp or "Готово")
                return

            # ==========================================
            # ПРИОРИТЕТ 2: АССИСТЕНТ 3 (КАМЕРА)
            # ==========================================
            elif has_cam_word or is_cam_session:
                print(f"[ASSISTANT DEBUG] -> ПОПАЛИ В ВЕТКУ: АССИСТЕНТ 3 (Камера)")
                if 'cam_words' in locals():
                    for w in cam_words:
                        norm_command = norm_command.replace(w, "").strip()

                self.current_session_mode = "cam"
                self.is_active = True
                self.last_active_time = time.time()
                print(f"[CAM ASSISTANT] Режим Камеры активен.")

                app_inst = app or getattr(self, 'app', None)
                if app_inst and hasattr(app_inst, 'root') and app_inst.root:
                    try:
                        current_screen = app_inst.root.current_screen
                        if current_screen and type(current_screen).__name__ == 'AICameraScreen':
                            current_screen.capture_and_process_ai()
                            return
                    except Exception as e:
                        print(f"[AI CAMERA ERROR]: {e}")
                return

            # ==========================================
            # ПРИОРИТЕТ 3: ДВУХШАГОВАЯ ЛОГИКА ИИ
            # ==========================================
            elif has_ai_word:
                print(f"[ASSISTANT DEBUG] -> Активация режима ИИ по слову: '{norm_command}'")

                self.current_session_mode = "ai"
                self.is_active = True
                self.last_active_time = time.time()
                self.speech_buffer = ""

                try:
                    if app and hasattr(app, 'update_current_screen_status'):
                        app.update_current_screen_status("Ассистент: Слушаю...", color=(0.2, 0.85, 0.3, 1))
                except Exception as e:
                    print(f"[STATUS ERROR]: {e}")

                if 'wake_response' in locals() and wake_response:
                    self.speak(wake_response)
                return

            elif is_ai_session:
                print(f"[ASSISTANT DEBUG] -> Получена фраза в активном режиме: '{norm_command}'")
                self.last_active_time = time.time()

                # 1. Запись надиктованного запроса
                if getattr(self, 'current_session_mode', None) == "text_dictation":
                    print(f"[STATE] Накоплен и отправлен текст запроса: '{norm_command}'")

                    self.is_active = False
                    self.current_session_mode = None
                    self.speech_buffer = ""

                    if app and app.root:
                        screen = app.root.current_screen
                        if screen and hasattr(screen, 'receive_voice_query'):
                            Clock.schedule_once(lambda dt: screen.receive_voice_query(norm_command), 0)
                    return

                # 2. Триггер Live-режима
                if norm_command and has_live_word:
                    print("[STATE] Второе слово совпало с триггером LIVE: Запуск Live API")

                    self.is_active = False
                    self.current_session_mode = None
                    self.speech_buffer = ""

                    if app:
                        app.is_live_active = True
                        if hasattr(app, 'speech_buffer'):
                            app.speech_buffer = ""
                        if hasattr(self, 'speech_buffer'):
                            self.speech_buffer = ""
                        if hasattr(app, 'reset_session_timer'):
                            app.reset_session_timer()

                        try:
                            if hasattr(app, 'poll_event') and app.poll_event:
                                try:
                                    app.poll_event.cancel()
                                except Exception:
                                    pass
                                app.poll_event = None

                            if app.root:
                                current_screen = app.root.current_screen
                                if hasattr(current_screen, 'poll_statuses'):
                                    Clock.unschedule(current_screen.poll_statuses)

                            if hasattr(app, 'live_manager') and hasattr(app.live_manager, 'start_in_background'):
                                app.live_manager.start_in_background()
                                print("[STATE] Запрошен запуск потока Live API.")
                        except Exception as e:
                            print(f"[STATE ERROR] Не удалось запустить Live: {e}")
                    return

                # 3. Триггер Текстового режима
                elif norm_command and has_text_word:
                    print(f"[STATE] Переход в режим диктовки текста. Ждем сам запрос...")

                    self.current_session_mode = "text_dictation"
                    self.speech_buffer = ""

                    if app and app.root:
                        screen = app.root.current_screen
                        if screen and hasattr(screen, 'update_assistant_status'):
                            Clock.schedule_once(lambda dt: screen.update_assistant_status("Диктуйте запрос...",
                                                                                          color=(0.2, 0.85, 0.3, 1)), 0)
                    return

                # 4. Ни один триггер не совпал — сброс сессии
                else:
                    print(f"[AI] Фраза '{norm_command}' не совпала ни с Live, ни с Текстом. Сброс сессии.")

                self.is_active = False
                self.current_session_mode = None
                self.speech_buffer = ""

                try:
                    hint = self.get_current_wake_hint() if hasattr(self, 'get_current_wake_hint') else "Алиса"
                    status_msg = f"Ассистент: Ожидание («{hint}»)"
                    if app and hasattr(app, 'update_current_screen_status'):
                        Clock.schedule_once(
                            lambda dt: app.update_current_screen_status(status_msg, color=(0.6, 0.6, 0.6, 1)), 0)
                    elif hasattr(self, 'update_assistant_status'):
                        Clock.schedule_once(lambda dt: self.update_assistant_status(status_msg, (0.6, 0.6, 0.6, 1)), 0)
                except Exception as e:
                    print(f"[STATUS RESET ERROR]: {e}")
                return

            else:
                print(f"[ASSISTANT DEBUG] Текст '{norm_command}' не подошел ни под одну известную ветку ассистента.")
                return

        except Exception as e:
            print(f"[PROCESS COMMAND ERROR]: {e}")
        finally:
            self.is_processing = False
            print("[ASSISTANT DEBUG] <<< Выход из process_command (флаг сброшен)\n")

class BaseScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(0.06, 0.07, 0.1, 1)
            self.bg_rect = RoundedRectangle(size=self.size, pos=self.pos)
        self.bind(pos=self.update_bg, size=self.update_bg)

    def update_bg(self, *args):
        self.bg_rect.pos = self.pos
        self.bg_rect.size = self.size


class SystemSettingsPopup(Popup):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Сохраняем предыдущий режим клавиатуры и включаем режим сдвига/адаптации
        self.prev_softinput_mode = Window.softinput_mode
        Window.softinput_mode = 'below_target'

        # Корневой контейнер попапа
        layout = BoxLayout(orientation='vertical', padding=dp(15), spacing=dp(10), size_hint=(1, 1))

        # Фоновый цвет для всего окна
        from kivy.graphics import Color, Rectangle
        with layout.canvas.before:
            Color(0.11, 0.13, 0.17, 1)
            bg_rect = Rectangle(size=layout.size, pos=layout.pos)

        layout.bind(
            size=lambda inst, val: setattr(bg_rect, 'size', val),
            pos=lambda inst, val: setattr(bg_rect, 'pos', val)
        )

        # Шапка попапа (Кнопка «Назад» и заголовок окна)
        top_bar = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(10))
        btn_back = FixedButton(
            text="Назад",
            bg_color=(0.2, 0.23, 0.3, 1),
            size_hint=(None, None),
            width=dp(100),
            height=dp(45)
        )
        top_bar.add_widget(btn_back)

        lbl_title = Label(
            text="Настройки системы",
            font_size='18sp',
            bold=True,
            color=(0.9, 0.9, 0.9, 1),
            halign='left',
            valign='middle'
        )
        lbl_title.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
        top_bar.add_widget(lbl_title)
        layout.add_widget(top_bar)

        # Контент прокрутки
        scroll = ScrollView(size_hint=(1, 1), do_scroll_x=False, do_scroll_y=True)
        content = BoxLayout(orientation='vertical', spacing=dp(14), size_hint_y=None,
                            padding=[dp(5), dp(5), dp(5), dp(5)])
        content.bind(minimum_height=content.setter('height'))
        scroll.add_widget(content)

        def create_section_header(text):
            lbl = Label(
                text=text,
                font_size='17sp',
                bold=False,
                color=(0.3, 0.7, 1, 1),
                size_hint_y=None,
                height=dp(32),
                halign='center',
                valign='middle'
            )
            lbl.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
            return lbl

        # Класс с поддержкой долгого нажатия для вставки из буфера обмена
        class LongPressTextInput(TextInput):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self._press_event = None

            def on_touch_down(self, touch):
                if self.collide_point(*touch.pos):
                    # Запускаем таймер долгого нажатия (0.6 секунды) для вставки
                    self._press_event = Clock.schedule_once(lambda dt: self.paste_from_clipboard(), 0.6)
                return super().on_touch_down(touch)

            def on_touch_up(self, touch):
                if self._press_event:
                    self._press_event.cancel()
                    self._press_event = None
                return super().on_touch_up(touch)

            def paste_from_clipboard(self):
                try:
                    from kivy.core.clipboard import Clipboard
                    clipboard_text = Clipboard.get('text')
                    if clipboard_text:
                        current_text = self.text or ""

                        # Защита: принудительно преобразуем индекс каретки в целое число (int)
                        raw_cursor = self.cursor_index
                        cursor_index = int(raw_cursor) if raw_cursor is not None else len(current_text)

                        self.text = current_text[:cursor_index] + clipboard_text + current_text[cursor_index:]
                        self.cursor_index = cursor_index + len(clipboard_text)
                        print(f"[CLIPBOARD] Успешно вставлено из буфера: {clipboard_text}")
                except Exception as e:
                    print(f"[CLIPBOARD ERROR]: {e}")

        # Реальная функция привязки голосового ввода к полю
        def start_voice_recording_for_input(text_input_instance):
            print(f"[VOICE INPUT] Ожидание голосового ввода для поля...")

            orig_bg = text_input_instance.background_color
            text_input_instance.background_color = (0.25, 0.2, 0.4, 1)
            text_input_instance.text = "Запись..."

            app = App.get_running_app()
            assistant = None

            if app:
                for attr_name in ['assistant', 'voice_assistant', 'ai', 'voice']:
                    if hasattr(app, attr_name) and getattr(app, attr_name):
                        assistant = getattr(app, attr_name)
                        break

                if not assistant and app.root:
                    current_screen = getattr(app.root, 'current_screen', None)
                    if current_screen:
                        for attr_name in ['assistant', 'voice_assistant', 'ai', 'voice']:
                            if hasattr(current_screen, attr_name) and getattr(current_screen, attr_name):
                                assistant = getattr(current_screen, attr_name)
                                break

                    if not assistant:
                        for attr_name in ['assistant', 'voice_assistant', 'ai']:
                            if hasattr(app.root, attr_name) and getattr(app.root, attr_name):
                                assistant = getattr(app.root, attr_name)
                                break
                        if not assistant and hasattr(app.root, 'screens'):
                            for screen in app.root.screens:
                                for attr_name in ['assistant', 'voice_assistant', 'ai']:
                                    if hasattr(screen, attr_name) and getattr(screen, attr_name):
                                        assistant = getattr(screen, attr_name)
                                        break
                                if assistant:
                                    break

            if assistant or app:
                is_finished = [False]

                def reset_field_state():
                    if not is_finished[0]:
                        is_finished[0] = True
                        Clock.schedule_once(lambda dt: setattr(text_input_instance, 'background_color', orig_bg), 0)
                        if text_input_instance.text == "Запись...":
                            Clock.schedule_once(lambda dt: setattr(text_input_instance, 'text', ""), 0)

                        if assistant and hasattr(assistant, 'set_voice_input_target'):
                            try:
                                assistant.set_voice_input_target(None)
                            except Exception:
                                pass
                        if assistant:
                            assistant.voice_input_target = None
                        if app:
                            app.voice_input_target = None

                def on_phrase_recognized(recognized_text):
                    if is_finished[0]:
                        return
                    is_finished[0] = True

                    Clock.schedule_once(lambda dt: setattr(text_input_instance, 'text', recognized_text), 0)
                    Clock.schedule_once(lambda dt: setattr(text_input_instance, 'background_color', orig_bg), 0)
                    print(f"[VOICE INPUT SUCCESS] Записано: {recognized_text}")

                if assistant:
                    if hasattr(assistant, 'set_voice_input_target'):
                        assistant.set_voice_input_target(on_phrase_recognized)
                    assistant.voice_input_target = on_phrase_recognized

                if app:
                    app.voice_input_target = on_phrase_recognized

                Clock.schedule_once(lambda dt: reset_field_state(), 10.0)
            else:
                print("[VOICE INPUT ERROR] Ассистент не найден ни в app, ни на экранах!")
                text_input_instance.background_color = orig_bg
                text_input_instance.text = ""

        # Улучшенный обработчик создания блока с автопрокруткой и поддержкой LongPress
        def create_setting_block(label_text, default_text="", input_filter=None, on_tap_callback=None,
                                 allow_clipboard=False):
            block = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(4))

            lbl = Label(
                text=label_text,
                font_size='16sp',
                font_name='Roboto',
                bold=False,
                color=(0.85, 0.85, 0.85, 1),
                halign='center',
                valign='middle',
                size_hint_y=None,
                height=dp(22)
            )
            lbl.bind(width=lambda inst, val: setattr(inst, 'text_size', (val, None)))
            block.add_widget(lbl)

            if on_tap_callback:
                class TapTextInput(LongPressTextInput):
                    def on_touch_down(self, touch):
                        if self.collide_point(*touch.pos):
                            on_tap_callback(self)
                            return True
                        return super().on_touch_down(touch)

                input_widget = TapTextInput(
                    text=str(default_text),
                    multiline=False,
                    size_hint_y=None,
                    height=dp(40),
                    font_size='13sp',
                    readonly=True,
                    background_color=(0.15, 0.17, 0.22, 1),
                    foreground_color=(1, 1, 1, 1),
                    halign='center',
                    padding=[dp(8), dp(10), dp(8), dp(8)]
                )
            else:
                # Класс для обычных полей или поля с возможностью вставки из буфера
                class SmartTextInput(LongPressTextInput):
                    def __init__(self, **kwargs):
                        super().__init__(**kwargs)
                        self._long_press_triggered = False

                    # Перехватываем долгое нажатие, если разрешен буфер обмена
                    def on_long_press(self, *args):
                        if allow_clipboard:
                            try:
                                pasted_text = Clipboard.get('text')
                                if pasted_text:
                                    self.text = pasted_text.strip()
                                    print(f"[CLIPBOARD] Ключ успешно вставлен из буфера обмена.")
                            except Exception as e:
                                print(f"[CLIPBOARD ERROR]: {e}")

                        if hasattr(super(), 'on_long_press'):
                            super().on_long_press(*args)

                input_widget = SmartTextInput(
                    text=str(default_text),
                    multiline=False,
                    size_hint_y=None,
                    height=dp(40),
                    font_size='13sp',
                    input_filter=input_filter,
                    # Если разрешен буфер, поле должно быть доступно для изменения
                    readonly=False if allow_clipboard else False,
                    background_color=(0.15, 0.17, 0.22, 1),
                    foreground_color=(1, 1, 1, 1),
                    halign='center',
                    padding=[dp(8), dp(10), dp(8), dp(8)]
                )

            # Автопрокрутка ScrollView к фокусному полю ввода, когда появляется клавиатура
            def _on_focus(instance, value):
                if value:
                    Clock.schedule_once(lambda dt: scroll.scroll_to(block), 0.15)

            input_widget.bind(focus=_on_focus)

            input_widget.size_hint_x = 1.0
            block.add_widget(input_widget)

            block.height = dp(22) + dp(4) + dp(40)
            return block, input_widget

        self.inputs = {}

        app = App.get_running_app()
        config = getattr(app, 'config_data', {})

        # --- Интеграция с ИИ ---
        content.add_widget(create_section_header("Интеграция с ИИ"))

        block, self.inputs['ai_provider'] = create_setting_block(
            "Провайдер ИИ (gemini/gigachat):", config.get('ai_provider', 'gemini')
        )
        content.add_widget(block)

        current_provider = config.get('ai_provider', 'gemini').strip().lower()
        saved_key = config.get(f"{current_provider}_api_key", config.get('ai_api_key', ''))

        raw_saved_model = config.get(f"{current_provider}_model_name", config.get('ai_model_name', 'gemini-3.8-flash'))
        if not raw_saved_model or "2.5" in raw_saved_model:
            saved_model = "gemini-3.8-flash"
        else:
            saved_model = raw_saved_model

        raw_saved_live_model = config.get(f"{current_provider}_live_model_name",
                                          config.get('ai_live_model_name', 'gemini-3.8-live'))
        if not raw_saved_live_model:
            saved_live_model = "gemini-3.8-live"
        else:
            saved_live_model = raw_saved_live_model

        # 1. Верхний блок: поле ввода для ключа текущего провайдера
        block_key, self.inputs['ai_api_key'] = create_setting_block(
            "API Ключ / Токен доступа:", saved_key
        )
        self.inputs['ai_api_key'].hint_text = "Вставьте или введите ключ"
        self.inputs['ai_api_key'].multiline = False
        content.add_widget(block_key)

        # 2. Нижний блок: строка-подсказка для открытия браузера
        block_get, input_get = create_setting_block(
            "", ""
        )
        input_get.hint_text = "Нажмите здесь, чтобы получить ключ"
        input_get.multiline = False
        input_get.readonly = True

        def on_get_touch(instance, touch):
            if instance.collide_point(*touch.pos):
                self.fetch_and_fill_api_key()
                return True
            return False

        input_get.bind(on_touch_down=on_get_touch)
        content.add_widget(block_get)

        # --- БЛОК НАЗВАНИЯ ТЕКСТОВОЙ МОДЕЛИ ---
        block, model_input = create_setting_block(
            "Текстовая модель:", saved_model
        )
        model_input.readonly = False
        model_input.hint_text = "Например: gemini-flash-lite-latest"
        self.inputs['ai_model_name'] = model_input
        content.add_widget(block)

        # --- БЛОК НАЗВАНИЯ ГОЛОСОВОЙ LIVE-МОДЕЛИ ---
        block, live_model_input = create_setting_block(
            "Голосовая модель (Live API):", saved_live_model
        )
        live_model_input.readonly = False
        live_model_input.hint_text = "Например: gemini-3.8-live"
        self.inputs['ai_live_model_name'] = live_model_input
        content.add_widget(block)

        def on_provider_change(instance, value):
            prov = value.strip().lower()
            app_ref = App.get_running_app()
            cfg = getattr(app_ref, 'config_data', {})

            if 'ai_api_key' in self.inputs:
                saved_prov_key = cfg.get(f"{prov}_api_key", "")
                if not saved_prov_key and prov == cfg.get('ai_provider', 'gemini').strip().lower():
                    saved_prov_key = cfg.get('ai_api_key', '')
                self.inputs['ai_api_key'].text = saved_prov_key

            if 'ai_model_name' in self.inputs:
                default_model = "gemini-flash-lite-latest" if prov == "gemini" else "GigaChat"
                m_val = cfg.get(f"{prov}_model_name",
                                cfg.get('ai_model_name',
                                        cfg.get('gemini_model_name', default_model)))
                if not m_val:
                    m_val = default_model
                self.inputs['ai_model_name'].text = m_val

            if 'ai_live_model_name' in self.inputs:
                default_live = "gemini-3.8-live" if prov == "gemini" else "GigaChat"
                l_val = cfg.get(f"{prov}_live_model_name", default_live)
                self.inputs['ai_live_model_name'].text = l_val

        self.inputs['ai_provider'].bind(text=on_provider_change)

        # --- Активация и время сна ---
        content.add_widget(create_section_header("Активация и время сна"))

        block, self.inputs['wake_word_ai'] = create_setting_block(
            "Слово пробуждения (ИИ):", config.get('wake_word_ai', 'джарвис'),
            on_tap_callback=start_voice_recording_for_input
        )
        content.add_widget(block)

        block, self.inputs['mode_word_text'] = create_setting_block(
            "Команда режима (Текст/Запрос):", config.get('mode_word_text', 'запрос, текст'),
            on_tap_callback=start_voice_recording_for_input
        )
        content.add_widget(block)

        block, self.inputs['mode_word_live'] = create_setting_block(
            "Команда режима (Live-диалог):", config.get('mode_word_live', 'поговорим, чат, диалог'),
            on_tap_callback=start_voice_recording_for_input
        )
        content.add_widget(block)

        block, self.inputs['wake_word_light'] = create_setting_block(
            "Слово пробуждения (Свет):", config.get('wake_word_light', 'свет'),
            on_tap_callback=start_voice_recording_for_input
        )
        content.add_widget(block)

        block, self.inputs['wake_word_cam'] = create_setting_block(
            "Слово пробуждения (Камера):", config.get('wake_word_cam', 'снимок'),
            on_tap_callback=start_voice_recording_for_input
        )
        content.add_widget(block)

        block, self.inputs['wake_response'] = create_setting_block(
            "Ответ на слово пробуждения:", config.get('wake_response', 'Слушаю'),
            on_tap_callback=start_voice_recording_for_input
        )
        content.add_widget(block)

        block, self.inputs['pause_timer'] = create_setting_block(
            "Таймер времени паузы (ИИ):", config.get('pause_timer', '5'), input_filter='int'
        )
        content.add_widget(block)

        block, self.inputs['activity_timer'] = create_setting_block(
            "Таймер активности (ИИ):", config.get('activity_timer', '30'), input_filter='int'
        )
        content.add_widget(block)

        block, self.inputs['activity_timer_light'] = create_setting_block(
            "Таймер активности (Свет):", config.get('activity_timer_light', '30'), input_filter='int'
        )
        content.add_widget(block)

        layout.add_widget(scroll)

        # Кнопка сохранения снизу
        btn_save = FixedButton(
            text="Сохранить настройки",
            bg_color=(0.18, 0.5, 0.25, 1),
            size_hint_y=None,
            height=dp(50)
        )
        btn_save.bind(on_press=self.save_settings_data)
        layout.add_widget(btn_save)

        # Конфигурация самого Popup
        self.title = ''
        self.separator_height = 0
        self.background = ''
        self.background_color = (0, 0, 0, 0)
        self.content = layout
        self.size_hint = (0.95, 0.92)
        self.auto_dismiss = False

        btn_back.bind(on_press=self.dismiss)

    def dismiss(self, *args, **kwargs):
        if hasattr(self, 'prev_softinput_mode'):
            Window.softinput_mode = self.prev_softinput_mode
        super().dismiss(*args, **kwargs)

    def fetch_and_fill_api_key(self):
        import webbrowser
        try:
            provider_text = ""
            if 'ai_provider' in self.inputs:
                provider_text = self.inputs['ai_provider'].text.lower()

            url = "https://aistudio.google.com/app/apikey"

            if "openrouter" in provider_text:
                url = "https://openrouter.ai/keys"
            elif "openai" in provider_text or "gpt" in provider_text:
                url = "https://platform.openai.com/api-keys"
            elif "groq" in provider_text:
                url = "https://console.groq.com/keys"

            webbrowser.open(url)
            print(f"[API KEY] Открыта страница для получения ключа: {url}")
        except Exception as e:
            print(f"[API KEY ERROR]: {e}")

    def save_settings_data(self, instance):
        raw_data = {k: v.text.strip() for k, v in self.inputs.items()}

        provider = raw_data.get('ai_provider', 'gemini').strip().lower()
        api_key = raw_data.get('ai_api_key', '')
        model_name = raw_data.get('ai_model_name', '')
        live_model_name = raw_data.get('ai_live_model_name', '')

        settings_data = {
            'ai_provider': provider,
            'ai_api_key': api_key,
            f"{provider}_api_key": api_key,
            f"{provider}_model_name": model_name,
            f"{provider}_live_model_name": live_model_name,
            'ai_model_name': model_name,
            'ai_live_model_name': live_model_name,

            'wake_word_ai': raw_data.get('wake_word_ai', 'джарвис'),
            'mode_word_text': raw_data.get('mode_word_text', 'запрос, текст'),
            'mode_word_live': raw_data.get('mode_word_live', 'поговорим, чат, диалог'),
            'wake_response': raw_data.get('wake_response', 'Слушаю'),

            'pause_timer': raw_data.get('pause_timer', '5'),
            'activity_timer': raw_data.get('activity_timer', '30'),

            'wake_word_light': raw_data.get('wake_word_light', 'свет'),
            'activity_timer_light': raw_data.get('activity_timer_light', '30'),

            'wake_word_cam': raw_data.get('wake_word_cam', 'снимок'),
            'activity_timer_cam': raw_data.get('activity_timer_cam', '30'),
        }

        print("[SYSTEM SETTINGS SAVED (ISOLATED)]: ", settings_data)

        app = App.get_running_app()
        if hasattr(app, 'config_data') and isinstance(app.config_data, dict):
            app.config_data.update(settings_data)
            if hasattr(app, 'save_config'):
                app.save_config()

        self.dismiss()



class GeminiLiveManager:
    def __init__(self, app):
        self.app = app
        self.kivy_app = App.get_running_app()

        self._lock = threading.Lock()
        self._thread = None
        self._loop = None
        self._task = None
        self.model_is_speaking = False

    def _status(self, text, color=(0.2, 0.85, 0.3, 1)):
        # Обновление интерфейса только через главный поток Kivy
        Clock.schedule_once(
            lambda dt: self.app.update_current_screen_status(text, color),
            0
        )

    def _get_assistant(self):
        assistant = getattr(self.app, "assistant", None)
        if assistant:
            return assistant

        root = getattr(self.app, "root", None)
        if root:
            for screen in getattr(root, "screens", []):
                assistant = getattr(screen, "assistant", None)
                if assistant:
                    return assistant

        return None

    def _init_client(self):
        config = self.app.config_data
        provider = config.get("ai_provider", "gemini").strip().lower()

        if provider != "gemini":
            raise RuntimeError("Голосовая Live-модель поддерживается только для Gemini")

        api_key = (
                config.get("gemini_api_key")
                or config.get("ai_api_key")
                or os.environ.get("GEMINI_API_KEY")
                or os.environ.get("GOOGLE_API_KEY")
        )
        if not api_key:
            raise RuntimeError("Не задан Gemini API-ключ")

        model = (
                config.get("gemini_live_model_name")
                or config.get("ai_live_model_name")
                or config.get("live_model")
        )
        if not model:
            raise RuntimeError("Не задано имя Live-модели")

        # Возвращаем ключ и нормализованное имя модели с префиксом models/ для WebSocket
        if not model.startswith("models/"):
            model = f"models/{model}"

        return api_key, model

    def start_in_background(self):
        if platform == "android":
            if not HAS_ANDROID_AUDIO:
                self._status(
                    "Live API: для Android требуется AudioRecord",
                    (0.9, 0.2, 0.2, 1)
                )
                return
        else:
            if not HAS_SOUNDDEVICE:
                self._status("Live API: не установлен sounddevice", (0.9, 0.2, 0.2, 1))
                return

        with self._lock:
            if self._thread and self._thread.is_alive():
                return

            self._thread = threading.Thread(
                target=self._thread_main,
                name="GeminiLive",
                daemon=True
            )
            self._thread.start()

    def _thread_main(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._task = self._loop.create_task(self._run())

        try:
            self._loop.run_until_complete(self._task)
        except asyncio.CancelledError:
            pass
        except Exception:
            traceback.print_exc()
        finally:
            self.is_live_active = False
            self._task = None
            self._loop.close()
            self._loop = None

    async def _run(self):
        assistant = self._get_assistant()

        # Жёстко останавливаем фоновый опрос через Clock
        if self.kivy_app:
            if hasattr(self.kivy_app, 'poll_event') and self.kivy_app.poll_event:
                try:
                    self.kivy_app.poll_event.cancel()
                except Exception:
                    pass
                self.kivy_app.poll_event = None

            try:
                current_screen = self.kivy_app.root.current_screen
                if hasattr(current_screen, 'poll_statuses'):
                    Clock.unschedule(current_screen.poll_statuses)
            except Exception as e:
                print(f"[POLL UNSCHEDULE ERROR]: {e}")

        # Освобождаем микрофон для Live-сессии
        if assistant:
            assistant.stop_listening()

        try:
            api_key, model = self._init_client()
            uri = f"wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key={api_key}"

            self.is_live_active = True
            if self.kivy_app:
                self.kivy_app.is_live_active = True

                # Класс-адаптер для 100% совместимости с рабочим протоколом
                class WebSocketSessionAdapter:
                    def __init__(self, ws):
                        self.ws = ws

                    async def send_realtime_input(self, audio):
                        audio_b64 = base64.b64encode(audio.data).decode('utf-8')
                        msg = {
                            "realtime_input": {
                                "audio": {
                                    "data": audio_b64,
                                    "mime_type": audio.mime_type
                                }
                            }
                        }
                        await self.ws.send(json.dumps(msg))

                    async def send_client_content(self, turns):
                        msg = {
                            "clientContent": {
                                "turns": [{"role": t.role, "parts": [{"text": p.text} for p in t.parts]} for t in
                                          turns],
                                "turnComplete": True
                            }
                        }
                        await self.ws.send(json.dumps(msg))

                    async def receive(self):
                        async for raw_message in self.ws:
                            try:
                                response_data = json.loads(raw_message)
                            except Exception:
                                continue

                            class ContentObj:
                                def __init__(self, d):
                                    server_content = d.get("serverContent", {})
                                    self.server_content = self if server_content else None
                                    self.turn_complete = server_content.get("turnComplete", False)
                                    self.interrupted = server_content.get("interrupted", False)

                                    model_turn = server_content.get("modelTurn")
                                    if model_turn:
                                        self.model_turn = self
                                        self.parts = [PartObj(p) for p in model_turn.get("parts", [])]
                                    else:
                                        self.model_turn = None

                            class PartObj:
                                def __init__(self, p):
                                    self.text = p.get("text")
                                    inline = p.get("inlineData") or p.get("inline_data")
                                    if inline:
                                        self.inline_data = InlineDataObj(inline)
                                    else:
                                        self.inline_data = None

                            class InlineDataObj:
                                def __init__(self, inline):
                                    data_str = inline.get("data", "")
                                    try:
                                        self.data = base64.b64decode(data_str)
                                    except Exception:
                                        self.data = b""

                            yield ContentObj(response_data)

            # Создаем SSL-контекст с доверенными сертификатами certifi для обхода ошибки Android SSL
            ssl_context = ssl.create_default_context(cafile=certifi.where())

            # ЗАЩИЩЕННЫЙ ЦИКЛ АВТОРЕКОННЕКТА (Ограничение в 3 попытки)
            max_retries = 3
            retry_count = 0

            while self.is_live_active and retry_count < max_retries:
                try:
                    self._status(f"Подключение к Live API (попытка {retry_count + 1}/{max_retries})...",
                                 (0.9, 0.5, 0.1, 1))

                    # Передаем ssl=ssl_context в websockets.connect
                    async with websockets.connect(uri, ping_interval=20, ping_timeout=20, ssl=ssl_context) as websocket:
                        # Успешное соединение — сбрасываем счетчик ошибок
                        retry_count = 0

                        session = WebSocketSessionAdapter(websocket)
                        self.active_session = session

                        # Отправка первичного сетапа конфигурации (setup)
                        setup_message = {
                            "setup": {
                                "model": model,
                                "generationConfig": {
                                    "responseModalities": ["AUDIO"],
                                    "speechConfig": {
                                        "voiceConfig": {
                                            "prebuiltVoiceConfig": {
                                                "voiceName": "Kore"
                                            }
                                        }
                                    }
                                },
                                "systemInstruction": {
                                    "parts": [{
                                        "text": (
                                            "Ты — русскоязычный голосовой помощник умного дома. "
                                            "Всегда общайся вежливо, кратко и исключительно на русском языке. "
                                            "Никогда не прощайся сам по себе, если пользователь не сказал 'пока' или 'до свидания'."
                                            "Если пользователь говорит 'стоп', 'хватит', 'выход' или 'закончим разговор', "
                                            "ты должна ответить 'До свидания!', обязательно добавить в текст маркер [DISCONNECT] и завершить диалог."                                        )
                                    }]
                                }
                            }
                        }
                        await websocket.send(json.dumps(setup_message))

                        from kivy.app import App
                        app_instance = App.get_running_app()
                        if app_instance:
                            app_instance.active_session = session
                            app_instance.live_manager = self

                        self._status("Ассистент: Слушаю вас...", (0.2, 0.85, 0.3, 1))
                        print("[LIVE] Успешное подключение к сессии WebSocket.")

                        # Показ кнопки завершения
                        if self.kivy_app and hasattr(self.kivy_app, 'root'):
                            def show_btn(dt):
                                screen = self.kivy_app.root.current_screen
                                if screen and hasattr(screen, 'end_call_button'):
                                    screen.end_call_button.opacity = 1
                                    screen.end_call_button.disabled = False

                            Clock.schedule_once(show_btn, 0)

                        # Принудительный старт приветствия
                        class DummyPart:
                            def __init__(self, text):
                                self.text = text

                        class DummyContent:
                            def __init__(self, role, parts):
                                self.role = role
                                self.parts = parts

                        await session.send_client_content(
                            turns=[
                                DummyContent(
                                    role="user",
                                    parts=[DummyPart("Поприветствуй пользователя коротко: скажи 'Слушаю вас'.")]
                                )
                            ]
                        )

                        # Сохраняем таски
                        self.send_task = asyncio.create_task(self._send_microphone(session), name="SendMic")
                        self.receive_task = asyncio.create_task(self._receive_audio(session), name="ReceiveAudio")
                        tasks = [self.send_task, self.receive_task]

                        try:
                            await asyncio.gather(*tasks)
                        except asyncio.CancelledError:
                            raise
                        except Exception as task_err:
                            print(f"[LIVE STREAM ERROR]: {task_err}")
                            retry_count += 1
                            if not self.is_live_active:
                                break
                            await asyncio.sleep(2.0)
                            continue
                        finally:
                            for task in tasks:
                                if not task.done():
                                    task.cancel()
                            await asyncio.gather(*tasks, return_exceptions=True)

                except Exception as net_err:
                    print(f"[LIVE NET ERROR]: {net_err}")
                    retry_count += 1
                    if not self.is_live_active or retry_count >= max_retries:
                        print("[LIVE] Превышено число попыток переподключения. Выход из Live.")
                        break
                    self._status(f"Обрыв связи, повтор ({retry_count}/{max_retries})...", (0.9, 0.2, 0.2, 1))
                    await asyncio.sleep(2.5)

            if retry_count >= max_retries:
                self._status("Ошибка: нет связи с сервером", (0.9, 0.2, 0.2, 1))

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            traceback.print_exc()
            self._status(f"Ошибка Live API: {exc}", (0.9, 0.2, 0.2, 1))

        finally:
            self.is_live_active = False
            if self.kivy_app:
                self.kivy_app.is_live_active = False
                self.kivy_app.active_session = None

            self.active_session = None

            # Скрытие кнопки завершения разговора
            def hide_btn(dt):
                try:
                    if self.kivy_app and self.kivy_app.root:
                        screen = self.kivy_app.root.current_screen
                        if screen and hasattr(screen, 'end_call_button'):
                            screen.end_call_button.opacity = 0
                            screen.end_call_button.disabled = True
                except Exception as e:
                    print(f"[HIDE BTN ERROR]: {e}")

            Clock.schedule_once(hide_btn, 0)

            # Сброс статуса на экранах
            try:
                config_data = getattr(self, 'config_data', {}) or getattr(self.kivy_app, 'config_data', {})
                ai_words = [w.strip() for w in config_data.get("wake_word_ai", "алиса").split(',') if w.strip()]
                hint = ai_words[0].capitalize() if ai_words else "Алиса"
                self._status(f"Ассистент: Ожидание («{hint}»)", (0.6, 0.6, 0.6, 1))
            except Exception as e:
                print(f"[STATUS RESET ERROR]: {e}")

            try:
                if self.kivy_app and self.kivy_app.root:
                    current_screen = self.kivy_app.root.current_screen
                    if current_screen and hasattr(current_screen, 'poll_statuses'):
                        if getattr(self.kivy_app, 'poll_event', None):
                            self.kivy_app.poll_event.cancel()
                            self.kivy_app.poll_event = None

                        self.kivy_app.poll_event = Clock.schedule_interval(
                            current_screen.poll_statuses, POLL_INTERVAL
                        )
            except Exception as e:
                print(f"[POLL RESUME ERROR]: {e}")

            if assistant:
                if hasattr(assistant, 'speech_buffer'):
                    assistant.speech_buffer = ""
                Clock.schedule_once(
                    lambda dt: assistant.start_listening(),
                    0.7
                )

    async def _send_microphone(self, session):
        if platform == "android":
            await self._send_microphone_android(session)
        else:
            await self._send_microphone_pc(session)

    async def _send_microphone_pc(self, session):
        if not HAS_SOUNDDEVICE:
            raise RuntimeError("На ПК не установлен sounddevice")

        print("[LIVE MIC] Запуск потока отправки микрофона с шумовым барьером...")
        loop = asyncio.get_running_loop()
        gemini_queue = asyncio.Queue()

        def gemini_enqueue(item):
            try:
                gemini_queue.put_nowait(item)
            except Exception:
                pass

        def callback(indata, frames, time_info, status):
            if not getattr(self, 'is_live_active', False):
                return

            if getattr(self, 'model_is_speaking', False):
                return

            if status:
                print(f"[LIVE MIC STATUS] {status}")

            pcm_bytes = bytes(indata)
            loop.call_soon_threadsafe(gemini_enqueue, pcm_bytes)

        try:
            with sd.InputStream(
                    samplerate=16000,
                    channels=1,
                    dtype="int16",
                    blocksize=1024,
                    callback=callback,
            ):
                while self.is_live_active:
                    try:
                        chunk = await asyncio.wait_for(gemini_queue.get(), timeout=0.1)
                        if not self.is_live_active:
                            break

                        class BlobObj:
                            def __init__(self, data, mime_type):
                                self.data = data
                                self.mime_type = mime_type

                        await session.send_realtime_input(
                            audio=BlobObj(
                                data=chunk,
                                mime_type="audio/pcm;rate=16000",
                            )
                        )
                    except asyncio.TimeoutError:
                        continue
                    except Exception as send_err:
                        print(f"[LIVE MIC SEND ERROR]: {send_err}")
                        break

        except Exception as e:
            print(f"[LIVE MIC PC ERROR]: {e}")
        finally:
            print("[LIVE MIC PC] Поток отправки микрофона окончательно остановлен.")

    async def _send_microphone_android(self, session):
        print("[LIVE MIC ANDROID] Запуск потока отправки микрофона...")
        loop = asyncio.get_running_loop()
        gemini_queue = asyncio.Queue()

        def gemini_enqueue(item):
            try:
                gemini_queue.put_nowait(item)
            except Exception:
                pass

        stop_event = threading.Event()

        def record_worker():
            recorder = None
            try:
                sample_rate = 16000
                channel = AudioFormat.CHANNEL_IN_MONO
                encoding = AudioFormat.ENCODING_PCM_16BIT

                min_size = AudioRecord.getMinBufferSize(sample_rate, channel, encoding)
                buffer_size = max(4096, min_size if min_size > 0 else 4096)

                recorder = AudioRecord(
                    AudioSource.VOICE_RECOGNITION,
                    sample_rate,
                    channel,
                    encoding,
                    buffer_size,
                )

                if recorder.getState() != AudioRecord.STATE_INITIALIZED:
                    print("[LIVE MIC ANDROID ERROR] AudioRecord не удалось инициализировать")
                    return

                recorder.startRecording()
                buffer = bytearray(buffer_size)
                print("[LIVE MIC ANDROID] Запись с микрофона успешно началась.")

                while self.is_live_active and not stop_event.is_set():
                    if getattr(self, 'model_is_speaking', False):
                        time.sleep(0.05)
                        continue

                    count = recorder.read(buffer, 0, len(buffer))
                    if count > 0:
                        pcm_bytes = bytes(buffer[:count])

                        audio_array = np.frombuffer(pcm_bytes, dtype=np.int16)
                        rms = np.sqrt(np.mean(audio_array.astype(float) ** 2)) if len(audio_array) > 0 else 0.0

                        if rms > 15.0:
                            loop.call_soon_threadsafe(gemini_enqueue, pcm_bytes)
                    else:
                        time.sleep(0.01)

            except Exception as e:
                print(f"[LIVE MIC ANDROID EXCEPTION]: {e}")
                traceback.print_exc()
            finally:
                if recorder is not None:
                    try:
                        if recorder.getRecordingState() == AudioRecord.RECORDSTATE_RECORDING:
                            recorder.stop()
                    except Exception:
                        pass
                    try:
                        recorder.release()
                    except Exception:
                        pass
                print("[LIVE MIC ANDROID] Нативный AudioRecord освобожден.")

        worker = threading.Thread(
            target=record_worker,
            name="AndroidAudioRecord",
            daemon=True,
        )
        worker.start()

        try:
            while self.is_live_active:
                try:
                    chunk = await asyncio.wait_for(gemini_queue.get(), timeout=0.1)
                    if not self.is_live_active:
                        break

                    class BlobObj:
                        def __init__(self, data, mime_type):
                            self.data = data
                            self.mime_type = mime_type

                    await session.send_realtime_input(
                        audio=BlobObj(
                            data=chunk,
                            mime_type="audio/pcm;rate=16000",
                        )
                    )
                except asyncio.TimeoutError:
                    continue
                except Exception as send_err:
                    print(f"[LIVE MIC SEND ERROR]: {send_err}")
                    break
        finally:
            stop_event.set()
            await asyncio.to_thread(worker.join, 2.0)
            print("[LIVE MIC ANDROID] Поток отправки микрофона окончательно остановлен.")

    async def _receive_audio(self, session):
        if platform == "android":
            await self._receive_audio_android(session)
        else:
            await self._receive_audio_pc(session)

    async def _receive_audio_pc(self, session):
        if not HAS_SOUNDDEVICE:
            raise RuntimeError("На ПК не установлен sounddevice")

        print("[LIVE RECEIVE] Запуск постоянного прослушивания ответов сервера...")

        try:
            with sd.OutputStream(samplerate=24000, channels=1, dtype=np.int16) as stream:
                while self.is_live_active:
                    try:
                        async for response in session.receive():
                            if not self.is_live_active:
                                break

                            content = response.server_content
                            if not content:
                                continue

                            if content.turn_complete:
                                print("[LIVE SERVER] Реплика модели завершена.")
                                self.model_is_speaking = False
                                await asyncio.sleep(0.3)

                            if content.interrupted:
                                print("[LIVE SERVER] Генерация прервана.")
                                self.model_is_speaking = False

                            if not content.model_turn:
                                continue

                            self.model_is_speaking = True

                            for part in content.model_turn.parts:
                                if hasattr(part, 'text') and part.text:
                                    model_text = part.text
                                    print(f"[LIVE MODEL TEXT]: {model_text}")

                                    # ЕСЛИ МОДЕЛЬ ПРИСЛАЛА МАРКЕР СБРОСА — НЕМЕДЛЕННО ВЫХОДИМ
                                    if "[disconnect]" in model_text.lower() or any(
                                            bye in model_text.lower() for bye in ["до свидания", "пока"]):
                                        print("[LIVE] Обнаружена команда завершения сессии. Сбрасываем соединение...")
                                        self.is_live_active = False
                                        return

                                if part.inline_data and part.inline_data.data:
                                    samples = np.frombuffer(part.inline_data.data, dtype=np.int16)
                                    if samples.size > 0:
                                        await asyncio.to_thread(stream.write, samples)

                    except Exception as stream_err:
                        if not self.is_live_active:
                            break
                        print(f"[LIVE STREAM RECONNECT WAIT]: {stream_err}")
                        await asyncio.sleep(1.0)
        finally:
            self.model_is_speaking = False
            print("[LIVE RECEIVE PC] Поток приема окончательно остановлен.")
            self._status("Ассистент отключен", (0.5, 0.5, 0.5, 1))

            await asyncio.sleep(1.0)

            try:
                assistant = self._get_assistant() if hasattr(self, '_get_assistant') else None
                if assistant:
                    if hasattr(assistant, 'speech_buffer'):
                        assistant.speech_buffer = ""
                    Clock.schedule_once(lambda dt: assistant.start_listening(), 0.1)
            except Exception as e:
                print(f"[RESET ASSISTANT ERROR]: {e}")

            print("[LIVE] Сессия полностью завершена.")

    async def _receive_audio_android(self, session):
        channel = AudioFormat.CHANNEL_OUT_MONO
        encoding = AudioFormat.ENCODING_PCM_16BIT
        sample_rate = 24000

        min_size = AudioTrack.getMinBufferSize(sample_rate, channel, encoding)
        buffer_size = max(min_size, 8192)

        track = AudioTrack(
            AudioManager.STREAM_MUSIC,
            sample_rate,
            channel,
            encoding,
            buffer_size,
            AudioTrack.MODE_STREAM,
        )

        try:
            track.play()
            print("[LIVE RECEIVE ANDROID] Начало прослушивания ответов сервера...")

            while self.is_live_active:
                try:
                    async for response in session.receive():
                        if not self.is_live_active:
                            break

                        content = response.server_content
                        if not content:
                            continue

                        if content.turn_complete:
                            print("[LIVE SERVER] Реплика модели завершена (turn_complete).")
                            self.model_is_speaking = False
                            await asyncio.sleep(0.3)

                        if content.interrupted:
                            print("[LIVE SERVER] Генерация прервана (interrupted).")
                            self.model_is_speaking = False

                        if not content.model_turn:
                            continue

                        self.model_is_speaking = True

                        for part in content.model_turn.parts:
                            if hasattr(part, 'text') and part.text:
                                model_text = part.text
                                print(f"[LIVE MODEL TEXT]: {model_text}")

                                # ЕСЛИ МОДЕЛЬ ПРИСЛАЛА МАРКЕР СБРОСА — НЕМЕДЛЕННО ВЫХОДИМ
                                if "[disconnect]" in model_text.lower() or any(
                                        bye in model_text.lower() for bye in ["до свидания", "пока"]):
                                    print("[LIVE] Обнаружена команда завершения сессии. Сбрасываем соединение...")
                                    self.is_live_active = False
                                    return

                            if part.inline_data and part.inline_data.data:
                                pcm = part.inline_data.data
                                await asyncio.to_thread(
                                    track.write,
                                    bytearray(pcm),
                                    0,
                                    len(pcm),
                                )
                except Exception as stream_err:
                    if not self.is_live_active:
                        break
                    print(f"[LIVE ANDROID RECONNECT WAIT]: {stream_err}")
                    await asyncio.sleep(1.0)

        except Exception as e:
            print(f"[LIVE RECEIVE ANDROID ERROR]: {e}")
            raise
        finally:
            self.model_is_speaking = False
            try:
                track.stop()
            except Exception:
                pass
            track.release()
            print("[LIVE RECEIVE ANDROID] Цикл приема завершен.")

            try:
                assistant = self._get_assistant() if hasattr(self, '_get_assistant') else None
                if assistant:
                    if hasattr(assistant, 'speech_buffer'):
                        assistant.speech_buffer = ""
                    Clock.schedule_once(lambda dt: assistant.start_listening(), 0.1)
            except Exception as e:
                print(f"[RESET ASSISTANT ANDROID ERROR]: {e}")

class MainHubScreen(BaseScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        root_layout = FloatLayout()

        # 1. Кнопка «Три точки» строго в верхнем правом углу
        btn_settings = FixedButton(
            text="•\n•\n•",
            font_size='14sp',
            bold=True,
            line_height=0.5,
            halign='center',
            valign='middle',
            text_size=(dp(45), dp(50)),
            size_hint=(None, None),
            size=(dp(45), dp(50)),
            background_normal='',
            background_down='',
            background_color=(0, 0, 0, 0),
            color=(1, 1, 1, 1),
            pos_hint={'right': 0.98, 'top': 0.98}
        )
        btn_settings.canvas.before.clear()
        btn_settings.bind(on_press=self.open_settings_handler)
        root_layout.add_widget(btn_settings)

        # 1.1 Строка статуса ассистента (выше поля ввода)
        self.assistant_label = Label(
            text="Ассистент: Инициализация...",
            font_size=sp(14),  # Вместо '13sp'
            color=(0.7, 0.8, 0.9, 1),
            size_hint=(None, None),
            size=(dp(320), dp(25)),
            pos_hint={'center_x': 0.5, 'top': 0.88},
            halign='center',
            valign='middle'
        )
        self.assistant_label.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
        root_layout.add_widget(self.assistant_label)

        # 1. Контейнер
        assistant_row = BoxLayout(
            orientation='horizontal',
            size_hint=(1, None),
            spacing=dp(6),
            pos_hint={'center_x': 0.5, 'top': 0.82},
            padding=[dp(15), 0, dp(15), 0]
        )

        # 2. Многострочный ввод с точной стартовой высотой 42dp
        self.assistant_input = TextInput(
            text="",
            hint_text="Введите запрос ассистенту...",
            multiline=True,
            size_hint_x=0.78,
            size_hint_y=None,
            height=dp(42),  # Жестко фиксируем стартовую высоту, как у кнопки
            font_size='13sp',
            halign='center',
            background_color=(0.15, 0.17, 0.22, 1),
            foreground_color=(1, 1, 1, 1),
            # Аккуратные отступы, чтобы текст был по центру одной строки
            padding=[dp(8), dp(10), dp(8), dp(8)]
        )

        # Функция для плавного роста инпута вниз только когда строк становится больше одной
        def update_input_height(instance, value):
            # Если минимальная высота стала больше 42dp (появилась 2-я строка), разрешаем расти
            if value > dp(42):
                instance.height = value
            else:
                instance.height = dp(42)

        # Привязываем динамический рост к minimum_height
        self.assistant_input.bind(minimum_height=update_input_height)
        assistant_row.add_widget(self.assistant_input)

        # 3. Кнопка AI (строго 42dp)
        self.btn_send = FixedButton(
            text="AI",
            font_size=sp(14),
            bold=True,
            bg_color=(0.18, 0.5, 0.25, 1),
            size_hint_x=0.22,
            size_hint_y=None,
            height=dp(42),
            pos_hint={'top': 1}  # Держится сверху, когда инпут растет вниз
        )
        self.btn_send.bind(on_press=self.on_ai_button_pressed)
        assistant_row.add_widget(self.btn_send)

        # Контейнер подстраивается под высоту инпута
        assistant_row.bind(minimum_height=assistant_row.setter('height'))

        root_layout.add_widget(assistant_row)

        # 2.1 Кнопка завершения звонка с PNG-иконкой (видима для настройки)
        self.end_call_button = Button(
            text="",  # Текст не нужен, так как иконка уже полноценная кнопка
            background_normal=IMG_PHONE,
            background_down=IMG_PHONE,
            size_hint=(None, None),
            size=(dp(100), dp(100)),  # Делаем её аккуратного квадратного размера
            pos_hint={'center_x': 0.5, 'top': 0.70}
        )
        self.end_call_button.opacity = 0
        self.end_call_button.disabled = True
        self.end_call_button.bind(on_press=self.terminate_live_session)
        root_layout.add_widget(self.end_call_button)

        # 3. Основной блок (Заголовок и кнопки режимов)
        content_box = BoxLayout(
            orientation='vertical',
            spacing=dp(15),
            size_hint=(None, None),
            width=dp(320),
            pos_hint={'center_x': 0.5, 'top': 0.52}
        )
        # Автоматическая высота под все видимые элементы
        content_box.bind(minimum_height=content_box.setter('height'))

        # Заголовок
        content_box.add_widget(Label(
            text="Голосовой помощник",
            font_size=sp(22),
            bold=True,
            color=(0.95, 0.95, 0.95, 1),
            size_hint_y=None,
            height=dp(40)
        ))

        # Кнопка Умный дом
        btn_smarthome = FixedButton(
            text="Умный дом и Голос",
            font_size=sp(16),
            bg_color=(0.18, 0.35, 0.6, 1),
            size_hint_y=None,
            height=dp(50)
        )
        btn_smarthome.bind(on_press=lambda x: setattr(self.manager, 'current', 'smarthome'))
        content_box.add_widget(btn_smarthome)

        # Кнопка ИИ Камера
        btn_camera = FixedButton(
            text="ИИ Камера",
            font_size=sp(16),
            bg_color=(0.35, 0.2, 0.5, 1),
            size_hint_y=None,
            height=dp(50)
        )
        btn_camera.bind(on_press=lambda x: setattr(self.manager, 'current', 'ai_camera'))
        content_box.add_widget(btn_camera)

        # Кнопка Телефон (переход к настройкам)
        btn_phone = FixedButton(
            text="Телефон",
            font_size=sp(16),
            bg_color=(0.18, 0.45, 0.25, 1),
            size_hint_y=None,
            height=dp(50)
        )
        btn_phone.bind(on_press=lambda x: setattr(self.manager, 'current', 'phone_settings'))
        content_box.add_widget(btn_phone)

        # ПОЛНОЦЕННАЯ ТЕСТОВАЯ КНОПКА (если нужна для проверки звонилки прямо с экрана)
        # Установите в True для отладки (покажет кнопку теста), в False — для скрытия
        DEBUG_MODE = False

        if DEBUG_MODE:
            test_call_btn = FixedButton(
                text="Тест звонка (Вызов)",
                font_size=sp(15),
                bg_color=(0.5, 0.2, 0.2, 1),
                size_hint_y=None,
                height=dp(45)
            )
            test_call_btn.bind(
                on_release=lambda x: App.get_running_app().show_incoming_call_ui("Иван Тест", "+7 (900) 555-35-35")
            )
            content_box.add_widget(test_call_btn)

        root_layout.add_widget(content_box)
        self.add_widget(root_layout)

    def on_text_changed(self, instance, value):
        """Меняем вид кнопки только в зависимости от статуса ИИ, а не от набора текста"""
        if getattr(self, 'is_speaking_now', False) or getattr(self, 'is_processing', False):
            return

        # Пока пользователь пишет, кнопка всегда готова отправить текст
        if value.strip():
            self.btn_send.text = "AI"  # или "Отправить"
            self.btn_send.bg_color = (0.18, 0.5, 0.25, 1)  # Зеленый
        else:
            self.btn_send.text = "AI"
            self.btn_send.bg_color = (0.18, 0.5, 0.25, 1)

    def on_ai_button_pressed(self, instance):
        """Универсальный обработчик: Отмена текущего процесса ИЛИ отправка запроса"""
        if getattr(self, 'is_speaking_now', False) or getattr(self, 'is_processing', False):
            print("[UI] Прерывание процесса по клику на кнопку отмены.")
            self.stop_current_speech()  # Она сама остановит звук и вызовет reset_assistant_state()
        else:
            # Иначе переводим в режим обработки и шлем запрос
            self.set_processing_state()
            self.send_assistant_command(instance)

    def set_processing_state(self):
        """Переводит кнопку в режим отмены при старте запроса или озвучки"""
        self.is_processing = True
        if hasattr(self, 'btn_send'):
            self.btn_send.text = "Отмена"
            self.btn_send.bg_color = (0.8, 0.25, 0.2, 1)

    def set_cancel_state(self):
        """Совместимость для озвучки"""
        self.set_processing_state()

    @mainthread
    def reset_assistant_state(self, clear_input=False):
        """Единый и полный сброс ассистента в исходный режим ожидания"""
        self.is_speaking_now = False
        self.is_processing = False

        # Снимаем блокировку сети для ESP
        app = App.get_running_app()
        if app:
            app.is_ai_busy = False

        # Очищаем поле ввода ТОЛЬКО если явно передан флаг clear_input=True
        if clear_input and hasattr(self, 'assistant_input'):
            self.assistant_input.text = ""

        # Возвращаем кнопку в зеленый режим 'AI'
        if hasattr(self, 'btn_send'):
            self.btn_send.text = "AI"
            self.btn_send.bg_color = (0.18, 0.5, 0.25, 1)

        # Возвращаем метку статуса в режим ожидания
        ai_word = "Алиса"
        if app and hasattr(app, 'config_data'):
            raw_ai = app.config_data.get("wake_word_ai", "алиса")
            ai_word = raw_ai.split(',')[0].strip().capitalize()

        self.update_assistant_status(f"Ассистент: Ожидание («{ai_word}»)", color=(0.6, 0.6, 0.6, 1))

        # Возобновляем фоновый опрос датчиков ESP
        if hasattr(self, 'resume_sensor_polling'):
            self.resume_sensor_polling()

    def stop_current_speech(self):
        """Останавливаем звук через SmartApp/ассистента и принудительно стираем текст"""
        print("[AI Screen] Запрос остановки процесса...")

        app = App.get_running_app()
        if app:
            # 1. Принудительно глушим централизованного ассистента
            assistant = getattr(app, 'assistant', None) or getattr(app, 'voice_assistant', None)
            if assistant and hasattr(assistant, 'stop'):
                assistant.stop()

            # 2. Вызываем глобальный метод приложения, если он есть
            if hasattr(app, 'stop_current_speech') and app.stop_current_speech != self.stop_current_speech:
                app.stop_current_speech()

        # 3. Принудительно сбрасываем состояние экрана И СТИРАЕМ ТЕКСТ (clear_input=True)
        if hasattr(self, 'reset_assistant_state'):
            self.reset_assistant_state(clear_input=True)

    def stop_speech(self):
        """Псевдоним для совместимости"""
        return self.stop_current_speech()

    def terminate_live_session(self, instance):
        """Штатный и безопасный сброс Live-сессии с полным возвратом в Vosk"""
        print("[UI] МЯГКИЙ И БЕЗОПАСНЫЙ СБРОС СЕССИИ!")

        app = App.get_running_app()
        controller = getattr(app, 'live_manager', None) or app or self

        self.is_live_active = False
        self.current_mode = 'VOSK'
        if controller and controller != self:
            controller.is_live_active = False
            controller.current_mode = 'VOSK'
        if app:
            app.is_live_active = False

        for target in (controller, app, self):
            if not target:
                continue
            for task_name in ('send_task', 'receive_task'):
                task = getattr(target, task_name, None)
                if task and not task.done():
                    try:
                        task.cancel()
                    except Exception:
                        pass

        def _force_ui(dt):
            try:
                target_app = app or getattr(self, 'app', None)
                if target_app and target_app.root:
                    screen = target_app.root.current_screen
                    if screen and hasattr(screen, 'update_assistant_status'):
                        screen.update_assistant_status("Ассистент: Ожидание («Алиса»)", (0.6, 0.6, 0.6, 1))

                    if screen and hasattr(screen, 'poll_statuses'):
                        # Безопасно гасим старый таймер через его объект
                        if getattr(target_app, 'poll_event', None):
                            target_app.poll_event.cancel()
                            target_app.poll_event = None

                        # Запускаем новый таймер с вашей константой POLL_INTERVAL
                        target_app.poll_event = Clock.schedule_interval(screen.poll_statuses, POLL_INTERVAL)

                    if screen and hasattr(screen, 'end_call_button'):
                        screen.end_call_button.opacity = 0
                        screen.end_call_button.disabled = True

                print("[RESET] Интерфейс успешно возвращен в режим ожидания.")
            except Exception as e:
                print(f"[RESET ERROR]: {e}")

        Clock.schedule_once(_force_ui, 0.1)

    def on_enter(self):
        super().on_enter()
        app = App.get_running_app()

        if hasattr(app, 'assistant') and app.assistant and getattr(app.assistant, 'model', None) is None:
            return

        ai_ww = app.config_data.get("wake_word_ai", "джарвис")
        first_ai_word = ai_ww.split(',')[0].strip().capitalize()

        self.update_assistant_status(f"Ассистент: Ожидание («{first_ai_word}»)...", color=(0.6, 0.6, 0.6, 1))

    def on_leave(self):
        super().on_leave()
        pass

    @mainthread
    def update_assistant_status(self, text, color=(0.6, 0.6, 0.6, 1)):
        print(f"[DEBUG MAIN SCREEN] Метод запущен. Текст: '{text}', Цвет: {color}")

        # Ищем именно метку статуса (например, в ids или отдельный атрибут),
        # НИКОГДА не используя assistant_label, если она связана с полем ввода!
        target_label = None

        if hasattr(self, 'ids') and 'assistant_status_label' in self.ids:
            target_label = self.ids.assistant_status_label
        elif hasattr(self, 'status_label') and self.status_label:
            target_label = self.status_label
        elif hasattr(self, 'assistant_label') and self.assistant_label:
            # Защита: проверяем, что это НЕ поле ввода
            from kivy.uix.textinput import TextInput
            if not isinstance(self.assistant_label, TextInput):
                target_label = self.assistant_label
            else:
                print(
                    "[DEBUG WARNING] assistant_label указывает на TextInput! Пропускаем, чтобы не портить строку ввода.")

        if target_label:
            app = App.get_running_app()
            ai_word = "Алиса"
            if app and hasattr(app, 'config_data'):
                raw_ai = app.config_data.get("wake_word_ai", "алиса")
                ai_word = raw_ai.split(',')[0].strip().capitalize()

            if "ожидание" in text.lower():
                text = f"Ассистент: Ожидание («{ai_word}»)"

            target_label.text = text
            if hasattr(target_label, 'color'):
                target_label.color = color

            print(f"[DEBUG MAIN SCREEN] Статус успешно обновлен в метке: '{target_label.text}'")
        else:
            print(f"[DEBUG MAIN SCREEN ERROR] Отдельная метка статуса не найдена, текст '{text}' выведен в консоль.")

    def receive_voice_query(self, query):
        print(f"[MAIN SCREEN] Получен голосовой запрос: '{query}'")
        clean_query = query.lower().strip()

        app = App.get_running_app()
        config = getattr(app, 'config_data', {}) if app else {}

        raw_text_words = config.get('mode_word_text', 'запрос, текст')
        raw_live_words = config.get('mode_word_live', 'поговорим, чат, диалог')

        text_words_list = [w.strip().lower() for w in raw_text_words.split(',') if w.strip()]
        live_words_list = [w.strip().lower() for w in raw_live_words.split(',') if w.strip()]

        is_live_mode = any(word in clean_query for word in live_words_list)
        is_text_mode = any(word in clean_query for word in text_words_list)

        if is_live_mode:
            print("[STATE] Выбран режим: ЖИВОЙ ДИАЛОГ (Live API)")
            self.update_assistant_status("Переход в Live-диалог...", (0.9, 0.5, 0.1, 1))

            if app:
                app.is_live_active = True

            if self.kivy_app and hasattr(self.kivy_app, 'root'):
                def show_btn(dt):
                    screen = self.kivy_app.root.current_screen
                    if screen and hasattr(screen, 'end_call_button'):
                        screen.end_call_button.opacity = 1
                        screen.end_call_button.disabled = False

                Clock.schedule_once(show_btn, 0)

                if hasattr(app, 'speech_buffer'):
                    app.speech_buffer = ""
                if hasattr(self, 'speech_buffer'):
                    self.speech_buffer = ""

                if hasattr(app, 'reset_session_timer'):
                    app.reset_session_timer()
                elif hasattr(self, 'reset_session_timer'):
                    self.reset_session_timer()

                try:
                    if hasattr(app, 'poll_event') and app.poll_event:
                        try:
                            app.poll_event.cancel()
                        except Exception:
                            pass
                        app.poll_event = None

                    if app.root:
                        try:
                            current_screen = app.root.current_screen
                            if hasattr(current_screen, 'poll_statuses'):
                                Clock.unschedule(current_screen.poll_statuses)
                        except Exception:
                            pass

                    app.live_manager.start_in_background()
                    print("[STATE] Запрошен запуск потока Live API.")
                except Exception as e:
                    print(f"[STATE ERROR] Не удалось запустить Live: {e}")
                return

        elif is_text_mode:
            print("[STATE] Выбран режим: ЯВНЫЙ ТЕКСТОВЫЙ ЗАПРОС")
            cleaned_query = query
            for w in text_words_list:
                cleaned_query = cleaned_query.replace(w, "").strip()
            if hasattr(self, 'assistant_input') and self.assistant_input:
                self.assistant_input.text = cleaned_query
            self.update_assistant_status(f"Запрос: {cleaned_query}", color=(0.2, 0.85, 0.3, 1))
            self.send_assistant_command(None)
            return

        print("[STATE] Выбран режим: ОБЫЧНЫЙ ЗАПРОС (Flash)")
        if hasattr(self, 'assistant_input') and self.assistant_input:
            self.assistant_input.text = query
        self.update_assistant_status(f"Запрос: {query}", color=(0.2, 0.85, 0.3, 1))
        self.send_assistant_command(None)

    def open_settings_handler(self, instance):
        SystemSettingsPopup().open()


    def send_assistant_command(self, instance):
        text = self.assistant_input.text.strip()
        if not text:
            return

        # 1. Переводим кнопку в режим "Отмена"
        self.set_processing_state()

        # 2. Показываем пользователю статус "Думаю..."
        self.update_assistant_status("Думаю...", color=(0.2, 0.7, 0.9, 1))

        print(f"[AI] Отправка текстового запроса: {text}")
        threading.Thread(target=self._background_ai_request, args=(text,), daemon=True).start()


    @mainthread
    def append_streaming_chunk(self, chunk_text):
        """Безопасно добавляет очередной кусок текста на экран в главном потоке."""
        # Если у вас текстовое поле или метка для вывода ответа:
        if hasattr(self, 'assistant_input'):  # или метка результата
            # Можно накапливать текст в переменную ответа и выводить
            pass

        # Обновляем статус или текст на экране
        current_text = getattr(self, '_current_streaming_answer', '')
        current_text += chunk_text
        self._current_streaming_answer = current_text

        # Выводим в интерфейс (например, в метку ответа ассистента)
        if hasattr(self, 'update_assistant_status'):
            self.update_assistant_status(current_text[:40] + "...", color=(0.2, 0.85, 0.3, 1))

        print(chunk_text, end="", flush=True)  # дублируем в консоль

    def _background_ai_request(self, text):
        # Получаем клиента и конфигурацию из класса приложения (SmartApp)
        app = App.get_running_app()
        ai_data = app.init_ai_client() if hasattr(app, 'init_ai_client') else None

        if not ai_data:
            # Безопасно обновляем UI через главный поток
            Clock.schedule_once(lambda dt: self.update_assistant_status("Ошибка: укажите API-ключ в настройках",
                                                                        color=(0.8, 0.2, 0.2, 1)), 0)
            Clock.schedule_once(lambda dt: self.reset_assistant_state(), 0)
            return

        provider = ai_data["provider"]
        client = ai_data["client"]
        model_name = ai_data["text_model"]
        # Берем готовый динамический список моделей из клиента
        models_to_try = ai_data.get("models_to_try", [model_name])

        try:
            if provider == 'gemini':
                clean_text = text.encode('utf-8', errors='ignore').decode('utf-8')

                response_stream = None
                success_model = None
                last_exception = None

                # Сначала ищем рабочую модель и открываем стрим
                for m in models_to_try:
                    if not getattr(self, 'is_processing', False):
                        print("[AI] Запрос был прерван пользователем.")
                        Clock.schedule_once(lambda dt: self.reset_assistant_state(), 0)
                        return

                    try:
                        print(f"[AI] Запуск стриминга через модель: {m}")
                        # Используем метод нашего REST-сервиса, завернутого в client.models
                        response_stream = client.models.generate_content_stream(
                            model=m,
                            contents=clean_text
                        )
                        success_model = m
                        break
                    except Exception as model_err:
                        last_exception = model_err
                        print(f"[AI WARNING] Модель {m} не дала стрим: {model_err}")
                        continue

                if response_stream is None:
                    raise last_exception if last_exception else Exception("Не удалось запустить стриминг")

                self._current_streaming_answer = ""
                full_answer = ""

                # Безопасно читаем стрим с защитой от обрыва соединения
                try:
                    for chunk in response_stream:
                        if not getattr(self, 'is_processing', False):
                            break

                        if hasattr(chunk, 'text') and chunk.text:
                            piece = chunk.text
                            full_answer += piece
                            self.append_streaming_chunk(piece)
                except Exception as stream_err:
                    print(f"[AI ERROR] Обрыв во время стриминга на модели {success_model}: {stream_err}")

                    # Автоперебор по динамическому списку при обрыве стрима
                    fallback_success = False
                    for fallback_model in models_to_try:
                        if fallback_model == success_model:
                            continue  # Пропускаем ту модель, на которой уже упали

                        print(f"[AI] Пробуем переключиться на модель {fallback_model} для завершения...")
                        try:
                            # Используем generate_content через тот же клиент
                            fallback_response = client.models.generate_content(
                                model=fallback_model,
                                contents=clean_text,
                            )
                            # Читаем текст из ответа
                            fb_text = ""
                            if hasattr(fallback_response, 'text'):
                                fb_text = fallback_response.text
                            elif hasattr(fallback_response, 'candidates'):
                                # На случай если это iterable/generator
                                for fc in fallback_response:
                                    if hasattr(fc, 'text'):
                                        fb_text += fc.text

                            if fb_text.strip():
                                full_answer = fb_text.strip()
                                fallback_success = True
                                print(f"[AI] Успешно завершено на модели: {fallback_model}")
                                break
                        except Exception as fb_err:
                            print(f"[AI WARNING] Модель {fallback_model} тоже недоступна: {fb_err}")
                            continue

                    if not fallback_success and not full_answer:
                        raise stream_err

                ai_answer = full_answer.strip()
                if not ai_answer:
                    raise Exception("Пустой ответ от модели")

            elif provider == 'gigachat':
                ai_answer = "GigaChat в процессе интеграции"

            print(f"\n[AI] Полный ответ получен: {ai_answer}")
            self.apply_response_on_main_thread(ai_answer)
            return

        except Exception as e:
            print(f"[AI ERROR] Ошибка стриминга: {e}")
            Clock.schedule_once(
                lambda dt: self.update_assistant_status("Ошибка: сервер ИИ перегружен", color=(0.8, 0.2, 0.2, 1)), 0)
            Clock.schedule_once(lambda dt: self.reset_assistant_state(), 0)

    @mainthread
    def apply_response_on_main_thread(self, ai_answer):
        self.update_assistant_status("Ответ получен", color=(0.2, 0.85, 0.3, 1))

        # 1. Запускаем озвучку ответа через централизованного ассистента приложения.
        # Вся очистка текста, блокировка микрофона и сброс состояния после речи
        # теперь управляются самим ассистентом (VoiceAssistant)!
        try:
            app = App.get_running_app()
            assistant_obj = getattr(app, 'assistant', None) or getattr(self, 'assistant', None)

            if assistant_obj:
                assistant_obj.speak(ai_answer)
            elif hasattr(self, 'speak_answer'):
                self.speak_answer(ai_answer)
        except Exception as e:
            print(f"[TTS ERROR]: {e}")
            # Если вдруг произошла ошибка, сразу возвращаем кнопку в норму, чтобы она не зависла
            if hasattr(self, 'set_normal_state'):
                self.set_normal_state()
            elif hasattr(self, 'reset_assistant_state'):
                self.reset_assistant_state()

        print("[ESP] Ответ от сервера получен, работа приложения штатно продолжается.")

    def _release_mic(self, dt=None):
        # код освобождения микрофона...
        """Снимает блокировку микрофона после завершения речи"""
        self.is_assistant_speaking = False
        if hasattr(self, 'reset_assistant_state'):
            self.reset_assistant_state()

class SmartHomeScreen(BaseScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        app_instance = App.get_running_app()
        self.config_data = app_instance.config_data

        # Переносим переменные состояния
        self.lamp_objects = []
        self.esp_connected = False
        self.failed_ip_checks = 0
        self.assistant = None  # Инициализируем поле для ассистента

        # --- Единственные точки хранения ссылок на таймеры ---
        self.poll_event = None       # Таймер для сетевого опроса ESP8266


        main_layout = BoxLayout(orientation='vertical', padding=15, spacing=15)

        # Верхняя панель (Шапка)
        top_bar = BoxLayout(
            size_hint_y=None,
            height=dp(50),  # Используем dp
            spacing=dp(10),
            padding=[dp(10), dp(5), dp(10), dp(5)]  # Отступы, чтобы элементы не прижимались к краям
        )

        btn_back = FixedButton(
            text="Меню",
            bg_color=(0.2, 0.23, 0.3, 1),
            size_hint=(None, None),
            width=dp(80),  # Сделаем чуть компактнее под sp/dp
            height=dp(40),
            font_size=sp(14)  # Добавили адаптивный размер шрифта кнопки
        )
        btn_back.bind(on_press=lambda x: setattr(self.manager, 'current', 'main'))
        top_bar.add_widget(btn_back)

        lbl_title = Label(
            text="Управление домом",
            font_size=sp(18),  # Используем sp для нормального размера текста на телефоне
            bold=True,
            color=(0.9, 0.9, 0.9, 1),
            halign='left',
            valign='middle'
        )
        lbl_title.bind(size=lbl_title.setter('text_size'))
        top_bar.add_widget(lbl_title)

        main_layout.add_widget(top_bar)

        # Карточка с закругленным фоном
        card_layout = BoxLayout(orientation='vertical', padding=15, spacing=10, size_hint=(1, 1))
        with card_layout.canvas.before:
            Color(0.12, 0.14, 0.19, 1)
            self.card_rect = RoundedRectangle(size=card_layout.size, pos=card_layout.pos, radius=[16])
            Color(0.22, 0.26, 0.35, 1)
            self.card_border = Line(
                rounded_rectangle=(card_layout.x, card_layout.y, card_layout.width, card_layout.height, 16), width=1.2)

        def update_card(instance, value):
            self.card_rect.pos = instance.pos
            self.card_rect.size = instance.size
            self.card_border.rounded_rectangle = (instance.x, instance.y, instance.width, instance.height, 16)

        card_layout.bind(pos=update_card, size=update_card)

        # Внутренний заголовок карточки (Wi-Fi и шестеренка настроек)
        header_box = BoxLayout(orientation='horizontal', size_hint=(1, None), height=dp(45))

        wifi_img_path = get_img(IMG_WIFI)
        if os.path.exists(wifi_img_path):
            self.wifi_icon = Image(
                source=wifi_img_path,
                size_hint=(None, None),
                size=(dp(32), dp(32)),
                pos_hint={'center_y': 0.5},
                color=(0.4, 0.4, 0.4, 1)
            )
        else:
            self.wifi_icon = Label(
                text="Wi-Fi",
                font_size='12sp',
                bold=True,
                size_hint=(None, None),
                size=(dp(40), dp(32)),
                pos_hint={'center_y': 0.5},
                color=(0.4, 0.4, 0.4, 1)
            )
        header_box.add_widget(self.wifi_icon)
        header_box.add_widget(Widget())

        btn_settings = Button(
            text="•\n•\n•",
            font_size='14sp',
            bold=True,
            line_height=0.5,
            halign='center',
            valign='middle',
            size_hint=(None, None),
            size=(dp(40), dp(45)),
            background_normal='',
            background_color=(0, 0, 0, 0),
            color=(1, 1, 1, 1),
            pos_hint={'center_y': 0.5}
        )
        btn_settings.bind(on_press=lambda instance: self.open_settings())
        header_box.add_widget(btn_settings)

        card_layout.add_widget(header_box)

        # Метки температуры и статуса ассистента
        self.temp_label = Label(
            text="Температура: -- °C",
            font_size=sp(18),  # Адаптивный размер шрифта для температуры
            bold=True,
            color=(1, 1, 1, 1),
            size_hint_y=None,
            height=dp(40),
            halign='center',
            valign='middle'
        )
        self.temp_label.bind(size=self.temp_label.setter('text_size'))
        card_layout.add_widget(self.temp_label)

        self.assistant_label = Label(
            text="Ассистент: Инициализация...",
            font_size=sp(14),  # Адаптивный размер шрифта для статуса
            color=(0.6, 0.6, 0.6, 1),
            size_hint_y=None,
            height=dp(25),
            halign='center',
            valign='middle'
        )
        self.assistant_label.bind(size=self.assistant_label.setter('text_size'))
        card_layout.add_widget(self.assistant_label)

        # Динамический список ламп из конфига
        lamps_container = GridLayout(cols=1, spacing=dp(10), size_hint_x=1, size_hint_y=None)
        lamps_container.bind(minimum_height=lamps_container.setter('height'))

        icon_pairs = [
            (IMG_LAMP_1_OFF, IMG_LAMP_1_ON),
            (IMG_LAMP_2_OFF, IMG_LAMP_2_ON),
            (IMG_LAMP_3_OFF, IMG_LAMP_3_ON),
        ]

        for idx, ch in enumerate(self.config_data.get("channels", [])):
            off_img, on_img = icon_pairs[idx] if idx < len(icon_pairs) else (IMG_LAMP_1_OFF, IMG_LAMP_1_ON)
            lamp = LampRow(ch["id"], off_img, on_img, lambda: f"http://{self.config_data.get('device_ip')}",
                           app_ref=app_instance)
            self.lamp_objects.append(lamp)
            lamps_container.add_widget(lamp)

        scroll = ScrollView(size_hint=(1, 1), do_scroll_x=False, do_scroll_y=True)
        scroll.add_widget(lamps_container)
        card_layout.add_widget(scroll)

        main_layout.add_widget(card_layout)

        # Кнопки управления снизу ("Включить все" / "Выключить все")
        btn_all_on = Button(
            text="ВКЛЮЧИТЬ ВСЕ",
            font_size=sp(13),  # Используем функцию sp()
            bold=True,
            background_normal='',
            background_color=(0.15, 0.2, 0.25, 1),
            color=(0.2, 0.85, 0.3, 1),
            size_hint=(1, None),
            height=dp(40)
        )
        btn_all_on.bind(on_press=lambda x: self.turn_all_on())

        btn_all_off = Button(
            text="ВЫКЛЮЧИТЬ ВСЕ",
            font_size=sp(13),  # Используем функцию sp()
            bold=True,
            background_normal='',
            background_color=(0.15, 0.2, 0.25, 1),
            color=(0.9, 0.2, 0.2, 1),
            size_hint=(1, None),
            height=dp(40)
        )
        btn_all_off.bind(on_press=lambda x: self.turn_all_off())

        btn_box = BoxLayout(orientation='horizontal', spacing=dp(12), size_hint=(1, None), height=dp(45))
        btn_box.add_widget(btn_all_on)
        btn_box.add_widget(btn_all_off)
        main_layout.add_widget(btn_box)

        self.add_widget(main_layout)

        # Запуск разрешений и единственной правильной цепочки инициализации
        self.request_android_permissions(on_granted=self._start_assistant)

    def on_enter(self):
        super().on_enter()
        self._is_active_screen = True  # Фиксируем, что мы на экране света

        app = App.get_running_app()
        is_assistant_active = app and hasattr(app, 'assistant') and app.assistant and getattr(app.assistant,
                                                                                              'is_active', False)

        if not is_assistant_active:
            light_word = "Зал"
            if app and hasattr(app, 'config_data'):
                raw_light = app.config_data.get("wake_word_light", "зал")
                light_word = raw_light.split(',')[0].strip().capitalize()

            self.update_assistant_status(f"Ассистент: Ожидание («{light_word}»)", color=(0.6, 0.6, 0.6, 1))

        # Сетевой опрос запускается ВСЕГДА при входе на экран
        self.start_polling()

    def on_leave(self):
        super().on_leave()
        self._is_active_screen = False  # Снимаем флаг присутствия на экране

        # При уходе с экрана глушим только сетевой опрос этого экрана
        self.stop_polling()

        # Если нужно гасить ассистента при уходе с экрана, вызываем метод приложения:
        app = App.get_running_app()
        if app and hasattr(app, 'stop_assistant_tick'):
            app.stop_assistant_tick()

    # --- ТОЛЬКО УПРАВЛЕНИЕ СЕТЕВЫМ ОПРОСОМ ЭКРАНА СВЕТА ---

    def start_polling(self):
        if self.poll_event is not None:
            return

        print("[POLL] Мгновенный первичный опрос ESP8266 при входе...")
        # 1. Опрашиваем устройство СРАЗУ же без ожидания таймера
        self.poll_statuses(0)

        print(f"[POLL] Запуск регулярного сетевого опроса ESP8266 каждые {POLL_INTERVAL} сек...")
        # 2. Запускаем периодический таймер на будущее
        self.poll_event = Clock.schedule_interval(self.poll_statuses, POLL_INTERVAL)

    def stop_polling(self):
        if self.poll_event:
            print("[POLL] Остановка сетевого опроса.")
            self.poll_event.cancel()
            self.poll_event = None

    def poll_statuses(self, dt):
        self.check_ip_connection()

    # --- Архитектура инициализации модели и ассистента без дублирующих потоков ---

    def _start_assistant(self):
        # Запускаем подготовку путей и фоновую загрузку (строго 1 раз)
        self.prepare_local_model()

    def start_assistant_tick(self, *args):
        """Безопасный запуск тика ассистента или фоновой проверки."""
        # Если здесь должен запускаться периодический опрос, добавьте его вызов,
        # например: if hasattr(self, 'start_polling'): self.start_polling()
        pass

    def prepare_local_model(self):
        if platform == 'android':
            self.model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model",
                                           "vosk-model-small-ru-0.22")
        else:
            self.model_path = "model/vosk-model-small-ru-0.22"

        # Запускаем асинхронную загрузку модели через Clock
        Clock.schedule_once(lambda dt: self._load_model_background(), 0)

    def _load_model_background(self):
        # АРХИТЕКТУРНАЯ ЗАЩИТА ОТ ПОВТОРНОГО ЗАПУСКА
        if getattr(self, '_model_loading_started', False):
            return
        self._model_loading_started = True

        try:
            print("[VOSK] Загрузка языковой модели в фоновом потоке...")
            abs_model_path = os.path.abspath(self.model_path)

            # Загружаем модель ровно один раз
            from vosk import Model
            self.model = Model(abs_model_path)
            print("[VOSK] Модель успешно загружена!")

            # Обновляем статус в интерфейсе
            Clock.schedule_once(
                lambda dt: self.update_assistant_status("Ассистент: Готов к работе", color=(0.2, 0.85, 0.3, 1)), 0)

            # Создаем экземпляр ассистента
            self.assistant = VoiceAssistant(self, self.lamp_objects)

            # Сохраняем ссылку в глобальный app, чтобы к нему был доступ отовсюду
            if app := App.get_running_app():
                app.assistant = self.assistant

            # ЗАПУСКАЕМ ПРОСЛУШИВАНИЕ НАПРЯМУЮ, БЕЗ ПЕРЕХОДА ЧЕРЕЗ STOP
            Clock.schedule_once(lambda dt: self.assistant.start_listening(), 0.1)

            # Запускаем единственный таймер тиков ассистента через централизованный метод
            self.start_assistant_tick()

        except Exception as e:
            print(f"[VOSK ERROR]: {e}")
            Clock.schedule_once(
                lambda dt: self.update_assistant_status("Ошибка загрузки модели", color=(1, 0.2, 0.2, 1)), 0)
            self._model_loading_started = False  # Сбрасываем флаг только при фатальном сбое для возможности повтора

    # --- Методы логики управления и опросов ---

    def turn_all_on(self):
        for l in self.lamp_objects:
            l.turn_on()

    def turn_all_off(self):
        for l in self.lamp_objects:
            l.turn_off()

    def poll_statuses(self, dt):
        # Если активен Live-диалог, временно пропускаем опрос сети
        app_instance = App.get_running_app()
        if getattr(app_instance, 'is_live_active', False):
            return

        # Единственный запрос, который проверяет связь,
        # обновляет все реле и забирает температуру со страницы за один раз!
        self.check_ip_connection()

    def check_ip_connection(self):
        def req():
            target_ip = self.config_data.get("device_ip")
            if not target_ip:
                self.set_wifi_status(False)
                return
            try:
                res = requests.get(f"http://{target_ip}/", timeout=3)
                if res.status_code == 200:
                    self.failed_ip_checks = 0
                    self.set_wifi_status(True)
                    if not self.esp_connected:
                        self.esp_connected = True
                        if hasattr(self, 'assistant') and self.assistant:
                            self.assistant.speak("Связь установлена")

                    raw_text = res.text.strip()
                    text_upper = raw_text.upper()

                    # 1. Обновляем состояние всех ламп
                    for lamp in getattr(self, 'lamp_objects', []):
                        if f"GPIO{lamp.channel_id}ON" in text_upper:
                            lamp.is_on = True
                        elif f"GPIO{lamp.channel_id}OFF" in text_upper:
                            lamp.is_on = False
                        lamp._update_ui()

                    # 2. Парсим температуру из того же ответа страницы
                    match = re.search(r"(\d+\.\d+)", raw_text)
                    if not match:
                        match = re.search(r"(?:Temp|Температура)[^\d]*(\d+(?:\.\d+)?)", raw_text, re.IGNORECASE)

                    if match:
                        current_temp = float(match.group(1))
                        self._set_temp_text(f"Температура: {current_temp:.1f} °C")

                else:
                    self._handle_ip_failure()
            except Exception:
                self._handle_ip_failure()

        threading.Thread(target=req, daemon=True).start()

    def _handle_ip_failure(self):
        self.failed_ip_checks += 1
        if self.failed_ip_checks >= 3:
            self.esp_connected = False
            self.set_wifi_status(False)

    @mainthread
    def set_wifi_status(self, is_connected: bool):
        if hasattr(self, 'wifi_icon') and self.wifi_icon:
            if is_connected:
                self.wifi_icon.color = (1, 1, 1, 1)
            else:
                self.wifi_icon.color = (0.4, 0.4, 0.4, 1)

    def fetch_temperature(self, speak_result=False):
        """Берем актуальную температуру (фоновый опрос и так держит её в актуальном состоянии)"""
        try:
            # Если нужно просто озвучить то, что уже есть на экране (ведь опрос каждые 5 сек обновляет метку)
            current_text = getattr(self.temp_label, 'text', '') if hasattr(self, 'temp_label') else ''

            if speak_result and self.config_data.get("tts_enabled", True):
                if hasattr(self, 'assistant') and self.assistant and current_text:
                    # Извлекаем цифру из текущего текста метки на экране, чтобы не делать лишний сетевой запрос
                    import re
                    match = re.search(r"(\d+(?:\.\d+)?)", current_text)
                    if match:
                        temp_val = float(match.group(1))
                        speech_text = format_temperature_speech(temp_val)
                        self.assistant.speak(speech_text)
                        return

            # Если фоновый опрос по какой-то причине еще не успел отработать, делаем разовый запрос
            sensor_ip = self.config_data.get("sensor_ip") or self.config_data.get("device_ip")
            if sensor_ip:
                def req():
                    try:
                        res = requests.get(f"http://{sensor_ip}/", timeout=3)
                        if res.status_code == 200:
                            raw_text = res.text.strip()
                            match = re.search(r"(\d+\.\d+)", raw_text) or re.search(
                                r"(?:Temp|Температура)[^\d]*(\d+(?:\.\d+)?)", raw_text, re.IGNORECASE)
                            if match:
                                current_temp = float(match.group(1))
                                self._set_temp_text(f"Температура: {current_temp:.1f} °C")
                                if speak_result and self.config_data.get("tts_enabled", True):
                                    if hasattr(self, 'assistant') and self.assistant:
                                        self.assistant.speak(format_temperature_speech(current_temp))
                    except Exception as e:
                        print(f"[ОШИБКА ДАТЧИКА]: {e}")

                threading.Thread(target=req, daemon=True).start()

        except Exception as e:
            print(f"[FETCH TEMP ERROR]: {e}")

    @mainthread
    def _set_temp_text(self, text):
        self.temp_label.text = text

    @mainthread
    def update_assistant_status(self, text, color=(0.6, 0.6, 0.6, 1)):
        if hasattr(self, 'assistant_label'):
            light_word = "Зал"
            if self.config_data:
                raw_light = self.config_data.get("wake_word_light", "зал")
                light_word = raw_light.split(',')[0].strip().capitalize()

            if "ожидание" in text.lower():
                text = f"Ассистент: Ожидание («{light_word}»)"

            self.assistant_label.text = text
            self.assistant_label.color = color

    def update_current_screen_status(self, text, color=None):
        pass

    def request_android_permissions(self, on_granted=None):
        if platform == 'android':
            try:
                from android.permissions import request_permissions, Permission
                def cb(permissions, results):
                    if all(results) and on_granted:
                        on_granted()

                request_permissions([Permission.RECORD_AUDIO, Permission.INTERNET], cb)
            except Exception:
                if on_granted:
                    on_granted()
        else:
            if on_granted:
                on_granted()

    def open_settings(self):
        layout = BoxLayout(orientation='vertical', padding=dp(15), spacing=dp(10), size_hint=(1, 1))

        from kivy.graphics import Color, Rectangle
        with layout.canvas.before:
            Color(0.11, 0.13, 0.17, 1)
            bg_rect = Rectangle(size=layout.size, pos=layout.pos)

        layout.bind(
            size=lambda inst, val: setattr(bg_rect, 'size', val),
            pos=lambda inst, val: setattr(bg_rect, 'pos', val)
        )

        # Исправленная шапка с использованием dp и sp
        top_bar = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(10))

        btn_back = FixedButton(
            text="Назад",
            bg_color=(0.2, 0.23, 0.3, 1),
            size_hint=(None, None),
            width=dp(80),  # Адаптивная ширина
            height=dp(40),  # Адаптивная высота
            font_size=sp(14)
        )
        top_bar.add_widget(btn_back)

        lbl_title = Label(
            text="Настройки системы",
            font_size=sp(18),  # Адаптивный размер шрифта через sp
            bold=True,
            color=(0.9, 0.9, 0.9, 1),
            halign='left',
            valign='middle'
        )
        lbl_title.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
        top_bar.add_widget(lbl_title)

        layout.add_widget(top_bar)

        scroll = ScrollView(size_hint=(1, 1), do_scroll_x=False, do_scroll_y=True)
        content = BoxLayout(orientation='vertical', spacing=dp(14), size_hint_y=None,
                            padding=[dp(5), dp(5), dp(5), dp(5)])
        content.bind(minimum_height=content.setter('height'))
        scroll.add_widget(content)

        def create_section_header(text):
            lbl = Label(
                text=text,
                font_size=sp(17),  # Используем функцию sp() вместо строки
                bold=False,
                color=(0.3, 0.7, 1, 1),
                size_hint_y=None,
                height=dp(32),
                halign='center',
                valign='middle'
            )
            lbl.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
            return lbl

        class TapTextInput(TextInput):
            def on_touch_down(self, touch):
                if self.collide_point(*touch.pos):
                    if hasattr(self, 'tap_callback') and self.tap_callback:
                        self.tap_callback(self)
                    return True
                return super().on_touch_down(touch)

        def start_voice_recording_for_input(text_input_instance):
            if not hasattr(self, 'assistant') or not self.assistant:
                text_input_instance.text = "Ошибка: ассистент не найден"
                return

            original_bg = text_input_instance.background_color
            text_input_instance.background_color = (0.25, 0.2, 0.4, 1)
            original_text = text_input_instance.text
            text_input_instance.text = "Слушаю..."

            self.update_assistant_status("Запись в настройках...", color=(1.0, 0.6, 0.2, 1))

            def on_phrase_captured(phrase):
                text_input_instance.text = phrase if phrase else original_text
                text_input_instance.background_color = original_bg

                raw_light = self.config_data.get("wake_word_light", "зал")
                wake_hint = raw_light.split(',')[0].strip().capitalize()

                self.update_assistant_status(f"Ассистент: Ожидание («{wake_hint}»)...", color=(0.6, 0.6, 0.6, 1))

            self.assistant.voice_input_target = on_phrase_captured

            def reset_timeout(dt):
                if getattr(self.assistant, 'voice_input_target', None) == on_phrase_captured:
                    self.assistant.voice_input_target = None
                    text_input_instance.text = original_text
                    text_input_instance.background_color = original_bg

                    raw_light = self.config_data.get("wake_word_light", "зал")
                    wake_hint = raw_light.split(',')[0].strip().capitalize()

                    self.update_assistant_status(f"Ассистент: Ожидание («{wake_hint}»)...", color=(0.6, 0.6, 0.6, 1))

            Clock.schedule_once(reset_timeout, 10)

        def create_voice_input(text="", input_filter=None):
            inp = TapTextInput(
                text=str(text),
                multiline=False,
                size_hint_y=None,
                height=dp(40),
                font_size=sp(13),  # Используем sp()
                readonly=True,
                input_filter=input_filter,
                background_color=(0.15, 0.17, 0.22, 1),
                foreground_color=(1, 1, 1, 1),
                halign='center',
                padding=[dp(8), dp(10), dp(8), dp(8)]
            )
            inp.tap_callback = start_voice_recording_for_input
            return inp

        def create_keyboard_input(text="", input_filter=None):
            inp = TextInput(
                text=str(text),
                multiline=False,
                size_hint_y=None,
                height=dp(40),
                font_size=sp(13),  # Используем sp()
                input_filter=input_filter,
                background_color=(0.15, 0.17, 0.22, 1),
                foreground_color=(1, 1, 1, 1),
                halign='center',
                padding=[dp(8), dp(10), dp(8), dp(8)]
            )
            return inp

        def create_setting_block(label_text, input_widget):
            block = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(4))

            lbl = Label(
                text=label_text,
                font_size=sp(16),  # Используем sp()
                font_name='Roboto',
                bold=False,
                color=(0.85, 0.85, 0.85, 1),
                halign='center',
                valign='middle',
                size_hint_y=None,
                height=dp(22)
            )
            lbl.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
            block.add_widget(lbl)

            input_widget.size_hint_x = 1.0
            block.add_widget(input_widget)

            block.height = dp(22) + dp(4) + dp(40)
            return block

        content.add_widget(create_section_header("Общие настройки"))
        ip_input = create_keyboard_input(self.config_data.get("device_ip", "192.168.1.39"))
        content.add_widget(create_setting_block("IP-адрес устройства:", ip_input))

        tts_block = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(4))
        lbl_tts = Label(
            text="Голосовой ответ:",
            font_size=sp(16),  # Используем sp()
            color=(0.85, 0.85, 0.85, 1),
            size_hint_y=None,
            height=dp(22),
            halign='center',
            valign='middle'
        )
        lbl_tts.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
        tts_block.add_widget(lbl_tts)

        is_tts = self.config_data.get("tts_enabled", True)
        btn_tts = Button(
            text="ВКЛ" if is_tts else "ВЫКЛ",
            background_normal='',
            background_color=(0.15, 0.17, 0.22, 1),
            size_hint=(1, None),
            height=dp(40),
            font_size=sp(12),  # Используем sp()
            bold=False,
            color=(1, 1, 1, 1)
        )
        btn_tts.bind(on_press=lambda instance: setattr(btn_tts, 'text', "ВЫКЛ" if btn_tts.text == "ВКЛ" else "ВКЛ"))
        tts_block.add_widget(btn_tts)
        tts_block.height = dp(22) + dp(4) + dp(40)
        content.add_widget(tts_block)

        content.add_widget(create_section_header("Блок 1: Фразы вызова (Команды)"))
        cmd_entries = {}
        cmd_items = [
            {"label": "Включить всё", "action": "all_on", "chid": None},
            {"label": "Выключить всё", "action": "all_off", "chid": None},
            {"label": "Запрос температуры", "action": "temp", "chid": None},
        ]

        for ch in self.config_data.get("channels", []):
            cmd_items.append({
                "label": f"Переключить {ch.get('name', 'Лампу')}",
                "action": "toggle",
                "chid": ch.get("id")
            })

        existing_cmds = self.config_data.get("voice_commands", [])

        for item in cmd_items:
            init_val = ""
            for ec in existing_cmds:
                if ec.get("action") == item["action"] and ec.get("channel_id") == item["chid"]:
                    init_val = ec.get("phrase", "")
                    break

            inp = create_voice_input(init_val)
            content.add_widget(create_setting_block(f"{item['label']}:", inp))
            cmd_entries[(item["action"], item["chid"])] = inp

        content.add_widget(create_section_header("Блок 2: Голосовые ответы"))
        resp_entries = {}
        resp_items = [
            {"label": "Ответ: Включить всё", "sub_action": "all_on", "chid": None},
            {"label": "Ответ: Выключить всё", "sub_action": "all_off", "chid": None},
        ]

        for ch in self.config_data.get("channels", []):
            ch_name = ch.get('name', 'Лампа')
            resp_items.append({"label": f"Ответ: Вкл {ch_name}", "sub_action": "on", "chid": ch.get("id")})
            resp_items.append({"label": f"Ответ: Выкл {ch_name}", "sub_action": "off", "chid": ch.get("id")})

        existing_resps = self.config_data.get("voice_responses", [])

        for item in resp_items:
            init_val = ""
            for er in existing_resps:
                if er.get("sub_action") == item["sub_action"] and er.get("channel_id") == item["chid"]:
                    init_val = er.get("response_text", "")
                    break

            inp = create_voice_input(init_val)
            content.add_widget(create_setting_block(f"{item['label']}:", inp))
            resp_entries[(item["sub_action"], item["chid"])] = inp

        layout.add_widget(scroll)

        btn_save = FixedButton(
            text="Сохранить настройки",
            bg_color=(0.18, 0.5, 0.25, 1),
            size_hint_y=None,
            height=dp(50),  # Адаптивная высота через dp
            font_size=sp(16)  # Адаптивный размер шрифта через sp
        )

        def save_settings_data(instance):
            app_ref = App.get_running_app()

            app_ref.config_data["device_ip"] = ip_input.text.strip()
            app_ref.config_data["tts_enabled"] = (btn_tts.text == "ВКЛ")

            updated_cmds = []
            for (action, chid), inp in cmd_entries.items():
                updated_cmds.append({"action": action, "channel_id": chid, "phrase": inp.text.strip()})
            app_ref.config_data["voice_commands"] = updated_cmds

            updated_resps = []
            for (sub_action, chid), resp_inp in resp_entries.items():
                updated_resps.append(
                    {"sub_action": sub_action, "channel_id": chid, "response_text": resp_inp.text.strip()})
            app_ref.config_data["voice_responses"] = updated_resps

            if hasattr(app_ref, 'save_config'):
                app_ref.save_config()
                print("[CONFIG] Настройки света успешно синхронизированы и сохранены!")
            else:
                try:
                    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
                    with open(config_path, "w", encoding="utf-8") as f:
                        json.dump(app_ref.config_data, f, ensure_ascii=False, indent=4)
                    print("[CONFIG] Настройки успешно сохранены!")
                except Exception as e:
                    print(f"[ОШИБКА СОХРАНЕНИЯ]: {e}")

            popup.dismiss()

        btn_save.bind(on_press=save_settings_data)
        layout.add_widget(btn_save)

        popup = Popup(
            title='',
            separator_height=0,
            background='',
            background_color=(0, 0, 0, 0),
            content=layout,
            size_hint=(0.95, 0.92),
            auto_dismiss=False
        )
        btn_back.bind(on_press=popup.dismiss)

        popup.open()


class ViewfinderOverlay(Widget):
    """Оверлей с центральным квадратом (зоной поиска для ИИ) и точкой"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(pos=self.update_canvas, size=self.update_canvas)

    def update_canvas(self, *args):
        self.canvas.clear()
        with self.canvas:
            Color(1, 1, 1, 0.8)

            # Размер квадрата (60% от меньшей стороны экрана)
            size_box = min(self.width, self.height) * 0.6
            cx, cy = self.center_x, self.center_y
            x = cx - size_box / 2
            y = cy - size_box / 2

            corner_len = dp(35)

            # Рисуем уголки квадрата зоны поиска
            Line(points=[x, y + size_box - corner_len, x, y + size_box, x + corner_len, y + size_box], width=dp(2))
            Line(points=[x + size_box - corner_len, y + size_box, x + size_box, y + size_box, x + size_box,
                         y + size_box - corner_len], width=dp(2))
            Line(points=[x, y + corner_len, x, y, x + corner_len, y], width=dp(2))
            Line(points=[x + size_box - corner_len, y, x + size_box, y, x + size_box, y + corner_len], width=dp(2))

            # Центральная точка прицела
            Color(1, 1, 1, 1)
            dot_size = dp(8)
            Ellipse(pos=(cx - dot_size / 2, cy - dot_size / 2), size=(dot_size, dot_size))


class RoundCaptureButton(Button):
    """Круглая полупрозрачная кнопка для снимка"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ''
        self.background_down = ''
        self.background_color = (0, 0, 0, 0)
        self.bind(pos=self.update_canvas, size=self.update_canvas)

    def update_canvas(self, *args):
        self.canvas.before.clear()
        with self.canvas.before:
            # Внешнее кольцо: полупрозрачный белый (альфа 0.6)
            Color(1, 1, 1, 0.6)
            self.outer_ring = Ellipse(pos=self.pos, size=self.size)

            padding = dp(4)
            # Внутренний круг: чуть более мягкий полупрозрачный белый (альфа 0.8) или 0.6
            Color(0.9, 0.9, 0.9, 0.6)
            self.inner_circle = Ellipse(
                pos=(self.x + padding, self.y + padding),
                size=(self.width - padding * 2, self.height - padding * 2)
            )

    def _update_elements(self, *args):
        padding = dp(4)
        self.outer_ring.pos = self.pos
        self.outer_ring.size = self.size
        self.inner_circle.pos = (self.x + padding, self.y + padding)
        self.inner_circle.size = (self.width - padding * 2, self.height - padding * 2)

# Выносим вспомогательный класс за пределы попапа (в начало файла)
# 1. Объявляем класс инпута снаружи, принимая callback-функцию
class TapTextInput(TextInput):
    def __init__(self, tap_callback=None, **kwargs):
        super().__init__(**kwargs)
        self.tap_callback = tap_callback

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            if self.tap_callback:
                self.tap_callback(self)  # Безопасно вызываем переданную функцию
            return True
        return super().on_touch_down(touch)


# Класс настроек ИИ-камеры, оформленный точно так же, как SystemSettingsPopup
class AICameraSettingsPopup(Popup):
    def __init__(self, camera_screen_ref, **kwargs):
        super().__init__(**kwargs)
        self.camera_screen_ref = camera_screen_ref

        layout = BoxLayout(orientation='vertical', padding=dp(15), spacing=dp(10), size_hint=(1, 1))

        with layout.canvas.before:
            Color(0.11, 0.13, 0.17, 1)  # Темный фон
            bg_rect = Rectangle(size=layout.size, pos=layout.pos)

        layout.bind(
            size=lambda inst, val: setattr(bg_rect, 'size', val),
            pos=lambda inst, val: setattr(bg_rect, 'pos', val)
        )

        # Шапка попапа
        top_bar = BoxLayout(
            size_hint_y=None,
            height=dp(50),
            spacing=dp(10),
            padding=[dp(10), dp(5), dp(10), dp(5)]
        )

        btn_back = FixedButton(
            text="Назад",
            bg_color=(0.2, 0.23, 0.3, 1),
            size_hint=(None, None),
            width=dp(80),
            height=dp(40),
            font_size=sp(14)
        )
        top_bar.add_widget(btn_back)

        lbl_title = Label(
            text="Настройки ИИ-камеры",
            font_size=sp(18),
            bold=True,
            color=(0.9, 0.9, 0.9, 1),
            halign='left',
            valign='middle'
        )
        lbl_title.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
        top_bar.add_widget(lbl_title)

        layout.add_widget(top_bar)

        # Контент прокрутки
        scroll = ScrollView(size_hint=(1, 1), do_scroll_x=False, do_scroll_y=True)
        content = BoxLayout(orientation='vertical', spacing=dp(14), size_hint_y=None,
                            padding=[dp(5), dp(5), dp(5), dp(5)])
        content.bind(minimum_height=content.setter('height'))
        scroll.add_widget(content)

        def create_section_header(text):
            lbl = Label(
                text=text,
                font_size=sp(17),
                bold=False,
                color=(0.3, 0.7, 1, 1),
                size_hint_y=None,
                height=dp(32),
                halign='center',
                valign='middle'
            )
            lbl.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
            return lbl

        # Функция голосового ввода для полей
        def start_voice_recording_for_input(text_input_instance):
            print(f"[VOICE INPUT] Ожидание голосового ввода для поля камеры...")

            orig_bg = text_input_instance.background_color
            text_input_instance.background_color = (0.25, 0.2, 0.4, 1)
            text_input_instance.text = "Запись..."

            app = App.get_running_app()
            assistant = None

            if app:
                for attr_name in ['assistant', 'voice_assistant', 'ai', 'voice']:
                    if hasattr(app, attr_name) and getattr(app, attr_name):
                        assistant = getattr(app, attr_name)
                        break

            if assistant or app:
                is_finished = [False]

                def reset_field_state():
                    if not is_finished[0]:
                        is_finished[0] = True
                        Clock.schedule_once(lambda dt: setattr(text_input_instance, 'background_color', orig_bg), 0)
                        if text_input_instance.text == "Запись...":
                            Clock.schedule_once(lambda dt: setattr(text_input_instance, 'text', ""), 0)

                        if assistant and hasattr(assistant, 'set_voice_input_target'):
                            try:
                                assistant.set_voice_input_target(None)
                            except Exception:
                                pass

                def on_phrase_recognized(recognized_text):
                    if is_finished[0]:
                        return
                    is_finished[0] = True

                    Clock.schedule_once(lambda dt: setattr(text_input_instance, 'text', recognized_text), 0)
                    Clock.schedule_once(lambda dt: setattr(text_input_instance, 'background_color', orig_bg), 0)
                    print(f"[VOICE INPUT SUCCESS] Записано: {recognized_text}")

                if assistant:
                    if hasattr(assistant, 'set_voice_input_target'):
                        assistant.set_voice_input_target(on_phrase_recognized)
                    assistant.voice_input_target = on_phrase_recognized

                if app:
                    app.voice_input_target = on_phrase_recognized

                Clock.schedule_once(lambda dt: reset_field_state(), 10.0)
            else:
                print("[VOICE INPUT ERROR] Ассистент не найден!")
                text_input_instance.background_color = orig_bg
                text_input_instance.text = ""

        # Выносим helper создания блока на уровень конструктора попапа
        def create_setting_block(label_text, input_widget):
            block = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(4))

            lbl = Label(
                text=label_text,
                font_size=sp(16),
                font_name='Roboto',
                bold=False,
                color=(0.85, 0.85, 0.85, 1),
                halign='center',
                valign='middle',
                size_hint_y=None,
                height=dp(22)
            )
            lbl.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
            block.add_widget(lbl)

            input_widget.size_hint_x = 1.0
            block.add_widget(input_widget)

            block.height = dp(22) + dp(4) + input_widget.height
            return block, input_widget

        self.inputs = {}
        app = App.get_running_app()
        config = getattr(app, 'config_data', {})

        content.add_widget(create_section_header("Параметры ИИ-камеры"))

        # 1. Многострочный инпут для промпта (без halign='center', так как он мультилинейный)
        prompt_input = TextInput(
            text=str(config.get('cam_prompt', "Что изображено в этой зоне поиска? Опиши кратко.")),
            multiline=True,
            size_hint_y=None,
            height=dp(70),
            font_size=sp(13),
            background_color=(0.15, 0.17, 0.22, 1),
            foreground_color=(1, 1, 1, 1),
            padding=[dp(8), dp(10), dp(8), dp(8)]
        )
        block, self.inputs['cam_prompt'] = create_setting_block("Промпт (запрос) для Gemini Vision:", prompt_input)
        content.add_widget(block)

        # 2. Интерактивный инпут для ключевого слова с поддержкой тапа/голосового ввода
        wake_input = TapTextInput(
            text=str(config.get('wake_word_cam', "снимок")),
            multiline=False,
            size_hint_y=None,
            height=dp(40),
            font_size=sp(13),
            background_color=(0.15, 0.17, 0.22, 1),
            foreground_color=(1, 1, 1, 1),
            halign='center',
            padding=[dp(8), dp(10), dp(8), dp(8)]
        )
        wake_input.hint_text = "Нажмите, чтобы записать голосом"

        block, self.inputs['wake_word_cam'] = create_setting_block("Ключевое слово для авто-снимка:", wake_input)
        content.add_widget(block)

        layout.add_widget(scroll)

        # Кнопка сохранения снизу
        btn_save = FixedButton(
            text="Сохранить настройки",
            bg_color=(0.18, 0.5, 0.25, 1),
            size_hint_y=None,
            height=dp(50),
            font_size=sp(16)
        )
        btn_save.bind(on_press=self.save_settings_data)
        layout.add_widget(btn_save)

        self.title = ''
        self.separator_height = 0
        self.background = ''
        self.background_color = (0, 0, 0, 0)
        self.content = layout
        self.size_hint = (0.95, 0.85)
        self.auto_dismiss = False

        btn_back.bind(on_press=self.dismiss)

    def save_settings_data(self, instance):
        raw_data = {k: v.text.strip() for k, v in self.inputs.items()}

        self.camera_screen_ref.ai_prompt = raw_data.get('cam_prompt',
                                                        "Что изображено в этой зоне поиска? Опиши кратко.")
        self.camera_screen_ref.ai_keyword = raw_data.get('wake_word_cam', "снимок")

        app = App.get_running_app()
        if hasattr(app, 'config_data') and isinstance(app.config_data, dict):
            app.config_data.update({
                "cam_prompt": self.camera_screen_ref.ai_prompt,
                "wake_word_cam": self.camera_screen_ref.ai_keyword
            })
            if hasattr(app, 'save_config'):
                app.save_config()

        print("[AI CAMERA SETTINGS SAVED]:", raw_data)
        self.dismiss()


class AICameraScreen(BaseScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # 0. ГАРАНТИРОВАННЫЙ ЧЕРНЫЙ ФОН ВСЕГО ЭКРАНА С ПЕРВОГО МИКРОКАДРА
        with self.canvas.before:
            Color(0, 0, 0, 1)
            self.screen_bg = Rectangle(size=self.size, pos=self.pos)
        self.bind(
            size=lambda inst, val: setattr(self.screen_bg, 'size', val),
            pos=lambda inst, val: setattr(self.screen_bg, 'pos', val)
        )

        # Переменная для сохранения последнего ответа ИИ (для кнопки "Повтор")
        self.last_ai_response = ""

        self.root_layout = FloatLayout()
        # ... (дальше идет ваш текущий код с cam_wrapper, img_feed, startup_cover и overlay)

        # 1. Слой видео с камеры: на Android используем Preview от Camera4Kivy
        if platform == 'android':
            if HAS_CAMERA4KIVY:
                # Создаем контейнер для камеры с черным фоном по умолчанию
                self.cam_wrapper = FloatLayout(size_hint=(1, 1))
                with self.cam_wrapper.canvas.before:
                    Color(0, 0, 0, 1)  # Черный фон для перекрытия белого моргания
                    self.cam_bg_rect = Rectangle(size=self.cam_wrapper.size, pos=self.cam_wrapper.pos)
                self.cam_wrapper.bind(
                    size=lambda inst, val: setattr(self.cam_bg_rect, 'size', val),
                    pos=lambda inst, val: setattr(self.cam_bg_rect, 'pos', val)
                )

                self.img_feed = Preview(
                    size_hint=(1, 1),
                    aspect_ratio='4:3',
                    letterbox_color=[0, 0, 0, 1]
                )

                # Поворот холста
                with self.img_feed.canvas.after:
                    from kivy.graphics import PushMatrix, PopMatrix, Rotate
                    PushMatrix()
                    self.cam_rot = Rotate(angle=90, origin=self.img_feed.center)
                with self.img_feed.canvas.after:
                    PopMatrix()

                def update_cam_rot(instance, *args):
                    self.cam_rot.origin = instance.center

                self.img_feed.bind(pos=update_cam_rot, size=update_cam_rot)

                # Кладем Preview внутрь черного контейнера
                self.cam_wrapper.add_widget(self.img_feed)
                self.root_layout.add_widget(self.cam_wrapper)

            else:
                self.img_feed = Camera(
                    play=False,
                    resolution=(-1, -1),
                    size_hint=(1, 1),
                    allow_stretch=True,
                    keep_ratio=False
                )
                self.root_layout.add_widget(self.img_feed)
        else:
            self.img_feed = Image(
                size_hint=(1, 1),
                allow_stretch=True,
                keep_ratio=False
            )

            # ЗАЩИТА ОТ БЕЛОЙ ВСПЫШКИ НА ПК:
            # Сразу создаем и подставляем черную текстуру в буфер
            from kivy.graphics.texture import Texture
            dummy_texture = Texture.create(size=(640, 480), colorfmt='rgb')
            black_buf = bytes([0] * (640 * 480 * 3))
            dummy_texture.blit_buffer(black_buf, colorfmt='rgb', bufferfmt='ubyte')
            self.img_feed.texture = dummy_texture

            self.root_layout.add_widget(self.img_feed)

        # 2. Черная шторка для маскировки белого моргания при старте
        if platform == 'android' and HAS_CAMERA4KIVY:
            self.startup_cover = Widget(size_hint=(1, 1))
            with self.startup_cover.canvas.before:
                Color(0, 0, 0, 1)
                self.cover_rect = Rectangle(size=self.startup_cover.size, pos=self.startup_cover.pos)
            self.startup_cover.bind(
                size=lambda inst, val: setattr(self.cover_rect, 'size', val),
                pos=lambda inst, val: setattr(self.cover_rect, 'pos', val)
            )
            self.root_layout.add_widget(self.startup_cover)

        # 3. Оверлей с центральным квадратом (зона поиска)
        self.overlay = ViewfinderOverlay(size_hint=(1, 1))
        self.root_layout.add_widget(self.overlay)

        # 4. ВЕРХНЯЯ ПАНЕЛЬ
        top_container = BoxLayout(
            orientation='vertical',
            size_hint=(1, None),
            height=dp(60),
            pos_hint={'top': 1}
        )
        with top_container.canvas.before:
            Color(0, 0, 0, 0.4)
            self.top_rect = Rectangle(size=top_container.size, pos=top_container.pos)
        top_container.bind(
            size=lambda inst, val: setattr(self.top_rect, 'size', val),
            pos=lambda inst, val: setattr(self.top_rect, 'pos', val)
        )

        top_bar = BoxLayout(size_hint=(1, 1), spacing=dp(10), padding=dp(10))

        btn_back = FixedButton(
            text="Назад", bg_color=(0.2, 0.23, 0.3, 1),
            size_hint=(None, None), width=dp(80), height=dp(40)
        )
        btn_back.bind(on_press=lambda x: setattr(self.manager, 'current', 'main'))
        top_bar.add_widget(btn_back)

        lbl_title = Label(
            text="ИИ Камера",
            font_size='18sp',
            bold=True,
            color=(0.9, 0.9, 0.9, 1),
            halign='center',
            valign='middle'
        )
        lbl_title.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
        top_bar.add_widget(lbl_title)

        btn_settings = Button(
            text="•\n•\n•",
            font_size='14sp',
            bold=True,
            line_height=0.5,
            halign='center',
            valign='middle',
            size_hint=(None, None),
            size=(dp(40), dp(40)),
            background_normal='',
            background_color=(0, 0, 0, 0),
            color=(1, 1, 1, 1),
            pos_hint={'center_y': 0.5}
        )
        btn_settings.bind(on_press=self.open_settings)
        top_bar.add_widget(btn_settings)

        top_container.add_widget(top_bar)
        self.root_layout.add_widget(top_container)

        # 5. НИЖНЯЯ ПАНЕЛЬ С КНОПКАМИ УПРАВЛЕНИЯ
        bottom_container = BoxLayout(
            orientation='vertical',
            size_hint=(1, None),
            height=dp(110),
            pos_hint={'bottom': 1}
        )
        with bottom_container.canvas.before:
            Color(0, 0, 0, 0.5)
            self.bottom_rect = Rectangle(size=bottom_container.size, pos=bottom_container.pos)
        bottom_container.bind(
            size=lambda inst, val: setattr(self.bottom_rect, 'size', val),
            pos=lambda inst, val: setattr(self.bottom_rect, 'pos', val)
        )

        bottom_bar = BoxLayout(
            orientation='horizontal',
            size_hint=(1, 1),
            padding=[dp(25), 0, dp(25), 0]
        )

        # --- Кнопка слева: ПОВТОР ---
        self.btn_repeat = Button(
            text="",
            size_hint=(None, None),
            size=(dp(55), dp(55)),
            pos_hint={'center_y': 0.5},
            background_normal="",
            background_color=(0, 0, 0, 0),
            color=(1, 1, 1, 1),
        )

        with self.btn_repeat.canvas.before:
            Color(0, 0, 0, 0.3)  # Полупрозрачная подложка
            self.repeat_bg = Ellipse(pos=self.btn_repeat.pos, size=self.btn_repeat.size)

        with self.btn_repeat.canvas:
            Color(1, 1, 1, 0.6)  # Полупрозрачная иконка треугольника
            self.repeat_triangle = Triangle(points=[0, 0, 0, 0, 0, 0])

        def update_repeat_graphics(instance, *args):
            self.repeat_bg.pos = instance.pos
            self.repeat_bg.size = instance.size
            self.repeat_triangle.points = [
                instance.x + instance.width * 0.38,
                instance.y + instance.height * 0.28,
                instance.x + instance.width * 0.38,
                instance.y + instance.height * 0.72,
                instance.x + instance.width * 0.72,
                instance.y + instance.height * 0.50,
            ]

        self.btn_repeat.bind(pos=update_repeat_graphics, size=update_repeat_graphics)
        self.btn_repeat.bind(on_press=lambda x: self.repeat_last_response())
        bottom_bar.add_widget(self.btn_repeat)

        bottom_bar.add_widget(Widget(size_hint_x=1))

        # --- Кнопка по центру: СНИМОК ---
        self.btn_capture = RoundCaptureButton(
            size_hint=(None, None),
            size=(dp(70), dp(70)),
            pos_hint={'center_y': 0.5}
        )

        # Если в классе RoundCaptureButton под капотом используются свои графические инструкции
        # с непрозрачным белым цветом, вы можете настроить его цвет через свойства или canvas:
        with self.btn_capture.canvas.after:
            Color(1, 1, 1, 0.6)  # Накладываем полупрозрачный фильтр поверх кнопки снимка

        self.btn_capture.bind(on_press=lambda x: self.capture_and_process_ai())
        bottom_bar.add_widget(self.btn_capture)

        bottom_bar.add_widget(Widget(size_hint_x=1))

        # --- Кнопка справа: ОТМЕНА ОЗВУЧКИ ---
        self.btn_stop_speech = Button(
            text="",
            size_hint=(None, None),
            size=(dp(55), dp(55)),
            pos_hint={'center_y': 0.5},
            background_normal="",
            background_color=(0, 0, 0, 0),
            color=(1, 1, 1, 1),
        )

        with self.btn_stop_speech.canvas.before:
            Color(0, 0, 0, 0.3)  # Полупрозрачная подложка
            self.stop_bg = Ellipse(pos=self.btn_stop_speech.pos, size=self.btn_stop_speech.size)

        with self.btn_stop_speech.canvas:
            Color(1, 1, 1, 0.6)  # Полупрозрачная иконка стоп
            self.stop_square = Rectangle(pos=(0, 0), size=(0, 0))

        def update_stop_graphics(instance, *args):
            self.stop_bg.pos = instance.pos
            self.stop_bg.size = instance.size

            sq_size = instance.width * 0.4
            sq_x = instance.center_x - sq_size / 2
            sq_y = instance.center_y - sq_size / 2

            self.stop_square.pos = (sq_x, sq_y)
            self.stop_square.size = (sq_size, sq_size)

        self.btn_stop_speech.bind(pos=update_stop_graphics, size=update_stop_graphics)
        self.btn_stop_speech.bind(on_press=lambda x: self.stop_speech())
        bottom_bar.add_widget(self.btn_stop_speech)

        bottom_container.add_widget(bottom_bar)
        self.root_layout.add_widget(bottom_container)

        self.add_widget(self.root_layout)

        self.capture = None
        self._texture = None

        app = App.get_running_app()
        cfg = getattr(app, 'config_data', {}) if app else {}
        self.ai_prompt = cfg.get('cam_prompt', "Что изображено в этой зоне поиска? Опиши кратко.")
        self.ai_keyword = cfg.get('wake_word_cam', "снимок")

    def open_settings(self, instance):
        AICameraSettingsPopup(camera_screen_ref=self).open()

    def on_enter(self):
        if platform == 'android':
            if HAS_CAMERA4KIVY:
                print("[AI CAMERA] Подключаем Camera4Kivy с filepath_callback")

                Clock.schedule_once(
                    lambda dt: self.img_feed.connect_camera(
                        camera_id='back',
                        filepath_callback=self.on_camera_photo_saved
                    ),
                    0.5
                )

                # Увеличиваем задержку до 1.5 секунд, чтобы камера точно перекрыла фон
                Clock.schedule_once(self.hide_startup_cover, 1.5)
            else:
                if hasattr(self.img_feed, 'play'):
                    self.img_feed.play = True
        else:
            try:
                self.capture = cv2.VideoCapture(0, cv2.CAP_ANY)
                if self.capture.isOpened():
                    Clock.schedule_interval(self.update_frame, 1.0 / 30.0)
            except Exception as e:
                print(f"[AI CAMERA EXCEPTION]: {e}")

    def hide_startup_cover(self, dt):
        if hasattr(self, 'startup_cover') and self.startup_cover:
            # Вместо удаления из дерева виджетов просто плавно или мгновенно скрываем через прозрачность
            self.startup_cover.opacity = 0
            print("[AI CAMERA] Черная шторка скрыта.")

    def update_frame(self, dt):
        if self.capture and self.capture.isOpened():
            ret, frame = self.capture.read()
            if ret and frame is not None:
                frame = cv2.flip(frame, 0)
                buf = frame.tobytes()
                h, w, _ = frame.shape

                if self._texture is None or self._texture.size != (w, h):
                    self._texture = Texture.create(size=(w, h), colorfmt='bgr')
                    self.img_feed.texture = self._texture

                self._texture.blit_buffer(buf, colorfmt='bgr', bufferfmt='ubyte')
                self.img_feed.canvas.ask_update()

    def on_leave(self):
        # ПРИ УХОДЕ с экрана сразу возвращаем шторку в непрозрачное состояние (черный цвет).
        # Теперь при следующем входе она будет черной с самого первого кадра!
        if hasattr(self, 'startup_cover'):
            self.startup_cover.opacity = 1

        if platform == 'android':
            if HAS_CAMERA4KIVY:
                self.img_feed.disconnect_camera()
            else:
                if hasattr(self.img_feed, 'play'):
                    self.img_feed.play = False
        else:
            Clock.unschedule(self.update_frame)
            self._texture = None
            if self.capture:
                try:
                    self.capture.release()
                except Exception:
                    pass
                self.capture = None

    @mainthread
    def capture_and_process_ai(self, *args):
        """Отправка команды на снимок (файл прилетит асинхронно в on_camera_photo_saved)"""
        if platform == 'android':
            if HAS_CAMERA4KIVY:
                try:
                    # Вызываем capture_photo — библиотека сама вызовет callback, когда запишет файл
                    self.img_feed.capture_photo(
                        location='private',
                        subdir='AI_Snapshots',
                        name='snapshot'
                    )
                    print("[AI CAMERA] Команда capture_photo отправлена")
                except Exception as e:
                    print(f"[AI CAMERA ERROR] Ошибка вызова capture_photo: {e}")
                    self.speak_text_safely("Не удалось сделать снимок")
            else:
                # Фоллбек для старого Camera виджета
                image_path = "snapshot_ai.jpg"
                texture = self.img_feed.texture
                if texture and PilImage:
                    img_pil = PilImage.frombytes(mode='rgba', size=texture.size, data=texture.pixels)
                    img_pil = img_pil.transpose(PilImage.FLIP_TOP_BOTTOM)
                    img_pil.save(image_path, format='JPEG')
                    self.process_and_send_image(image_path)
        else:
            # ПК версия с OpenCV
            image_path = "snapshot_ai.jpg"
            if not self.capture or not self.capture.isOpened():
                print("[AI CAMERA] Ошибка: Камера на ПК не активна")
                self.speak_text_safely("Не удалось сделать снимок")
                return

            ret, frame = self.capture.read()
            if not ret or frame is None:
                print("[AI CAMERA] Ошибка: Не удалось прочитать кадр")
                self.speak_text_safely("Не удалось сделать снимок")
                return
            cv2.imwrite(image_path, frame)
            self.process_and_send_image(image_path)

    def on_camera_photo_saved(self, filename):
        """Коллбек от camera4kivy: срабатывает, когда файл физически записан на диск"""
        print(f"[AI CAMERA] Файл успешно сохранен нативно: {filename}")
        if filename and os.path.exists(filename):
            image_path = "snapshot_ai.jpg"
            try:
                import shutil
                shutil.copy(filename, image_path)

                # Вырезаем центральную зону поиска через OpenCV
                img = cv2.imread(image_path)
                if img is not None:
                    h, w, _ = img.shape
                    box_size = int(min(h, w) * 0.6)
                    cx, cy = w // 2, h // 2
                    x1 = max(0, cx - box_size // 2)
                    y1 = max(0, cy - box_size // 2)
                    x2 = min(w, cx + box_size // 2)
                    y2 = min(h, cy + box_size // 2)

                    cropped_frame = img[y1:y2, x1:x2]
                    cv2.imwrite(image_path, cropped_frame)
                    print("[AI CAMERA] Зона поиска успешно вырезана.")

                self.process_and_send_image(image_path)
            except Exception as e:
                print(f"[AI CAMERA ERROR] Ошибка обработки кадра в коллбеке: {e}")
                self.speak_text_safely("Не удалось сделать снимок")
        else:
            print("[AI CAMERA ERROR] Получен пустой или несуществующий путь от коллбека")
            self.speak_text_safely("Не удалось сделать снимок")

    def process_and_send_image(self, image_path):
        self.speak_text_safely("Снимок сделан, анализирую область...")

        app = App.get_running_app()

        import threading
        def background_ai_task():
            try:
                prompt = getattr(self, 'ai_prompt', "Что изображено в этой зоне поиска? Опиши кратко.")

                # Вызываем вашу централизованную функцию отправки запроса с картинкой
                if hasattr(app, 'send_ai_request'):
                    response_text = app.send_ai_request(prompt, image_path=image_path)
                else:
                    response_text = "Ошибка: метод отправки ИИ не найден в приложении."

                print(f"[AI CAMERA] Ответ от ИИ получен: {response_text}")

                self.last_ai_response = response_text

                if response_text:
                    self.speak_text_safely(response_text)
                    if hasattr(self, 'show_ai_response'):
                        self.show_ai_response(response_text)
            except Exception as e:
                print(f"[AI CAMERA ERROR] Ошибка потока анализа: {e}")
                self.speak_text_safely("Ошибка при анализе снимка")

        threading.Thread(target=background_ai_task, daemon=True).start()

    def repeat_last_response(self):
        """Повторяет последний озвученный ответ ИИ"""
        if self.last_ai_response:
            print("[AI CAMERA] Повторяем последний ответ...")
            self.speak_text_safely(self.last_ai_response)
        else:
            print("[AI CAMERA] Нет сохраненного ответа для повтора")
            self.speak_text_safely("Сначала сделайте снимок")

    def stop_current_speech(self):
        """Делегируем остановку централизованному методу в SmartApp"""
        print("[AI CAMERA] Запрос остановки в SmartApp...")
        app = App.get_running_app()
        if app and hasattr(app, 'stop_current_speech'):
            app.stop_current_speech()
        else:
            # Запасной вариант, если вдруг app недоступен
            if hasattr(self, 'reset_assistant_state'):
                self.reset_assistant_state()

    def stop_speech(self):
        """Псевдоним для совместимости"""
        return self.stop_current_speech()

    def on_ai_button_pressed(self, instance):
        """Универсальный обработчик кнопки для камеры"""
        if getattr(self, 'is_speaking_now', False) or getattr(self, 'is_processing', False):
            print("[AI CAMERA] Прерывание процесса по клику на кнопку отмены.")
            self.stop_current_speech()
        else:
            if hasattr(self, 'set_processing_state'):
                self.set_processing_state()
            if hasattr(self, 'send_assistant_command'):
                self.send_assistant_command(instance)

    def speak_text_safely(self, text):
        app = App.get_running_app()
        if not app:
            print(f"[TTS MOCK]: {text}")
            return

        if not text or not str(text).strip():
            return

        cleaned_text = str(text)
        assistant = getattr(app, 'assistant', None) or getattr(app, 'voice_assistant', None)

        # 1. Очистка текста через ассистента, если доступно
        if assistant and hasattr(assistant, 'clean_text_for_tts') and callable(assistant.clean_text_for_tts):
            try:
                cleaned_text = assistant.clean_text_for_tts(text)
            except Exception as e:
                print(f"[TTS CLEAN ERROR]: {e}")

        # 2. Очистка от лишних символов (Markdown, звездочки, решетки)
        cleaned_text = re.sub(r'\*+', '', cleaned_text)
        cleaned_text = cleaned_text.replace('#', '')
        cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()

        if not cleaned_text:
            return

        # Устанавливаем флаги активности речи в приложении
        app.is_speaking_now = True
        app.is_processing = False

        # Определяем callback для автоматического сброса интерфейса по окончании речи
        def on_speech_finished():
            print("[TTS] Озвучка завершена естественным образом.")
            app.is_speaking_now = False
            app.is_processing = False

            # Безопасно сбрасываем интерфейс на текущем экране
            def reset_ui(dt):
                if hasattr(app, 'root') and app.root:
                    current_screen = getattr(app.root, 'current_screen', None)
                    if current_screen and hasattr(current_screen, 'reset_assistant_state'):
                        current_screen.reset_assistant_state()

            Clock.schedule_once(reset_ui, 0)

        spoken = False

        # 3. Пытаемся запустить озвучку, передавая callback
        for method_name in ['speak', 'speak_text', 'say']:
            target_obj = None
            if assistant and hasattr(assistant, method_name) and callable(getattr(assistant, method_name)):
                target_obj = assistant
            elif hasattr(app, method_name) and callable(getattr(app, method_name)):
                target_obj = app

            if target_obj:
                try:
                    print(f"[TTS SAFE] Запуск через {method_name}: {cleaned_text[:35]}...")
                    # Сразу передаем callback, так как ассистент его поддерживает
                    getattr(target_obj, method_name)(cleaned_text, on_done_callback=on_speech_finished)
                    spoken = True
                    break
                except Exception as e:
                    print(f"[TTS Method {method_name} Error]: {e}")

        if not spoken:
            print(f"[TTS MOCK]: {cleaned_text}")
            app.is_speaking_now = False
            on_speech_finished()



class PhoneSettingsScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        layout = FloatLayout()

        with layout.canvas.before:
            Color(0.11, 0.13, 0.17, 1)
            bg_rect = Rectangle(size=layout.size, pos=layout.pos)

        layout.bind(
            size=lambda inst, val: setattr(bg_rect, 'size', val),
            pos=lambda inst, val: setattr(bg_rect, 'pos', val)
        )

        top_bar = BoxLayout(
            size_hint=(1, None),
            height=dp(50),
            pos_hint={'top': 1},
            padding=[dp(10), 0, dp(10), 0],
            spacing=dp(10)
        )

        # Заменили на FixedButton для красивого стиля
        btn_back = FixedButton(
            text="Назад",
            bg_color=(0.2, 0.23, 0.3, 1),
            size_hint=(None, None),
            width=dp(80),
            height=dp(40),
            font_size=sp(14)
        )
        btn_back.bind(on_press=lambda x: setattr(self.manager, 'current', 'main'))
        top_bar.add_widget(btn_back)

        lbl_title = Label(
            text="Настройки ассистента звонков",
            font_size=sp(18),
            bold=True,
            color=(0.9, 0.9, 0.9, 1),
            halign='left',
            valign='middle'
        )
        lbl_title.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
        top_bar.add_widget(lbl_title)

        layout.add_widget(top_bar)

        scroll = ScrollView(
            size_hint=(1, 1),
            pos_hint={'top': 0.88, 'bottom': 0.12},
            do_scroll_x=False,
            do_scroll_y=True
        )

        content = BoxLayout(
            orientation='vertical',
            spacing=dp(14),
            size_hint_y=None,
            padding=[dp(15), dp(5), dp(15), dp(5)]
        )
        content.bind(minimum_height=content.setter('height'))
        scroll.add_widget(content)
        layout.add_widget(scroll)

        def create_section_header(text):
            lbl = Label(
                text=text,
                font_size=sp(17),
                bold=False,
                color=(0.3, 0.7, 1, 1),
                size_hint_y=None,
                height=dp(32),
                halign='center',
                valign='middle'
            )
            lbl.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
            return lbl

        def start_voice_recording_for_input(text_input_instance):
            app_ref = App.get_running_app()
            if not hasattr(app_ref, 'assistant') or not app_ref.assistant:
                text_input_instance.text = "Ошибка: ассистент не найден"
                return

            original_bg = text_input_instance.background_color
            text_input_instance.background_color = (0.25, 0.2, 0.4, 1)
            original_text = text_input_instance.text
            text_input_instance.text = "Слушаю..."

            if hasattr(app_ref, 'update_assistant_status'):
                app_ref.update_assistant_status("Запись в настройках...", color=(1.0, 0.6, 0.2, 1))

            def on_phrase_captured(phrase):
                text_input_instance.text = phrase if phrase else original_text
                text_input_instance.background_color = original_bg
                if hasattr(app_ref, 'update_assistant_status'):
                    app_ref.update_assistant_status("Ассистент: Ожидание...", color=(0.6, 0.6, 0.6, 1))

            app_ref.assistant.voice_input_target = on_phrase_captured

            def reset_timeout(dt):
                if getattr(app_ref.assistant, 'voice_input_target', None) == on_phrase_captured:
                    app_ref.assistant.voice_input_target = None
                    text_input_instance.text = original_text
                    text_input_instance.background_color = original_bg

            Clock.schedule_once(reset_timeout, 10)

        def create_voice_input(text=""):
            inp = TapTextInput(
                text=str(text),
                multiline=False,
                size_hint_y=None,
                height=dp(40),
                font_size=sp(13),
                readonly=True,
                background_color=(0.15, 0.17, 0.22, 1),
                foreground_color=(1, 1, 1, 1),
                halign='center',
                padding=[dp(8), dp(10), dp(8), dp(8)]
            )
            inp.tap_callback = start_voice_recording_for_input
            return inp

        def create_setting_block(label_text, input_widget):
            block = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(4))
            lbl = Label(
                text=label_text,
                font_size=sp(16),
                bold=False,
                color=(0.85, 0.85, 0.85, 1),
                halign='center',
                valign='middle',
                size_hint_y=None,
                height=dp(22)
            )
            lbl.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
            block.add_widget(lbl)
            input_widget.size_hint_x = 1.0
            block.add_widget(input_widget)
            block.height = dp(22) + dp(4) + dp(40)
            return block

        # Секция 1: Системные разрешения
        content.add_widget(create_section_header("Системные разрешения"))

        # Заменили на FixedButton
        btn_permission = FixedButton(
            text="Запросить разрешение на оверлей",
            bg_color=(0.25, 0.35, 0.5, 1),
            size_hint=(1, None),
            height=dp(45),
            font_size=sp(14)
        )
        btn_permission.bind(on_press=self.request_overlay_permission)
        content.add_widget(btn_permission)

        # Секция 2: Голосовые команды звонков
        content.add_widget(create_section_header("Голосовые команды звонков"))

        app_ref = App.get_running_app()
        config_data = getattr(app_ref, 'config_data', {})

        self.input_answer_word = create_voice_input(config_data.get("wake_word_answer", "алло"))
        content.add_widget(create_setting_block("Ключевое слово для ответа:", self.input_answer_word))

        self.input_reject_word = create_voice_input(config_data.get("wake_word_reject", "сброс"))
        content.add_widget(create_setting_block("Ключевое слово для сброса:", self.input_reject_word))

        # Секция 3: Голосовой набор (Исходящие)
        content.add_widget(create_section_header("Голосовой набор (Исходящие)"))

        self.input_call_word = create_voice_input(config_data.get("wake_word_call", "позвони"))
        content.add_widget(create_setting_block("Ключевая фраза для вызова:", self.input_call_word))

        self.input_cancel_word = create_voice_input(config_data.get("wake_word_call_cancel", "отмена"))
        content.add_widget(create_setting_block("Ключевая фраза для отмены:", self.input_cancel_word))

        # Кнопка сохранения — заменена на FixedButton
        btn_save = FixedButton(
            text="Сохранить настройки",
            bg_color=(0.18, 0.5, 0.25, 1),
            size_hint=(None, None),
            width=dp(320),
            height=dp(45),
            font_size=sp(16),
            pos_hint={'center_x': 0.5, 'y': 0.02}
        )
        btn_save.bind(on_press=self.save_settings_data)
        layout.add_widget(btn_save)

        self.add_widget(layout)

    def request_overlay_permission(self, instance):
        if platform == 'android':
            try:
                from jnius import autoclass
                PythonActivity = autoclass('org.kivy.android.PythonActivity')
                Settings = autoclass('android.provider.Settings')
                Intent = autoclass('android.content.Intent')
                Uri = autoclass('android.net.Uri')

                context = PythonActivity.mActivity
                if not Settings.canDrawOverlays(context):
                    intent = Intent(
                        Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                        Uri.parse("package:" + context.getPackageName())
                    )
                    context.startActivity(intent)
            except Exception as e:
                print(f"[PERMISSION ERROR]: {e}")
        else:
            print("[PC SIMULATION]: Запрос разрешения SYSTEM_ALERT_WINDOW (на ПК не требуется)")

    def save_settings_data(self, instance):
        app_ref = App.get_running_app()
        if not hasattr(app_ref, 'config_data'):
            app_ref.config_data = {}

        app_ref.config_data["wake_word_answer"] = self.input_answer_word.text.strip()
        app_ref.config_data["wake_word_reject"] = self.input_reject_word.text.strip()
        app_ref.config_data["wake_word_call"] = self.input_call_word.text.strip()
        app_ref.config_data["wake_word_call_cancel"] = self.input_cancel_word.text.strip()

        if hasattr(app_ref, 'save_config'):
            app_ref.save_config()
            print("[CONFIG] Настройки телефонии успешно сохранены!")
        else:
            try:
                config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(app_ref.config_data, f, ensure_ascii=False, indent=4)
                print("[CONFIG] Настройки телефонии сохранены в config.json!")
            except Exception as e:
                print(f"[ОШИБКА СОХРАНЕНИЯ]: {e}")

        # Обязательный возврат на главный экран после сохранения
        if self.manager:
            self.manager.current = 'main'


class PhoneAssistantManager:
    def __init__(self):
        self.is_waiting_for_call_target = False
        self.is_incoming_active = False  # Флаг входящего вызова для голосовых команд («алло» / «сброс»)
        self.is_waiting_for_number_choice = False  # Флаг ожидания выбора конкретного номера
        self.pending_choices = []  # Список найденных номеров для текущего контакта
        self.receiver = None
        self.app_instance = None

    def init_receiver(self, app_instance):
        """Регистрация динамического BroadcastReceiver с изоляцией в главный поток (Clock)"""
        self.app_instance = app_instance
        if platform == 'android':
            try:
                activity = PythonActivity.mActivity
                self.receiver = PhoneStateReceiver(
                    lambda state, num: Clock.schedule_once(lambda dt: self.handle_phone_state(state, num), 0)
                )

                intent_filter = IntentFilter()
                intent_filter.addAction(TelephonyManager.ACTION_PHONE_STATE_CHANGED)

                activity.registerReceiver(self.receiver, intent_filter)
                print("[TELEPHONY] Фоновый BroadcastReceiver успешно зарегистрирован!")
            except Exception as e:
                print(f"[TELEPHONY RECEIVER ERROR]: {e}")
        else:
            print("[PC SIMULATION] Инициализация симуляции слушателя звонков")

    def handle_phone_state(self, state, number):
        """Обработчик системных событий звонка (выполняется в главном потоке Kivy)"""
        if not self.app_instance:
            return

        if state == "ringing":
            self.is_incoming_active = True
            contact_name = self.get_contact_name_by_number(number)
            display_text = f"Входящий вызов: {contact_name}"
            print(f"[TELEPHONY EVENT] {display_text}")

            if hasattr(self.app_instance, 'show_incoming_call_ui'):
                self.app_instance.show_incoming_call_ui(contact_name, number)
            else:
                self.app_instance.update_current_screen_status(
                    f"{display_text} («Алло» / «Сброс»)",
                    color=(1.0, 0.5, 0.2, 1)
                )

            self.speak_text(f"Входящий вызов от абонента {contact_name}")

        elif state == "idle":
            self.is_incoming_active = False
            print("[TELEPHONY EVENT] Вызов завершен / сброшен")

            if hasattr(self.app_instance, 'hide_incoming_call_ui'):
                self.app_instance.hide_incoming_call_ui()
            else:
                self.app_instance.update_current_screen_status(
                    "Ассистент: Ожидание",
                    color=(0.6, 0.6, 0.6, 1)
                )

            self.cancel_call_waiting()

    def cancel_call_waiting(self):
        """Полный сброс всех состояний ожидания по команде 'отмена'"""
        self.is_waiting_for_call_target = False
        self.is_waiting_for_number_choice = False
        self.pending_choices = []
        print("[TELEPHONY] Режимы ожидания сброшены.")

    def get_phone_number_by_name(self, name_query):
        """Регистронезависимый поиск с возвратом списка для диалога выбора"""
        if not name_query:
            return ""

        phone_number = name_query.strip()
        digits_only = "".join([c for c in phone_number if c.isdigit()])
        if len(digits_only) >= 3:
            return phone_number  # Передан готовый номер телефона

        if platform == 'android':
            try:
                ContactsContract = autoclass('android.provider.ContactsContract$CommonDataKinds$Phone')
                context = PythonActivity.mActivity
                content_resolver = context.getContentResolver()

                uri = ContactsContract.CONTENT_URI
                projection = [
                    ContactsContract.DISPLAY_NAME,
                    ContactsContract.NUMBER,
                    ContactsContract.TYPE
                ]

                # Регистронезависимый поиск через LOWER()
                selection = f"LOWER({ContactsContract.DISPLAY_NAME}) LIKE ?"
                query_lower = f"%{name_query.lower()}%"
                selection_args = [query_lower]

                cursor = content_resolver.query(uri, projection, selection, selection_args, None)

                found_numbers = []
                if cursor:
                    while cursor.moveToNext():
                        name_idx = cursor.getColumnIndex(ContactsContract.DISPLAY_NAME)
                        num_idx = cursor.getColumnIndex(ContactsContract.NUMBER)
                        type_idx = cursor.getColumnIndex(ContactsContract.TYPE)

                        contact_name = cursor.getString(name_idx)
                        number = cursor.getString(num_idx)
                        num_type = cursor.getInt(type_idx)

                        # Расшифровываем тип номера
                        type_name = "мобильный"
                        if num_type == 1:
                            type_name = "домашний"
                        elif num_type == 2:
                            type_name = "мобильный"
                        elif num_type == 3:
                            type_name = "рабочий"

                        found_numbers.append({'name': contact_name, 'number': number, 'type_str': type_name})
                    cursor.close()

                if found_numbers:
                    # Уникализируем номера, чтобы избежать дублей
                    unique_dict = {item['number']: item for item in found_numbers}
                    found_numbers = list(unique_dict.values())

                    print(f"[CONTACTS] Найдено уникальных номеров для '{name_query}': {len(found_numbers)}")

                    if len(found_numbers) == 1:
                        return found_numbers[0]['number']
                    else:
                        # Сохраняем варианты для интерактивного выбора голосом
                        self.pending_choices = found_numbers
                        self.is_waiting_for_number_choice = True

                        types_desc = ", ".join([item['type_str'] for item in found_numbers])
                        prompt = f"У абонента {found_numbers[0]['name']} несколько номеров: {types_desc}. Какой набрать?"
                        print(f"[TELEPHONY CHOICE] {prompt}")
                        self.speak_text(prompt)
                        return None  # Ждем ответа пользователя по номеру
                else:
                    print(f"[CONTACTS] Контакт '{name_query}' не найден в записной книжке.")
            except Exception as e:
                print(f"[CONTACTS ERROR]: {e}")

        return phone_number

    def handle_number_choice(self, user_speech):
        """Обрабатывает ответ пользователя («мобильный», «рабочий», «первый»)"""
        if not self.is_waiting_for_number_choice or not self.pending_choices:
            return False

        speech_lower = user_speech.lower()
        selected_item = None

        # Проверяем тип номера
        for item in self.pending_choices:
            if item['type_str'] in speech_lower:
                selected_item = item
                break

        # Проверяем порядковый номер («первый», «второй»)
        if not selected_item:
            if "перв" in speech_lower and len(self.pending_choices) >= 1:
                selected_item = self.pending_choices[0]
            elif "втор" in speech_lower and len(self.pending_choices) >= 2:
                selected_item = self.pending_choices[1]

        if selected_item:
            self.is_waiting_for_number_choice = False
            choices_backup = self.pending_choices
            self.pending_choices = []
            self._start_call_action(selected_item['number'], selected_item['name'])
            return True
        else:
            self.speak_text("Не понял, какой номер набрать. Скажите: мобильный или рабочий.")
            return True

    def execute_outgoing_call(self, query_target):
        """Запуск исходящего вызова с проверкой контактов и озвучкой"""
        phone_number = self.get_phone_number_by_name(query_target)

        # Если сработал диалог выбора нескольких номеров, phone_number будет None — прерываем досрочно
        if self.is_waiting_for_number_choice:
            return

        if not phone_number or any(c.isalpha() for c in phone_number):
            error_msg = f"Контакт {query_target} не найден"
            print(f"[TELEPHONY ERROR] {error_msg}")
            self.speak_text(error_msg)
            if self.app_instance and hasattr(self.app_instance, 'update_current_screen_status'):
                self.app_instance.update_current_screen_status(error_msg, color=(1, 0.3, 0.3, 1))
            return

        contact_name = self.get_contact_name_by_number(phone_number)
        if not contact_name or contact_name == phone_number:
            contact_name = query_target

        self._start_call_action(phone_number, contact_name)

    def _start_call_action(self, phone_number, contact_name):
        """Фактический запуск набора номера"""
        print(f"[TELEPHONY] Набор номера: {contact_name} ({phone_number})")

        if self.app_instance and hasattr(self.app_instance, 'show_outgoing_call_ui'):
            self.app_instance.show_outgoing_call_ui(contact_name, phone_number)

        self.speak_text(f"Звоню абоненту {contact_name}")

        if platform == 'android':
            try:
                context = PythonActivity.mActivity
                intent = Intent(Intent.ACTION_CALL)
                intent.setData(Uri.parse(f"tel:{phone_number}"))
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)

                context.startActivity(intent)
                print(f"[CALL SUCCESS] ACTION_CALL запущен для {phone_number}")
            except Exception as e:
                print(f"[CALL ERROR (Проверьте разрешение CALL_PHONE)]: {e}")
        else:
            print(f"[PC SIMULATION] Имитация исходящего вызова на: {phone_number}")

    def answer_incoming_call(self):
        """Ответ на входящий вызов (TelecomManager + эмуляция гарнитуры HeadsetHook)"""
        print("[TELEPHONY] Ответ на входящий вызов...")
        self.is_incoming_active = False
        if platform == 'android':
            try:
                context = PythonActivity.mActivity
                telecom_manager = context.getSystemService(Context.TELECOM_SERVICE)
                if telecom_manager and hasattr(telecom_manager, 'acceptRingingCall'):
                    telecom_manager.acceptRingingCall()
                    print("[CALL SUCCESS] Вызов принят через TelecomManager")
                    return
            except Exception as e:
                print(f"[ANSWER TELECOM WARNING]: {e}")

            try:
                context = PythonActivity.mActivity
                down_intent = Intent(Intent.ACTION_MEDIA_BUTTON)
                down_intent.putExtra(Intent.EXTRA_KEY_EVENT,
                                     KeyEvent(KeyEvent.ACTION_DOWN, KeyEvent.KEYCODE_HEADSETHOOK))
                context.sendOrderedBroadcast(down_intent, None)

                up_intent = Intent(Intent.ACTION_MEDIA_BUTTON)
                up_intent.putExtra(Intent.EXTRA_KEY_EVENT, KeyEvent(KeyEvent.ACTION_UP, KeyEvent.KEYCODE_HEADSETHOOK))
                context.sendOrderedBroadcast(up_intent, None)
                print("[CALL SUCCESS] Сигнал ответа отправлен через HeadsetHook")
            except Exception as e:
                print(f"[ANSWER ERROR HEADSETHOOK]: {e}")
        else:
            print("[PC SIMULATION] Имитация ответа на звонок")

    def reject_incoming_call(self):
        """Сброс входящего вызова"""
        print("[TELEPHONY] Сброс входящего вызова...")
        self.is_incoming_active = False
        if platform == 'android':
            try:
                context = PythonActivity.mActivity
                telecom_manager = context.getSystemService(Context.TELECOM_SERVICE)
                if telecom_manager and hasattr(telecom_manager, 'endCall'):
                    telecom_manager.endCall()
                    print("[CALL SUCCESS] Вызов отклонен через TelecomManager")
                    return
            except Exception as e:
                print(f"[REJECT TELECOM WARNING]: {e}")

            try:
                context = PythonActivity.mActivity
                intent = Intent(Intent.ACTION_MEDIA_BUTTON)
                intent.putExtra(Intent.EXTRA_KEY_EVENT, KeyEvent(KeyEvent.ACTION_DOWN, KeyEvent.KEYCODE_ENDCALL))
                context.sendBroadcast(intent)
                print("[CALL SUCCESS] Сигнал сброса отправлен")
            except Exception as e:
                print(f"[REJECT ERROR]: {e}")
        else:
            print("[PC SIMULATION] Имитация сброса звонка")

    def get_contact_name_by_number(self, phone_number):
        """Определяет имя контакта по входящему номеру"""
        if not phone_number or platform != 'android':
            return phone_number

        try:
            ContactsContract = autoclass('android.provider.ContactsContract$PhoneLookup')
            context = PythonActivity.mActivity
            content_resolver = context.getContentResolver()

            uri = Uri.withAppendedPath(ContactsContract.CONTENT_FILTER_URI, Uri.encode(phone_number))
            projection = [ContactsContract.DISPLAY_NAME]

            cursor = content_resolver.query(uri, projection, None, None, None)
            if cursor and cursor.moveToFirst():
                name_idx = cursor.getColumnIndex(ContactsContract.DISPLAY_NAME)
                contact_name = cursor.getString(name_idx)
                cursor.close()
                return contact_name

            if cursor:
                cursor.close()
        except Exception as e:
            print(f"[CONTACTS LOOKUP ERROR]: {e}")

        return phone_number

    def speak_text(self, text):
        """Безопасная озвучка через plyer.tts"""
        cleaned_text = text
        if self.app_instance and hasattr(self.app_instance, 'clean_text_for_tts'):
            try:
                cleaned_text = self.app_instance.clean_text_for_tts(text)
            except Exception:
                pass

        print(f"[TELEPHONY SPEECH]: {cleaned_text}")
        if platform == 'android':
            try:
                from plyer import tts
                tts.speak(cleaned_text)
            except Exception as e:
                print(f"[TTS ERROR]: {e}")
        else:
            print(f"[PC SIMULATION SPEECH]: {cleaned_text}")



# Класс кликабельной картинки-кнопки
class ImageButton(ButtonBehavior, Image):
    pass


def show_incoming_call_ui(self, contact_name, number):
    # Закрываем старое окно, если оно уже висело
    self.hide_incoming_call_ui()

    # Основной контейнер с отступами
    content = BoxLayout(orientation='vertical', padding=dp(25), spacing=dp(15))

    # Рисуем полупрозрачный темный закругленный фон внутри попапа
    with content.canvas.before:
        Color(0.12, 0.12, 0.12, 0.9)
        self.bg_rect = RoundedRectangle(size=content.size, pos=content.pos, radius=[dp(20)])
    content.bind(pos=lambda *x: setattr(self.bg_rect, 'pos', content.pos),
                 size=lambda *x: setattr(self.bg_rect, 'size', content.size))

    # Текст с информацией о звонящем (сохраняем ссылку как self.call_status_lbl для таймера)
    self.call_status_lbl = Label(
        text=f"[b]Входящий вызов[/b]\n{contact_name}\n{number}",
        markup=True,
        font_size=sp(20),
        color=(1, 1, 1, 1),
        halign='center',
        valign='middle'
    )
    self.call_status_lbl.bind(size=lambda s, w: setattr(s, 'text_size', w))
    content.add_widget(self.call_status_lbl)

    # Блок для круглых кнопок
    btn_layout = BoxLayout(
        orientation='horizontal',
        size_hint_y=None,
        height=dp(75),
        spacing=dp(40)
    )
    btn_layout.padding = [dp(60), 0, dp(60), 0]

    # Зеленая кнопка ответа («Алло») -> принимает вызов и запускает таймер на экране
    accept_btn = ImageButton(
        source='green.png',
        size_hint=(None, None),
        size=(dp(70), dp(70))
    )
    accept_btn.bind(on_release=lambda x: [
        self.telephony.answer_incoming_call(),
        self.start_call_timer(self.call_status_lbl)
    ])

    # Красная кнопка сброса («Сброс») -> останавливает таймер, сбрасывает вызов и закрывает окно
    reject_btn = ImageButton(
        source='red.png',
        size_hint=(None, None),
        size=(dp(70), dp(70))
    )
    reject_btn.bind(on_release=lambda x: [
        self.stop_call_timer(),
        self.telephony.reject_incoming_call(),
        self.hide_incoming_call_ui()
    ])

    btn_layout.add_widget(accept_btn)
    btn_layout.add_widget(reject_btn)
    content.add_widget(btn_layout)

    # Сам Popup
    self.incoming_popup = Popup(
        title='',
        content=content,
        size_hint=(0.85, 0.42),
        auto_dismiss=False,
        separator_height=0,
        background=''
    )

    self.incoming_popup.background_color = (0, 0, 0, 0.6)
    self.incoming_popup.open()

class SmartApp(App):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.config_data = DEFAULT_CONFIG.copy()
        self.load_config()
        self.device_ip = self.config_data.get("device_ip", "192.168.1.39")
        self.lamp_objects = []
        self.assistant = None
        self.assistant_event = None
        # Подключаем вынесенный менеджер Live-диалога
        self.live_manager = GeminiLiveManager(self)
        # --- ПОДКЛЮЧАЕМ МЕНЕДЖЕР ТЕЛЕФОНИИ ---
        self.telephony = PhoneAssistantManager()

    @property
    def is_live_active(self):
        return self.live_manager.is_live_active

    @is_live_active.setter
    def is_live_active(self, value):
        self.live_manager.is_live_active = value

    def on_start(self):
        # Инициализируем голосового ассистента
        self.init_assistant()

        # Запускаем фоновое отслеживание звонков и регистрацию BroadcastReceiver
        if hasattr(self, 'telephony'):
            self.telephony.init_receiver(self)

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    self.config_data.update(loaded)
            except Exception as e:
                print(f"[CONFIG LOAD ERROR]: {e}")

    def save_config(self):
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.config_data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"[CONFIG SAVE ERROR]: {e}")

    def build(self):
        sm = ScreenManager()
        sm.add_widget(MainHubScreen(name='main'))
        sm.add_widget(SmartHomeScreen(name='smarthome'))
        sm.add_widget(AICameraScreen(name='ai_camera'))
        sm.add_widget(PhoneSettingsScreen(name='phone_settings'))

        # Инициализируем менеджер телефонии и запускаем фоновый прослушиватель звонков
        self.telephony = PhoneAssistantManager()
        self.telephony.init_receiver(self)

        return sm

    def process_voice_command(self, recognized_speech):
        """Централизованная обработка голосовых команд для телефонии и ассистента"""
        if not recognized_speech:
            return

        text = recognized_speech.lower()
        print(f"[VOICE COMMAND RECEIVED]: {text}")

        # 1. Приоритетная проверка команды «отмена» или «стоп»
        if any(word in text for word in ["отмена", "стоп", "хватит"]):
            if hasattr(self, 'telephony'):
                self.telephony.cancel_call_waiting()
                self.telephony.speak_text("Отменено")
            return

        # 2. Если ассистент ждет уточнения, какой именно номер набрать из нескольких
        if hasattr(self, 'telephony') and self.telephony.is_waiting_for_number_choice:
            self.telephony.handle_number_choice(text)
            return

        # 3. Если ассистент ждет имя контакта для исходящего звонка
        if hasattr(self, 'telephony') and self.telephony.is_waiting_for_call_target:
            self.telephony.execute_outgoing_call(text)
            self.telephony.is_waiting_for_call_target = False
            return

        # 4. Управление входящим вызовом голосом («алло» / «сброс»)
        if hasattr(self, 'telephony') and self.telephony.is_incoming_active:
            if any(word in text for word in ["алло", "принять", "ответ", "говори"]):
                self.telephony.answer_incoming_call()
                self.start_call_timer(self.call_status_lbl if hasattr(self, 'call_status_lbl') else None)
            elif any(word in text for word in ["сброс", "отбой", "положить", "не хочу"]):
                self.telephony.reject_incoming_call()
                self.hide_incoming_call_ui()
            return

    def start_call_timer(self, label_widget):
        """Запускает секундомер длительности вызова"""
        self.stop_call_timer()  # На всякий случай гасим старый таймер
        self.call_seconds = 0
        self.timer_label_ref = label_widget

        def update_timer(dt):
            self.call_seconds += 1
            mins = self.call_seconds // 60
            secs = self.call_seconds % 60
            if self.timer_label_ref and hasattr(self.timer_label_ref, 'text'):
                self.timer_label_ref.text = f"[b]Соединение установлено[/b]\n{mins:02d}:{secs:02d}"

        self.timer_event = Clock.schedule_interval(update_timer, 1)

    def stop_call_timer(self):
        """Останавливает секундомер вызова"""
        if hasattr(self, 'timer_event') and self.timer_event:
            self.timer_event.cancel()
            self.timer_event = None
        self.timer_label_ref = None

    def show_incoming_call_ui(self, contact_name, number):
        # Гарантированно закрываем старое окно и останавливаем таймер
        self.hide_incoming_call_ui()

        content = BoxLayout(orientation='vertical', padding=dp(25), spacing=dp(15))

        from kivy.graphics import Color, RoundedRectangle
        with content.canvas.before:
            Color(0.12, 0.12, 0.12, 0.9)
            self.bg_rect = RoundedRectangle(size=content.size, pos=content.pos, radius=[dp(20)])
        content.bind(pos=lambda *x: setattr(self.bg_rect, 'pos', content.pos),
                     size=lambda *x: setattr(self.bg_rect, 'size', content.size))

        self.call_status_lbl = Label(
            text=f"[b]Входящий вызов[/b]\n{contact_name}\n{number}",
            markup=True,
            font_size=sp(20),
            color=(1, 1, 1, 1),
            halign='center',
            valign='middle'
        )
        self.call_status_lbl.bind(size=lambda s, w: setattr(s, 'text_size', w))
        content.add_widget(self.call_status_lbl)

        btn_layout = BoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(75),
            spacing=dp(40)
        )
        btn_layout.padding = [dp(60), 0, dp(60), 0]

        accept_btn = ImageButton(
            source='green.png',
            size_hint=(None, None),
            size=(dp(70), dp(70))
        )
        accept_btn.bind(on_release=lambda x: [
            self.telephony.answer_incoming_call(),
            self.start_call_timer(self.call_status_lbl)
        ])

        reject_btn = ImageButton(
            source='red.png',
            size_hint=(None, None),
            size=(dp(70), dp(70))
        )
        reject_btn.bind(on_release=lambda x: [
            self.stop_call_timer(),
            self.telephony.reject_incoming_call(),
            self.hide_incoming_call_ui()
        ])

        btn_layout.add_widget(accept_btn)
        btn_layout.add_widget(reject_btn)
        content.add_widget(btn_layout)

        self.incoming_popup = Popup(
            title='',
            content=content,
            size_hint=(0.85, 0.42),
            auto_dismiss=False,
            separator_height=0,
            background=''
        )
        self.incoming_popup.background_color = (0, 0, 0, 0.6)
        self.incoming_popup.open()

    def show_outgoing_call_ui(self, contact_name, number):
        """Окно исходящего вызова внутри приложения"""
        self.hide_incoming_call_ui()
        content = BoxLayout(orientation='vertical', padding=dp(25), spacing=dp(15))

        from kivy.graphics import Color, RoundedRectangle
        with content.canvas.before:
            Color(0.12, 0.12, 0.12, 0.95)
            self.bg_rect = RoundedRectangle(size=content.size, pos=content.pos, radius=[dp(20)])
        content.bind(pos=lambda *x: setattr(self.bg_rect, 'pos', content.pos),
                     size=lambda *x: setattr(self.bg_rect, 'size', content.size))

        self.call_status_lbl = Label(
            text=f"[b]Исходящий вызов[/b]\n{contact_name}\n{number}",
            markup=True,
            font_size=sp(20),
            color=(1, 1, 1, 1),
            halign='center',
            valign='middle'
        )
        self.call_status_lbl.bind(size=lambda s, w: setattr(s, 'text_size', w))
        content.add_widget(self.call_status_lbl)

        btn_layout = BoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(75),
            spacing=dp(40)
        )
        btn_layout.padding = [dp(110), 0, dp(110), 0]

        reject_btn = ImageButton(
            source='red.png',
            size_hint=(None, None),
            size=(dp(70), dp(70))
        )
        # Исправлено: при сбросе исходящего вызова вызываем reject_incoming_call (или endCall), чтобы прервать набор
        reject_btn.bind(on_release=lambda x: [
            self.stop_call_timer(),
            self.telephony.reject_incoming_call(),
            self.hide_incoming_call_ui()
        ])

        btn_layout.add_widget(reject_btn)
        content.add_widget(btn_layout)

        self.incoming_popup = Popup(
            title='',
            content=content,
            size_hint=(0.85, 0.42),
            auto_dismiss=False,
            separator_height=0,
            background=''
        )
        self.incoming_popup.background_color = (0, 0, 0, 0.6)
        self.incoming_popup.open()

        # Автоматически запускаем таймер на исходящем вызове
        self.start_call_timer(self.call_status_lbl)

    def hide_incoming_call_ui(self):
        self.stop_call_timer()
        if hasattr(self, 'incoming_popup') and self.incoming_popup:
            try:
                self.incoming_popup.dismiss()
            except Exception as e:
                print(f"[POPUP ERROR]: {e}")
            self.incoming_popup = None

    def handle_user_query(self, query):
        # Показываем статус "Думаю..." через метод моста
        self.update_current_screen_status("Думаю...", (0.2, 0.7, 0.9, 1))
        # Запускаем сетевой запрос в фоновом потоке
        threading.Thread(target=self._send_to_ai_background, args=(query,), daemon=True).start()

    def _send_to_ai_background(self, query):
        try:
            ai_data = self.init_ai_client()
            if not ai_data or ai_data.get("provider") != "gemini":
                Clock.schedule_once(lambda dt: self.show_ai_response("Ошибка: ИИ клиент не настроен"))
                return

            client = ai_data["client"]
            models_to_try = ai_data.get("models_to_try", [ai_data["text_model"]])

            response_text = None
            for model_name in models_to_try:
                try:
                    print(f"[AI REQUEST] Запрос к модели: {model_name}")
                    response = client.models.generate_content(
                        model=model_name,
                        contents=query,
                    )
                    if response and response.text:
                        response_text = response.text.strip()
                        break
                except Exception as mod_err:
                    print(f"[AI WARNING] Модель {model_name} не ответила: {mod_err}")
                    continue

            if response_text:
                Clock.schedule_once(lambda dt: self.show_ai_response(response_text))
            else:
                Clock.schedule_once(lambda dt: self.show_ai_response("Ошибка: сервер ИИ перегружен"))

        except Exception as e:
            print("[AI ERROR]:", e)
            Clock.schedule_once(lambda dt: self.show_ai_response("Ошибка связи с ИИ"))

    def show_ai_response(self, text):
        self.update_current_screen_status(text, (0.2, 0.85, 0.3, 1))
        if hasattr(self, 'reset_session_timer'):
            self.reset_session_timer()

    def init_ai_client(self):
        """Финальная стабильная инициализация клиента с поддержкой автоперебора и памяти"""
        try:
            config = getattr(self, 'config_data', {})
            api_key = config.get('ai_api_key', '') or os.environ.get("GEMINI_API_KEY", "")

            if not api_key:
                print("[AI ERROR] API-ключ не найден в конфигурации.")
                return None

            # Приоритет модели из конфига/памяти, с актуальным дефолтом вместо устаревшей 3.8
            preferred_model = config.get('gemini_model_name',
                                         config.get('ai_model_name', config.get('ai_model', 'gemini-2.0-flash')))
            live_model_name = config.get('gemini_live_model_name', config.get('ai_live_model_name', 'gemini-2.0-flash'))

            class SimpleGenerativeService:
                def __init__(self, key, app_instance):
                    self.api_key = key
                    self.app = app_instance

                def _is_cancelled(self):
                    current_screen = getattr(self.app, 'root', None)
                    if hasattr(current_screen, 'is_processing') and not current_screen.is_processing:
                        return True
                    return False

                def generate_content_stream(self, model, contents, **kwargs):
                    m_name = model.replace("models/", "")
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{m_name}:generateContent?key={self.api_key}"

                    parts_list = []
                    items = contents if isinstance(contents, list) else [contents]

                    for item in items:
                        if hasattr(item, "save") and hasattr(item, "format"):
                            try:
                                buffered = BytesIO()
                                img_format = item.format if item.format in ["JPEG", "PNG", "WEBP", "GIF"] else "JPEG"
                                item.save(buffered, format=img_format)
                                img_bytes = buffered.getvalue()
                                img_base64 = base64.b64encode(img_bytes).decode("utf-8")
                                mime_type = f"image/{img_format.lower()}"

                                parts_list.append({
                                    "inline_data": {
                                        "mime_type": mime_type,
                                        "data": img_base64
                                    }
                                })
                                continue
                            except Exception as img_err:
                                print(f"[AI WARNING] Не удалось обработать PIL Image: {img_err}")

                        text_val = ""
                        if hasattr(item, "text"):
                            text_val = str(item.text)
                        elif hasattr(item, "parts"):
                            text_val = " ".join([p.text for p in item.parts if hasattr(p, "text")])
                        else:
                            text_val = str(item)

                        if text_val.strip():
                            parts_list.append({"text": text_val})

                    if not parts_list:
                        parts_list = [{"text": "Проанализируй это."}]

                    payload = {
                        "contents": [{
                            "parts": parts_list
                        }]
                    }

                    max_retries = 3
                    delay = 1.5

                    class StreamChunk:
                        def __init__(self, text):
                            self.text = text

                    for attempt in range(max_retries):
                        if self._is_cancelled():
                            print("[AI] Запрос прерван пользователем.")
                            return

                        try:
                            # Заменено с httpx на requests
                            response = requests.post(url, json=payload, timeout=8.0)

                            if response.status_code == 200:
                                data = response.json()
                                candidates = data.get("candidates", [])
                                if candidates:
                                    parts = candidates[0].get("content", {}).get("parts", [])
                                    for p in parts:
                                        if "text" in p:
                                            yield StreamChunk(p["text"])

                                            # --- ЖЕСТКАЯ АВТОМАТИЧЕСКАЯ ЗАПИСЬ НА ДИСК И В ПАМЯТЬ ---
                                            try:
                                                cfg_path = "config.json"
                                                file_data = {}
                                                if os.path.exists(cfg_path):
                                                    with open(cfg_path, 'r', encoding='utf-8') as f:
                                                        file_data = json.load(f)

                                                # Обновляем все ключи моделей на рабочую победительницу
                                                file_data['ai_model_name'] = m_name
                                                file_data['gemini_model_name'] = m_name
                                                provider = file_data.get('ai_provider', 'gemini').strip().lower()
                                                file_data[f"{provider}_model_name"] = m_name

                                                with open(cfg_path, 'w', encoding='utf-8') as f:
                                                    json.dump(file_data, f, ensure_ascii=False, indent=4)

                                                # СРАЗУ ОБНОВЛЯЕМ ПАМЯТЬ ПРИЛОЖЕНИЯ БЕЗ ПЕРЕЗАПУСКА
                                                if hasattr(self, 'app') and hasattr(self.app, 'config_data'):
                                                    self.app.config_data.update(file_data)

                                                print(
                                                    f"[AI AUTO-MEMORY] Модель '{m_name}' записана на диск и обновлена в памяти!")
                                            except Exception as save_err:
                                                print(f"[AI AUTO-MEMORY ERROR]: {save_err}")
                                            # --------------------------------------------------------
                                return
                            elif response.status_code in [503, 504, 429] and attempt < max_retries - 1:
                                print(
                                    f"[AI] Модель {m_name} перегружена ({response.status_code}), попытка {attempt + 1}. Ждем {delay}с...")
                                for _ in range(int(delay * 10)):
                                    if self._is_cancelled():
                                        return
                                    time.sleep(0.1)
                                delay *= 2
                                continue
                            else:
                                raise RuntimeError(f"API Error {response.status_code}: {response.text}")

                        except (requests.Timeout, requests.ConnectionError) as net_err:
                            if attempt < max_retries - 1:
                                for _ in range(int(delay * 10)):
                                    if self._is_cancelled():
                                        return
                                    time.sleep(0.1)
                                delay *= 2
                                continue
                            raise net_err

                def generate_content(self, model, contents, **kwargs):
                    full_text = ""
                    for chunk in self.generate_content_stream(model, contents, **kwargs):
                        if hasattr(chunk, 'text') and chunk.text:
                            full_text += chunk.text

                    class DummyResponse:
                        def __init__(self, text):
                            self.text = text

                    return DummyResponse(full_text)

            service = SimpleGenerativeService(api_key, self)

            class SimpleModelInfo:
                def __init__(self, name):
                    self.name = name

            class SimpleModelsAPI:
                def __init__(self, key):
                    self.api_key = key

                def list(self):
                    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={self.api_key}"
                    try:
                        # Заменено с httpx на requests.get
                        response = requests.get(url, timeout=10.0)
                        if response.status_code == 200:
                            data = response.json()
                            models_list = []
                            for m in data.get("models", []):
                                m_name = m.get("name", "").replace("models/", "")
                                if m_name:
                                    models_list.append(SimpleModelInfo(m_name))
                            return models_list
                    except Exception as e:
                        print(f"[AI] Ошибка запроса списка моделей: {e}")
                    return [SimpleModelInfo(preferred_model), SimpleModelInfo("gemini-flash-latest")]

            class FullClientMock:
                def __init__(self, key, app_instance):
                    self.api_key = key
                    self.models = SimpleModelsAPI(key)
                    self.models.generate_content_stream = service.generate_content_stream
                    self.models.generate_content = service.generate_content

            client = FullClientMock(api_key, self)

            # Формируем список моделей, ставя сохраненную в конфиге на первое место
            models_to_try = [preferred_model]
            try:
                for model_info in client.models.list():
                    m_name = model_info.name.replace("models/", "") if hasattr(model_info, 'name') else str(model_info)
                    m_lower = m_name.lower()

                    if "gemini" in m_lower and m_name not in models_to_try:
                        if any(bad in m_lower for bad in
                               ["live", "tts", "audio", "embed", "imagen", "image", "2.5", "2-5"]):
                            continue
                        models_to_try.append(m_name)
            except Exception as list_err:
                print(f"[AI] Ошибка сбора динамического списка: {list_err}")

            if not models_to_try:
                models_to_try = [preferred_model, "gemini-flash-latest"]

            return {
                "client": client,
                "text_model": preferred_model,
                "models_to_try": models_to_try,
                "live_model": live_model_name,
                "provider": "gemini"
            }
        except Exception as e:
            print(f"[AI INIT ERROR]: {e}")
            return None

    def send_ai_request(self, prompt, image_path=None):
        """Централизованная функция с динамическим умным перебором моделей через чистый REST API"""
        try:
            app = App.get_running_app()

            # 1. Получаем API-ключ
            api_key = None
            if hasattr(app, 'config_data') and app.config_data:
                api_key = app.config_data.get('gemini_api_key') or app.config_data.get('api_key')
            if not api_key and hasattr(app, 'api_key'):
                api_key = app.api_key

            if not api_key:
                print("[AI ERROR] API-ключ не найден в конфигурации.")
                return "Ошибка: проверьте API ключ в настройках."

            # 2. УМНЫЙ ДИНАМИЧЕСКИЙ ПЕРЕБОР МОДЕЛЕЙ (как у вас было задумано)
            ai_data = app.init_ai_client() if hasattr(app, 'init_ai_client') else None
            saved_preferred_model = app.config_data.get('gemini_model_name', 'gemini-2.0-flash') if hasattr(app,
                                                                                                            'config_data') else 'gemini-2.0-flash'

            # Базовый список на случай, если динамический еще не подгрузился
            models_to_try = [saved_preferred_model, "gemini-2.0-flash", "gemini-1.5-flash"]

            if ai_data and isinstance(ai_data, dict):
                fetched_models = ai_data.get("models_to_try", [])
                if fetched_models:
                    # Фильтруем серверный список: убираем старые версии (3.8, 2.5 и т.д.)
                    filtered_models = [m for m in fetched_models if "3.8" not in m and "2.5" not in m]
                    # Формируем умный порядок: сначала любимая модель, затем остальные уникальные из сети
                    models_to_try = [saved_preferred_model] + [m for m in filtered_models if m != saved_preferred_model]

            # Убираем дубликаты из списка моделей, сохраняя порядок
            models_to_try = list(dict.fromkeys(models_to_try))
            print(f"[AI DYNAMIC MODELS] Список для перебора: {models_to_try}")

            # 3. Подготовка содержимого запроса (поддержка текста и картинок)
            parts = [{"text": prompt}]

            if image_path:
                print(f"[AI REQUEST] Чтение изображения {image_path} для Vision-запроса...")
                try:
                    # Определяем MIME-тип по расширению файла (надежно и без imghdr)
                    ext = image_path.lower().split('.')[-1]
                    mime_map = {
                        'jpg': 'image/jpeg',
                        'jpeg': 'image/jpeg',
                        'png': 'image/png',
                        'webp': 'image/webp',
                        'heic': 'image/heic',
                        'heif': 'image/heif'
                    }
                    mime_type = mime_map.get(ext, 'image/jpeg')

                    with open(image_path, "rb") as img_file:
                        img_bytes = img_file.read()
                        img_b64 = base64.b64encode(img_bytes).decode('utf-8')

                    parts.append({
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": img_b64
                        }
                    })
                except Exception as img_err:
                    print(f"[AI IMAGE ERROR]: {img_err}")

            response_text = None

            # 4. Перебираем модели через чистый REST API
            for model_name in models_to_try:
                try:
                    clean_model = model_name.replace("models/", "")
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:generateContent?key={api_key}"

                    headers = {'Content-Type': 'application/json'}
                    payload = {
                        "contents": [{
                            "parts": parts
                        }]
                    }

                    print(f"[AI REST REQUEST] Запрос к модели: {clean_model}")
                    response = requests.post(url, headers=headers, json=payload, timeout=25)

                    if response.status_code == 200:
                        data = response.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            content = candidates[0].get("content", {})
                            resp_parts = content.get("parts", [])
                            if resp_parts:
                                response_text = resp_parts[0].get("text", "").strip()
                                print(f"[AI REST REQUEST] Успешный ответ от модели: {clean_model}")

                                # Автоматически обновляем поле модели в настройках, если они открыты
                                try:
                                    current_screen = getattr(app, 'root', None)
                                    if hasattr(current_screen, 'current_screen'):
                                        active_scr = current_screen.current_screen
                                        if hasattr(active_scr, 'inputs') and 'ai_model_name' in active_scr.inputs:
                                            active_scr.inputs['ai_model_name'].text = clean_model
                                            print("[UI] Поле модели в настройках обновлено!")
                                except Exception as ui_err:
                                    print(f"[UI UPDATE DEBUG]: {ui_err}")

                                break
                    else:
                        print(f"[AI WARNING] Модель {clean_model} вернула код {response.status_code}: {response.text}")

                except Exception as mod_err:
                    print(f"[AI WARNING] Ошибка запроса к модели {model_name}: {mod_err}")
                    continue

            return response_text or "Не удалось получить ответ от сервера ИИ."

        except Exception as e:
            print(f"[AI CRITICAL ERROR]: {e}")
            traceback.print_exc()
            return None

    def init_assistant(self):
        if getattr(self, '_assistant_initializing', False) or self.assistant:
            return
        self._assistant_initializing = True

        try:
            if not self.assistant:
                self.assistant = VoiceAssistant(self, self.lamp_objects)
                self.start_assistant_tick()
        finally:
            self._assistant_initializing = False

    def start_assistant_tick(self):
        if self.assistant_event:
            self.assistant_event.cancel()

        if self.assistant:
            self.assistant_event = Clock.schedule_interval(
                self.assistant.check_activity_timeout, ASSISTANT_TICK_INTERVAL
            )

    def stop_assistant_tick(self):
        if self.assistant_event:
            self.assistant_event.cancel()
            self.assistant_event = None

    def update_assistant_status(self, text, color=None):
        def update_ui(dt):
            sm = self.root
            if sm and hasattr(sm, 'current'):
                current_screen_name = sm.current
                if sm.has_screen(current_screen_name):
                    screen = sm.get_screen(current_screen_name)
                    if screen and hasattr(screen, 'update_assistant_status'):
                        if color:
                            screen.update_assistant_status(text, color=color)
                        else:
                            screen.update_assistant_status(text)

        Clock.schedule_once(update_ui, 0)

    @mainthread
    def update_current_screen_status(self, text, color=(0.2, 0.85, 0.3, 1)):
        try:
            sm = self.root
            if sm and hasattr(sm, 'current') and sm.has_screen(sm.current):
                screen = sm.get_screen(sm.current)
                if screen and hasattr(screen, 'update_assistant_status'):
                    current_ui_text = getattr(screen, '_last_applied_status', '')
                    if current_ui_text == text:
                        return
                    screen._last_applied_status = text
                    screen.update_assistant_status(text, color=color)
        except Exception as e:
            print(f"[BRIDGE EXCEPTION]: {e}")

    def update_temperature_ui(self, temp_str):
        def update_ui(dt):
            sm = self.root
            if sm and sm.has_screen('smarthome'):
                sm.get_screen('smarthome').temp_label.text = f"Температура: {temp_str} °C"

        Clock.schedule_once(update_ui, 0)

    def stop_current_speech(self):
        """Единая и чистая точка остановки (для класса SmartApp)"""
        print("[SmartApp] Нажата кнопка 'Стоп'")

        # 1. Находим ассистента и вызываем его метод stop()
        assistant = getattr(self, 'assistant', None) or getattr(self, 'voice_assistant', None)
        if assistant and hasattr(assistant, 'stop'):
            assistant.stop()

        # 2. Сбрасываем глобальные флаги приложения
        self.is_processing = False
        self.is_speaking_now = False

        # 3. Принудительно сбрасываем интерфейс на текущем активном экране (например, в камере)
        if hasattr(self, 'root') and self.root:
            current_screen = getattr(self.root, 'current_screen', None)
            if current_screen and hasattr(current_screen, 'reset_assistant_state'):
                current_screen.reset_assistant_state()
                current_screen.is_processing = False
                current_screen.is_speaking_now = False

        print("[SmartApp] Озвучка и интерфейс успешно сброшены.")

    def turn_all_on(self):
        for lamp in self.lamp_objects:
            lamp.turn_on()

    def turn_all_off(self):
        for lamp in self.lamp_objects:
            lamp.turn_off()


if __name__ == '__main__':
    SmartApp().run()
