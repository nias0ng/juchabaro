"""OverlayPublisher의 게시·예외 흡수·프레임 드롭 계약 테스트."""

from __future__ import annotations

import pytest

from src.live.overlay_publisher import OverlayPublisher


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _publisher(render, clock, *, target_fps: float = 15.0) -> OverlayPublisher:
    return OverlayPublisher(render=render, target_fps=target_fps, monotonic=clock)


def test_latest_jpeg_is_none_before_any_frame() -> None:
    publisher = _publisher(lambda f, b, r: b"jpeg", _FakeClock())

    assert publisher.latest_jpeg() is None


def test_publishes_rendered_bytes_on_first_frame() -> None:
    publisher = _publisher(lambda f, b, r: b"first", _FakeClock())

    publisher(object(), object(), object())

    assert publisher.latest_jpeg() == b"first"


def test_drops_frames_arriving_faster_than_target_fps() -> None:
    clock = _FakeClock()
    rendered: list[bytes] = []

    def render(frame, tracking_batch, result) -> bytes:
        payload = f"frame-{len(rendered)}".encode("ascii")
        rendered.append(payload)
        return payload

    publisher = _publisher(render, clock, target_fps=10.0)

    publisher(object(), object(), object())
    clock.now = 0.05  # 목표 간격 0.1초의 절반 — 드롭돼야 한다
    publisher(object(), object(), object())

    assert rendered == [b"frame-0"]
    assert publisher.latest_jpeg() == b"frame-0"


def test_publishes_again_once_target_interval_has_passed() -> None:
    clock = _FakeClock()
    rendered: list[bytes] = []

    def render(frame, tracking_batch, result) -> bytes:
        payload = f"frame-{len(rendered)}".encode("ascii")
        rendered.append(payload)
        return payload

    publisher = _publisher(render, clock, target_fps=10.0)

    publisher(object(), object(), object())
    clock.now = 0.2
    publisher(object(), object(), object())

    assert rendered == [b"frame-0", b"frame-1"]
    assert publisher.latest_jpeg() == b"frame-1"


def test_swallows_render_failure_and_publishes_placeholder() -> None:
    def render(frame, tracking_batch, result) -> bytes:
        raise ValueError("render exploded")

    publisher = _publisher(render, _FakeClock())

    publisher(object(), object(), object())  # 예외가 밖으로 나오면 안 된다

    latest = publisher.latest_jpeg()
    assert latest is not None
    assert latest.startswith(b"\xff\xd8")  # JPEG SOI — placeholder가 들어갔다


def test_requires_zones_or_render() -> None:
    with pytest.raises(ValueError, match="zones 또는 render"):
        OverlayPublisher()


def test_rejects_non_positive_target_fps() -> None:
    with pytest.raises(ValueError, match="target_fps"):
        OverlayPublisher(render=lambda f, b, r: b"x", target_fps=0.0)
