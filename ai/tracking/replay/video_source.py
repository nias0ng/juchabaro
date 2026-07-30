"""녹화된 영상 파일을 baseline의 FrameSource로 공급한다."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
from typing import Any

from jetson_vehicle_tracking_baseline import BaselineError, CapturedFrame, _import_cv2

# 영상 시간의 기준점. 고정값이라 같은 영상·같은 설정이면 항상 같은 타임스탬프가 나온다.
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class EndOfVideo(BaselineError):
    """영상의 프레임이 모두 소진되었음을 알린다. 정상 종료 신호다."""


@dataclass
class VideoFileFrameSource:
    """mp4를 프레임 단위로 읽어 영상 시간이 찍힌 CapturedFrame을 만든다.

    captured_at을 벽시계(datetime.now)가 아니라 `t0 + frame_index / fps`로 찍는 것이
    이 클래스의 존재 이유다. ViolationMonitor는 정차 시간·유예 시간을 전부
    captured_at에서 계산하므로, 이 값이 영상 시간이면 10분짜리 정차 시나리오를
    실시간을 기다리지 않고 검증할 수 있고, 같은 입력에 항상 같은 판정이 나온다.
    """

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
            raise BaselineError(f"영상 파일이 없습니다: {self.path}")
        cv2 = _import_cv2()
        capture = cv2.VideoCapture(str(self.path))
        if not capture.isOpened():
            capture.release()
            raise BaselineError(f"영상 파일을 열 수 없습니다: {self.path}")
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        if not math.isfinite(fps) or fps <= 0.0:
            capture.release()
            # fps를 모르면 captured_at을 만들 수 없고, 그러면 정차 시간 판정 전체가
            # 무의미해진다. 임의값으로 진행하면 조용히 틀린 결과가 나온다.
            raise BaselineError(f"영상의 fps를 읽을 수 없습니다(fps={fps}): {self.path}")
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
            raise BaselineError("영상이 초기화되지 않았습니다. open()을 먼저 호출하세요.")
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
            frame_id=self._next_frame_id,
            captured_at=self.t0 + timedelta(seconds=self._next_index / self._fps),
            image=image,
        )
        self._next_index += 1
        self._next_frame_id += 1
        return frame

    def close(self) -> None:
        """영상 핸들을 해제한다."""

        capture, self._capture = self._capture, None
        if capture is not None:
            capture.release()
