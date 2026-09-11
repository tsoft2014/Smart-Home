import os
import json
import re
import threading
import time
import requests

from kivy.config import Config

Config.set('graphics', 'width', '380')
Config.set('graphics', 'height', '520')

from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.image import Image
from kivy.uix.widget import Widget
from kivy.uix.popup import Popup
from kivy.uix.textinput import TextInput
from kivy.uix.scrollview import ScrollView
from kivy.core.window import Window
from kivy.utils import platform
from kivy.uix.relativelayout import RelativeLayout
from kivy.graphics import Color, RoundedRectangle

# --- Размеры окна для тестов на ПК ---
Window.size = (380, 680)

# Проверка платформы Android и инициализация Java-классов для SpeechRecognizer
if platform == 'android':
    try:
        from jnius import autoclass, java_method, PythonJavaClass

        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        Context = autoclass('android.content.Context')
        Intent = autoclass('android.content.Intent')
        RecognizerIntent = autoclass('android.speech.RecognizerIntent')
        SpeechRecognizer = autoclass('android.speech.SpeechRecognizer')
        Looper = autoclass('android.os.Looper')
        Handler = autoclass('android.os.Handler')
        Locale = autoclass('java.util.Locale')


        class PyRunnable(PythonJavaClass):
            __javaclass__ = 'java/lang/Runnable'

            def __init__(self, callback):
                super().__init__()
                self.callback = callback

            @java_method('()V')
            def run(self):
                self.callback()


        HAS_SPEECH_RECOGNIZER = True
    except Exception as e:
        print(f"[ANDROID SPEECH INIT ERROR]: {e}")
        HAS_SPEECH_RECOGNIZER = False
else:
    HAS_SPEECH_RECOGNIZER = False

tts_lock = threading.Lock()


def speak(text, on_done_callback=None):
    if not text or not str(text).strip():
        if on_done_callback:
            on_done_callback()
        return

    text = str(text).strip()
    print(f"[TTS WORK]: Озвучиваю -> '{text}'")

    def _say_thread():
        with tts_lock:
            if platform == 'android':
                try:
                    import importlib
                    plyer_tts = importlib.import_module('plyer.tts')
                    plyer_tts.speak(text)
                except Exception as e:
                    print(f"[ANDROID TTS ERROR]: {e}")
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
                    engine = pyttsx3.init()
                    engine.setProperty('rate', 170)
                    engine.say(text)
                    engine.runAndWait()
                    engine.stop()
                except Exception as e:
                    print(f"[PC TTS ERROR]: {e}")
                finally:
                    if pythoncom_imported:
                        try:
                            import pythoncom
                            pythoncom.CoUninitialize()
                        except Exception:
                            pass

            if on_done_callback:
                on_done_callback()

    threading.Thread(target=_say_thread, daemon=True).start()


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


IMG_LAMP_1_OFF = "lamp_1_off.png"
IMG_LAMP_1_ON = "lamp_1_on.png"
IMG_LAMP_2_OFF = "lamp_2_off.png"
IMG_LAMP_2_ON = "lamp_2_on.png"
IMG_LAMP_3_OFF = "lamp_3_off.png"
IMG_LAMP_3_ON = "lamp_3_on.png"

IMG_SWITCH_OFF = "Switch_OFF.png"
IMG_SWITCH_ON = "Switch_ON-1.png"
IMG_WIFI = "wifi_icon.png"

CONFIG_FILE = "config.json"
DEFAULT_CONFIG = {
    "device_ip": "192.168.1.39",
    "sensor_ip": "192.168.1.39",
    "tts_enabled": True,
    "wake_word": "джарвис",
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
POLL_INTERVAL = 5.0


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


class RoundedButton(Button):
    def __init__(self, bg_color=(0.18, 0.55, 0.22, 1), radius=[8], **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ''
        self.background_down = ''
        self.background_color = (0, 0, 0, 0)
        self.bg_color = bg_color
        self.radius = radius

        with self.canvas.before:
            self.canvas_color = Color(*self.bg_color)
            self.rect = RoundedRectangle(pos=self.pos, size=self.size, radius=self.radius)

        self.bind(pos=self._update_rect, size=self._update_rect)

    def _update_rect(self, *args):
        self.rect.pos = self.pos
        self.rect.size = self.size


class LampRow(BoxLayout):
    def __init__(self, channel_id, icon_off, icon_on, base_url_provider, app_ref=None, **kwargs):
        super().__init__(
            orientation='horizontal',
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


class VoiceAssistant:
    def __init__(self, app, lamp_objects):
        self.app = app
        self.lamp_objects = lamp_objects
        self.listening = False
        self.is_active = False
        self.last_active_time = 0
        self.speech_recognizer = None
        self.handler = None
        if platform == 'android':
            self.handler = Handler(Looper.getMainLooper())

    def speak(self, text):
        if text and self.app.config_data.get("tts_enabled", True):
            self.app.update_assistant_status(f"Ответ: «{text}»", color=(0.9, 0.8, 0.2, 1))

            def restore_status():
                if self.is_active:
                    self.app.update_assistant_status("Ассистент: Слушаю команды...", color=(0.2, 0.85, 0.3, 1))
                else:
                    ww = self.app.config_data.get("wake_word", "джарвис").capitalize()
                    self.app.update_assistant_status(f"Ассистент: Ожидание («{ww}»)", color=(0.6, 0.6, 0.6, 1))
                self.restart_listening()

            speak(text, on_done_callback=restore_status)

    def start_listening(self):
        self.listening = True
        if platform == 'android' and HAS_SPEECH_RECOGNIZER:
            self.handler.post(PyRunnable(self._init_and_start_recognizer))
        else:
            self.app.update_assistant_status("Ассистент: SpeechRecognizer доступен на Android",
                                             color=(0.6, 0.6, 0.6, 1))

    def _init_and_start_recognizer(self):
        try:
            activity = PythonActivity.mActivity
            self.speech_recognizer = SpeechRecognizer.createSpeechRecognizer(activity)

            class AndroidRecognitionListener(PythonJavaClass):
                __javaclass__ = 'android/speech/RecognitionListener'

                def __init__(self, assistant):
                    super().__init__()
                    self.assistant = assistant

                @java_method('(Landroid/os/Bundle;)V')
                def onReadyForSpeech(self, params):
                    pass

                @java_method('()V')
                def onBeginningOfSpeech(self):
                    pass

                @java_method('(F)V')
                def onRmsChanged(self, rmsdB):
                    pass

                @java_method('([B)V')
                def onBufferReceived(self, buffer):
                    pass

                @java_method('()V')
                def onEndOfSpeech(self):
                    pass

                @java_method('(I)V')
                def onError(self, error):
                    # При ошибке тайм-аута или тишины автоматически возобновляем прослушивание
                    Clock.schedule_once(lambda dt: self.assistant.restart_listening())

                @java_method('(Landroid/os/Bundle;)V')
                def onResults(self, results):
                    matches = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                    if matches and matches.size() > 0:
                        text = matches.get(0)
                        if text:
                            Clock.schedule_once(lambda dt, t=text: self.assistant.process_command(t))
                    else:
                        Clock.schedule_once(lambda dt: self.assistant.restart_listening())

                @java_method('(Landroid/os/Bundle;)V')
                def onPartialResults(self, partialResults):
                    pass

                @java_method('(ILandroid/os/Bundle;)V')
                def onEvent(self, eventType, params):
                    pass

            self.listener = AndroidRecognitionListener(self)
            self.speech_recognizer.setRecognitionListener(self.listener)
            self.restart_listening()
        except Exception as e:
            print(f"[SPEECH RECOGNIZER INIT ERROR]: {e}")

    def restart_listening(self):
        if not self.listening:
            return
        if platform == 'android' and self.speech_recognizer:
            try:
                intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
                intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "ru-RU")
                intent.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 5)

                def start_act():
                    try:
                        self.speech_recognizer.startListening(intent)
                    except Exception:
                        pass

                self.handler.post(PyRunnable(start_act))

                ww = self.app.config_data.get("wake_word", "джарвис").capitalize()
                if self.is_active:
                    self.app.update_assistant_status("Ассистент: Слушаю команды...", color=(0.2, 0.85, 0.3, 1))
                else:
                    self.app.update_assistant_status(f"Ассистент: Ожидание («{ww}»)", color=(0.6, 0.6, 0.6, 1))
            except Exception as e:
                print(f"[SPEECH RECOGNIZER RESTART ERROR]: {e}")

    def check_activity_timeout(self, dt=None):
        if not self.is_active:
            return

        try:
            timeout_sec = int(self.app.config_data.get("wake_timeout_sec", 120))
        except (ValueError, TypeError):
            timeout_sec = 120

        if time.time() - self.last_active_time > timeout_sec:
            self.is_active = False
            ww = self.app.config_data.get("wake_word", "джарвис").capitalize()
            self.app.update_assistant_status(f"Ассистент: Ожидание («{ww}»)", color=(0.6, 0.6, 0.6, 1))

    def activate(self):
        self.is_active = True
        self.last_active_time = time.time()
        self.app.update_assistant_status("Ассистент: Слушаю команды...", color=(0.2, 0.85, 0.3, 1))

    def get_custom_response(self, sub_action, channel_id=None):
        responses = self.app.config_data.get("voice_responses", [])
        for r in responses:
            if r.get("sub_action") == sub_action and r.get("channel_id") == channel_id:
                val = (r.get("response_text") or "").strip()
                if val:
                    return val
        return ""

    def process_command(self, raw_command):
        norm_command = raw_command.lower().strip()
        if not norm_command:
            self.restart_listening()
            return

        wake_word = (self.app.config_data.get("wake_word") or "джарвис").strip().lower()
        wake_response = self.app.config_data.get("wake_response")
        if not wake_response or not str(wake_response).strip():
            wake_response = "Слушаю"
        else:
            wake_response = str(wake_response).strip()

        has_wake_word = wake_word in norm_command

        if has_wake_word:
            norm_command = norm_command.replace(wake_word, "").strip()
            self.activate()

            if not norm_command:
                self.speak(wake_response)
                return

        if not self.is_active:
            self.restart_listening()
            return

        self.activate()

        voice_cmds = self.app.config_data.get("voice_commands", [])
        for cmd in voice_cmds:
            phrase = (cmd.get("phrase") or "").strip().lower()
            if phrase and phrase in norm_command:
                action = cmd.get("action")
                chid = cmd.get("channel_id")

                if action == "temp":
                    self.app.fetch_temperature(speak_result=True)
                    return
                elif action == "all_on":
                    self.app.turn_all_on()
                    resp = self.get_custom_response("all_on") or "Включаю весь свет"
                    self.speak(resp)
                    return
                elif action == "all_off":
                    self.app.turn_all_off()
                    resp = self.get_custom_response("all_off") or "Выключаю весь свет"
                    self.speak(resp)
                    return
                elif action == "toggle" and chid is not None:
                    for lamp in self.lamp_objects:
                        if lamp.channel_id == chid:
                            if lamp.is_on:
                                lamp.turn_off()
                                resp = self.get_custom_response("off", chid) or "Выключаю"
                            else:
                                lamp.turn_on()
                                resp = self.get_custom_response("on", chid) or "Включаю"
                            self.speak(resp)
                            return

        num_replacements = {
            r'\b(одна|одно|одну|первая|первую)\b': '1',
            r'\b(две|два|вторая|вторую)\b': '2',
            r'\b(три|третья|третью)\b': '3'
        }
        for pattern, repl in num_replacements.items():
            norm_command = re.sub(pattern, repl, norm_command)

        if "температур" in norm_command:
            self.app.fetch_temperature(speak_result=True)
            return

        has_off = any(w in norm_command for w in ["выключ", "погаси", "отключи"])
        has_on = any(w in norm_command for w in ["включ", "зажги", "вруби"])

        if "все" in norm_command or "всё" in norm_command:
            if has_off:
                self.app.turn_all_off()
                resp = self.get_custom_response("all_off") or "Выключаю весь свет"
                self.speak(resp)
            elif has_on:
                self.app.turn_all_on()
                resp = self.get_custom_response("all_on") or "Включаю весь свет"
                self.speak(resp)
            return

        target_idx = None
        if "1" in norm_command or "перв" in norm_command:
            target_idx = 0
        elif "2" in norm_command or "втор" in norm_command:
            target_idx = 1
        elif "3" in norm_command or "трет" in norm_command:
            target_idx = 2

        if target_idx is not None and target_idx < len(self.lamp_objects):
            lamp = self.lamp_objects[target_idx]
            if has_off:
                lamp.turn_off()
                resp = self.get_custom_response("off", lamp.channel_id) or "Выключаю"
            elif has_on:
                lamp.turn_on()
                resp = self.get_custom_response("on", lamp.channel_id) or "Включаю"
            else:
                if lamp.is_on:
                    lamp.turn_off()
                    resp = self.get_custom_response("off", lamp.channel_id) or "Выключаю"
                else:
                    lamp.turn_on()
                    resp = self.get_custom_response("on", lamp.channel_id) or "Включаю"
            self.speak(resp)
        else:
            self.restart_listening()


class SmartHomeApp(App):
    def build(self):
        self.title = "Управление освещением"
        self.config_data = load_config()
        self.lamp_objects = []
        self.esp_connected = False
        self.failed_ip_checks = 0

        Window.clearcolor = (0.11, 0.11, 0.11, 1)

        root_layout = BoxLayout(
            orientation='vertical',
            padding=[dp(15), dp(15), dp(15), dp(40)],
            spacing=dp(10)
        )

        header_box = RelativeLayout(size_hint_y=None, height=dp(45))

        wifi_img_path = get_img(IMG_WIFI)
        if os.path.exists(wifi_img_path):
            self.wifi_icon = Image(
                source=wifi_img_path,
                size_hint=(None, None),
                size=(dp(32), dp(32)),
                pos_hint={'x': 0.0, 'center_y': 0.5},
                color=(0.4, 0.4, 0.4, 1)
            )
        else:
            self.wifi_icon = Label(
                text="Wi-Fi",
                font_size='12sp',
                bold=True,
                size_hint=(None, None),
                size=(dp(40), dp(32)),
                pos_hint={'x': 0.0, 'center_y': 0.5},
                color=(0.4, 0.4, 0.4, 1)
            )
        header_box.add_widget(self.wifi_icon)

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
            pos_hint={'right': 1.0, 'center_y': 0.5}
        )
        btn_settings.bind(on_press=lambda instance: self.open_settings())
        header_box.add_widget(btn_settings)

        root_layout.add_widget(header_box)

        labels_container = BoxLayout(
            orientation='vertical',
            size_hint_y=None,
            height=dp(60),
            spacing=dp(2)
        )

        self.temp_label = Label(
            text="Температура: -- °C",
            font_size='20sp',
            bold=True,
            color=(1, 1, 1, 1),
            halign='center'
        )

        self.assistant_label = Label(
            text="Ассистент: Инициализация...",
            font_size='13sp',
            color=(0.6, 0.6, 0.6, 1),
            halign='center'
        )

        labels_container.add_widget(self.temp_label)
        labels_container.add_widget(self.assistant_label)
        root_layout.add_widget(labels_container)

        lamps_container = GridLayout(cols=1, spacing=10, size_hint_y=None)
        lamps_container.bind(minimum_height=lamps_container.setter('height'))

        icon_pairs = [
            (IMG_LAMP_1_OFF, IMG_LAMP_1_ON),
            (IMG_LAMP_2_OFF, IMG_LAMP_2_ON),
            (IMG_LAMP_3_OFF, IMG_LAMP_3_ON),
        ]

        for idx, ch in enumerate(self.config_data.get("channels", [])):
            off_img, on_img = icon_pairs[idx] if idx < len(icon_pairs) else (IMG_LAMP_1_OFF, IMG_LAMP_1_ON)
            lamp = LampRow(ch["id"], off_img, on_img, lambda: f"http://{self.config_data.get('device_ip')}",
                           app_ref=self)
            self.lamp_objects.append(lamp)
            lamps_container.add_widget(lamp)

        root_layout.add_widget(lamps_container)
        root_layout.add_widget(Widget())

        btn_box = BoxLayout(orientation='horizontal', spacing=12, size_hint_y=None, height=50)

        btn_all_on = Button(
            text="ВКЛЮЧИТЬ ВСЕ",
            font_size='15sp',
            bold=True,
            background_normal='',
            background_color=(0, 0, 0, 0),
            color=(0.2, 0.85, 0.3, 1)
        )
        btn_all_on.bind(on_press=lambda x: self.turn_all_on())

        btn_all_off = Button(
            text="ВЫКЛЮЧИТЬ ВСЕ",
            font_size='15sp',
            bold=True,
            background_normal='',
            background_color=(0, 0, 0, 0),
            color=(0.9, 0.2, 0.2, 1)
        )
        btn_all_off.bind(on_press=lambda x: self.turn_all_off())

        btn_box.add_widget(btn_all_on)
        btn_box.add_widget(btn_all_off)
        root_layout.add_widget(btn_box)

        # Запрос разрешений и запуск микрофона
        self.request_android_permissions(on_granted=self._start_assistant)

        Clock.schedule_once(lambda dt: self.poll_statuses(None), 0.5)
        Clock.schedule_interval(self.poll_statuses, POLL_INTERVAL)

        return root_layout

    def _start_assistant(self):
        self.assistant = VoiceAssistant(self, self.lamp_objects)
        self.assistant.start_listening()
        Clock.schedule_interval(self.assistant.check_activity_timeout, 1.0)

    @mainthread
    def set_wifi_status(self, is_connected: bool):
        if hasattr(self, 'wifi_icon') and self.wifi_icon:
            if is_connected:
                self.wifi_icon.color = (1, 1, 1, 1)
            else:
                self.wifi_icon.color = (0.4, 0.4, 0.4, 1)

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
                        print(f"[ESP]: Подключено к {target_ip}")
                        if hasattr(self, 'assistant') and self.assistant:
                            self.assistant.speak("Связь установлена")
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
    def update_assistant_status(self, text, color=(0.6, 0.6, 0.6, 1)):
        if hasattr(self, 'assistant_label'):
            self.assistant_label.text = text
            self.assistant_label.color = color

    def request_android_permissions(self, on_granted=None):
        if platform == 'android':
            try:
                from android.permissions import request_permissions, Permission

                def cb(permissions, results):
                    if all(results):
                        print("[PERMISSIONS] Разрешение на микрофон получено")
                        if on_granted:
                            on_granted()
                    else:
                        print("[PERMISSIONS] Отказано в доступе к микрофону")
                        self.update_assistant_status("Ассистент: Нет прав на микрофон", color=(0.9, 0.2, 0.2, 1))

                request_permissions([Permission.RECORD_AUDIO, Permission.INTERNET], cb)
            except Exception as e:
                print(f"[PERMISSIONS ERROR]: {e}")
                if on_granted:
                    on_granted()
        else:
            if on_granted:
                on_granted()

    def turn_all_on(self):
        for l in self.lamp_objects:
            l.turn_on()

    def turn_all_off(self):
        for l in self.lamp_objects:
            l.turn_off()

    def fetch_temperature(self, speak_result=False):
        def req():
            sensor_ip = self.config_data.get("sensor_ip") or self.config_data.get("device_ip")
            try:
                res = requests.get(f"http://{sensor_ip}/temperature", timeout=TIMEOUT)
                if res.status_code == 200:
                    raw_text = res.text.strip()
                    match = re.search(r"(\d+\.\d+)", raw_text)
                    if not match:
                        match = re.search(r"(?:Temp|Температура)[^\d]*(\d+(?:\.\d+)?)", raw_text, re.IGNORECASE)

                    if match:
                        current_temp = float(match.group(1))
                        speech_text = format_temperature_speech(current_temp)
                        self._set_temp_text(f"Температура: {current_temp:.1f} °C")

                        if speak_result and self.config_data.get("tts_enabled", True):
                            if hasattr(self, 'assistant') and self.assistant:
                                self.assistant.speak(speech_text)
            except Exception as e:
                print(f"[ОШИБКА ДАТЧИКА]: {e}")

        threading.Thread(target=req, daemon=True).start()

    @mainthread
    def _set_temp_text(self, text):
        self.temp_label.text = text

    def poll_statuses(self, dt):
        self.check_ip_connection()
        for l in self.lamp_objects:
            l.check_status()
        self.fetch_temperature()

    def open_settings(self):
        scroll = ScrollView(size_hint=(1, 1))
        content = GridLayout(cols=1, spacing=dp(10), size_hint_y=None, padding=[dp(12), dp(10), dp(12), dp(10)])
        content.bind(minimum_height=content.setter('height'))

        def create_section_header(text):
            lbl = Label(
                text=text,
                font_size='14sp',
                bold=True,
                color=(0.3, 0.7, 1, 1),
                size_hint_y=None,
                height=dp(30),
                halign='left',
                valign='middle'
            )
            lbl.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
            return lbl

        def create_auto_input(text="", input_filter=None, font_size='13sp', multiline=False):
            inp = TextInput(
                text=str(text),
                multiline=multiline,
                size_hint_y=None,
                font_size=font_size,
                input_filter=input_filter,
                padding=[dp(8), dp(8), dp(8), dp(8)]
            )
            inp.bind(minimum_height=lambda inst, val: setattr(inst, 'height', max(dp(40), inst.minimum_height)))
            inp.height = max(dp(40), inp.minimum_height)
            return inp

        def create_mic_button(on_press_callback):
            mic_path = get_img('mic.png')
            if os.path.exists(mic_path):
                btn = Button(
                    background_normal=mic_path,
                    background_down=mic_path,
                    size_hint=(None, None),
                    size=(dp(36), dp(36)),
                    border=(0, 0, 0, 0),
                    pos_hint={'center_y': 0.5}
                )
            else:
                btn = Button(
                    text="MIC",
                    font_size='11sp',
                    bold=True,
                    size_hint=(None, None),
                    size=(dp(45), dp(36)),
                    background_normal='',
                    background_color=(0.3, 0.3, 0.3, 1),
                    color=(1, 1, 1, 1),
                    pos_hint={'center_y': 0.5}
                )
            btn.bind(on_press=on_press_callback)
            return btn

        def create_setting_row(label_text, input_widget, mic_btn=None, is_flexible_input=True):
            row = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(44), spacing=dp(8))
            lbl = Label(
                text=label_text,
                font_size='12sp',
                color=(0.85, 0.85, 0.85, 1),
                halign='left',
                valign='middle',
                size_hint_x=0.45
            )
            lbl.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
            row.add_widget(lbl)

            if is_flexible_input:
                input_widget.size_hint_x = 0.55
            row.add_widget(input_widget)

            if mic_btn:
                row.add_widget(mic_btn)
            else:
                row.add_widget(Widget(size_hint=(None, None), size=(dp(36), dp(36))))

            input_widget.bind(height=lambda inst, val, r=row: setattr(r, 'height', max(dp(44), val)))
            row.height = max(dp(44), input_widget.height)
            return row

        def record_to_entry(entry_widget):
            if platform != 'android' or not HAS_SPEECH_RECOGNIZER:
                entry_widget.text = "Только на Android"
                return

            original_text = entry_widget.text
            self.update_assistant_status("Запись в настройках...", color=(1.0, 0.6, 0.2, 1))
            Clock.schedule_once(lambda _dt: setattr(entry_widget, 'text', "Слушаю..."))

            def _listen_setting():
                try:
                    activity = PythonActivity.mActivity
                    setting_recognizer = SpeechRecognizer.createSpeechRecognizer(activity)

                    class SettingListener(PythonJavaClass):
                        __javaclass__ = 'android/speech/RecognitionListener'

                        def __init__(self, rec_obj, widget, orig, app_ref):
                            super().__init__()
                            self.rec_obj = rec_obj
                            self.widget = widget
                            self.orig = orig
                            self.app_ref = app_ref

                        @java_method('(Landroid/os/Bundle;)V')
                        def onReadyForSpeech(self, params):
                            pass

                        @java_method('()V')
                        def onBeginningOfSpeech(self):
                            pass

                        @java_method('(F)V')
                        def onRmsChanged(self, rmsdB):
                            pass

                        @java_method('([B)V')
                        def onBufferReceived(self, buffer):
                            pass

                        @java_method('()V')
                        def onEndOfSpeech(self):
                            pass

                        @java_method('(I)V')
                        def onError(self, error):
                            Clock.schedule_once(lambda dt: setattr(self.widget, 'text', self.orig))
                            try:
                                self.rec_obj.destroy()
                            except:
                                pass
                            self._restore_status()

                        @java_method('(Landroid/os/Bundle;)V')
                        def onResults(self, results):
                            matches = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                            txt = self.orig
                            if matches and matches.size() > 0:
                                t = matches.get(0)
                                if t:
                                    txt = t
                            Clock.schedule_once(lambda dt: setattr(self.widget, 'text', txt))
                            try:
                                self.rec_obj.destroy()
                            except:
                                pass
                            self._restore_status()

                        @java_method('(Landroid/os/Bundle;)V')
                        def onPartialResults(self, partialResults):
                            pass

                        @java_method('(ILandroid/os/Bundle;)V')
                        def onEvent(self, eventType, params):
                            pass

                        def _restore_status(self):
                            if hasattr(self.app_ref, 'assistant') and self.app_ref.assistant:
                                if self.app_ref.assistant.is_active:
                                    self.app_ref.update_assistant_status("Ассистент: Слушаю команды...",
                                                                         color=(0.2, 0.85, 0.3, 1))
                                else:
                                    ww = self.app_ref.config_data.get("wake_word", "джарвис").capitalize()
                                    self.app_ref.update_assistant_status(f"Ассистент: Ожидание («{ww}»)",
                                                                         color=(0.6, 0.6, 0.6, 1))
                                self.app_ref.assistant.restart_listening()

                    listener = SettingListener(setting_recognizer, entry_widget, original_text, self)
                    setting_recognizer.setRecognitionListener(listener)

                    intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
                    intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                    intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "ru-RU")

                    setting_recognizer.startListening(intent)
                except Exception as e:
                    print(f"[SETTING REC ERROR]: {e}")
                    Clock.schedule_once(lambda dt: setattr(entry_widget, 'text', original_text))

            if hasattr(self, 'assistant') and self.assistant and self.assistant.speech_recognizer:
                try:
                    self.assistant.speech_recognizer.stopListening()
                except:
                    pass

            self.assistant.handler.post(PyRunnable(_listen_setting))

        content.add_widget(create_section_header("Общие настройки"))
        ip_input = create_auto_input(self.config_data.get("device_ip", "192.168.1.39"), multiline=False)
        content.add_widget(create_setting_row("IP-адрес:", ip_input))

        tts_box = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(44), spacing=dp(8))
        lbl_tts = Label(text="Включить голосовой ответ:", font_size='12sp', color=(0.85, 0.85, 0.85, 1),
                        size_hint_x=0.55, halign='left', valign='middle')
        lbl_tts.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
        tts_box.add_widget(lbl_tts)

        is_tts = self.config_data.get("tts_enabled", True)
        btn_tts = Button(
            text="ВКЛ" if is_tts else "ВЫКЛ",
            background_normal='',
            background_color=(0.2, 0.2, 0.2, 1),
            size_hint=(0.45, None),
            height=dp(36),
            font_size='12sp',
            bold=True,
            pos_hint={'center_y': 0.5}
        )

        def toggle_tts(instance):
            btn_tts.text = "ВЫКЛ" if btn_tts.text == "ВКЛ" else "ВКЛ"

        btn_tts.bind(on_press=toggle_tts)
        tts_box.add_widget(btn_tts)
        tts_box.add_widget(Widget(size_hint=(None, None), size=(dp(36), dp(36))))
        content.add_widget(tts_box)

        content.add_widget(create_section_header("Активация и время сна"))
        wake_word_entry = create_auto_input(self.config_data.get("wake_word", "джарвис"))
        btn_rec_ww = create_mic_button(lambda x: record_to_entry(wake_word_entry))
        content.add_widget(create_setting_row("1. Слово активации:", wake_word_entry, btn_rec_ww))

        wake_response_entry = create_auto_input(self.config_data.get("wake_response", "Слушаю"))
        btn_rec_wr = create_mic_button(lambda x: record_to_entry(wake_response_entry))
        content.add_widget(create_setting_row("2. Ответ активации:", wake_response_entry, btn_rec_wr))

        wake_timeout_entry = create_auto_input(self.config_data.get("wake_timeout_sec", 120), input_filter='int',
                                               multiline=False)
        content.add_widget(create_setting_row("3. Время активности (сек):", wake_timeout_entry))

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

            inp = create_auto_input(init_val)
            btn_mic = create_mic_button(lambda x, e=inp: record_to_entry(e))
            content.add_widget(create_setting_row(f"{item['label']}:", inp, btn_mic))
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

            inp = create_auto_input(init_val)
            btn_mic = create_mic_button(lambda x, e=inp: record_to_entry(e))
            content.add_widget(create_setting_row(f"{item['label']}:", inp, btn_mic))
            resp_entries[(item["sub_action"], item["chid"])] = inp

        scroll.add_widget(content)

        popup_layout = BoxLayout(orientation='vertical', padding=[dp(10), dp(10), dp(10), dp(10)], spacing=dp(10))
        popup_layout.add_widget(scroll)

        btn_box = BoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(40),
            spacing=dp(10)
        )

        btn_box.add_widget(Widget())

        btn_save = RoundedButton(
            text='Сохранить',
            font_size='12sp',
            bold=True,
            size_hint=(None, None),
            size=(dp(100), dp(32)),
            bg_color=(0, 0, 0, 0),
            radius=[dp(10)],
            color=(0.2, 0.85, 0.3, 1)
        )

        btn_cancel = RoundedButton(
            text='Отмена',
            font_size='12sp',
            bold=True,
            size_hint=(None, None),
            size=(dp(100), dp(32)),
            bg_color=(0, 0, 0, 0),
            radius=[dp(10)],
            color=(0.9, 0.2, 0.2, 1)
        )

        def save_settings_data(instance):
            self.config_data["device_ip"] = ip_input.text.strip()
            self.config_data["tts_enabled"] = (btn_tts.text == "ВКЛ")
            self.config_data["wake_word"] = wake_word_entry.text.strip()
            self.config_data["wake_response"] = wake_response_entry.text.strip()
            try:
                self.config_data["wake_timeout_sec"] = int(wake_timeout_entry.text.strip())
            except ValueError:
                pass

            updated_cmds = []
            for (action, chid), inp in cmd_entries.items():
                updated_cmds.append({"action": action, "channel_id": chid, "phrase": inp.text.strip()})
            self.config_data["voice_commands"] = updated_cmds

            updated_resps = []
            for (sub_action, chid), resp_inp in resp_entries.items():
                updated_resps.append(
                    {"sub_action": sub_action, "channel_id": chid, "response_text": resp_inp.text.strip()})
            self.config_data["voice_responses"] = updated_resps

            try:
                config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(self.config_data, f, ensure_ascii=False, indent=4)
                print("[CONFIG] Настройки успешно сохранены!")
            except Exception as e:
                print(f"[ОШИБКА СОХРАНЕНИЯ]: {e}")

            popup.dismiss()

        btn_save.bind(on_press=save_settings_data)

        btn_box.add_widget(btn_save)
        btn_box.add_widget(btn_cancel)
        popup_layout.add_widget(btn_box)

        popup = Popup(
            title='Настройки',
            content=popup_layout,
            size_hint=(0.95, 0.92),
            auto_dismiss=False
        )
        btn_cancel.bind(on_press=popup.dismiss)

        popup.open()


if __name__ == '__main__':
    SmartHomeApp().run()
