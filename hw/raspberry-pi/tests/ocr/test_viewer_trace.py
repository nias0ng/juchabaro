"""실제 모델 없이 OCR viewer의 trace 기반 진단 계약을 고정한다."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
import sys
from threading import Lock
import unittest
from unittest.mock import patch

import numpy as np


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


from ai.ocr.pipeline_viewer.service import (  # noqa: E402
    DebugRun,
    DebugRuntime,
    DecodedBurst,
    DecodedFrame,
    ModelPaths,
    StartupReport,
    run_debug_pipeline,
)
from ai.ocr.pipeline_viewer.tracing import (  # noqa: E402
    PipelineTrace,
    StageCall,
)
try:  # Python 3.12 전체 테스트 환경에는 Streamlit이 없다.
    from ai.ocr.pipeline_viewer import ui as viewer_ui  # noqa: E402
except ModuleNotFoundError as exc:  # pragma: no cover - 환경별 분기
    if exc.name != "streamlit":
        raise
    viewer_ui = None

from ocr.errors import OcrComponentError  # noqa: E402
from ocr.policy import OcrPipelinePolicy  # noqa: E402
from ocr.types import (  # noqa: E402
    AnchorSelection,
    CapturedFrame,
    DetectedPlate,
    EstimatedQuad,
    FrameQuality,
    OcrCandidate,
    PlateDecision,
    PlateReadResult,
    PreparedPlate,
    Quad,
    QuadSource,
    RawOcrResult,
    ReadStatus,
    RectifiedPlate,
)
from ocr.vision.geometry import PlateGeometry  # noqa: E402


PLATE_NUMBER = "12가3456"
PLATE_QUAD: Quad = (
    (4.0, 4.0),
    (24.0, 4.0),
    (24.0, 14.0),
    (4.0, 14.0),
)


class FakeSelector:
    def select_anchors(
        self,
        frames: Sequence[CapturedFrame],
    ) -> AnchorSelection:
        qualities = tuple(
            FrameQuality(
                frame_index=frame.frame_index,
                sharpness=1.0,
                contrast=1.0,
                mean_brightness=100.0,
                dark_ratio=0.0,
                bright_ratio=0.0,
                score=float(frame.frame_index),
            )
            for frame in frames
        )
        return AnchorSelection(
            earlier_frame_index=0,
            later_frame_index=len(frames) - 1,
            qualities=qualities,
        )


class RaisingSelector:
    def select_anchors(
        self,
        frames: Sequence[CapturedFrame],
    ) -> AnchorSelection:
        del frames
        raise RuntimeError("selector exploded")


class ChainedErrorSelector:
    def select_anchors(
        self,
        frames: Sequence[CapturedFrame],
    ) -> AnchorSelection:
        del frames
        try:
            raise ValueError("raw adapter cause")
        except ValueError as exc:
            raise OcrComponentError(
                "selector adapter failed"
            ) from exc


class FakeDetector:
    def __init__(self, *, detected: bool = True) -> None:
        self._detected = detected

    def detect(
        self,
        frame: CapturedFrame,
    ) -> tuple[DetectedPlate, ...]:
        if not self._detected:
            return ()
        return (
            DetectedPlate(
                frame_index=frame.frame_index,
                bbox_xyxy=(4.0, 4.0, 24.0, 14.0),
                quad=PLATE_QUAD,
                detector_score=0.9,
            ),
        )


class InvalidSceneDetector(FakeDetector):
    def detect(
        self,
        frame: CapturedFrame,
    ) -> tuple[DetectedPlate, ...]:
        return (
            DetectedPlate(
                frame_index=frame.frame_index,
                bbox_xyxy=(-10.0, -10.0, -1.0, -1.0),
                quad=(
                    (-10.0, -10.0),
                    (-1.0, -10.0),
                    (-1.0, -1.0),
                    (-10.0, -1.0),
                ),
                detector_score=0.9,
            ),
        )


class MultipleCandidateDetector(FakeDetector):
    def detect(
        self,
        frame: CapturedFrame,
    ) -> tuple[DetectedPlate, ...]:
        return tuple(
            DetectedPlate(
                frame_index=frame.frame_index,
                bbox_xyxy=bbox,
                quad=PLATE_QUAD,
                detector_score=score,
            )
            for score, bbox in (
                (0.95, (4.0, 4.0, 24.0, 14.0)),
                (0.80, (5.0, 5.0, 23.0, 13.0)),
                (0.70, (6.0, 6.0, 22.0, 12.0)),
                (0.60, (7.0, 7.0, 21.0, 11.0)),
            )
        )


class FakeGeometry:
    def estimate_quads(
        self,
        frames: Sequence[CapturedFrame],
        detections: Sequence[DetectedPlate],
    ) -> tuple[EstimatedQuad, ...]:
        anchor_indices = tuple(
            detection.frame_index
            for detection in detections
        )
        return tuple(
            EstimatedQuad(
                frame_index=frame.frame_index,
                quad=PLATE_QUAD,
                source=QuadSource.DETECTED,
                source_anchor_indices=anchor_indices,
            )
            for frame in frames
        )

    def rectify(
        self,
        frame: CapturedFrame,
        estimate: EstimatedQuad,
    ) -> RectifiedPlate:
        return RectifiedPlate(
            frame_index=frame.frame_index,
            image=frame.image.copy(),
            quad_estimate=estimate,
        )


class FakePreprocessor:
    def process(self, plate: RectifiedPlate) -> PreparedPlate:
        return PreparedPlate(
            frame_index=plate.frame_index,
            image=plate.image.copy(),
            quad_estimate=plate.quad_estimate,
            preprocessing_applied=False,
        )


class FakeReader:
    def recognize(
        self,
        plates: Sequence[PreparedPlate],
    ) -> tuple[RawOcrResult, ...]:
        return tuple(
            RawOcrResult(
                frame_index=plate.frame_index,
                raw_text=PLATE_NUMBER,
                rec_score=0.9,
            )
            for plate in plates
        )


class FakeAggregator:
    def aggregate(
        self,
        candidates: Sequence[OcrCandidate],
    ) -> PlateDecision:
        candidate_tuple = tuple(candidates)
        return PlateDecision(
            status=ReadStatus.SUCCESS,
            plate_number=PLATE_NUMBER,
            valid_frames=len(candidate_tuple),
            vote_count=len(candidate_tuple),
            vote_ratio=1.0,
            mean_rec_score=0.9,
        )


def _burst(frame_count: int = 3) -> DecodedBurst:
    frames = tuple(
        DecodedFrame(
            frame_index=index,
            file_name=f"{index + 1:02d}.jpg",
            image=np.full(
                (20, 30, 3),
                index,
                dtype=np.uint8,
            ),
            byte_size=100 + index,
        )
        for index in range(frame_count)
    )
    return DecodedBurst(frames=frames, signature="fake-burst")


def _runtime(
    *,
    selector: object | None = None,
    detector: object | None = None,
    geometry: object | None = None,
) -> DebugRuntime:
    model_root = REPOSITORY_ROOT / "unused-models"
    return DebugRuntime(
        model_paths=ModelPaths(
            root=model_root,
            detector=model_root / "detector.pt",
            recognizer=model_root / "recognizer",
        ),
        device="cpu",
        policy=OcrPipelinePolicy(frame_count=3),
        selector=selector or FakeSelector(),
        detector=detector or FakeDetector(),
        geometry=geometry or FakeGeometry(),
        preprocessor=FakePreprocessor(),
        reader=FakeReader(),
        aggregator=FakeAggregator(),
        startup=StartupReport(
            detector_load_ms=0.0,
            detector_warm_up_ms=0.0,
            recognizer_load_ms=0.0,
            recognizer_warm_up_ms=0.0,
        ),
        run_lock=Lock(),
    )


class StreamlitStub:
    """Renderer 제어 흐름만 실행하는 최소 Streamlit 대역."""

    def __init__(self, events=None):
        self.events = events if events is not None else []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        del exc_type, exc_value, traceback
        return False

    def columns(self, spec):
        count = spec if isinstance(spec, int) else len(spec)
        return tuple(
            StreamlitStub(self.events)
            for _ in range(count)
        )

    def tabs(self, labels):
        return tuple(
            StreamlitStub(self.events)
            for _ in labels
        )

    def expander(self, *args, **kwargs):
        del args, kwargs
        return StreamlitStub(self.events)

    def __getattr__(self, name):
        def no_op(*args, **kwargs):
            self.events.append((name, args, kwargs))
            return None

        return no_op


def _render_with_stub(
    run,
    burst: DecodedBurst,
) -> list[tuple[object, ...]]:
    assert viewer_ui is not None
    stub = StreamlitStub()
    with patch.object(viewer_ui, "st", stub):
        viewer_ui.render_debug_run(run, burst)
    return stub.events


def _render_detection_with_stub(
    run: DebugRun,
) -> list[tuple[object, ...]]:
    assert viewer_ui is not None
    stub = StreamlitStub()
    with patch.object(viewer_ui, "st", stub):
        viewer_ui._render_detection(run)
    return stub.events


def _detection_only_run(output: object) -> DebugRun:
    frame = CapturedFrame(
        frame_index=0,
        image=np.zeros((20, 30, 3), dtype=np.uint8),
    )
    return DebugRun(
        request_signature="detection-only",
        file_names=("01.jpg",),
        result=None,
        trace=PipelineTrace(
            calls=[
                StageCall(
                    stage="detection",
                    frame_indices=(0,),
                    inputs=frame,
                    output=output,
                    elapsed_ms=1.0,
                ),
            ],
        ),
    )


def _stage_signature(
    trace: PipelineTrace,
) -> tuple[tuple[str, tuple[int, ...]], ...]:
    """Component trace의 실행 순서와 호출 단위를 비교 가능한 값으로 만든다."""

    return tuple(
        (call.stage, call.frame_indices)
        for call in trace.calls
    )


class ViewerTraceTest(unittest.TestCase):
    def test_success_diagnostics_come_from_trace_not_public_result(
        self,
    ) -> None:
        run = run_debug_pipeline(_runtime(), _burst())

        self.assertIsInstance(run.result, PlateReadResult)
        self.assertEqual(run.result.status, ReadStatus.SUCCESS)
        self.assertEqual(run.result.plate_number, PLATE_NUMBER)

        pipeline_call = run.trace.pipeline_call
        self.assertIsNotNone(pipeline_call)
        assert pipeline_call is not None
        self.assertTrue(pipeline_call.succeeded)
        self.assertIs(pipeline_call.output, run.result)
        self.assertEqual(pipeline_call.frame_indices, (0, 1, 2))
        self.assertGreaterEqual(pipeline_call.elapsed_ms, 0.0)

        candidates = run.trace.successful_outputs(
            "text_postprocessing"
        )
        self.assertEqual(len(candidates), 3)
        self.assertTrue(
            all(
                candidate.normalized_text == PLATE_NUMBER
                for candidate in candidates
            )
        )

        aggregation = run.trace.first("aggregation")
        self.assertIsNotNone(aggregation)
        assert aggregation is not None
        decision = aggregation.output
        self.assertEqual(decision.valid_frames, 3)
        self.assertEqual(decision.vote_count, 3)
        self.assertEqual(decision.vote_ratio, 1.0)
        self.assertEqual(decision.mean_rec_score, 0.9)

        self.assertEqual(len(run.trace.calls_for("detection")), 2)
        self.assertEqual(len(run.trace.calls_for("recognition")), 1)
        self.assertGreaterEqual(
            run.trace.elapsed_ms_for(
                "geometry",
                "rectification",
            ),
            0.0,
        )

    def test_success_trace_preserves_stage_order_and_call_units(
        self,
    ) -> None:
        run = run_debug_pipeline(_runtime(), _burst())

        self.assertEqual(
            _stage_signature(run.trace),
            (
                ("frame_selection", (0, 1, 2)),
                ("detection", (0,)),
                ("detection", (2,)),
                ("geometry", (0, 1, 2)),
                ("rectification", (0,)),
                ("rectification", (1,)),
                ("rectification", (2,)),
                ("preprocessing", (0,)),
                ("preprocessing", (1,)),
                ("preprocessing", (2,)),
                ("recognition", (0, 1, 2)),
                ("text_postprocessing", (0,)),
                ("text_postprocessing", (1,)),
                ("text_postprocessing", (2,)),
                ("aggregation", (0, 1, 2)),
            ),
        )

    @unittest.skipIf(viewer_ui is None, "streamlit is not installed")
    def test_multiple_candidates_keep_one_call_per_anchor_and_render_best_first(
        self,
    ) -> None:
        run = run_debug_pipeline(
            _runtime(detector=MultipleCandidateDetector()),
            _burst(),
        )

        detection_calls = run.trace.calls_for("detection")
        self.assertEqual(len(detection_calls), 2)
        self.assertTrue(
            all(
                isinstance(call.output, tuple)
                and tuple(
                    candidate.detector_score
                    for candidate in call.output
                )
                == (0.95, 0.80, 0.70, 0.60)
                for call in detection_calls
            )
        )

        events = _render_detection_with_stub(run)
        dataframe_events = [
            event
            for event in events
            if event[0] == "dataframe"
        ]
        self.assertEqual(len(dataframe_events), 1)
        rows = dataframe_events[0][1][0]
        self.assertEqual(
            [row["candidate"] for row in rows],
            [
                "BEST",
                "#2",
                "#3",
                "#4",
                "BEST",
                "#2",
                "#3",
                "#4",
            ],
        )
        self.assertTrue(
            any(
                event[0] == "success"
                and "후보 4개" in str(event[1])
                for event in events
            )
        )

    @unittest.skipIf(viewer_ui is None, "streamlit is not installed")
    def test_missing_and_empty_detection_outputs_are_distinct(
        self,
    ) -> None:
        missing_events = _render_detection_with_stub(
            _detection_only_run(None)
        )
        empty_events = _render_detection_with_stub(
            _detection_only_run(())
        )

        self.assertTrue(
            any(
                event[0] == "warning"
                and "출력이 기록되지 않았습니다" in str(event[1])
                for event in missing_events
            )
        )
        self.assertTrue(
            any(
                event[0] == "warning"
                and "번호판 미검출" in str(event[1])
                for event in empty_events
            )
        )

    @unittest.skipIf(viewer_ui is None, "streamlit is not installed")
    def test_large_finite_detection_coordinates_render_safely(
        self,
    ) -> None:
        detection = DetectedPlate(
            frame_index=0,
            bbox_xyxy=(-1e300, -1e300, 1e300, 1e300),
            quad=(
                (-1e300, -1e300),
                (1e300, -1e300),
                (1e300, 1e300),
                (-1e300, 1e300),
            ),
            detector_score=0.9,
        )

        events = _render_detection_with_stub(
            _detection_only_run((detection,))
        )

        self.assertTrue(any(event[0] == "image" for event in events))
        self.assertFalse(any(event[0] == "error" for event in events))

    def test_repeated_runs_keep_trace_state_isolated(self) -> None:
        runtime = _runtime()
        burst = _burst()

        first = run_debug_pipeline(runtime, burst)
        first_signature = _stage_signature(first.trace)
        second = run_debug_pipeline(runtime, burst)

        self.assertIsNot(first.trace, second.trace)
        self.assertIsNot(first.trace.calls, second.trace.calls)
        self.assertIsNot(
            first.trace.pipeline_call,
            second.trace.pipeline_call,
        )
        self.assertEqual(_stage_signature(first.trace), first_signature)
        self.assertEqual(_stage_signature(second.trace), first_signature)
        self.assertEqual(len(first.trace.calls), 15)
        self.assertEqual(len(second.trace.calls), 15)

    def test_normal_no_detection_keeps_successful_pipeline_trace(
        self,
    ) -> None:
        run = run_debug_pipeline(
            _runtime(detector=FakeDetector(detected=False)),
            _burst(),
        )

        self.assertIsNotNone(run.result)
        assert run.result is not None
        self.assertEqual(
            run.result.status,
            ReadStatus.NO_PLATE_REGION,
        )
        self.assertTrue(run.trace.pipeline_call.succeeded)
        detection_calls = run.trace.calls_for("detection")
        self.assertEqual(len(detection_calls), 2)
        self.assertTrue(
            all(
                call.succeeded and call.output == ()
                for call in detection_calls
            )
        )
        self.assertEqual(
            _stage_signature(run.trace),
            (
                ("frame_selection", (0, 1, 2)),
                ("detection", (0,)),
                ("detection", (2,)),
            ),
        )
        self.assertIsNone(run.trace.first("aggregation"))

    def test_scene_rejection_reason_survives_in_normal_result_trace(
        self,
    ) -> None:
        run = run_debug_pipeline(
            _runtime(
                detector=InvalidSceneDetector(),
                geometry=PlateGeometry(),
            ),
            _burst(),
        )

        self.assertIsNotNone(run.result)
        assert run.result is not None
        self.assertEqual(
            run.result.status,
            ReadStatus.NO_PLATE_REGION,
        )
        self.assertTrue(run.trace.pipeline_call.succeeded)
        self.assertEqual(
            _stage_signature(run.trace),
            (
                ("frame_selection", (0, 1, 2)),
                ("detection", (0,)),
                ("detection", (2,)),
                ("geometry", (0, 1, 2)),
            ),
        )

        geometry_call = run.trace.first("geometry")
        self.assertIsNotNone(geometry_call)
        assert geometry_call is not None
        self.assertFalse(geometry_call.succeeded)
        self.assertIn(
            "frame_index=0",
            geometry_call.error_message,
        )
        self.assertIn(
            "경계를 벗어납니다",
            geometry_call.error_message,
        )

    def test_pipeline_exception_returns_debug_run_with_partial_trace(
        self,
    ) -> None:
        run = run_debug_pipeline(
            _runtime(selector=RaisingSelector()),
            _burst(),
        )

        self.assertIsNone(run.result)
        pipeline_call = run.trace.pipeline_call
        self.assertIsNotNone(pipeline_call)
        assert pipeline_call is not None
        self.assertFalse(pipeline_call.succeeded)
        self.assertEqual(pipeline_call.error_type, "RuntimeError")
        self.assertEqual(
            pipeline_call.error_message,
            "selector exploded",
        )

        selection_call = run.trace.first("frame_selection")
        self.assertIsNotNone(selection_call)
        assert selection_call is not None
        self.assertFalse(selection_call.succeeded)
        self.assertEqual(selection_call.error_type, "RuntimeError")
        self.assertEqual(selection_call.frame_indices, (0, 1, 2))

    def test_pipeline_trace_preserves_adapter_cause_chain(
        self,
    ) -> None:
        run = run_debug_pipeline(
            _runtime(selector=ChainedErrorSelector()),
            _burst(),
        )

        pipeline_call = run.trace.pipeline_call
        self.assertIsNotNone(pipeline_call)
        assert pipeline_call is not None
        self.assertEqual(
            tuple(
                error_type
                for error_type, _ in pipeline_call.error_chain
            )[-2:],
            ("OcrComponentError", "ValueError"),
        )
        self.assertEqual(
            pipeline_call.error_chain[-1],
            ("ValueError", "raw adapter cause"),
        )

    @unittest.skipIf(viewer_ui is None, "streamlit is not installed")
    def test_call_error_displays_preserved_cause_chain(self) -> None:
        run = run_debug_pipeline(
            _runtime(selector=ChainedErrorSelector()),
            _burst(),
        )

        pipeline_call = run.trace.pipeline_call
        self.assertIsNotNone(pipeline_call)
        assert pipeline_call is not None
        assert viewer_ui is not None
        displayed = viewer_ui._call_error(pipeline_call)

        self.assertIsNotNone(displayed)
        assert displayed is not None
        self.assertIn("OcrComponentError: selector adapter failed", displayed)
        self.assertIn("ValueError: raw adapter cause", displayed)

    @unittest.skipIf(viewer_ui is None, "streamlit is not installed")
    def test_normal_trace_renders_without_diagnostics_errors(
        self,
    ) -> None:
        burst = _burst()
        run = run_debug_pipeline(_runtime(), burst)

        self.assertIsNotNone(run.result)
        events = _render_with_stub(run, burst)
        self.assertTrue(any(event[0] == "image" for event in events))
        self.assertFalse(any(event[0] == "error" for event in events))

    @unittest.skipIf(viewer_ui is None, "streamlit is not installed")
    def test_pipeline_error_is_not_hidden_by_recovered_stage_error(
        self,
    ) -> None:
        trace = PipelineTrace(
            calls=[
                StageCall(
                    stage="rectification",
                    frame_indices=(0,),
                    inputs=None,
                    output=None,
                    elapsed_ms=1.0,
                    error_type="GeometryError",
                    error_message="scene quad rejected",
                )
            ],
            pipeline_call=StageCall(
                stage="pipeline",
                frame_indices=(0, 1, 2),
                inputs=(),
                output=None,
                elapsed_ms=2.0,
                error_type="OcrRuntimeError",
                error_message="preprocessor contract error",
            ),
        )
        run = DebugRun(
            request_signature="failed-run",
            file_names=("01.jpg", "02.jpg", "03.jpg"),
            result=None,
            trace=trace,
        )

        assert viewer_ui is not None
        rows = viewer_ui._trace_failure_rows(run)

        self.assertEqual(
            [row["stage"] for row in rows],
            ["rectification", "pipeline"],
        )


if __name__ == "__main__":
    unittest.main()
