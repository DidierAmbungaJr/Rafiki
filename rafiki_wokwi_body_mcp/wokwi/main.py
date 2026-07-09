"""
Rafiki Body Controller - Wokwi / ESP32 MicroPython
==================================================
Rôle : simuler le corps de Rafiki dans Wokwi :
- 1 écran OLED SSD1306 128x64 pour les expressions faciales et messages courts
- 3 servomoteurs : tête, bras gauche, bras droit
- 1 buzzer optionnel pour un petit feedback sonore
- Communication MQTT avec l'agent MCP/LLM

Topics MQTT :
- Commandes reçues : rafiki/468994098570147841/body/cmd
- État publié     : rafiki/468994098570147841/body/status

Commandes JSON supportées :
1) Expression écran :
   {"action":"expression","name":"happy","text":"Bravo !"}

2) Message écran :
   {"action":"screen_text","text":"Je reflechis...","expression":"thinking"}

3) Pose directe :
   {"action":"pose","head":90,"left_arm":130,"right_arm":50}

4) Geste prédéfini :
   {"action":"gesture","name":"greet","repeat":1}

5) Démo complète :
   {"action":"demo"}
"""

from machine import Pin, PWM, I2C
import network
import time
import ujson
from umqtt.simple import MQTTClient
import ssd1306

# =========================
# CONFIGURATION WIFI / MQTT
# =========================
WIFI_SSID = "Wokwi-GUEST"
WIFI_PASSWORD = ""

MQTT_BROKER = "broker.emqx.io"
MQTT_PORT = 1883

# ID unique pour éviter les conflits sur le broker public
MQTT_CLIENT_ID = "rafiki_body_wokwi_" + str(time.ticks_ms())

MQTT_TOPIC_CMD = b"rafiki/468994098570147841/body/cmd"
MQTT_TOPIC_STATUS = b"rafiki/468994098570147841/body/status"
STATUS_INTERVAL_MS = 1000
# ================
# CONFIGURATION I/O
# ================
PIN_OLED_SDA = 21
PIN_OLED_SCL = 22

PIN_SERVO_HEAD = 18
PIN_SERVO_LEFT_ARM = 19
PIN_SERVO_RIGHT_ARM = 23
PIN_BUZZER = 5

OLED_WIDTH = 128
OLED_HEIGHT = 64

# =================
# OBJETS MATERIELS
# =================
i2c = I2C(0, scl=Pin(PIN_OLED_SCL), sda=Pin(PIN_OLED_SDA))
oled = ssd1306.SSD1306_I2C(OLED_WIDTH, OLED_HEIGHT, i2c)

buzzer = PWM(Pin(PIN_BUZZER), freq=800, duty=0)


class Servo:
    """Contrôle simple d'un servomoteur avec PWM 50Hz sur ESP32 MicroPython."""

    def __init__(self, pin_number, name, initial_angle=90):
        self.name = name
        self.pwm = PWM(Pin(pin_number), freq=50)
        self.angle = initial_angle
        self.write(initial_angle)

    def _angle_to_duty(self, angle):
        # 0.5ms à 2.4ms sur période 20ms => environ duty 26 à 123 / 1023
        angle = max(0, min(180, int(angle)))
        return int(26 + (angle / 180) * 97)

    def write(self, angle):
        angle = max(0, min(180, int(angle)))
        self.angle = angle
        self.pwm.duty(self._angle_to_duty(angle))

    def smooth_write(self, target_angle, step=3, delay_ms=15):
        target_angle = max(0, min(180, int(target_angle)))
        if target_angle == self.angle:
            return
        direction = 1 if target_angle > self.angle else -1
        for a in range(self.angle, target_angle, direction * step):
            self.write(a)
            time.sleep_ms(delay_ms)
        self.write(target_angle)


head = Servo(PIN_SERVO_HEAD, "head", 90)
left_arm = Servo(PIN_SERVO_LEFT_ARM, "left_arm", 90)
right_arm = Servo(PIN_SERVO_RIGHT_ARM, "right_arm", 90)

state = {
    "device": "rafiki_body_wokwi",
    "mode": "simulation",
    "expression": "neutral",
    "screen_text": "Pret",
    "last_command": None,
    "pose": {"head": 90, "left_arm": 90, "right_arm": 90},
    "mqtt_connected": False,
    "wifi_connected": False,
}

mqtt_client = None
last_status_ms = 0

# ======================
# AFFICHAGE / EXPRESSIONS
# ======================
def clear_screen():
    oled.fill(0)


def text_line(text, x, y, max_chars=16):
    if text is None:
        text = ""
    text = str(text)
    oled.text(text[:max_chars], x, y)


def draw_mouth_happy():
    oled.line(48, 39, 56, 47, 1)
    oled.line(56, 47, 72, 47, 1)
    oled.line(72, 47, 80, 39, 1)


def draw_mouth_sad():
    oled.line(48, 47, 56, 39, 1)
    oled.line(56, 39, 72, 39, 1)
    oled.line(72, 39, 80, 47, 1)


def draw_expression(name="neutral", text=""):
    name = (name or "neutral").lower()
    clear_screen()

    # Zone visage : y 0 à 50. Zone texte : y 52 à 63.
    if name == "happy":
        # Yeux souriants
        oled.line(31, 23, 39, 17, 1)
        oled.line(39, 17, 47, 23, 1)
        oled.line(81, 23, 89, 17, 1)
        oled.line(89, 17, 97, 23, 1)
        draw_mouth_happy()

    elif name == "sad":
        oled.line(31, 18, 39, 24, 1)
        oled.line(39, 24, 47, 18, 1)
        oled.line(81, 18, 89, 24, 1)
        oled.line(89, 24, 97, 18, 1)
        draw_mouth_sad()

    elif name == "thinking":
        oled.fill_rect(32, 20, 10, 10, 1)
        oled.fill_rect(86, 20, 10, 10, 1)
        oled.line(50, 43, 78, 43, 1)
        oled.text("?", 105, 8)

    elif name == "surprise":
        oled.rect(30, 17, 16, 16, 1)
        oled.rect(82, 17, 16, 16, 1)
        oled.rect(58, 40, 12, 12, 1)

    elif name == "sleep":
        oled.line(30, 24, 47, 24, 1)
        oled.line(82, 24, 99, 24, 1)
        oled.line(52, 43, 76, 43, 1)
        oled.text("Zz", 94, 8)

    elif name == "alert":
        oled.rect(27, 15, 22, 22, 1)
        oled.rect(79, 15, 22, 22, 1)
        oled.fill_rect(35, 23, 6, 6, 1)
        oled.fill_rect(87, 23, 6, 6, 1)
        oled.text("SOS", 52, 42)

    elif name == "angry":
        oled.line(28, 16, 48, 25, 1)
        oled.line(80, 25, 100, 16, 1)
        oled.fill_rect(35, 25, 8, 8, 1)
        oled.fill_rect(86, 25, 8, 8, 1)
        oled.line(50, 45, 78, 40, 1)

    else:
        name = "neutral"
        oled.fill_rect(34, 20, 12, 12, 1)
        oled.fill_rect(84, 20, 12, 12, 1)
        oled.line(50, 43, 78, 43, 1)

    # Petit cadre texte en bas
    oled.line(0, 51, 127, 51, 1)
    text_line(text or name, 0, 55, 16)
    oled.show()

    state["expression"] = name
    state["screen_text"] = text or name


def beep(freq=900, duration_ms=80):
    buzzer.freq(freq)
    buzzer.duty(120)
    time.sleep_ms(duration_ms)
    buzzer.duty(0)


# =====================
# MOUVEMENTS / GESTES
# =====================
def update_pose_state():
    state["pose"] = {
        "head": head.angle,
        "left_arm": left_arm.angle,
        "right_arm": right_arm.angle,
    }


def set_pose(head_angle=None, left_angle=None, right_angle=None, smooth=True):
    if head_angle is not None:
        head.smooth_write(head_angle) if smooth else head.write(head_angle)
    if left_angle is not None:
        left_arm.smooth_write(left_angle) if smooth else left_arm.write(left_angle)
    if right_angle is not None:
        right_arm.smooth_write(right_angle) if smooth else right_arm.write(right_angle)
    update_pose_state()


def neutral_pose():
    set_pose(90, 90, 90)


def arms_down():
    set_pose(90, 155, 25)


def arms_up():
    set_pose(90, 35, 145)


def gesture_greet(repeat=1):
    draw_expression("happy", "Bonjour !")
    time.sleep_ms(400)
    set_pose(90, 90, 45)
    for _ in range(max(1, int(repeat))):
        right_arm.smooth_write(140)
        right_arm.smooth_write(55)
    time.sleep_ms(500)
    neutral_pose()
    draw_expression("happy", "Bonjour !")


def gesture_celebrate(repeat=1):
    draw_expression("happy", "Bravo !")
    beep(1200, 90)
    for _ in range(max(1, int(repeat))):
        arms_up()
        time.sleep_ms(150)
        set_pose(80, 60, 120)
        time.sleep_ms(100)
        set_pose(100, 35, 145)
    neutral_pose()


def gesture_thinking(repeat=1):
    draw_expression("thinking", "Je pense...")
    for _ in range(max(1, int(repeat))):
        set_pose(70, 120, 65)
        time.sleep_ms(250)
        set_pose(110, 120, 65)
        time.sleep_ms(250)
    set_pose(90, 120, 65)


def gesture_yes(repeat=2):
    # Sur ce prototype, la tête est simulée en rotation gauche-droite.
    draw_expression("happy", "Oui")
    for _ in range(max(1, int(repeat))):
        head.smooth_write(75)
        head.smooth_write(105)
    head.smooth_write(90)
    update_pose_state()


def gesture_no(repeat=2):
    draw_expression("sad", "Non")
    for _ in range(max(1, int(repeat))):
        head.smooth_write(45)
        head.smooth_write(135)
    head.smooth_write(90)
    update_pose_state()


def gesture_alert(repeat=1):
    repeat = max(1, min(2, int(repeat)))
    draw_expression("alert", "SOS")
    for _ in range(repeat):
        beep(1500, 100)
        set_pose(90, 40, 140, smooth=False)
        time.sleep_ms(180)
        set_pose(90, 155, 25, smooth=False)
        time.sleep_ms(180)
    set_pose(90, 90, 90, smooth=False)
    draw_expression("neutral", "Pret")


def gesture_sleep(repeat=1):
    draw_expression("sleep", "Repos")
    arms_down()


def run_gesture(name, repeat=1):
    name = (name or "neutral").lower()
    state["last_command"] = {"action": "gesture", "name": name, "repeat": repeat}

    if name in ("greet", "salut", "bonjour"):
        gesture_greet(repeat)
    elif name in ("celebrate", "bravo", "success"):
        gesture_celebrate(repeat)
    elif name in ("thinking", "think", "reflechir"):
        gesture_thinking(repeat)
    elif name in ("yes", "oui"):
        gesture_yes(repeat)
    elif name in ("no", "non"):
        gesture_no(repeat)
    elif name in ("alert", "sos"):
        gesture_alert(repeat)
    elif name in ("sleep", "repos"):
        gesture_sleep(repeat)
    else:
        neutral_pose()
        draw_expression("neutral", "Pret")


# =================
# WIFI / MQTT
# =================
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        draw_expression("thinking", "WiFi...")
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        timeout = 20
        while not wlan.isconnected() and timeout > 0:
            time.sleep(0.5)
            timeout -= 1
    state["wifi_connected"] = wlan.isconnected()
    return wlan.isconnected()


def publish_status():
    global mqtt_client
    update_pose_state()
    payload = state.copy()
    payload["timestamp_ms"] = time.ticks_ms()
    try:
        mqtt_client.publish(MQTT_TOPIC_STATUS, ujson.dumps(payload))
        print("STATUS published:", payload)
    except Exception as exc:
        state["mqtt_connected"] = False
        print("STATUS publish failed:", exc)


def on_mqtt_message(topic, msg):
    print("MQTT message:", topic, msg)
    try:
        command = ujson.loads(msg.decode())
    except Exception:
        draw_expression("alert", "JSON invalide")
        print("Invalid JSON command")
        return

    action = command.get("action", "")
    state["last_command"] = command
    print("Command action:", action, command)

    try:
        if action == "expression":
            name = command.get("name", "neutral")
            text = command.get("text", "")
            draw_expression(name, text)
            if command.get("beep", False):
                beep()

        elif action == "screen_text":
            text = command.get("text", "")
            expr = command.get("expression", state.get("expression", "neutral"))
            draw_expression(expr, text)

        elif action == "pose":
            set_pose(
                command.get("head", None),
                command.get("left_arm", None),
                command.get("right_arm", None),
                smooth=command.get("smooth", True),
            )

        elif action == "gesture":
            run_gesture(command.get("name", "neutral"), command.get("repeat", 1))

        elif action == "demo":
            demo_sequence()

        elif action == "beep":
            beep(command.get("freq", 900), command.get("duration_ms", 80))

        else:
            draw_expression("alert", "Action inconnue")
            print("Unknown action:", action)

    except Exception as e:
        draw_expression("alert", "Erreur action")
        print("Action error:", e)

    publish_status()


def connect_mqtt():
    global mqtt_client
    draw_expression("thinking", "MQTT...")
    print("Connecting MQTT:", MQTT_BROKER, MQTT_PORT)
    mqtt_client = MQTTClient(MQTT_CLIENT_ID, MQTT_BROKER, port=MQTT_PORT, keepalive=60)
    mqtt_client.set_callback(on_mqtt_message)
    mqtt_client.connect()
    mqtt_client.subscribe(MQTT_TOPIC_CMD)
    state["mqtt_connected"] = True
    print("MQTT connected, subscribed:", MQTT_TOPIC_CMD)
    draw_expression("happy", "Rafiki pret")
    publish_status()


def reconnect_mqtt():
    global mqtt_client
    print("Reconnecting MQTT...")
    try:
        if mqtt_client:
            mqtt_client.disconnect()
    except Exception:
        pass
    time.sleep(1)
    connect_mqtt()


# ==========
# DEMO LOCAL
# ==========
def demo_sequence():
    draw_expression("happy", "Salut !")
    gesture_greet(1)
    draw_expression("thinking", "Question...")
    gesture_thinking(1)
    draw_expression("happy", "Bonne reponse")
    gesture_celebrate(1)
    draw_expression("neutral", "Pret")
    neutral_pose()


# ============
# PROGRAMME
# ============
def main():
    print("Rafiki body boot")
    draw_expression("neutral", "Demarrage")
    neutral_pose()

    if connect_wifi():
        draw_expression("happy", "WiFi OK")
        print("WiFi connected")
    else:
        draw_expression("alert", "WiFi KO")
        print("WiFi failed")
        return

    try:
        connect_mqtt()
    except Exception as exc:
        draw_expression("alert", "MQTT KO")
        print("MQTT failed:", exc)
        return

    global last_status_ms
    last_status_ms = time.ticks_ms()

    while True:
        try:
            mqtt_client.check_msg()
        except Exception as exc:
            state["mqtt_connected"] = False
            print("MQTT check failed:", exc)
            try:
                reconnect_mqtt()
            except Exception as reconnect_exc:
                draw_expression("alert", "Reconnect...")
                print("MQTT reconnect failed:", reconnect_exc)
                time.sleep(2)

        now = time.ticks_ms()
        if time.ticks_diff(now, last_status_ms) > STATUS_INTERVAL_MS:
            publish_status()
            last_status_ms = now

        time.sleep_ms(50)


main()
