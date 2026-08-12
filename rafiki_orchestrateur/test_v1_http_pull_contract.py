"""Smoke test V1: mobile/server chat -> body command queue -> Raspberry HTTP pull.

Lancer depuis la racine du repo:
python rafiki_orchestrateur/test_v1_http_pull_contract.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from rafiki_app import app  # noqa: E402


def main() -> None:
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200, health.text
        assert health.json()["status"] == "ok"

        chat = client.post(
            "/api/chat",
            json={
                "message": "Rafiki, salue l'enfant avec ton ecran et ton bras.",
                "input_mode": "voice_mobile",
                "child_id": "test_child",
                "parent_id": "test_parent",
                "session_id": "test_session",
                "child_profile": {"name": "Amani", "age": 7},
                "parental_controls": {"safe_mode": True},
            },
        )
        assert chat.status_code == 200, chat.text
        payload = chat.json()
        assert payload["status"] == "ok"
        assert payload["reply"]

        first_pull = client.get("/api/body/next")
        assert first_pull.status_code == 200, first_pull.text
        first_command = first_pull.json()["command"]
        assert first_command["target"] == "body"
        assert first_command["action"] == "set_expression"
        assert first_command["params"]["emotion"] == "joie"

        second_pull = client.get("/api/body/next")
        assert second_pull.status_code == 200, second_pull.text
        second_command = second_pull.json()["command"]
        assert second_command["target"] == "body"
        assert second_command["action"] == "motor_gesture"
        assert second_command["params"]["gesture"] == "saluer"

        status = client.post(
            "/api/body/status",
            json={
                "status": {
                    "connected": True,
                    "last_command_id": second_command["id"],
                    "serial_commands": ["B1"],
                }
            },
        )
        assert status.status_code == 200, status.text
        assert status.json()["status"] == "ok"

    print("OK - Contrat V1 HTTP pull valide.")


if __name__ == "__main__":
    main()
