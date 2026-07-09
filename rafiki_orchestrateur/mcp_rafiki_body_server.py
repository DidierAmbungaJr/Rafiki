"""
MCP Server - Rafiki Body Wokwi
==============================
Expose à l'agent LLM les outils MCP pour piloter le corps Rafiki simulé dans Wokwi.

Transport recommandé : stdio avec fastmcp.
Ce serveur communique avec le projet Wokwi via MQTT :
- Publie les commandes sur : rafiki/468994098570147841/body/cmd
- Écoute le statut sur    : rafiki/468994098570147841/body/status

Important : ne pas utiliser print() vers stdout dans un serveur MCP stdio.
Les logs passent par stderr pour ne pas casser le protocole MCP.
"""

from __future__ import annotations

import json
import os
import sys
import time
import threading
from typing import Any, Dict, Optional

import paho.mqtt.client as mqtt
from fastmcp import FastMCP

mcp = FastMCP("Rafiki Body Wokwi")

MQTT_BROKER = os.getenv("RAFIKI_BODY_MQTT_BROKER", "broker.emqx.io")
MQTT_PORT = int(os.getenv("RAFIKI_BODY_MQTT_PORT", "1883"))
TOPIC_CMD = os.getenv("RAFIKI_BODY_CMD_TOPIC", "rafiki/468994098570147841/body/cmd")
TOPIC_STATUS = os.getenv("RAFIKI_BODY_STATUS_TOPIC", "rafiki/468994098570147841/body/status")
CLIENT_ID = os.getenv("RAFIKI_BODY_MCP_CLIENT_ID", f"rafiki_body_mcp_{int(time.time())}")

VALID_EXPRESSIONS = {
    "neutral",
    "happy",
    "sad",
    "thinking",
    "surprise",
    "sleep",
    "alert",
    "angry",
}

VALID_GESTURES = {
    "neutral",
    "greet",
    "salut",
    "bonjour",
    "celebrate",
    "bravo",
    "success",
    "thinking",
    "think",
    "reflechir",
    "yes",
    "oui",
    "no",
    "non",
    "alert",
    "sos",
    "sleep",
    "repos",
}

latest_status: Dict[str, Any] = {}
status_lock = threading.Lock()
mqtt_connected = False
last_command_sent: Optional[Dict[str, Any]] = None


def log(message: str) -> None:
    print(f"[RafikiBodyMCP] {message}", file=sys.stderr, flush=True)


def wait_for_mqtt_connection(timeout_seconds: float = 2.0) -> bool:
    """Attend brièvement le callback MQTT initial.

    paho-mqtt connecte le socket de façon synchrone, mais le flag
    mqtt_connected n'est mis à jour qu'après le on_connect du loop_start().
    """
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if mqtt_connected:
            return True
        time.sleep(0.05)
    return mqtt_connected


def make_mqtt_client() -> mqtt.Client:
    """Crée un client compatible paho-mqtt v1 et v2."""
    try:
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id=CLIENT_ID)
    except Exception:
        return mqtt.Client(client_id=CLIENT_ID)


client = make_mqtt_client()


def on_connect(client: mqtt.Client, userdata: Any, flags: Dict[str, Any], rc: int) -> None:
    global mqtt_connected
    mqtt_connected = rc == 0
    log(f"Connexion MQTT rc={rc}, broker={MQTT_BROKER}:{MQTT_PORT}")
    if rc == 0:
        client.subscribe(TOPIC_STATUS)
        log(f"Abonnement statut: {TOPIC_STATUS}")


def on_disconnect(client: mqtt.Client, userdata: Any, rc: int) -> None:
    global mqtt_connected
    mqtt_connected = False
    log(f"Déconnexion MQTT rc={rc}")


def on_message(client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
    try:
        payload = msg.payload.decode("utf-8")
        data = json.loads(payload)
        with status_lock:
            latest_status.clear()
            latest_status.update(data)
        log(f"Statut reçu: {data}")
    except Exception as exc:
        log(f"Erreur parsing statut MQTT: {exc}")


client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.on_message = on_message

try:
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_start()
except Exception as exc:
    log(f"Erreur connexion MQTT: {exc}")


def publish_command(command: Dict[str, Any]) -> Dict[str, Any]:
    """Publie une commande vers Wokwi et renvoie un accusé de publication."""
    global last_command_sent
    try:
        wait_for_mqtt_connection()
        payload = json.dumps(command, ensure_ascii=False)
        info = client.publish(TOPIC_CMD, payload)
        try:
            info.wait_for_publish(timeout=2.0)
        except TypeError:
            info.wait_for_publish()
        except Exception as exc:
            log(f"Publication MQTT non confirmée immédiatement: {exc}")
        last_command_sent = command
        return {
            "status": "sent",
            "mqtt_connected": mqtt_connected,
            "topic": TOPIC_CMD,
            "mid": getattr(info, "mid", None),
            "command": command,
        }
    except Exception as exc:
        return {
            "status": "error",
            "message": f"Erreur publication MQTT: {exc}",
            "command": command,
        }


def wait_for_status_match(expected: Dict[str, Any], timeout_seconds: float = 4.0) -> Dict[str, Any]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        with status_lock:
            status = latest_status.copy()
        if status:
            matches = True
            for key, value in expected.items():
                if status.get(key) != value:
                    matches = False
                    break
            if matches:
                return {"status": "confirmed", "body": status}
        time.sleep(0.15)
    with status_lock:
        status = latest_status.copy()
    return {"status": "timeout", "expected": expected, "last_body": status}


def wait_for_last_command(action: str, name: str = "", timeout_seconds: float = 5.0) -> Dict[str, Any]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        with status_lock:
            status = latest_status.copy()
        command = status.get("last_command") if status else None
        if isinstance(command, dict) and command.get("action") == action:
            if not name or command.get("name") == name:
                return {"status": "confirmed", "body": status}
        time.sleep(0.15)
    with status_lock:
        status = latest_status.copy()
    return {"status": "timeout", "expected_action": action, "expected_name": name, "last_body": status}


def wait_for_pose_match(expected_pose: Dict[str, int], timeout_seconds: float = 6.0) -> Dict[str, Any]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        with status_lock:
            status = latest_status.copy()
        pose = status.get("pose") if status else None
        if isinstance(pose, dict):
            if all(int(pose.get(key, -1)) == int(value) for key, value in expected_pose.items()):
                return {"status": "confirmed", "body": status}
        time.sleep(0.15)
    with status_lock:
        status = latest_status.copy()
    return {"status": "timeout", "expected_pose": expected_pose, "last_body": status}


def clamp_angle(value: Optional[int], default: int = 90) -> int:
    if value is None:
        return default
    try:
        return max(0, min(180, int(value)))
    except Exception:
        return default


@mcp.tool(
    name="rafiki_body_status",
    description="Lit le dernier état reçu du corps Rafiki simulé dans Wokwi : expression, texte écran, pose des servos et connexion MQTT.",
)
def rafiki_body_status() -> Dict[str, Any]:
    wait_for_mqtt_connection()
    with status_lock:
        status = latest_status.copy()

    if not status:
        return {
            "status": "no_data_yet",
            "message": "Aucun statut reçu. Lance la simulation Wokwi et vérifie les topics MQTT.",
            "mqtt_connected": mqtt_connected,
            "expected_status_topic": TOPIC_STATUS,
            "expected_command_topic": TOPIC_CMD,
            "last_command_sent": last_command_sent,
        }

    return {
        "status": "ok",
        "mqtt_connected": mqtt_connected,
        "body": status,
        "last_command_sent": last_command_sent,
    }


@mcp.tool(
    name="rafiki_set_expression",
    description="Change l'expression du visage de Rafiki sur l'écran OLED. Expressions : neutral, happy, sad, thinking, surprise, sleep, alert, angry.",
)
def rafiki_set_expression(
    expression: str = "",
    text: str = "",
    beep: bool = False,
    emotion: Optional[str] = None,
) -> Dict[str, Any]:
    expr = (expression or emotion or "neutral").lower().strip()
    if expr not in VALID_EXPRESSIONS:
        return {
            "status": "error",
            "message": f"Expression invalide: {expression}",
            "valid_expressions": sorted(VALID_EXPRESSIONS),
        }

    command = {
        "action": "expression",
        "name": expr,
        "text": text[:32] if text else "",
        "beep": bool(beep),
    }
    return publish_command(command)


@mcp.tool(
    name="rafiki_screen_text",
    description="Affiche un message court sur l'écran OLED de Rafiki avec une expression associée.",
)
def rafiki_screen_text(text: str, expression: str = "neutral") -> Dict[str, Any]:
    expr = (expression or "neutral").lower().strip()
    if expr not in VALID_EXPRESSIONS:
        expr = "neutral"

    command = {
        "action": "screen_text",
        "text": (text or "")[:32],
        "expression": expr,
    }
    return publish_command(command)


@mcp.tool(
    name="rafiki_set_pose",
    description="Positionne directement les servomoteurs de Rafiki. Angles entre 0 et 180 : head, left_arm, right_arm.",
)
def rafiki_set_pose(
    head: Optional[int] = None,
    left_arm: Optional[int] = None,
    right_arm: Optional[int] = None,
    smooth: bool = True,
) -> Dict[str, Any]:
    command: Dict[str, Any] = {
        "action": "pose",
        "smooth": bool(smooth),
    }

    if head is not None:
        command["head"] = clamp_angle(head)
    if left_arm is not None:
        command["left_arm"] = clamp_angle(left_arm)
    if right_arm is not None:
        command["right_arm"] = clamp_angle(right_arm)

    if len(command) == 2:
        return {
            "status": "error",
            "message": "Aucun angle fourni. Donne au moins head, left_arm ou right_arm.",
        }

    publish_result = publish_command(command)
    expected_pose = {
        key: command[key]
        for key in ("head", "left_arm", "right_arm")
        if key in command
    }
    confirmation = wait_for_pose_match(expected_pose)
    return {
        "status": "confirmed" if confirmation["status"] == "confirmed" else "sent_unconfirmed",
        "mqtt_connected": mqtt_connected,
        "publish": publish_result,
        "pose_confirm": confirmation,
    }


@mcp.tool(
    name="rafiki_gesture",
    description="Exécute un geste prédéfini du corps Rafiki : greet, celebrate, thinking, yes, no, alert, sleep, neutral.",
)
def rafiki_gesture(gesture: str, repeat: int = 1) -> Dict[str, Any]:
    name = (gesture or "neutral").lower().strip()
    if name not in VALID_GESTURES:
        return {
            "status": "error",
            "message": f"Geste invalide: {gesture}",
            "valid_gestures": sorted(VALID_GESTURES),
        }

    command = {
        "action": "gesture",
        "name": name,
        "repeat": max(1, min(5, int(repeat or 1))),
    }
    return publish_command(command)


@mcp.tool(
    name="rafiki_body_demo",
    description="Lance une petite démonstration complète dans Wokwi : salut, réflexion, célébration et retour au neutre.",
)
def rafiki_body_demo() -> Dict[str, Any]:
    publish_result = publish_command({"action": "demo"})
    confirmation = wait_for_last_command("demo", timeout_seconds=15.0)
    return {
        "status": "confirmed" if confirmation["status"] == "confirmed" else "sent_unconfirmed",
        "mqtt_connected": mqtt_connected,
        "publish": publish_result,
        "demo_confirm": confirmation,
    }


@mcp.tool(
    name="rafiki_salute_child",
    description="Salue l'enfant avec l'écran OLED et le bras de Rafiki. Utiliser pour une salutation simple.",
)
def rafiki_salute_child(text: str = "Bonjour !") -> Dict[str, Any]:
    label = (text or "Bonjour !")[:32]
    screen_command = {
        "action": "screen_text",
        "text": label,
        "expression": "happy",
    }
    gesture_command = {
        "action": "gesture",
        "name": "greet",
        "repeat": 1,
    }

    screen_result = publish_command(screen_command)
    screen_confirm = wait_for_status_match({"screen_text": label}, timeout_seconds=3.0)
    if screen_confirm["status"] != "confirmed":
        screen_retry = publish_command(screen_command)
        screen_confirm = wait_for_status_match({"screen_text": label}, timeout_seconds=3.0)
    else:
        screen_retry = None

    time.sleep(0.6)
    gesture_result = publish_command(gesture_command)
    gesture_confirm = wait_for_last_command("gesture", "greet", timeout_seconds=6.0)
    if gesture_confirm["status"] != "confirmed":
        gesture_retry = publish_command(gesture_command)
        gesture_confirm = wait_for_last_command("gesture", "greet", timeout_seconds=6.0)
    else:
        gesture_retry = None

    status = "confirmed" if (
        screen_confirm["status"] == "confirmed"
        or gesture_confirm["status"] == "confirmed"
    ) else "sent_unconfirmed"
    return {
        "status": status,
        "mqtt_connected": mqtt_connected,
        "screen": screen_result,
        "screen_retry": screen_retry,
        "screen_confirm": screen_confirm,
        "gesture": gesture_result,
        "gesture_retry": gesture_retry,
        "gesture_confirm": gesture_confirm,
    }


@mcp.tool(
    name="rafiki_think",
    description="Affiche que Rafiki réfléchit et lance un petit geste de réflexion.",
)
def rafiki_think(text: str = "Je réfléchis...") -> Dict[str, Any]:
    label = (text or "Je réfléchis...")[:32]
    screen_result = publish_command(
        {
            "action": "screen_text",
            "text": label,
            "expression": "thinking",
        }
    )
    time.sleep(0.2)
    gesture_result = publish_command(
        {
            "action": "gesture",
            "name": "thinking",
            "repeat": 1,
        }
    )
    return {
        "status": "sent",
        "mqtt_connected": mqtt_connected,
        "screen": screen_result,
        "gesture": gesture_result,
    }


@mcp.tool(
    name="rafiki_alert",
    description="Affiche une alerte sur l'écran OLED et lance le geste d'alerte.",
)
def rafiki_alert(text: str = "Alerte !") -> Dict[str, Any]:
    label = (text or "Alerte !")[:32]
    expression_result = publish_command(
        {
            "action": "expression",
            "name": "alert",
            "text": label,
            "beep": True,
        }
    )
    expression_confirm = wait_for_status_match({"expression": "alert"}, timeout_seconds=3.0)
    time.sleep(0.4)
    gesture_result = publish_command(
        {
            "action": "gesture",
            "name": "alert",
            "repeat": 1,
        }
    )
    gesture_confirm = wait_for_last_command("gesture", "alert", timeout_seconds=5.0)
    status = "confirmed" if gesture_confirm["status"] == "confirmed" else "sent_unconfirmed"
    return {
        "status": status,
        "mqtt_connected": mqtt_connected,
        "expression": expression_result,
        "expression_confirm": expression_confirm,
        "gesture": gesture_result,
        "gesture_confirm": gesture_confirm,
    }


@mcp.tool(
    name="rafiki_celebrate",
    description="Félicite l'enfant avec l'écran OLED et un geste de célébration.",
)
def rafiki_celebrate(text: str = "Bravo !") -> Dict[str, Any]:
    label = (text or "Bravo !")[:32]
    expression_result = publish_command(
        {
            "action": "expression",
            "name": "happy",
            "text": label,
            "beep": True,
        }
    )
    time.sleep(0.2)
    gesture_result = publish_command(
        {
            "action": "gesture",
            "name": "celebrate",
            "repeat": 1,
        }
    )
    return {
        "status": "sent",
        "mqtt_connected": mqtt_connected,
        "expression": expression_result,
        "gesture": gesture_result,
    }


@mcp.tool(
    name="rafiki_react_to_child_result",
    description="Réaction corporelle simple selon la réponse d'un enfant : correct=true déclenche joie/bravo, correct=false déclenche encouragement/réflexion.",
)
def rafiki_react_to_child_result(correct: bool, child_name: str = "") -> Dict[str, Any]:
    if correct:
        label = f"Bravo {child_name}!" if child_name else "Bravo !"
        expression_result = publish_command({"action": "expression", "name": "happy", "text": label, "beep": True})
        time.sleep(0.2)
        gesture_result = publish_command({"action": "gesture", "name": "celebrate", "repeat": 1})
        gesture_confirm = wait_for_last_command("gesture", "celebrate", timeout_seconds=6.0)
        return {
            "status": "confirmed" if gesture_confirm["status"] == "confirmed" else "sent_unconfirmed",
            "mqtt_connected": mqtt_connected,
            "expression": expression_result,
            "gesture": gesture_result,
            "gesture_confirm": gesture_confirm,
        }

    label = f"Essaie encore {child_name}" if child_name else "Essaie encore"
    expression_result = publish_command({"action": "expression", "name": "thinking", "text": label})
    time.sleep(0.2)
    gesture_result = publish_command({"action": "gesture", "name": "thinking", "repeat": 1})
    gesture_confirm = wait_for_last_command("gesture", "thinking", timeout_seconds=6.0)
    return {
        "status": "confirmed" if gesture_confirm["status"] == "confirmed" else "sent_unconfirmed",
        "mqtt_connected": mqtt_connected,
        "expression": expression_result,
        "gesture": gesture_result,
        "gesture_confirm": gesture_confirm,
    }


@mcp.tool(
    name="rafiki_wait_for_body",
    description="Attend quelques secondes que Wokwi publie un statut. Utile après le lancement de la simulation.",
)
def rafiki_wait_for_body(timeout_seconds: int = 8) -> Dict[str, Any]:
    timeout_seconds = max(1, min(30, int(timeout_seconds)))
    wait_for_mqtt_connection()
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        with status_lock:
            if latest_status:
                return {
                    "status": "ok",
                    "message": "Corps Rafiki détecté.",
                    "body": latest_status.copy(),
                }
        time.sleep(0.2)

    return {
        "status": "timeout",
        "message": "Aucun statut reçu. Vérifie que la simulation Wokwi tourne et utilise les mêmes topics MQTT.",
        "expected_status_topic": TOPIC_STATUS,
        "expected_command_topic": TOPIC_CMD,
    }


if __name__ == "__main__":
    mcp.run()
