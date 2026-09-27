"""
Dieu khien va giam sat cam bien va dong co voi web server tren Raspberry Pi
----------------------------------------------------------------------------
- Stepper motor (28BYJ-48 + ULN2003 driver) on BCM pins 17, 18, 27, 22
- Digital light sensor module on BCM pin 6
- DHT temperature/humidity sensor on BCM pin 4 (board.D4)
- Flask web server exposing status + motor control endpoints
"""

import threading
import time
import traceback

import RPi.GPIO as GPIO
import adafruit_dht
import board
from flask import Flask, jsonify, render_template, request

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
IN1 = 17
IN2 = 18
IN3 = 27
IN4 = 22
STEP_PINS = [IN1, IN2, IN3, IN4]

LIGHT_SENSOR_PIN = 6
DHT_PIN = board.D4

DO_LOW_MEANS_BRIGHT = True   # flip to False if your light module reads HIGH in bright light
DHT_MAX_RETRY = 5
DHT_RETRY_DELAY = 2          # seconds between DHT read retries
STEP_DELAY = 0.002           # seconds between stepper motor steps
MIN_POSITION = 0
MAX_POSITION = 512           # ~1 revolution for a 28BYJ-48 in half-step mode

# ---------------------------------------------------------------------------
# GPIO setup
# ---------------------------------------------------------------------------
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

for pin in STEP_PINS:
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, GPIO.LOW)

GPIO.setup(LIGHT_SENSOR_PIN, GPIO.IN)

dht_sensor = adafruit_dht.DHT11(DHT_PIN)  # use adafruit_dht.DHT22(DHT_PIN) if that's your sensor

STEP_SEQUENCE = [
    [1, 0, 0, 0],
    [1, 1, 0, 0],
    [0, 1, 0, 0],
    [0, 1, 1, 0],
    [0, 0, 1, 0],
    [0, 0, 1, 1],
    [0, 0, 0, 1],
    [1, 0, 0, 1],
]

current_position = 0
step_index = 0
motor_lock = threading.Lock()  # prevents two requests from driving the motor at once


# ---------------------------------------------------------------------------
# Sensor helpers
# ---------------------------------------------------------------------------
def is_bright():
    value = GPIO.input(LIGHT_SENSOR_PIN)
    if DO_LOW_MEANS_BRIGHT:
        return value == GPIO.LOW
    return value == GPIO.HIGH


def read_temperature():
    for attempt in range(1, DHT_MAX_RETRY + 1):
        try:
            temp = dht_sensor.temperature
            if temp is None:
                raise RuntimeError("Sensor returned no reading")
            return temp
        except RuntimeError:
            if attempt < DHT_MAX_RETRY:
                time.sleep(DHT_RETRY_DELAY)
        except Exception:
            traceback.print_exc()
            break
    return None


# ---------------------------------------------------------------------------
# Motor control
# ---------------------------------------------------------------------------
def move_to_position(target_position):
    global current_position, step_index

    target_position = max(MIN_POSITION, min(MAX_POSITION, target_position))
    diff = target_position - current_position
    if diff == 0:
        return current_position

    direction = 1 if diff > 0 else -1
    steps_needed = abs(diff)

    with motor_lock:
        for _ in range(steps_needed):
            step_index = (step_index + direction) % len(STEP_SEQUENCE)
            for pin, value in zip(STEP_PINS, STEP_SEQUENCE[step_index]):
                GPIO.output(pin, value)
            time.sleep(STEP_DELAY)
        current_position = target_position

        # de-energize coils so the motor doesn't overheat while idle
        for pin in STEP_PINS:
            GPIO.output(pin, GPIO.LOW)

    return current_position


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    return jsonify(
        {
            "bright": is_bright(),
            "temperature": read_temperature(),
            "position": current_position,
        }
    )


@app.route("/api/motor", methods=["POST"])
def api_motor():
    data = request.get_json(silent=True) or {}
    target = data.get("position")
    if target is None:
        return jsonify({"error": "Missing 'position' in request body"}), 400
    try:
        target = int(target)
    except (TypeError, ValueError):
        return jsonify({"error": "'position' must be an integer"}), 400

    new_position = move_to_position(target)
    return jsonify({"position": new_position})


if __name__ == "__main__":
    try:
        app.run(host="0.0.0.0", port=5000, debug=False)
    finally:
        GPIO.cleanup()
