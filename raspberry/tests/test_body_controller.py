from raspberry.app.controller import build_body_commands
from raspberry.app.body_pull_client import serial_commands_for_body_command
from raspberry.app.models import RafikiDecision


def make_decision(
    *,
    emotion: str = "happy",
    movement: str = "none",
    screen_mode: str = "face",
    screen_content: str = ":)",
) -> RafikiDecision:
    return RafikiDecision(
        speech="Bonjour",
        emotion=emotion,
        movement=movement,
        screen_mode=screen_mode,
        screen_content=screen_content,
    )


def test_body_uses_emotion_for_face_behavior() -> None:
    plan = build_body_commands(make_decision(emotion="surprised"))

    assert plan.commands == ("S0", "E6", "SHOW_EYES")


def test_body_movement_overrides_emotion() -> None:
    plan = build_body_commands(make_decision(emotion="sad", movement="dance"))

    assert plan.commands == ("B2",)


def test_body_keeps_moving_face_and_servos_synchronized() -> None:
    plan = build_body_commands(make_decision(emotion="surprised", movement="swing"))

    assert plan.commands == ("B6",)


def test_body_text_mode_sends_screen_content() -> None:
    plan = build_body_commands(
        make_decision(
            emotion="thinking",
            screen_mode="text",
            screen_content="Je reflechis...\nEncore un instant.",
        )
    )

    assert plan.commands == ("S0", "TEXT:Je reflechis... Encore un instant.")


def test_body_text_mode_without_content_keeps_face() -> None:
    plan = build_body_commands(
        make_decision(
            screen_mode="text",
            screen_content="",
        )
    )

    assert plan.commands == ("S0", "E0", "SHOW_EYES")


def test_body_learning_mode_keeps_emotional_face() -> None:
    plan = build_body_commands(
        make_decision(
            emotion="thinking",
            screen_mode="learning",
            screen_content="Un texte que le modele ne doit pas afficher.",
        )
    )

    assert plan.commands == ("S0", "E4", "SHOW_EYES")


def test_body_stop_stops_behavior() -> None:
    plan = build_body_commands(make_decision(movement="stop"))

    assert plan.commands == ("S0", "E0", "SHOW_EYES")


def test_pull_expression_command_maps_to_arduino_face() -> None:
    commands = serial_commands_for_body_command(
        {"action": "set_expression", "params": {"emotion": "joie"}}
    )

    assert commands == ("E0", "SHOW_EYES")


def test_pull_gesture_command_maps_to_arduino_behavior() -> None:
    commands = serial_commands_for_body_command(
        {"action": "motor_gesture", "params": {"gesture": "danser"}}
    )

    assert commands == ("B8",)


def test_pull_screen_text_command_maps_to_text_view() -> None:
    commands = serial_commands_for_body_command(
        {"action": "screen_text", "params": {"text": "Bonjour Rafiki"}}
    )

    assert commands == ("TEXT:Bonjour Rafiki",)
