"""영상 파일·웹캠 입력을 보정 좌표계의 ``CapturedFrame``으로 변환한다.

``FrameSource``는 장치 생명주기와 RGB frame 공급만 소유한다. 촬영·보정
실패는 ``FrameSourceError``에 비신뢰 ``ObservationStatus``와 발생 시각을
담아 application으로 전달한다. 실제 웹캠은 벽시계, 영상 리플레이는 영상
시간을 사용하며, fisheye 보정은 ``RemapFrameSource``가 담당한다.
"""

from __future__ import annotations

import hashlib
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

from src.camera.calibration_utils import DEFAULT_REMAP_BALANCE
from src.camera.models import CapturedFrame
from src.domain.models import (
    ObservationReason,
    ObservationState,
    ObservationStatus,
    require_aware,
)

LOGGER = logging.getLogger(__name__)

# 영상 시간의 기준점. 고정값이라 같은 영상·같은 설정이면 항상 같은 타임스탬프가 나온다.
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class FrameSourceError(RuntimeError):
    """프레임 공급 실패와 그 시점의 비신뢰 관측을 함께 전달한다."""

    def __init__(
        self,
        message: str,
        *,
        state: ObservationState = ObservationState.UNKNOWN,
        reason: ObservationReason = ObservationReason.CAMERA_UNAVAILABLE,
        observed_at: datetime | None = None,
    ) -> None:
        super().__init__(message)
        if state is ObservationState.OBSERVED:
            raise ValueError("FrameSourceError cannot carry OBSERVED state")
        self.observed_at = observed_at or datetime.now(timezone.utc)
        require_aware(self.observed_at, "observed_at")
        self.observation = ObservationStatus(state=state, reason=reason)


class EndOfVideo(FrameSourceError):
    """영상의 프레임이 모두 소진되었음을 알린다. 정상 종료 신호다."""


class FrameSource(Protocol):
    """프레임 공급자의 초기화, 촬영, 해제 생명주기 계약."""

    def open(self) -> None:
        """프레임 공급자를 한 번 초기화한다."""

    def capture(self) -> CapturedFrame:
        """RGB uint8 프레임 한 장을 촬영한다."""

    def close(self) -> None:
        """프레임 공급자의 자원을 해제한다."""


def _import_cv2() -> Any:
    try:
        import cv2
    except ImportError as exc:
        raise FrameSourceError(
            f"OpenCV import에 실패했습니다. `pip install opencv-python`으로 설치하세요. 원인: {exc}",
            reason=ObservationReason.DEPENDENCY_UNAVAILABLE,
        ) from exc
    return cv2


def calibration_fingerprint(calibration_path: Path | None, balance: float) -> dict[str, Any]:
    """zone 폴리곤이 어떤 보정 좌표계에서 찍혔는지 식별하는 지문.

    remap은 1080p/balance 0.5에서 픽셀을 평균 44px, 최대 133px 옮긴다. 보정 없이 찍은
    구 zone 파일을 보정과 함께 쓰면 아무 에러 없이 폴리곤이 그만큼 어긋나 위반 판정이
    전부 틀어지므로, 캡처 시점의 설정을 기록해두고 실행 시 비교한다.
    """

    if calibration_path is None:
        return {"remap": False}
    try:
        digest = hashlib.sha256(calibration_path.read_bytes()).hexdigest()[:16]
    except OSError as exc:
        raise FrameSourceError(
            f"calibration 파일을 읽을 수 없습니다({calibration_path}): {exc}",
            reason=ObservationReason.DEPENDENCY_UNAVAILABLE,
        ) from exc
    return {"remap": True, "calibrationSha256": digest, "balance": round(float(balance), 6)}


def normalize_fingerprint(raw: Mapping[str, Any]) -> dict[str, Any]:
    """서버·캐시·사이드카에서 온 지문을 비교 가능한 정규형으로 바꾼다.

    dict를 통째로 비교하면 두 군데서 깨진다. remap=False일 때 이 파일은
    {"remap": False} 한 키만 만들지만 서버는 나머지를 null로 채워 보내고, balance는
    MySQL DECIMAL(8,6)을 거치며 0.5가 0.500000으로 돌아온다. 둘 다 정상 상황인데
    불일치로 판정되면 기동이 거부된다.
    """

    if not bool(raw.get("remap", False)):
        return {"remap": False}
    try:
        return {
            "remap": True,
            "calibrationSha256": str(raw["calibrationSha256"]).lower(),
            "balance": round(float(raw["balance"]), 6),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise FrameSourceError(
            f"calibration 지문 형식이 올바르지 않습니다: {raw!r} ({exc})",
            reason=ObservationReason.DEPENDENCY_UNAVAILABLE,
        ) from exc


@dataclass
class VideoFileFrameSource:
    """mp4를 프레임 단위로 읽어 영상 시간이 찍힌 CapturedFrame을 만든다.

    captured_at을 벽시계(datetime.now)가 아니라 `t0 + frame_index / fps`로 찍는 것이
    이 클래스의 존재 이유다 — 정차 판정이 전부 captured_at에서 계산되므로, 이 값이
    영상 시간이면 10분짜리 정차 시나리오를 실시간을 기다리지 않고 검증할 수 있고,
    같은 입력에 항상 같은 판정이 나온다.

    보정을 직접 하지 않으므로 `calibration_id`는 항상 None이다 — 왜곡 보정이
    필요하면 이 소스를 `RemapFrameSource`로 감싼다.
    """

    camera_id: str
    path: Path
    t0: datetime = EPOCH
    start_seconds: float = 0.0
    end_seconds: float | None = None
    _capture: Any | None = field(default=None, init=False, repr=False)
    _fps: float = field(default=0.0, init=False, repr=False)
    _frame_size: tuple[int, int] = field(default=(0, 0), init=False, repr=False)
    _frame_count: int = field(default=0, init=False, repr=False)
    _next_index: int = field(default=0, init=False, repr=False)
    _next_frame_id: int = field(default=1, init=False, repr=False)
    _exhausted: bool = field(default=False, init=False, repr=False)

    @property
    def fps(self) -> float:
        """영상의 초당 프레임 수. open() 이후에만 유효하다."""

        return self._fps

    @property
    def frame_size(self) -> tuple[int, int]:
        """(width, height). open() 이후에만 유효하다."""

        return self._frame_size

    @property
    def duration_seconds(self) -> float:
        """영상 전체 길이(초). end_seconds로 자른 구간이 아니라 원본 길이다."""

        return self._frame_count / self._fps if self._fps else 0.0

    def open(self) -> None:
        """영상을 열고 fps·해상도를 읽는다. start_seconds 지점으로 이동한다."""

        if self._capture is not None:
            return
        if not self.path.exists():
            raise FrameSourceError(
                f"영상 파일이 없습니다: {self.path}",
                reason=ObservationReason.DEPENDENCY_UNAVAILABLE,
            )
        cv2 = _import_cv2()
        capture = cv2.VideoCapture(str(self.path))
        if not capture.isOpened():
            capture.release()
            raise FrameSourceError(
                f"영상 파일을 열 수 없습니다: {self.path}",
                reason=ObservationReason.DEPENDENCY_UNAVAILABLE,
            )
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        if not math.isfinite(fps) or fps <= 0.0:
            capture.release()
            # fps를 모르면 captured_at을 만들 수 없고, 그러면 정차 시간 판정 전체가
            # 무의미해진다. 임의값으로 진행하면 조용히 틀린 결과가 나온다.
            raise FrameSourceError(
                f"영상의 fps를 읽을 수 없습니다(fps={fps}): {self.path}",
                reason=ObservationReason.DEPENDENCY_UNAVAILABLE,
            )
        self._fps = fps
        self._frame_size = (
            int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )
        self._frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        self._next_index = max(0, int(self.start_seconds * fps))
        if self._next_index:
            capture.set(cv2.CAP_PROP_POS_FRAMES, self._next_index)
        self._capture = capture

    def capture(self) -> CapturedFrame:
        """다음 프레임을 RGB로 반환한다. 소진되면 EndOfVideo를 던진다."""

        if self._capture is None:
            raise FrameSourceError(
                "영상이 초기화되지 않았습니다. open()을 먼저 호출하세요.",
                reason=ObservationReason.PIPELINE_STALLED,
            )
        if self._exhausted:
            raise EndOfVideo(f"영상의 프레임이 소진되었습니다: {self.path}")
        if self.end_seconds is not None and self._next_index >= self.end_seconds * self._fps:
            self._exhausted = True
            raise EndOfVideo(f"end_seconds({self.end_seconds}s)에 도달했습니다: {self.path}")
        cv2 = _import_cv2()
        ok, frame_bgr = self._capture.read()
        if not ok or frame_bgr is None:
            self._exhausted = True
            raise EndOfVideo(f"영상의 프레임이 소진되었습니다: {self.path}")
        image = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        frame = CapturedFrame(
            camera_id=self.camera_id,
            frame_id=self._next_frame_id,
            captured_at=self.t0 + timedelta(seconds=self._next_index / self._fps),
            image=image,
            width=self._frame_size[0],
            height=self._frame_size[1],
            calibration_id=None,
        )
        self._next_index += 1
        self._next_frame_id += 1
        return frame

    def close(self) -> None:
        """영상 핸들을 해제한다."""

        capture, self._capture = self._capture, None
        if capture is not None:
            capture.release()


@dataclass
class OpenCvWebcamFrameSource:
    """일반 웹캠에서 벽시계 시각이 찍힌 RGB 프레임을 공급한다.

    `width`/`height`는 카메라에 요청하는 해상도일 뿐이다 — 장치가 그 값을
    그대로 못 맞출 수 있어서, `CapturedFrame.width`/`height`는 실제로 캡처된
    프레임에서 계산한다. 0이면 요청 자체를 생략하고 장치 기본값을 쓴다.

    `captured_at`은 벽시계 시각이다 — 실시간 장치라 `VideoFileFrameSource`처럼
    "영상 시간"을 재현할 방법이 없다. 결정론적 검증이 필요하면 리플레이
    (`VideoFileFrameSource`)를 쓴다.
    """

    camera_id: str
    camera_index: int
    width: int = 0
    height: int = 0
    _capture: Any | None = field(default=None, init=False, repr=False)
    _next_frame_id: int = field(default=1, init=False, repr=False)

    def __post_init__(self) -> None:
        # 음수 인덱스를 cv2.VideoCapture에 그대로 넘기면 백엔드마다 다르게
        # 반응하므로 구성 시점에 거부한다.
        if self.camera_index < 0:
            raise ValueError(f"camera_index는 음수일 수 없습니다: {self.camera_index}")
        # 0은 "요청 생략"(장치 기본 해상도 사용)이라는 의미가 있어 허용하지만,
        # 음수는 truthy라 0과 같은 취급을 못 받고 그대로 capture.set()에 넘어가
        # cv2가 정의하지 않은 값을 받게 된다.
        if self.width < 0 or self.height < 0:
            raise ValueError(f"width/height는 음수일 수 없습니다: width={self.width}, height={self.height}")

    def open(self) -> None:
        """웹캠 장치를 연다. 이미 열려 있으면 아무 일도 하지 않는다."""

        if self._capture is not None:
            return
        cv2 = _import_cv2()
        capture = cv2.VideoCapture(self.camera_index)
        if self.width:
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        if self.height:
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        if not capture.isOpened():
            capture.release()
            raise FrameSourceError(f"웹캠 장치를 열 수 없습니다: index={self.camera_index}")
        self._capture = capture

    def capture(self) -> CapturedFrame:
        """다음 프레임을 RGB로 반환한다."""

        if self._capture is None:
            raise FrameSourceError(
                "웹캠이 초기화되지 않았습니다. open()을 먼저 호출하세요.",
                reason=ObservationReason.PIPELINE_STALLED,
            )
        cv2 = _import_cv2()
        ok, frame_bgr = self._capture.read()
        if not ok or frame_bgr is None:
            raise FrameSourceError(f"웹캠 프레임 캡처에 실패했습니다: index={self.camera_index}")
        try:
            image = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        except cv2.error as error:
            raise FrameSourceError(
                "웹캠 프레임 형식을 RGB로 변환할 수 없습니다.",
                state=ObservationState.DEGRADED,
                reason=ObservationReason.PARTIAL_FRAME,
            ) from error
        height, width = image.shape[:2]
        frame = CapturedFrame(
            camera_id=self.camera_id,
            frame_id=self._next_frame_id,
            captured_at=datetime.now(timezone.utc),
            image=image,
            width=width,
            height=height,
            calibration_id=None,
        )
        self._next_frame_id += 1
        return frame

    def close(self) -> None:
        """웹캠 장치를 해제한다. 열린 적이 없으면 아무 일도 하지 않는다."""

        capture, self._capture = self._capture, None
        if capture is not None:
            capture.release()


class RemapFrameSource:
    """다른 FrameSource가 공급하는 프레임에 fisheye remap(왜곡 보정)을 씌운다.

    보정 맵은 첫 프레임의 실제 크기를 확인한 뒤 한 번만 계산해 재사용한다
    (캘리브레이션 사진 해상도와 카메라 해상도가 다르면 자동으로 스케일링). 스트림
    중간에 해상도가 바뀌면(USB 재연결·v4l2 재협상) 캐시된 맵이 조용히 잘못된 좌표를
    만들기 때문에 — cv2.remap은 크기가 달라도 예외를 던지지 않고 원본 맵 크기의
    이미지를 반환한다 — 매 프레임 크기를 확인하고 달라지면 맵을 다시 만든다.

    이 클래스가 실제로 보정을 적용하므로, 나가는 프레임의 `calibration_id`를
    `calibration_fingerprint()`의 해시로 채운다 — 구역 polygon과 같은
    calibration_id 좌표계인지 검증할 수 있게 하기 위함이다(데이터흐름.md §1).
    """

    def __init__(
        self,
        *,
        inner: FrameSource,
        calibration_path: str,
        balance: float = DEFAULT_REMAP_BALANCE,
    ) -> None:
        self._inner = inner
        self._calibration_path = calibration_path
        self._balance = balance
        self._map1: Any | None = None
        self._map2: Any | None = None
        self._map_size: tuple[int, int] | None = None
        self._dst: Any | None = None
        self._calibration_id: str | None = None

    def open(self) -> None:
        self._inner.open()

    def capture(self) -> CapturedFrame:
        frame = self._inner.capture()
        cv2 = _import_cv2()
        frame_size = self._frame_size(frame.image)
        if self._map1 is None or frame_size != self._map_size:
            if self._map_size is not None:
                LOGGER.warning(
                    "프레임 해상도가 %s에서 %s로 바뀌어 보정 맵을 다시 만듭니다.", self._map_size, frame_size
                )
            self._map1, self._map2 = self._build_maps(frame_size, cv2)
            self._map_size = frame_size
            self._dst = None
            self._calibration_id = calibration_fingerprint(
                Path(self._calibration_path), self._balance
            ).get("calibrationSha256")
        # dst 버퍼를 재사용해 프레임당 수 MB 할당을 없앤다(측정상 30% 이상 빠름).
        try:
            undistorted = cv2.remap(
                frame.image,
                self._map1,
                self._map2,
                interpolation=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_CONSTANT,
                dst=self._dst,
            )
        except cv2.error as error:
            raise FrameSourceError(
                "프레임 왜곡 보정에 실패했습니다.",
                state=ObservationState.DEGRADED,
                reason=ObservationReason.PARTIAL_FRAME,
                observed_at=frame.captured_at,
            ) from error
        self._dst = undistorted
        return CapturedFrame(
            camera_id=frame.camera_id,
            frame_id=frame.frame_id,
            captured_at=frame.captured_at,
            image=undistorted,
            width=frame_size[0],
            height=frame_size[1],
            calibration_id=self._calibration_id,
        )

    @staticmethod
    def _frame_size(image: Any) -> tuple[int, int]:
        """(width, height)를 돌려주되, 보정 맵을 만들 수 없는 프레임은 미리 걸러낸다.

        하류 트래커에도 같은 가드가 있지만(빈 프레임에서 ZeroDivisionError 방지),
        remap은 그보다 상류라 여기서 막지 않으면 cv2.remap이 생짜 cv2.error를 던진다.
        """

        shape = getattr(image, "shape", None)
        if shape is None or len(shape) < 2:
            raise FrameSourceError(
                "프레임 이미지 크기를 확인할 수 없습니다.",
                state=ObservationState.DEGRADED,
                reason=ObservationReason.PARTIAL_FRAME,
            )
        height, width = int(shape[0]), int(shape[1])
        if height <= 0 or width <= 0:
            raise FrameSourceError(
                "프레임 크기가 올바르지 않아 왜곡 보정을 할 수 없습니다: "
                f"shape={shape}",
                state=ObservationState.DEGRADED,
                reason=ObservationReason.PARTIAL_FRAME,
            )
        return width, height

    def _build_maps(self, frame_size: tuple[int, int], cv2: Any) -> tuple[Any, Any]:
        from src.camera import calibration_utils
        import numpy as np

        try:
            K_cal, D, cal_size = calibration_utils.load_calibration(self._calibration_path)
            K = calibration_utils.scale_K(K_cal, cal_size, frame_size)
        except calibration_utils.CalibrationError as exc:
            raise FrameSourceError(
                str(exc),
                reason=ObservationReason.DEPENDENCY_UNAVAILABLE,
            ) from exc
        if cal_size != frame_size:
            LOGGER.info("캘리브레이션 해상도 %s를 프레임 해상도 %s로 스케일링했습니다.", cal_size, frame_size)
        try:
            new_K = cv2.fisheye.estimateNewCameraMatrixForUndistortRectify(
                K,
                D,
                frame_size,
                np.eye(3),
                balance=self._balance,
            )
            return cv2.fisheye.initUndistortRectifyMap(
                K,
                D,
                np.eye(3),
                new_K,
                frame_size,
                cv2.CV_16SC2,
            )
        except cv2.error as error:
            raise FrameSourceError(
                "calibration 값으로 왜곡 보정 맵을 만들 수 없습니다.",
                reason=ObservationReason.DEPENDENCY_UNAVAILABLE,
            ) from error

    def close(self) -> None:
        # 맵/버퍼는 1080p에서 12~22MB라, 재연결 루프가 추가될 경우를 대비해 여기서 놓아준다.
        self._map1 = None
        self._map2 = None
        self._map_size = None
        self._dst = None
        self._inner.close()


class CropFrameSource:
    """다른 FrameSource가 공급하는 프레임의 좌우 여백을 잘라낸다.

    `RemapFrameSource` 뒤에 놓아 이미 보정이 끝난 프레임을 자르는 용도다.
    `calibration_id`는 캘리브레이션 파일 자체의 지문이라 crop과 무관하므로
    그대로 통과시킨다(`calibration_fingerprint()` 참고) — crop을 껴 넣어도
    캘리브레이션 재작업이나 zones 파일의 `calibrationReference` 변경이 필요
    없다. zone polygon만 새 폭 기준으로 재정규화하면 된다
    (`scripts/recrop_zone_definition.py`).
    """

    def __init__(
        self,
        *,
        inner: FrameSource,
        crop_left_px: int = 0,
        crop_right_px: int = 0,
    ) -> None:
        if crop_left_px < 0:
            raise ValueError(f"crop_left_px는 음수일 수 없습니다: {crop_left_px}")
        if crop_right_px < 0:
            raise ValueError(f"crop_right_px는 음수일 수 없습니다: {crop_right_px}")
        self._inner = inner
        self._crop_left_px = crop_left_px
        self._crop_right_px = crop_right_px

    def open(self) -> None:
        self._inner.open()

    def capture(self) -> CapturedFrame:
        frame = self._inner.capture()
        width = frame.width
        total_crop = self._crop_left_px + self._crop_right_px
        if total_crop >= width:
            raise FrameSourceError(
                "crop 합이 프레임 폭 이상입니다: "
                f"crop_left_px={self._crop_left_px}, crop_right_px={self._crop_right_px}, width={width}",
                state=ObservationState.DEGRADED,
                reason=ObservationReason.PARTIAL_FRAME,
                observed_at=frame.captured_at,
            )
        right_bound = width - self._crop_right_px
        cropped_image = frame.image[:, self._crop_left_px:right_bound]
        return CapturedFrame(
            camera_id=frame.camera_id,
            frame_id=frame.frame_id,
            captured_at=frame.captured_at,
            image=cropped_image,
            width=right_bound - self._crop_left_px,
            height=frame.height,
            calibration_id=frame.calibration_id,
        )

    def close(self) -> None:
        self._inner.close()
