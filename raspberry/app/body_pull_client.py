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


def command_duration_ms(command: Dict[str, Any]) -> int:
    if command.get("action") != "motor_gesture":
        return 0
    params = command.get("params", {})
    if not isinstance(params, dict):
        params = {}
    default_durations = {
        "saluer": 900,
        "wave": 900,
        "danser": 1500,
        "dance": 1500,
        "hocher_tete": 700,
        "nod": 700,
        "tourner_gauche": 700,
        "tourner_droite": 700,
        "stop": 0,
    }
    gesture = str(params.get("gesture", "stop")).strip().lower()
    duration = int(params.get("duration_ms", default_durations.get(gesture, 800)))
    return max(0, min(duration, 3000))


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


def post_status(brain_url: str, session_id: str, status: Dict[str, Any]) -> bool:
    try:
        response = requests.post(
            f"{brain_url}/api/body/status",
            params={"session_id": session_id},
            json={"status": status},
            timeout=2,
        )
        response.raise_for_status()
        return True
    except requests.RequestException as exc:
        print(f"Statut corps non envoyé au PC: {exc}", flush=True)
        return False


def run(
    *,
    brain_url: str,
    body_port: str,
    baudrate: int,
    poll_interval: float,
    idle_interval: float,
    status_interval: float,
    session_id: str,
) -> int:
    body = ArduinoSerialBodyController(port=body_port, baudrate=baudrate)
    body.prepare()
    base_status = {
        "connected": True,
        "transport": "http_pull",
        "controller": "arduino_serial",
        "body_port": body_port,
        "baudrate": baudrate,
        "error": None,
    }
    if post_status(brain_url, session_id, base_status):
        print(
            f"Corps Rafiki connecté au PC: {brain_url} | Arduino: {body_port}",
            flush=True,
        )
    else:
        print(
            "Corps Arduino prêt, mais le PC Rafiki ne reçoit pas encore son heartbeat.",
            flush=True,
        )
    last_status_at = time.monotonic()

    try:
        while True:
            if time.monotonic() - last_status_at >= status_interval:
                post_status(brain_url, session_id, base_status)
                last_status_at = time.monotonic()
            try:
                response = requests.get(
                    f"{brain_url}/api/body/next",
                    params={"session_id": session_id},
                    timeout=5,
                )
                response.raise_for_status()
                payload = response.json()
            except requests.RequestException as exc:
                if time.monotonic() - last_status_at >= status_interval:
                    post_status(
                        brain_url,
                        session_id,
                        {**base_status, "connected": False, "error": str(exc)},
                    )
                    last_status_at = time.monotonic()
                time.sleep(idle_interval)
                continue

            command = payload.get("command")
            if not command:
                time.sleep(idle_interval)
                continue

            serial_commands = serial_commands_for_body_command(command)
            if serial_commands:
                print(
                    f"Commande reçue: {command.get('action')} -> {', '.join(serial_commands)}",
                    flush=True,
                )
                body.write_commands(serial_commands)
                if command.get("action") == "motor_gesture":
                    duration = command_duration_ms(command)
                    if duration > 0 and "BSTOP" not in serial_commands:
                        time.sleep(duration / 1000.0)
                        body.write_commands(("BSTOP",))
            post_status(
                brain_url,
                session_id,
                {
                    **base_status,
                    "last_command_id": command.get("id"),
                    "last_action": command.get("action"),
                    "serial_commands": list(serial_commands),
                    "duration_ms": command_duration_ms(command),
                },
            )
            time.sleep(poll_interval)
    finally:
        body.close()


def main() -> int:
    import sys
    from pathlib import Path
    # Résoudre le chemin de la racine pour importer shared
    repo_root = Path(__file__).resolve().parent.parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    parser = argparse.ArgumentParser(description="Rafiki Raspberry HTTP pull body client")
    parser.add_argument("--brain-url", default="", help="URL du cerveau PC (laisser vide pour la decouverte automatique)")
    parser.add_argument("--body-port", default="/dev/ttyACM0")
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--poll-interval", type=float, default=0.2)
    parser.add_argument("--idle-interval", type=float, default=0.5)
    parser.add_argument("--status-interval", type=float, default=5.0)
    parser.add_argument("--session-id", default="default_session")
    args = parser.parse_args()

    brain_url = args.brain_url.strip()
    if not brain_url:
        from shared.discovery import discover_brain_url
        discovered = discover_brain_url()
        if discovered:
            brain_url = discovered
        else:
            brain_url = "http://127.0.0.1:7860"
            print(f"Decouverte automatique echouee. Utilisation par defaut de : {brain_url}")

    try:
        return run(
            brain_url=brain_url.rstrip("/"),
            body_port=args.body_port,
            baudrate=args.baudrate,
            poll_interval=args.poll_interval,
            idle_interval=args.idle_interval,
            status_interval=max(2.0, args.status_interval),
            session_id=args.session_id,
        )
    except BodyControlError as exc:
        print(f"Erreur corps Rafiki: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
