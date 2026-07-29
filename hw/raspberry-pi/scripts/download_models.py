"""
models 및 하위 폴더를 생성하고 번호판 탐지·인식 모델을 내려받는다.

plate_detector : YOLOv8n-pose(파인튜닝)
plate_recognizer : paddleOCR(korean_PP-OCRv5_mobile_rec)
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

# [설정 상수]
DEFAULT_MODELS_DIR = Path("/home/e202/models")
DOWNLOAD_TIMEOUT = 120
BUFFER_SIZE = 1024 * 1024

DETECTOR_FILENAME = "bestv1_1.pt"
DETECTOR_URL = (
    "https://huggingface.co/sysy9292/smart-parking-plate-detector/"
    "resolve/ae73d3f85f89944288d18a2a8f6a4fe9aa80bb7c/"
    f"{DETECTOR_FILENAME}"
)
DETECTOR_SHA256 = (
    "3fffe0902787acc693cfcf9a5696d8affb4306c9541b33c0a296056ed73ba1b1"
)

PADDLE_MODEL_NAME = "korean_PP-OCRv5_mobile_rec"
PADDLE_URL = (
    "https://paddle-model-ecology.bj.bcebos.com/paddlex/"
    "official_inference_model/paddle3.0.0/"
    f"{PADDLE_MODEL_NAME}_infer.tar"
)
PADDLE_SHA256 = (
    "a6261f800ad335aa6ef77b6f7c4dcedfd5e11b95f4d70982d41ee31c2ace5e66"
)
PADDLE_FILES = ("inference.json", "inference.pdiparams", "inference.yml")


# [예외]
class ModelDownloadError(RuntimeError):
    """모델을 다운로드하거나 검증할 수 없는 경우."""


# [검증]
def _sha256(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


# [공통 다운로드]
def _download(url: str, destination: Path, expected_sha256: str) -> None:
    """파일을 임시 경로에 받은 뒤 SHA-256을 확인하고 교체한다."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_file = tempfile.NamedTemporaryFile(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        delete=False,
    )
    temp_path = Path(temp_file.name)

    try:
        request = Request(
            url,
            headers={"User-Agent": "smart-parking-model-downloader/1.0"},
        )
        with temp_file, urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
            shutil.copyfileobj(response, temp_file, BUFFER_SIZE)

        actual_sha256 = _sha256(temp_path)
        if actual_sha256 != expected_sha256:
            raise ModelDownloadError(
                "SHA-256 검증에 실패했습니다: "
                f"expected={expected_sha256}, actual={actual_sha256}"
            )

        os.replace(temp_path, destination)
    except URLError as exc:
        raise ModelDownloadError(f"다운로드에 실패했습니다: {url}") from exc
    finally:
        temp_path.unlink(missing_ok=True)

# [YOLO 가중치 설치]
def _install_detector(models_dir: Path, *, force: bool) -> Path:
    destination = models_dir / "plate_detector" / DETECTOR_FILENAME
    if not force and destination.is_file() and _sha256(destination) == DETECTOR_SHA256:
        print(f"[skip] 번호판 탐지 모델: {destination}")
        return destination

    print(f"[download] 번호판 탐지 모델: {DETECTOR_URL}")
    _download(DETECTOR_URL, destination, DETECTOR_SHA256)
    print(f"[ok] 번호판 탐지 모델: {destination}")
    return destination


# [paddleOCR 모델 설치]
def _paddle_is_ready(model_dir: Path) -> bool:
    return all(
        (model_dir / filename).is_file()
        and (model_dir / filename).stat().st_size > 0
        for filename in PADDLE_FILES
    )

def _extract_paddle(archive_path: Path, destination: Path) -> None:
    """검증된 아카이브에서 로더가 요구하는 파일만 꺼낸다."""

    with tarfile.open(archive_path) as archive:
        members = {
            Path(member.name).name: member
            for member in archive.getmembers()
            if member.isfile() and Path(member.name).name in PADDLE_FILES
        }
        missing = set(PADDLE_FILES) - members.keys()
        if missing:
            raise ModelDownloadError(
                "PaddleOCR 필수 파일이 없습니다: " + ", ".join(sorted(missing))
            )

        for filename in PADDLE_FILES:
            source = archive.extractfile(members[filename])
            if source is None:
                raise ModelDownloadError(f"PaddleOCR 파일을 읽을 수 없습니다: {filename}")
            with source, (destination / filename).open("wb") as output:
                shutil.copyfileobj(source, output, BUFFER_SIZE)

def _install_paddle(models_dir: Path, *, force: bool) -> Path:
    model_dir = models_dir / "plate_recognizer"
    model_dir.mkdir(parents=True, exist_ok=True)
    if not force and _paddle_is_ready(model_dir):
        print(f"[skip] PaddleOCR 모델: {model_dir}")
        return model_dir

    print(f"[download] PaddleOCR 모델 ({PADDLE_MODEL_NAME}): {PADDLE_URL}")
    with tempfile.TemporaryDirectory(dir=model_dir, prefix=".install-") as temp_dir:
        staging_dir = Path(temp_dir)
        archive_path = staging_dir / "model.tar"
        _download(PADDLE_URL, archive_path, PADDLE_SHA256)
        _extract_paddle(archive_path, staging_dir)
        for filename in PADDLE_FILES:
            os.replace(staging_dir / filename, model_dir / filename)

    print(f"[ok] PaddleOCR 모델: {model_dir}")
    return model_dir


# [모델 설치 실행]
def download_models(models_dir: Path, *, force: bool = False) -> tuple[Path, Path]:
    """두 모델을 설치하고 실제 설치 경로를 반환한다."""

    models_dir = models_dir.expanduser().resolve()
    detector_path = _install_detector(models_dir, force=force)
    recognizer_dir = _install_paddle(models_dir, force=force)
    return detector_path, recognizer_dir


# [CLI]
def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="번호판 탐지 모델과 PaddleOCR 한국어 인식 모델을 내려받습니다."
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=DEFAULT_MODELS_DIR,
        help=f"모델 설치 경로 (기본값: {DEFAULT_MODELS_DIR})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="설치된 모델도 다시 내려받습니다.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        detector_path, recognizer_dir = download_models(
            args.models_dir,
            force=args.force,
        )
    except (ModelDownloadError, OSError, tarfile.TarError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    print("모델 설치가 완료되었습니다.")
    print(f"  detector: {detector_path}")
    print(f"  recognizer: {recognizer_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
