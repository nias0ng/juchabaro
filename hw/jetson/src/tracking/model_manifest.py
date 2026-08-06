"""Vehicle detector asset manifest·SHA-256 기동 계약을 검증한다.

파일명이 같은 stock COCO model과 차량 단일 클래스 fine-tuned
model을 구분하는 정본은 이 manifest의 SHA-256이다. 이 모듈은
Ultralytics를 import하지 않고, camera·model 장치 객체를 만들기 전에
배포 asset이 런타임 차량 검출 계약과 같은지 fail-closed로
확인한다.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from src.tracking.vehicle_model_contract import (
    VEHICLE_MODEL_CLASS_NAMES,
    VEHICLE_MODEL_TASK,
)


VEHICLE_MODEL_MANIFEST_SCHEMA_VERSION = 1

_MANIFEST_FIELDS = {
    "schemaVersion",
    "modelVersion",
    "sha256",
    "task",
    "classNames",
}
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class VehicleModelManifest:
    """배포한 vehicle detector binary의 불변 식별·runtime 계약."""

    schema_version: int
    model_version: str
    sha256: str
    task: str
    class_names: Mapping[int, str]


def load_vehicle_model_manifest(path: Path) -> VehicleModelManifest:
    """JSON manifest를 읽고 현재 runtime이 지원하는 계약을 검증한다."""

    if not path.is_file():
        raise ValueError(
            "vehicle_model_manifest_path가 실제 JSON 파일이 아닙니다: "
            f"{path}"
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            "vehicle model manifest가 올바른 JSON이 아닙니다: "
            f"path={path}, line={exc.lineno}, column={exc.colno}"
        ) from exc
    except OSError as exc:
        raise ValueError(
            f"vehicle model manifest를 읽을 수 없습니다: path={path}, cause={exc}"
        ) from exc

    if not isinstance(raw, dict):
        raise ValueError("vehicle model manifest의 root는 JSON object여야 합니다.")
    actual_fields = set(raw)
    if actual_fields != _MANIFEST_FIELDS:
        missing = sorted(_MANIFEST_FIELDS - actual_fields)
        unknown = sorted(actual_fields - _MANIFEST_FIELDS)
        raise ValueError(
            "vehicle model manifest field 계약이 일치하지 않습니다: "
            f"missing={missing}, unknown={unknown}"
        )

    schema_version = raw["schemaVersion"]
    if (
        type(schema_version) is not int
        or schema_version != VEHICLE_MODEL_MANIFEST_SCHEMA_VERSION
    ):
        raise ValueError(
            "지원하지 않는 vehicle model manifest schemaVersion입니다: "
            f"expected={VEHICLE_MODEL_MANIFEST_SCHEMA_VERSION}, "
            f"actual={schema_version!r}"
        )

    model_version = raw["modelVersion"]
    if not isinstance(model_version, str) or not model_version.strip():
        raise ValueError(
            "vehicle model manifest modelVersion은 빈 문자열일 수 없습니다."
        )

    expected_sha256 = raw["sha256"]
    if not isinstance(expected_sha256, str) or not _SHA256_PATTERN.fullmatch(
        expected_sha256
    ):
        raise ValueError(
            "vehicle model manifest sha256은 소문자 16진수 64자여야 합니다."
        )

    task = raw["task"]
    if task != VEHICLE_MODEL_TASK:
        raise ValueError(
            "vehicle model manifest task 계약이 일치하지 않습니다: "
            f"expected={VEHICLE_MODEL_TASK!r}, actual={task!r}"
        )

    class_names = raw["classNames"]
    expected_class_names = {"0": "vehicle"}
    if class_names != expected_class_names:
        raise ValueError(
            "vehicle model manifest classNames 계약이 일치하지 않습니다: "
            f"expected={expected_class_names!r}, actual={class_names!r}"
        )

    return VehicleModelManifest(
        schema_version=schema_version,
        model_version=model_version.strip(),
        sha256=expected_sha256,
        task=task,
        class_names=VEHICLE_MODEL_CLASS_NAMES,
    )


def validate_vehicle_model_assets(
    *,
    model_path: Path,
    manifest_path: Path,
) -> VehicleModelManifest:
    """Model binary가 manifest에 핀된 정본인지 byte 단위로 확인한다."""

    if not model_path.is_file():
        raise ValueError(
            "vehicle_model_path가 실제 vehicle model 파일이 아닙니다: "
            f"{model_path}"
        )
    manifest = load_vehicle_model_manifest(manifest_path)
    digest = hashlib.sha256()
    try:
        with model_path.open("rb") as model_file:
            for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ValueError(
            f"vehicle model 파일을 읽을 수 없습니다: path={model_path}, cause={exc}"
        ) from exc

    actual_sha256 = digest.hexdigest()
    if actual_sha256 != manifest.sha256:
        raise ValueError(
            "vehicle model SHA-256이 manifest와 일치하지 않습니다: "
            f"modelVersion={manifest.model_version}, "
            f"expected={manifest.sha256}, actual={actual_sha256}"
        )
    return manifest
