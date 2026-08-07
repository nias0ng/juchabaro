"""UltralyticsVehicleTracker 기동·frame 계약 회귀 테스트.

ai/training/tests/test_tracking_baseline.py의 test_tracker_rejects_zero_sized_frame과
같은 전략으로 실제 YOLO binary·ultralytics 설치 없이 검증한다.
Fake module과 model로 `open()`의 task·class map을, `_model` stub으로
frame 크기·ByteTrack projection 계약을 확인한다.
"""

import sys
from datetime import datetime, timezone
from types import ModuleType

import numpy as np
import pytest
from src.camera.models import CapturedFrame
from src.tracking.adapters import ultralytics_bytetrack as adapter_module
from src.tracking.adapters.ultralytics_bytetrack import UltralyticsVehicleTracker
from src.tracking.models import TrackSegmentId
from src.tracking.protocols import TrackingError


class _FakeImage:
    """테스트에서 프레임 크기만 흉내 내는 최소 이미지 스텁."""

    def __init__(self, shape: tuple[int, ...]) -> None:
        self.shape = shape


class _FakeCv2:
    """테스트가 로컬 OpenCV 설치 여부에 의존하지 않게 한다."""

    COLOR_RGB2BGR = object()

    @staticmethod
    def cvtColor(image, _conversion):
        return image


@pytest.fixture(autouse=True)
def _stub_cv2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapter_module, "_import_cv2", lambda: _FakeCv2)


def _make_frame(image, *, width: int = 100, height: int = 100) -> CapturedFrame:
    return CapturedFrame(
        camera_id="cam-1",
        frame_id=1,
        captured_at=datetime.now(timezone.utc),
        image=image,
        # CapturedFrame metadata는 양수여야 하지만 adapter는 실제
        # ndarray shape를 별도로 검증한다.
        width=width,
        height=height,
        calibration_id=None,
    )


def test_track_before_open_raises():
    tracker = UltralyticsVehicleTracker(model_path="unused.pt", tracker_config="bytetrack.yaml", confidence=0.5)

    with pytest.raises(TrackingError):
        tracker.track(_make_frame(_FakeImage((100, 100, 3))))


def test_rejects_zero_sized_frame():
    """카메라가 순간적으로 빈 프레임을 반환하면 ZeroDivisionError 대신
    TrackingError로 처리되어야 한다."""
    tracker = UltralyticsVehicleTracker(model_path="unused.pt", tracker_config="bytetrack.yaml", confidence=0.5)
    tracker._model = object()  # open() 없이 track()의 프레임 크기 검증만 확인

    with pytest.raises(TrackingError):
        tracker.track(_make_frame(_FakeImage((0, 0, 3))))


def test_rejects_frame_metadata_that_does_not_match_image_shape():
    tracker = UltralyticsVehicleTracker(
        model_path="unused.pt",
        tracker_config="bytetrack.yaml",
        confidence=0.5,
    )
    tracker._model = object()

    with pytest.raises(TrackingError, match="metadata"):
        tracker.track(
            _make_frame(
                _FakeImage((80, 120, 3)),
                width=100,
                height=100,
            )
        )


def test_model_info_reflects_configured_paths_before_open():
    tracker = UltralyticsVehicleTracker(
        model_path="yolo_vehicle.pt", tracker_config="bytetrack.yaml", confidence=0.5
    )

    info = tracker.model_info

    assert info.library == "ultralytics"
    assert info.model_name == "yolo_vehicle.pt"
    assert info.tracker_config == "bytetrack.yaml"
    assert info.library_version == "not-initialized"


def test_close_before_open_does_not_raise():
    tracker = UltralyticsVehicleTracker(model_path="unused.pt", tracker_config="bytetrack.yaml", confidence=0.5)

    tracker.close()  # 예외 없이 조용히 통과해야 한다


class _RaisingModel:
    """실제 YOLO 모델 대신 추론 중 예외를 흉내 내는 더미."""

    def track(self, **kwargs):
        raise RuntimeError("추론 백엔드 오류(예: CUDA 메모리 부족)")


def test_wraps_inference_exception_as_tracking_error():
    """YOLO/ByteTrack 추론(self._model.track) 중 예외가 나면 원인을 담아
    TrackingError로 감싸야 한다 — 상위 계층(pipeline)이 카메라·OpenCV 예외와
    구분 없이 한 종류로 처리할 수 있어야 하기 때문이다."""
    tracker = UltralyticsVehicleTracker(model_path="unused.pt", tracker_config="bytetrack.yaml", confidence=0.5)
    tracker._model = _RaisingModel()
    image = np.zeros((100, 100, 3), dtype=np.uint8)

    with pytest.raises(TrackingError) as excinfo:
        tracker.track(_make_frame(image))

    assert excinfo.value.__cause__ is not None  # 원인 예외가 체이닝돼 있어야 디버깅 가능


def test_wraps_color_conversion_exception_as_tracking_error(
    monkeypatch: pytest.MonkeyPatch,
):
    class _RaisingCv2:
        COLOR_RGB2BGR = object()

        @staticmethod
        def cvtColor(_image, _conversion):
            raise RuntimeError("color conversion failed")

    monkeypatch.setattr(adapter_module, "_import_cv2", lambda: _RaisingCv2)
    tracker = UltralyticsVehicleTracker(
        model_path="unused.pt",
        tracker_config="bytetrack.yaml",
        confidence=0.5,
    )
    tracker._model = _SuccessfulModel(track_ids=())

    with pytest.raises(TrackingError) as excinfo:
        tracker.track(_make_frame(_FakeImage((100, 100, 3))))

    assert excinfo.value.__cause__ is not None


def test_close_releases_model_reference_after_being_set():
    """close() 뒤에는 모델 참조가 실제로 해제돼야 한다 — 참조가 남아있으면
    close() 이후에도 track()이 '초기화 안 됨' 대신 조용히 계속 동작할 위험이 있다."""
    tracker = UltralyticsVehicleTracker(model_path="unused.pt", tracker_config="bytetrack.yaml", confidence=0.5)
    tracker._model = _RaisingModel()

    tracker.close()

    with pytest.raises(TrackingError):
        tracker.track(_make_frame(np.zeros((100, 100, 3), dtype=np.uint8)))


class _Boxes:
    def __init__(self, *, track_ids=(), detection_count: int | None = None) -> None:
        if detection_count is None:
            detection_count = len(track_ids)
        if detection_count < len(track_ids):
            raise ValueError("detection_count cannot be smaller than tracked ID count")
        self.id = np.asarray(track_ids, dtype=float) if track_ids else None
        self.xyxy = np.asarray(
            [[10.0, 20.0, 30.0, 40.0] for _ in range(detection_count)],
            dtype=float,
        )
        self.conf = np.asarray([0.9 for _ in range(detection_count)], dtype=float)
        self.cls = np.asarray([0.0 for _ in range(detection_count)], dtype=float)


class _Result:
    def __init__(self, *, track_ids=(), detection_count: int | None = None) -> None:
        self.boxes = _Boxes(
            track_ids=track_ids,
            detection_count=detection_count,
        )


class _RemovedTrack:
    def __init__(self, track_id: int) -> None:
        self.track_id = track_id


class _ByteTrackerState:
    def __init__(self) -> None:
        self.removed_stracks: list[_RemovedTrack] = []


class _Predictor:
    def __init__(self, byte_tracker: _ByteTrackerState) -> None:
        self.trackers = [byte_tracker]


class _SuccessfulModel:
    def __init__(self, *, track_ids=(), detection_count: int | None = None) -> None:
        self.task = "detect"
        self.names = {0: "vehicle"}
        self.track_ids = track_ids
        self.detection_count = (
            len(track_ids) if detection_count is None else detection_count
        )
        self.byte_tracker = _ByteTrackerState()
        self.predictor = _Predictor(self.byte_tracker)
        self._postprocess_callbacks = []
        self.predict_calls = []
        self.track_calls = []

    def add_callback(self, event: str, callback) -> None:
        if event == "on_predict_postprocess_end":
            self._postprocess_callbacks.append(callback)

    def predict(self, **kwargs):
        self.predict_calls.append(kwargs)
        raw_result = _Result(track_ids=(), detection_count=self.detection_count)
        callback_predictor = type(
            "CallbackPredictor",
            (),
            {"results": [raw_result]},
        )()
        for callback in self._postprocess_callbacks:
            callback(callback_predictor)
        return [raw_result]

    def track(self, **kwargs):
        self.track_calls.append(kwargs)
        raw_result = _Result(track_ids=(), detection_count=self.detection_count)
        callback_predictor = type(
            "CallbackPredictor",
            (),
            {"results": [raw_result]},
        )()
        for callback in self._postprocess_callbacks:
            callback(callback_predictor)
        return [_Result(track_ids=self.track_ids)]


class _ModelWithoutTrackerInternals(_SuccessfulModel):
    def __init__(self) -> None:
        super().__init__(track_ids=())
        del self.predictor


def _attach_model(
    tracker: UltralyticsVehicleTracker,
    model,
) -> None:
    tracker._model = model
    model.add_callback(
        "on_predict_postprocess_end",
        tracker._capture_pretrack_detection_count,
    )


def _install_fake_ultralytics(
    monkeypatch: pytest.MonkeyPatch,
    model: _SuccessfulModel,
) -> None:
    module = ModuleType("ultralytics")
    module.__version__ = "test-ultralytics"
    module.YOLO = lambda _model_path: model
    monkeypatch.setitem(sys.modules, "ultralytics", module)


def test_open_accepts_detect_vehicle_single_class_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _SuccessfulModel(track_ids=())
    _install_fake_ultralytics(monkeypatch, model)
    tracker = UltralyticsVehicleTracker(
        model_path="vehicle.pt",
        tracker_config="bytetrack.yaml",
        confidence=0.5,
    )

    tracker.open()

    assert tracker._model is model
    assert tracker.model_info.library_version == "test-ultralytics"
    assert len(model._postprocess_callbacks) == 1


@pytest.mark.parametrize(
    ("task", "names", "message"),
    (
        ("segment", {0: "vehicle"}, "task"),
        ("detect", {0: "person"}, "class map"),
        ("detect", {0: "vehicle", 1: "car"}, "class map"),
    ),
)
def test_open_rejects_model_runtime_contract_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    task: str,
    names: dict[int, str],
    message: str,
) -> None:
    model = _SuccessfulModel(track_ids=())
    model.task = task
    model.names = names
    _install_fake_ultralytics(monkeypatch, model)
    tracker = UltralyticsVehicleTracker(
        model_path="vehicle.pt",
        tracker_config="bytetrack.yaml",
        confidence=0.5,
    )

    with pytest.raises(TrackingError, match=message):
        tracker.open()

    assert tracker._model is None
    assert model._postprocess_callbacks == []


def test_warm_up_uses_predict_without_creating_bytetrack_state():
    tracker = UltralyticsVehicleTracker(
        model_path="unused.pt",
        tracker_config="bytetrack.yaml",
        confidence=0.4,
        capture_detections=True,
    )
    model = _SuccessfulModel(track_ids=(7,), detection_count=1)
    _attach_model(tracker, model)
    frame = _make_frame(np.zeros((100, 100, 3), dtype=np.uint8))

    tracker.warm_up(frame)

    assert len(model.predict_calls) == 1
    assert model.track_calls == []
    assert model.predict_calls[0]["source"] is frame.image
    assert model.predict_calls[0]["conf"] == pytest.approx(0.4)
    assert model.predict_calls[0]["verbose"] is False
    assert tracker._pretrack_detection_count is None
    assert tracker._pretrack_detections is None


def test_warm_up_before_open_raises():
    tracker = UltralyticsVehicleTracker(
        model_path="unused.pt",
        tracker_config="bytetrack.yaml",
        confidence=0.5,
    )

    with pytest.raises(TrackingError, match="초기화"):
        tracker.warm_up(
            _make_frame(np.zeros((100, 100, 3), dtype=np.uint8))
        )


def test_visible_result_is_normalized_without_inventing_segment_end():
    tracker = UltralyticsVehicleTracker(
        model_path="unused.pt",
        tracker_config="bytetrack.yaml",
        confidence=0.5,
        capture_detections=True,
    )
    model = _SuccessfulModel(track_ids=(7,))
    _attach_model(tracker, model)

    result = tracker.track(_make_frame(np.zeros((100, 100, 3), dtype=np.uint8)))

    assert len(result.observations) == 1
    assert result.observations[0].track_segment_id == TrackSegmentId(7)
    assert result.all_detections_tracked is True
    assert result.ended_track_segment_ids == ()
    assert result.detection_count == 1
    assert len(result.detections) == 1
    assert result.detections[0].confidence == pytest.approx(0.9)
    assert result.detections[0].class_id == 0
    assert result.detections[0].bbox.x1 == pytest.approx(0.1)
    assert result.detections[0].bbox.y1 == pytest.approx(0.2)
    assert result.detections[0].bbox.x2 == pytest.approx(0.3)
    assert result.detections[0].bbox.y2 == pytest.approx(0.4)
    assert model.track_calls[-1]["classes"] == [0]


def test_pretrack_detection_payload_capture_is_opt_in():
    tracker = UltralyticsVehicleTracker(
        model_path="unused.pt",
        tracker_config="bytetrack.yaml",
        confidence=0.5,
    )
    _attach_model(tracker, _SuccessfulModel(track_ids=(7,)))

    result = tracker.track(_make_frame(np.zeros((100, 100, 3), dtype=np.uint8)))

    assert result.detection_count == 1
    assert result.detections == ()
    assert result.all_detections_tracked is True


def test_empty_visible_result_without_bytetrack_removal_is_not_segment_end():
    tracker = UltralyticsVehicleTracker(
        model_path="unused.pt",
        tracker_config="bytetrack.yaml",
        confidence=0.5,
    )
    _attach_model(tracker, _SuccessfulModel(track_ids=()))

    result = tracker.track(_make_frame(np.zeros((100, 100, 3), dtype=np.uint8)))

    assert result.observations == ()
    assert result.all_detections_tracked is True
    assert result.ended_track_segment_ids == ()


def test_tentative_detection_without_track_id_marks_frame_untrusted():
    tracker = UltralyticsVehicleTracker(
        model_path="unused.pt",
        tracker_config="bytetrack.yaml",
        confidence=0.5,
        capture_detections=True,
    )
    _attach_model(
        tracker,
        _SuccessfulModel(track_ids=(7,), detection_count=2),
    )

    result = tracker.track(_make_frame(np.zeros((100, 100, 3), dtype=np.uint8)))

    assert tuple(
        observation.track_segment_id for observation in result.observations
    ) == (TrackSegmentId(7),)
    assert result.all_detections_tracked is False
    assert result.ended_track_segment_ids == ()
    assert result.detection_count == 2
    assert len(result.detections) == 2


def test_non_detect_result_shape_marks_frame_untrusted():
    class _ModelWithMissingBoxes(_SuccessfulModel):
        def track(self, **kwargs):
            callback_predictor = type(
                "CallbackPredictor",
                (),
                {"results": [object()]},
            )()
            for callback in self._postprocess_callbacks:
                callback(callback_predictor)
            return [_Result(track_ids=())]

    tracker = UltralyticsVehicleTracker(
        model_path="unused.pt",
        tracker_config="bytetrack.yaml",
        confidence=0.5,
        capture_detections=True,
    )
    _attach_model(tracker, _ModelWithMissingBoxes(track_ids=()))

    result = tracker.track(_make_frame(np.zeros((100, 100, 3), dtype=np.uint8)))

    assert result.observations == ()
    assert result.all_detections_tracked is False
    assert result.detection_count is None
    assert result.detections == ()


def test_unprojectable_tracked_box_marks_frame_untrusted():
    class _OutOfFrameModel(_SuccessfulModel):
        def track(self, **kwargs):
            results = super().track(**kwargs)
            result = results[0]
            result.boxes.xyxy = np.asarray(
                [[110.0, 20.0, 130.0, 40.0]],
                dtype=float,
            )
            return results

    tracker = UltralyticsVehicleTracker(
        model_path="unused.pt",
        tracker_config="bytetrack.yaml",
        confidence=0.5,
    )
    _attach_model(tracker, _OutOfFrameModel(track_ids=(7,)))

    result = tracker.track(
        _make_frame(np.zeros((100, 100, 3), dtype=np.uint8))
    )

    assert result.observations == ()
    assert result.all_detections_tracked is False


def test_missing_bytetrack_internal_state_falls_back_to_no_segment_end():
    """내부 API를 읽을 수 없어도 frame 차집합으로 종료를 발명하지 않는다."""

    tracker = UltralyticsVehicleTracker(
        model_path="unused.pt",
        tracker_config="bytetrack.yaml",
        confidence=0.5,
    )
    _attach_model(tracker, _ModelWithoutTrackerInternals())

    result = tracker.track(_make_frame(np.zeros((100, 100, 3), dtype=np.uint8)))

    assert result.observations == ()
    assert result.ended_track_segment_ids == ()


def test_bytetrack_removed_segment_is_reported_once():
    tracker = UltralyticsVehicleTracker(
        model_path="unused.pt",
        tracker_config="bytetrack.yaml",
        confidence=0.5,
    )
    model = _SuccessfulModel(track_ids=())
    model.byte_tracker.removed_stracks.append(_RemovedTrack(7))
    _attach_model(tracker, model)
    frame = _make_frame(np.zeros((100, 100, 3), dtype=np.uint8))

    first = tracker.track(frame)
    second = tracker.track(frame)

    assert first.ended_track_segment_ids == (TrackSegmentId(7),)
    assert second.ended_track_segment_ids == ()
