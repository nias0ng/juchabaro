"""운영 OCR factory의 조립 순서와 startup 실패 계약을 검증한다."""

from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import Mock, call, patch

import src.ocr as public_ocr
from src.ocr import factory as factory_module
from src.ocr.factory import OcrRuntimeConfig, load_plate_ocr_pipeline
from src.ocr.pipeline import PlateOcrPipeline
from src.ocr.policy import OcrPipelinePolicy
from src.ocr.postprocessing.aggregator import PlateAggregator
from src.ocr.vision.frame_selector import QualityFrameSelector
from src.ocr.vision.geometry import PlateGeometry
from src.ocr.vision.plate_preprocessor import PlatePreprocessor


DETECTOR_PATH = Path("models/plate_detector/best.pt")
RECOGNIZER_DIR = Path("models/plate_recognizer")


def _config(
    *,
    policy: OcrPipelinePolicy | None = None,
    device: str = "cpu",
    warm_up: bool = True,
) -> OcrRuntimeConfig:
    return OcrRuntimeConfig(
        detector_model_path=DETECTOR_PATH,
        recognizer_model_dir=RECOGNIZER_DIR,
        policy=policy or OcrPipelinePolicy(),
        device=device,
        warm_up=warm_up,
    )


class OcrRuntimeConfigTests(unittest.TestCase):
    def test_rejects_invalid_public_configuration_types(self) -> None:
        base: dict[str, object] = {
            "detector_model_path": DETECTOR_PATH,
            "recognizer_model_dir": RECOGNIZER_DIR,
            "policy": OcrPipelinePolicy(),
            "device": "cpu",
            "warm_up": True,
        }
        cases = (
            ("detector_model_path", "detector.pt", TypeError),
            ("recognizer_model_dir", "recognizer", TypeError),
            ("policy", object(), TypeError),
            ("device", "  ", ValueError),
            ("warm_up", 1, TypeError),
        )

        for field_name, value, error_type in cases:
            with self.subTest(field=field_name, value=value):
                with self.assertRaises(error_type):
                    OcrRuntimeConfig(
                        **(base | {field_name: value})  # type: ignore[arg-type]
                    )

    def test_factory_requires_runtime_config(self) -> None:
        with self.assertRaises(TypeError):
            load_plate_ocr_pipeline(object())  # type: ignore[arg-type]


class PlateOcrFactoryTests(unittest.TestCase):
    def test_public_package_exports_factory_api(self) -> None:
        self.assertIs(public_ocr.OcrRuntimeConfig, OcrRuntimeConfig)
        self.assertIs(
            public_ocr.load_plate_ocr_pipeline,
            load_plate_ocr_pipeline,
        )

    def test_loads_models_once_and_assembles_default_components(
        self,
    ) -> None:
        policy = OcrPipelinePolicy(frame_count=8)
        config = _config(
            policy=policy,
            device="device:test",
            warm_up=True,
        )
        detector = Mock(name="detector")
        reader = Mock(name="reader")
        loader_calls = Mock()

        with (
            patch.object(
                factory_module,
                "load_yolo_plate_detector",
                return_value=detector,
            ) as detector_loader,
            patch.object(
                factory_module,
                "load_paddle_plate_reader",
                return_value=reader,
            ) as reader_loader,
        ):
            loader_calls.attach_mock(detector_loader, "detector")
            loader_calls.attach_mock(reader_loader, "reader")
            pipeline = load_plate_ocr_pipeline(config)

        self.assertIsInstance(pipeline, PlateOcrPipeline)
        self.assertIsInstance(pipeline._selector, QualityFrameSelector)
        self.assertIsInstance(pipeline._geometry, PlateGeometry)
        self.assertIsInstance(pipeline._preprocessor, PlatePreprocessor)
        self.assertIsInstance(pipeline._aggregator, PlateAggregator)
        self.assertIs(pipeline._policy, policy)
        self.assertIs(pipeline._selector._policy, policy)
        self.assertIs(pipeline._detector, detector)
        self.assertIs(pipeline._reader, reader)

        self.assertEqual(
            loader_calls.mock_calls,
            [
                call.detector(
                    DETECTOR_PATH,
                    device="device:test",
                    warm_up=True,
                ),
                call.reader(
                    RECOGNIZER_DIR,
                    device="device:test",
                    warm_up=True,
                ),
            ],
        )

        # Warm-up은 각 loader가 소유하며 factory가 반환 객체에 중복 호출하지 않는다.
        detector.warm_up.assert_not_called()
        reader.warm_up.assert_not_called()

    def test_warm_up_false_is_forwarded_to_both_loaders(self) -> None:
        config = _config(warm_up=False)

        with (
            patch.object(
                factory_module,
                "load_yolo_plate_detector",
                return_value=Mock(),
            ) as detector_loader,
            patch.object(
                factory_module,
                "load_paddle_plate_reader",
                return_value=Mock(),
            ) as reader_loader,
        ):
            load_plate_ocr_pipeline(config)

        detector_loader.assert_called_once_with(
            DETECTOR_PATH,
            device="cpu",
            warm_up=False,
        )
        reader_loader.assert_called_once_with(
            RECOGNIZER_DIR,
            device="cpu",
            warm_up=False,
        )

    def test_detector_startup_failure_is_not_hidden(self) -> None:
        startup_error = RuntimeError("의도한 detector load 또는 warm-up 실패")

        with (
            patch.object(
                factory_module,
                "load_yolo_plate_detector",
                side_effect=startup_error,
            ),
            patch.object(
                factory_module,
                "load_paddle_plate_reader",
            ) as reader_loader,
            patch.object(
                factory_module,
                "PlateOcrPipeline",
            ) as pipeline_constructor,
        ):
            with self.assertRaises(RuntimeError) as raised:
                load_plate_ocr_pipeline(_config())

        self.assertIs(raised.exception, startup_error)
        reader_loader.assert_not_called()
        pipeline_constructor.assert_not_called()

    def test_reader_startup_failure_does_not_return_partial_pipeline(
        self,
    ) -> None:
        startup_error = RuntimeError("의도한 reader load 또는 warm-up 실패")

        with (
            patch.object(
                factory_module,
                "load_yolo_plate_detector",
                return_value=Mock(),
            ) as detector_loader,
            patch.object(
                factory_module,
                "load_paddle_plate_reader",
                side_effect=startup_error,
            ),
            patch.object(
                factory_module,
                "PlateOcrPipeline",
            ) as pipeline_constructor,
        ):
            with self.assertRaises(RuntimeError) as raised:
                load_plate_ocr_pipeline(_config())

        self.assertIs(raised.exception, startup_error)
        detector_loader.assert_called_once()
        pipeline_constructor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
