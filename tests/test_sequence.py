from __future__ import annotations

import threading
import time

from src.automation import AutomationEngine
from src.settings_manager import Settings


class FakeController:
    def __init__(self) -> None:
        self.events: list[tuple[str, str | None]] = []
        self.lock = threading.Lock()

    def key_down(self, key: str) -> None:
        with self.lock:
            self.events.append(("down", key))

    def key_up(self, key: str) -> None:
        with self.lock:
            self.events.append(("up", key))

    def release_all(self) -> None:
        with self.lock:
            self.events.append(("release_all", None))


def test_engine_repeats_sequence_and_releases_keys() -> None:
    controller = FakeController()
    settings = Settings(interval_ms=20, press_duration_ms=5, sequence=("W", "A", "S", "D"))
    engine = AutomationEngine(controller, settings)

    assert engine.start() is True
    time.sleep(0.14)
    assert engine.stop() is True

    downs = [key for action, key in controller.events if action == "down"]
    ups = [key for action, key in controller.events if action == "up"]
    assert len(downs) >= 3
    assert downs[:4] == ["W", "A", "S", "D"]
    assert downs == ups
    assert any(action == "release_all" for action, _ in controller.events)
    assert engine.is_running is False


def test_engine_does_not_create_duplicate_cycles() -> None:
    controller = FakeController()
    settings = Settings(interval_ms=40, press_duration_ms=5, sequence=("W",))
    engine = AutomationEngine(controller, settings)

    assert engine.start() is True
    assert engine.start() is False
    time.sleep(0.03)
    engine.stop()

    downs = [event for event in controller.events if event == ("down", "W")]
    assert 1 <= len(downs) <= 2


def test_stop_is_interruptible_and_releases_all() -> None:
    controller = FakeController()
    settings = Settings(interval_ms=5000, press_duration_ms=500, sequence=("W",))
    engine = AutomationEngine(controller, settings)

    engine.start()
    time.sleep(0.03)
    started_stop = time.monotonic()
    engine.stop()
    elapsed = time.monotonic() - started_stop

    assert elapsed < 0.5
    assert engine.is_running is False
    assert ("up", "W") in controller.events
    assert any(action == "release_all" for action, _ in controller.events)
