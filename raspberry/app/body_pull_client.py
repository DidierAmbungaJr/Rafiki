from __future__ import annotations

import argparse
import time
from typing import Any, Dict

import requests

from raspberry.app.controller import ArduinoSerialBodyController, BodyControlError


EMOTION_TO_SERIAL = {
    "joie": "E0",
    "happy": "E0",
    "tristesse": "E2",
    "sad": "E2",
    "neutre": "E4",
    "neutral": "E4",
    "réflexion": "E7",
    "reflexion": "E7",
    "thinking": "E7",
    "curiosité": "E7",
    "curiosite": "E7",
    "surprise": "E6",
    "surprised": "E6",
    "encouragement": "E8",
}

GESTURE_TO_SERIAL = {
    "saluer": "B1",
    "wave": "B1",
    "danser": "B8",
    "dance": "B8",
    "hocher_tete": "B7",
    "nod": "B7",
    "tourner_gauche": "B7",
    "tourner_droite": "B7",
    "stop": "BSTOP",
}


def serial_commands_for_body_command(command: Dict[str, Any]) -> tuple[str, ...]:
    action = str(command.get("action", "")).strip()
    params = command.get("params", {})
    if not isinstance(params, dict):
        params = {}

    if action == "set_expression":
        emotion = str(params.get("emotion", "neutre")).strip().lower()
        serial = EMOTION_TO_SERIAL.get(emotion, "E4")
        return (serial, "SHOW_EYES")

    if action == "motor_gesture":
        gesture = str(params.get("gesture", "stop")).strip().lower()
        return (GESTURE_TO_SERIAL.get(gesture, "B7"),)

    if action == "screen_text":
        text = " ".join(str(params.get("text", "")).split())[:160]
        return (f"TEXT:{text}",) if text else ()

    if action == "status_ping":
        return ()

    return ()


def post_status(brain_url: str, status: Dict[str, Any]) -> None:
    try:
        requests.post(
            f"{brain_url}/api/body/status",
            json={"status": status},
            timeout=2,
        )
    except requests.RequestException:
        return


def run(
    *,
    brain_url: str,
    body_port: str,
    baudrate: int,
    poll_interval: float,
    idle_interval: float,
) -> int:
    body = ArduinoSerialBodyController(port=body_port, baudrate=baudrate)
    body.prepare()
    post_status(brain_url, {"connected": True, "body_port": body_port})

    try:
        while True:
            try:
                response = requests.get(f"{brain_url}/api/body/next", timeout=5)
                response.raise_for_status()
                payload = response.json()
            except requests.RequestException as exc:
                post_status(brain_url, {"connected": False, "error": str(exc)})
                time.sleep(idle_interval)
                continue

            command = payload.get("command")
            if not command:
                time.sleep(idle_interval)
                continue

            serial_commands = serial_commands_for_body_command(command)
            if serial_commands:
                body.write_commands(serial_commands)
            post_status(
                brain_url,
                {
                    "connected": True,
                    "last_command_id": command.get("id"),
                    "last_action": command.get("action"),
                    "serial_commands": list(serial_commands),
                },
            )
            time.sleep(poll_interval)
    finally:
        body.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Rafiki Raspberry HTTP pull body client")
    parser.add_argument("--brain-url", default="http://127.0.0.1:7860")
    parser.add_argument("--body-port", default="/dev/ttyACM0")
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--poll-interval", type=float, default=0.2)
    parser.add_argument("--idle-interval", type=float, default=0.5)
    args = parser.parse_args()
    try:
        return run(
            brain_url=args.brain_url.rstrip("/"),
            body_port=args.body_port,
            baudrate=args.baudrate,
            poll_interval=args.poll_interval,
            idle_interval=args.idle_interval,
        )
    except BodyControlError as exc:
        print(f"Erreur corps Rafiki: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
