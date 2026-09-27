from flask import Flask, render_template, request, jsonify
from gpiozero import OutputDevice
import time
import board
import adafruit_dht
import threading

app = Flask(__name__)

dhtDevice = adafruit_dht.DHT11(board.D17)

pins = [OutputDevice(9), OutputDevice(25), OutputDevice(10), OutputDevice(4)]

HALF_STEP = [
    [1, 0, 0, 0], [1, 1, 0, 0], [0, 1, 0, 0], [0, 1, 1, 0],
    [0, 0, 1, 0], [0, 0, 1, 1], [0, 0, 0, 1], [1, 0, 0, 1]
]

motor_running = False
target_angle = 0
target_direction = "thuan"
motor_thread = None

def release_pins():
    for pin in pins:
        pin.off()

def rotate_once(angle, direction):
    steps = int((angle / 360.0) * 4096)
    seq = HALF_STEP if direction == "thuan" else list(reversed(HALF_STEP))

    for step in range(steps):
        pattern = seq[step % 8]
        for i in range(4):
            pins[i].value = pattern[i]
        time.sleep(0.001)

    release_pins()

def motor_worker():
    """Luồng chạy nền: quay hết nhịp -> nghỉ 0.5s -> kiểm tra lệnh mới"""
    global motor_running, target_angle, target_direction
    while motor_running:
        curr_angle = target_angle
        curr_dir = target_direction

        rotate_once(curr_angle, curr_dir)

        for _ in range(5):
            if not motor_running:
                break
            time.sleep(0.1)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/sensor')
def get_sensor_data():
    global motor_running
    if motor_running:
        return jsonify({'status': 'busy'})
    try:
        t, h = dhtDevice.temperature, dhtDevice.humidity
        if t is not None and h is not None:
            return jsonify({'temp': t, 'hum': h, 'status': 'ok'})
    except RuntimeError:
        pass
    return jsonify({'status': 'error'})

@app.route('/api/motor', methods=['POST'])
def control_motor():
    global motor_running, target_angle, target_direction, motor_thread
    data = request.get_json()
    angle = float(data.get('angle', 0))
    direction = data.get('direction', 'thuan')

    if angle > 0:
        target_angle = angle
        target_direction = direction

        if not motor_running or motor_thread is None or not motor_thread.is_alive():
            motor_running = True
            motor_thread = threading.Thread(target=motor_worker, daemon=True)
            motor_thread.start()

        return jsonify({'status': 'success', 'message': f'Đã cập nhật: Quay {direction} {angle}°, nghỉ 0.5s lặp lại'})

    return jsonify({'status': 'error', 'message': 'Góc không hợp lệ'})

@app.route('/api/motor/stop', methods=['POST'])
def stop_motor():
    global motor_running
    motor_running = False
    release_pins()
    return jsonify({'status': 'success', 'message': 'Sẽ dừng hẳn sau khi quay nốt nhịp hiện tại.'})

if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', port=5000, debug=False)
    except KeyboardInterrupt:
        pass
    finally:
        motor_running = False
        release_pins()