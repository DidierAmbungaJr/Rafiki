from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from raspberry.app.models import RafikiDecision


class BodyControlError(RuntimeError):
    """Raised when Rafiki cannot send a body command."""


class BodyController(Protocol):
    def is_available(self) -> bool:
        ...

    def prepare(self) -> None:
        ...

    def apply(self, decision: RafikiDecision) -> None:
        ...

    def stop_motion(self) -> None:
        ...

    def close(self) -> None:
        ...


EMOTION_TO_EXPRESSION = {
    "happy": 0,
    "sad": 2,
    "neutral": 4,
    "thinking": 4,
    "surprised": 6,
}

EMOTION_TO_BEHAVIOR = {
    "happy": 0,
    "sad": 2,
    "neutral": 4,
    "thinking": 7,
    "surprised": 6,
}


@dataclass(frozen=True)
class BodyCommandPlan:
    commands: tuple[str, ...]


def build_body_commands(decision: RafikiDecision) -> BodyCommandPlan:
    commands: list[str] = []

    if decision.movement == "stop":
        commands.append("S0")
    elif decision.movement == "none":
        commands.append("S0")
    else:
        # A B command owns both the face and servo animation on the Mega.
        # Using the emotion here keeps those two outputs synchronized.
        commands.append(f"B{EMOTION_TO_BEHAVIOR[decision.emotion]}")

    if _should_show_text(decision):
        commands.append(f"TEXT:{_single_line(decision.screen_content)}")
    elif decision.movement in {"none", "stop"}:
        commands.append(f"E{EMOTION_TO_EXPRESSION[decision.emotion]}")
        commands.append("SHOW_EYES")

    return BodyCommandPlan(tuple(commands))


def _single_line(text: str, limit: int = 160) -> str:
    normalized = " ".join(text.strip().split())
    return normalized[:limit]


def _should_show_text(decision: RafikiDecision) -> bool:
    return (
        decision.screen_mode in {"text", "quiz"}
        and bool(_single_line(decision.screen_content))
    )


class NullBodyController:
    def is_available(self) -> bool:
        return True

    def prepare(self) -> None:
        return

    def apply(self, decision: RafikiDecision) -> None:
        return

    def stop_motion(self) -> None:
        return

    def close(self) -> None:
        return


class LoggingBodyController:
    def is_available(self) -> bool:
        return True

    def prepare(self) -> None:
        return

    def apply(self, decision: RafikiDecision) -> None:
        plan = build_body_commands(decision)
        print("Corps >", " | ".join(plan.commands))

    def stop_motion(self) -> None:
        print("Corps > S0")

    def close(self) -> None:
        return


class CommandBodyController:
    def __init__(self, executable: str) -> None:
        self.executable = executable

    def is_available(self) -> bool:
        return bool(self.executable.strip())

    def prepare(self) -> None:
        return

    def apply(self, decision: RafikiDecision) -> None:
        payload = json.dumps(decision.model_dump(), ensure_ascii=True)
        try:
            subprocess.run([self.executable, payload], check=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise BodyControlError(f"Body command failed: {exc}") from exc

    def stop_motion(self) -> None:
        return

    def close(self) -> None:
        return


class ArduinoSerialBodyController:
    def __init__(
        self,
        port: str | Path,
        baudrate: int = 115200,
        timeout: float = 1.0,
        startup_delay: float = 8.0,
    ) -> None:
        self.port = str(port)
        self.baudrate = baudrate
        self.timeout = timeout
        self.startup_delay = startup_delay
        self._serial = None

    def is_available(self) -> bool:
        return Path(self.port).exists() and self._load_serial_module() is not None

    def prepare(self) -> None:
        self._connection()

    def apply(self, decision: RafikiDecision) -> None:
        self._write_commands(build_body_commands(decision).commands)

    def write_commands(self, commands: tuple[str, ...]) -> None:
        self._write_commands(commands)

    def stop_motion(self) -> None:
        self._write_commands(("S0",))

    def close(self) -> None:
        if self._serial is not None:
            self.stop_motion()
            self._serial.close()
            self._serial = None

    def _write_commands(self, commands: tuple[str, ...]) -> None:
        serial_conn = self._connection()
        for command in commands:
            serial_conn.write(f"{command}\n".encode("utf-8"))
            serial_conn.flush()

    def _connection(self):
        if self._serial is not None:
            return self._serial

        serial_module = self._load_serial_module()
        if serial_module is None:
            raise BodyControlError("pyserial is not installed")

        try:
            self._serial = serial_module.Serial(
                self.port,
                self.baudrate,
                timeout=self.timeout,
                write_timeout=self.timeout,
            )
            # Opening a Mega serial port toggles reset on common USB drivers.
            # Wait for setup() and the TFT boot screen before the first command.
            if self.startup_delay > 0:
                time.sleep(self.startup_delay)
            self._serial.reset_input_buffer()
        except Exception as exc:
            raise BodyControlError(
                f"Cannot open Arduino serial port {self.port}: {exc}"
            ) from exc

        return self._serial

    @staticmethod
    def _load_serial_module():
        try:
            import serial
        except ImportError:
            return None

        return serial
