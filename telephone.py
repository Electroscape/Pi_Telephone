import argparse
import json
import logging
import os

import simpleaudio as sa
from pynput import keyboard
from scipy.io import wavfile
import numpy as np

try:
    import RPi.GPIO as GPIO
except ImportError:
    import Mock.GPIO as GPIO
from time import sleep, perf_counter

from threading import Thread, Lock
from pathlib import Path
from datetime import datetime as dt, timedelta
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

root_path = Path(os.getcwd())
print(f"root path of the script: {root_path}")
sound_path = root_path.joinpath("sounds")

# store the specific project sound files here and add them into the config json
parent_path = root_path.parent.joinpath("Pi_Telephone_files")

sound_path_local = parent_path.joinpath("sounds")
if not sound_path_local.exists():
    print("defaulting to testing config")
    sound_path_local = sound_path.joinpath("local_project")

GPIO.setmode(GPIO.BOARD)

'''
logging.basicConfig(
    filename='log.log',
    level=logging.ERROR,
    format="{asctime} {levelname:<8} {message}",
    style='{'
)
'''

argparser = argparse.ArgumentParser(description='Telephone')
argparser.add_argument('-c', '--city', default='st', help='name of the city: [hh / st]')

location = argparser.parse_args().city

dialed_numbers = []


class Telephone:
    def __init__(self, _location):
        cfg = self.__get_cfg()
        self.number_dialed = ""
        # currently not used, but hard to see
        self.max_digits = 12
        self.current_sound = None
        self.sound_queue = []
        self.key_events = []
        self.call_active = False
        self.play_obj = None
        self.lock = Lock()
        try:
            self.contacts = cfg["contacts"]
            self.incoming_callers = cfg["incoming"]
            self.language = "deu/"
            self.dial_delay = 3
            self.location = _location
            # set to board, board 12 is GPIO 18
            self.phone_pin = 12
            GPIO.setup(self.phone_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            self.last_keypress = dt.now()
            self.running_call = False

            self.pressed_keys = set()
            self.listener = keyboard.Listener(
                on_press=self.on_press,
                on_release=self.on_release
            )
            self.listener.start()

            self.loop = Thread(target=self.main_loop, daemon=True)
            self.loop.start()

        except KeyError as er:
            print(er)
            # logging.error(er)

    def on_press(self, key):
        with self.lock:
            try:
                key_char = key.char
                if key_char in self.pressed_keys:
                    return  # Ignore repeated presses while key is held

                self.pressed_keys.add(key_char)  # Mark key as pressed
                self.key_events.append(key_char)
                self.last_keypress = dt.now()

            except AttributeError:
                pass  # Ignore special keys

    def on_release(self, key):
        with self.lock:
            try:
                key_char = key.char
                if key_char in self.pressed_keys:
                    self.pressed_keys.remove(key_char)  # Remove key when released
            except AttributeError:
                pass  # Ignore special keys

    @staticmethod
    def __get_cfg():
        config_path = parent_path.joinpath("config.json")
        if not config_path.exists():
            config_path = 'config.json'
        try:
            with open(config_path, 'r') as config_file:
                return json.load(config_file)
        except (FileNotFoundError, ValueError) as err:
            # logging.error(f"failed to fetch config file {err}")
            exit(f"failed to fetch config file {err}")

    def get_scaled_sound(self, sound_file, volume):
        rate, data = wavfile.read(sound_file)

        # Normalize to int16 if needed
        if data.dtype == np.int16:
            scaled = (data * volume).astype(np.int16)
        elif data.dtype == np.int32:
            scaled = (data / (2 ** 16) * volume).astype(np.int16)
        elif data.dtype == np.uint8:
            # Center and scale unsigned 8-bit to signed 16-bit
            centered = data.astype(np.int16) - 128
            scaled = (centered * 256 * volume).astype(np.int16)
        elif data.dtype == np.float32:
            # Scale float [-1.0, 1.0] to int16
            scaled = (data * 32767 * volume).astype(np.int16)
        else:
            raise ValueError(f"Unsupported WAV format: {data.dtype}")

        # num_channels = 1 if len(scaled.shape) == 1 else scaled.shape[1]
        # sa.play_buffer(scaled, num_channels, 2, rate)
        return scaled

    def play_sound(self, sound_file, dialing=False, volume=1):
        try:
            print(sound_file)
            if volume == 1:
                wave_obj = sa.WaveObject.from_wave_file(str(sound_file))
                self.play_obj = wave_obj.play()
            else:
                rate, _ = wavfile.read(sound_file)
                data = self.get_scaled_sound(sound_file, volume)

                num_channels = 1 if len(data.shape) == 1 else data.shape[1]
                bytes_per_sample = 2  # because we cast to int16
                self.play_obj = sa.play_buffer(data, num_channels, bytes_per_sample, rate)

            if not dialing:
                self.play_obj.wait_done()
        except FileNotFoundError:
            print(f"failed to find sound {sound_file}")

    def set_german(self, is_german):
        if is_german:
            self.language = "deu/"
        else:
            self.language = "eng/"

    def pause_current_sound(self):
        self.sound_queue = []
        sa.stop_all()

    @staticmethod
    def add_to_history(number):
        timestamp = dt.now().strftime("%H:%M:%S")
        global dialed_numbers
        dialed_numbers.insert(0, f"{number}: {timestamp}")
        dialed_numbers = dialed_numbers[-5:]

    def check_number(self):
        self.call_active = True
        try:
            print("checkNumber")
            sa.stop_all()
            sound_file = self.contacts.get(self.number_dialed, False)
            if sound_file:
                self.play_sound(sound_path.joinpath("014_wahl&rufzeichen.wav"))
                self.sound_queue = [sound_path_local.joinpath(self.language + sound_file)]
                self.sound_queue.append(sound_path.joinpath("beepSound.wav"))
                self.add_to_history(sound_file)
            else:
                self.play_sound(sound_path.joinpath("dialedWrongNumber.wav"))
                self.add_to_history(self.number_dialed)

            self.reset_dialing()
        except Exception as exp:
            print(exp)

    def reset_dialing(self):
        do_update = bool(self.number_dialed)
        # print("resetting dialing")
        self.number_dialed = ""
        self.play_obj = None
        if do_update:
            send_number(self.number_dialed)

    def handle_keys(self):

        if self.call_active:
            return

        update = False

        with self.lock:
            while self.key_events:
                key = self.key_events.pop(0)
                update = True
                self.number_dialed += f"{key}"
                print(f"{key}")
                self.pause_current_sound()
                self.play_sound(sound_path.joinpath(f"{key}.wav"), True)

        if update:
            send_number(self.number_dialed)
            txt = "number dialed is " + self.number_dialed
            print(txt)
            # logging.info(txt)

    def phone_down(self):
        self.reset_dialing()
        self.pause_current_sound()
        with self.lock:
            self.key_events.clear()
        self.call_active = False

    def phone_up(self):
        self.handle_keys()

        if not self.call_active:
            if self.number_dialed:
                if (dt.now() - self.last_keypress).total_seconds() > self.dial_delay:
                    self.check_number()
            elif self.play_obj is None or not self.play_obj.is_playing():
                fz = sound_path.joinpath("output.wav")
                self.play_sound(fz, True)
        else:
            if self.sound_queue:
                if self.play_obj is None or not self.play_obj.is_playing():
                    self.play_sound(self.sound_queue.pop(0))


    def main_loop(self):
        print("phone mainloop")
        last_check_time = perf_counter()  # Track time instead of sleeping

        while True:

            if GPIO.input(self.phone_pin):
                self.phone_down()
            else:
                self.phone_up()

            while perf_counter() - last_check_time < 0.02:
                pass  # Busy wait for 20ms
            last_check_time = perf_counter()  # Reset timer


@app.route("/set-language", methods=["POST"])
def set_language():
    data = request.get_json()
    if "language" in data:
        selected_language = data["language"]
        phone.set_german(selected_language == "de")
        print(f"Language changed to: {selected_language}")
        return jsonify({"message": "Language updated", "language": selected_language}), 200
    return jsonify({"error": "Invalid request"}), 400

@app.route("/incoming-call", methods=["POST"])
def incoming_call():
    print("received an incoming call")

    caller = request.get_json()
    sound_file, sound_scale = phone.incoming_callers.get(caller)
    print(phone.incoming_callers)
    print(sound_scale)
    print(f"{caller}: {sound_file}")
    if sound_file:
        phone.play_sound(sound_path_local.joinpath(phone.language + sound_file), False, sound_scale)
    return jsonify({"message": "incoming call from ", "caller": caller}), 200


def send_number(number):
    print(f"Emitting number: {number}")
    try:
        socketio.emit("update_number", number)
    except Exception as exp:
        print()
        # logging.error(exp)


@app.route("/get-history")
def get_history():
    return jsonify({"history": dialed_numbers})


# Web route to render the frontend
@app.route("/", methods=["GET", "POST"])
def index():
    return render_template("index.html", incoming_callers=phone.incoming_callers)


def main():
    global phone
    phone = Telephone(location)
    # phone.play_sound(sound_path.joinpath("beepSound.wav"), False, 0.5)

    print("Telephone app is running")
    # phone.play_sound(sound_path.joinpath("014_wahl&rufzeichen.wav"))
    # Debug True will cause a double instance of the telephone making a mulitple executions of sounds
    socketio.run(app, debug=False, host='0.0.0.0', port=5500, allow_unsafe_werkzeug=True)


if __name__ == '__main__':
    main()
