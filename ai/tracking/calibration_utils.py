from __future__ import annotations
import json
from pathlib import Path

import numpy as np

# 캘리브레이션 사진과 실제 프레임의 종횡비가 이 이상 벌어지면 scale_K를 신뢰할 수 없다.
# (해상도 모드 변경이 단순 리샘플이 아니라 센서 크롭인 경우 cx/cy 스케일링이 틀어진다.)
ASPECT_RATIO_TOLERANCE = 0.01

DEFAULT_REMAP_BALANCE = 0.5


class CalibrationError(ValueError):
    """캘리브레이션 파일이 없거나 형식이 잘못된 경우."""


def load_calibration(path: str) -> tuple[np.ndarray, np.ndarray, tuple[int, int]]:
    """camera_calibration.json에서 K(내부 파라미터), D(왜곡계수), 계산 당시 해상도를 읽는다."""

    file_path = Path(path)
    try:
        raw = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CalibrationError(f"캘리브레이션 파일을 읽을 수 없습니다: {file_path} ({exc})") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CalibrationError(f"캘리브레이션 파일이 올바른 JSON이 아닙니다: {file_path} ({exc})") from exc

    for key in ("K", "D", "image_size"):
        if key not in data:
            raise CalibrationError(f"캘리브레이션 파일에 '{key}' 항목이 없습니다: {file_path}")

    K = np.array(data["K"], dtype=np.float64)
    if K.shape != (3, 3):
        raise CalibrationError(f"K는 3x3이어야 합니다(현재 {K.shape}): {file_path}")

    D_raw = np.array(data["D"], dtype=np.float64).reshape(-1)
    if D_raw.size != 4:
        # cv2.fisheye 모델은 계수가 정확히 4개(k1~k4)다. 5개짜리(핀홀 모델) 값을 넣으면
        # reshape(4, 1)이 조용히 실패하거나 잘린 값으로 보정되므로 여기서 막는다.
        raise CalibrationError(f"fisheye D는 계수가 4개여야 합니다(현재 {D_raw.size}개): {file_path}")
    D = D_raw.reshape(4, 1)

    size_raw = data["image_size"]
    if not isinstance(size_raw, (list, tuple)) or len(size_raw) != 2:
        raise CalibrationError(f"image_size는 [width, height] 형식이어야 합니다: {file_path}")
    image_size = (int(size_raw[0]), int(size_raw[1]))
    if image_size[0] <= 0 or image_size[1] <= 0:
        raise CalibrationError(f"image_size가 올바르지 않습니다 {image_size}: {file_path}")

    return K, D, image_size


def scale_K(K: np.ndarray, from_size: tuple[int, int], to_size: tuple[int, int]) -> np.ndarray:
    """`from_size`(캘리브레이션 사진 해상도)에서 구한 내부 파라미터를 `to_size`(실제 프레임
    해상도)로 다시 스케일링한다.

    두 해상도가 **단순 리샘플 관계**(같은 화각, 같은 종횡비)일 때만 유효하다. 센서 크롭으로
    화각 자체가 달라지는 경우엔 cx/cy 스케일링이 틀리기 때문에, 종횡비가 어긋나면 예외를
    던진다. fisheye D는 입사각 θ에 작용하므로 해상도와 무관하다 — 스케일링하지 않는다.
    """

    if from_size == to_size:
        # 호출자가 반환값을 in-place로 수정해도 원본이 오염되지 않도록 항상 복사본을 준다.
        return K.copy()

    from_aspect = from_size[0] / from_size[1]
    to_aspect = to_size[0] / to_size[1]
    if abs(from_aspect - to_aspect) > ASPECT_RATIO_TOLERANCE:
        raise CalibrationError(
            f"캘리브레이션 해상도 {from_size}(종횡비 {from_aspect:.3f})와 프레임 해상도 "
            f"{to_size}(종횡비 {to_aspect:.3f})의 종횡비가 다릅니다. 내부 파라미터를 단순 "
            f"스케일링할 수 없으니 해당 해상도로 재캘리브레이션하세요."
        )

    sx = to_size[0] / from_size[0]
    sy = to_size[1] / from_size[1]
    scaled = K.copy()
    scaled[0, 0] *= sx  # fx
    scaled[1, 1] *= sy  # fy
    scaled[0, 2] *= sx  # cx
    scaled[1, 2] *= sy  # cy
    return scaled
