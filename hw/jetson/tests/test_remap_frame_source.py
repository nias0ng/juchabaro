"""RemapFrameSource 회귀 테스트 (428, ai/training/tests/test_remap_frame_source.py에서 이관·확장).

핵심 검증 전략: "출력이 입력과 다르다" 같은 약한 단정은 잘못된 변환도 통과시킨다.
대신 **알려진 기하**를 쓴다 — 직선의 fisheye 투영(즉 휘어진 점열)을 입력으로 넣고,
보정 후 그 점들이 원래의 직선 위치로 정확히 돌아오는지 본다.
"""

import json
from datetime import datetime, timezone

import cv2
import numpy as np
import pytest
from src.camera.frame_source import FrameSourceError, RemapFrameSource
from src.camera.models import CapturedFrame

# 눈에 보일 만큼 휘게 만드는, 실제 광각 렌즈에 가까운 배럴 왜곡 계수.
FIXTURE_K = [[260.0, 0.0, 205.0], [0.0, 260.0, 148.0], [0.0, 0.0, 1.0]]
FIXTURE_D = [-0.12, 0.04, -0.01, 0.002]
FRAME_W, FRAME_H = 400, 300
LINE_Y = 90.0
BALANCE = 0.5


class FakeFrameSource:
    """capture()마다 미리 준비된 이미지를 그대로 돌려주는 테스트용 FrameSource."""

    def __init__(self, image, camera_id="cam-1"):
        self.image = image
        self.camera_id = camera_id
        self.opened = False
        self.closed = False
        self._next_frame_id = 1

    def open(self):
        self.opened = True

    def capture(self):
        frame = CapturedFrame(
            camera_id=self.camera_id,
            frame_id=self._next_frame_id,
            captured_at=datetime.now(timezone.utc),
            image=self.image,
            width=self.image.shape[1],
            height=self.image.shape[0],
            calibration_id=None,
        )
        self._next_frame_id += 1
        return frame

    def close(self):
        self.closed = True


def write_calibration(tmp_path, name="camera_calibration.json", image_size=(FRAME_W, FRAME_H), K=None, D=None):
    path = tmp_path / name
    path.write_text(
        json.dumps({"K": K or FIXTURE_K, "D": D or FIXTURE_D, "image_size": list(image_size)}),
        encoding="utf-8",
    )
    return path


def make_curved_line_image(cal_size, frame_size):
    """보정 후 y=LINE_Y의 직선이 되어야 하는, 휘어진 점열 이미지를 만든다."""
    K_cal = np.array(FIXTURE_K, dtype=np.float64)
    D = np.array(FIXTURE_D, dtype=np.float64).reshape(4, 1)

    sx = frame_size[0] / cal_size[0]
    sy = frame_size[1] / cal_size[1]
    K = K_cal.copy()
    K[0, 0] *= sx
    K[1, 1] *= sy
    K[0, 2] *= sx
    K[1, 2] *= sy

    new_K = cv2.fisheye.estimateNewCameraMatrixForUndistortRectify(
        K, D, frame_size, np.eye(3), balance=BALANCE
    )

    xs = np.linspace(60, frame_size[0] - 60, 120)
    out_pts = np.stack([xs, np.full_like(xs, LINE_Y)], axis=1)
    homog = np.concatenate([out_pts, np.ones((len(out_pts), 1))], axis=1)
    normalized = (np.linalg.inv(new_K) @ homog.T).T
    normalized = normalized[:, :2] / normalized[:, 2:3]
    in_pts = cv2.fisheye.distortPoints(
        normalized.reshape(1, -1, 2).astype(np.float64), K, D
    ).reshape(-1, 2)

    width, height = frame_size
    image = np.zeros((height, width, 3), np.uint8)
    for x, y in in_pts:
        px, py = int(round(x)), int(round(y))
        if 0 <= px < width and 0 <= py < height:
            image[py, px] = 255
    return image, in_pts


def line_residual(points):
    """점열이 직선에서 얼마나 벗어나는지(최대 잔차, px)."""
    coeffs = np.polyfit(points[:, 0], points[:, 1], 1)
    return float(np.abs(np.polyval(coeffs, points[:, 0]) - points[:, 1]).max())


def bright_pixels(image):
    ys, xs = np.nonzero(image[:, :, 0] > 64)
    return np.stack([xs, ys], axis=1).astype(float)


def test_remap_straightens_a_fisheye_projected_line(tmp_path):
    image, in_pts = make_curved_line_image((FRAME_W, FRAME_H), (FRAME_W, FRAME_H))
    # 입력이 실제로 휘어 있어야 이 테스트가 의미를 갖는다(항등변환으로는 통과 불가).
    assert line_residual(in_pts) > 3.0

    source = RemapFrameSource(
        inner=FakeFrameSource(image), calibration_path=str(write_calibration(tmp_path)), balance=BALANCE
    )
    source.open()

    out = bright_pixels(source.capture().image)

    assert len(out) > 50
    # 보정 후 점들이 원래의 직선 y=90 위로 돌아와야 한다.
    assert out[:, 1].mean() == pytest.approx(LINE_Y, abs=0.5)
    assert line_residual(out) < 2.5


def test_remap_straightens_line_when_frame_is_larger_than_calibration(tmp_path):
    """캘리브레이션(200x150)과 프레임(400x300) 해상도가 다를 때 scale_K가 실제로
    올바르게 적용되는지 — no-op이면 선이 y=237 근처로 완전히 어긋난다."""
    cal_size = (FRAME_W // 2, FRAME_H // 2)
    image, in_pts = make_curved_line_image(cal_size, (FRAME_W, FRAME_H))
    assert line_residual(in_pts) > 3.0

    source = RemapFrameSource(
        inner=FakeFrameSource(image),
        calibration_path=str(write_calibration(tmp_path, image_size=cal_size)),
        balance=BALANCE,
    )
    source.open()

    out = bright_pixels(source.capture().image)

    assert len(out) > 50
    assert out[:, 1].mean() == pytest.approx(LINE_Y, abs=0.5)


def test_rebuilds_maps_when_frame_size_changes_mid_stream(tmp_path):
    """cv2.remap은 캐시된 맵과 프레임 크기가 달라도 예외를 던지지 않고 맵 크기의
    이미지를 돌려준다 — 좌표가 조용히 오염되므로 맵을 다시 만들어야 한다."""
    inner = FakeFrameSource(np.full((FRAME_H, FRAME_W, 3), 200, np.uint8))
    source = RemapFrameSource(
        inner=inner, calibration_path=str(write_calibration(tmp_path)), balance=BALANCE
    )
    source.open()
    first = source.capture()
    assert first.image.shape == (FRAME_H, FRAME_W, 3)

    # 카메라가 해상도를 절반으로 재협상한 상황.
    inner.image = np.full((FRAME_H // 2, FRAME_W // 2, 3), 200, np.uint8)
    second = source.capture()

    assert second.image.shape == (FRAME_H // 2, FRAME_W // 2, 3)


def test_rejects_zero_sized_frame_with_frame_source_error(tmp_path):
    """빈 프레임은 하류 트래커에도 가드가 있지만, remap이 더 상류라 여기서 막지 않으면
    생짜 cv2.error가 난다."""
    source = RemapFrameSource(
        inner=FakeFrameSource(np.zeros((0, 0, 3), np.uint8)),
        calibration_path=str(write_calibration(tmp_path)),
        balance=BALANCE,
    )
    source.open()

    with pytest.raises(FrameSourceError):
        source.capture()


def test_wraps_missing_calibration_file_as_frame_source_error(tmp_path):
    source = RemapFrameSource(
        inner=FakeFrameSource(np.full((FRAME_H, FRAME_W, 3), 200, np.uint8)),
        calibration_path=str(tmp_path / "nope.json"),
        balance=BALANCE,
    )
    source.open()

    with pytest.raises(FrameSourceError):
        source.capture()


def test_reuses_calibration_across_captures(tmp_path):
    """맵 캐싱 검증 — private 속성을 들여다보는 대신 협력자 호출 횟수로 확인한다."""
    from src.camera import calibration_utils

    calls = []
    real = calibration_utils.load_calibration

    def counting(path):
        calls.append(path)
        return real(path)

    source = RemapFrameSource(
        inner=FakeFrameSource(np.full((FRAME_H, FRAME_W, 3), 200, np.uint8)),
        calibration_path=str(write_calibration(tmp_path)),
        balance=BALANCE,
    )
    source.open()
    calibration_utils.load_calibration = counting
    try:
        source.capture()
        source.capture()
        source.capture()
    finally:
        calibration_utils.load_calibration = real

    assert len(calls) == 1


def test_delegates_open_and_close_to_inner_source(tmp_path):
    inner = FakeFrameSource(np.full((FRAME_H, FRAME_W, 3), 200, np.uint8))
    source = RemapFrameSource(
        inner=inner, calibration_path=str(write_calibration(tmp_path)), balance=BALANCE
    )

    source.open()
    assert inner.opened
    source.capture()
    source.close()

    assert inner.closed
    # 맵은 1080p에서 12~22MB라 close 시 놓아준다.
    assert source._map1 is None
    assert source._map_size is None


def test_preserves_frame_id_and_timestamp(tmp_path):
    inner = FakeFrameSource(np.full((FRAME_H, FRAME_W, 3), 200, np.uint8))
    source = RemapFrameSource(
        inner=inner, calibration_path=str(write_calibration(tmp_path)), balance=BALANCE
    )
    source.open()

    first = source.capture()
    second = source.capture()

    assert (first.frame_id, second.frame_id) == (1, 2)
    assert second.captured_at >= first.captured_at


class TestNewCapturedFrameContract:
    """428: RemapFrameSource는 실제 보정을 적용하는 쪽이라 calibration_id를
    채워야 한다 — 옛 baseline판은 이 필드 자체가 없었다."""

    def test_propagates_camera_id_from_inner_source(self, tmp_path):
        inner = FakeFrameSource(np.full((FRAME_H, FRAME_W, 3), 200, np.uint8), camera_id="cam-9")
        source = RemapFrameSource(
            inner=inner, calibration_path=str(write_calibration(tmp_path)), balance=BALANCE
        )
        source.open()

        assert source.capture().camera_id == "cam-9"

    def test_sets_calibration_id_from_fingerprint(self, tmp_path):
        from src.camera.frame_source import calibration_fingerprint

        calibration_path = write_calibration(tmp_path)
        expected = calibration_fingerprint(calibration_path, BALANCE)["calibrationSha256"]

        inner = FakeFrameSource(np.full((FRAME_H, FRAME_W, 3), 200, np.uint8))
        source = RemapFrameSource(
            inner=inner, calibration_path=str(calibration_path), balance=BALANCE
        )
        source.open()

        assert source.capture().calibration_id == expected

    def test_calibration_id_changes_with_calibration_file(self, tmp_path):
        """구역 polygon과 좌표계가 다른데도 같은 calibration_id면 불일치를 놓친다."""
        K_a = [[260.0, 0.0, 205.0], [0.0, 260.0, 148.0], [0.0, 0.0, 1.0]]
        K_b = [[999.0, 0.0, 205.0], [0.0, 999.0, 148.0], [0.0, 0.0, 1.0]]
        cal_a = write_calibration(tmp_path, name="a.json", K=K_a)
        cal_b = write_calibration(tmp_path, name="b.json", K=K_b)

        image = np.full((FRAME_H, FRAME_W, 3), 200, np.uint8)
        source_a = RemapFrameSource(inner=FakeFrameSource(image), calibration_path=str(cal_a), balance=BALANCE)
        source_b = RemapFrameSource(inner=FakeFrameSource(image), calibration_path=str(cal_b), balance=BALANCE)
        source_a.open()
        source_b.open()

        assert source_a.capture().calibration_id != source_b.capture().calibration_id
