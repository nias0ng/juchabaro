'''
번호판 OCR에 사용할 모델을 선정하기 위해
EasyOCR,
PaddleOCR 한국어 PP-OCRv5 Mobile,
PaddleOCR PP-OCRv5 Server를 비교해보고 싶어 구현했습니다.

번호판 영역 검출(객체 검출)은 별도의 YOLOv8n-pose모델이 담당하므로,
각 모델은 recognition-only 방식으로 사용합니다.
따라서 각 프레임워크에 포함된 텍스트 검출기는 비교 대상에서 제외되며,
비교 결과에는 번호판 이미지에 대한 문자 인식 성능만 반영됩니다.

# 환경 생성 (Miniforge 터미널)
conda create -n plate-ocr-bench python=3.13 -y
conda activate plate-ocr-bench

python -m pip install --upgrade pip setuptools wheel

# EasyOCR CPU용 PyTorch
python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

# PaddlePaddle CPU
python -m pip install paddlepaddle -i https://www.paddlepaddle.org.cn/packages/stable/cpu/

# OCR 및 Streamlit 앱 의존성
python -m pip install "paddleocr>=3.3,<4" easyocr==1.7.2 streamlit pandas pillow opencv-python-headless
'''
from __future__ import annotations

import io
import json
import time
import unicodedata
from typing import Any, Callable

import cv2
import numpy as np
import pandas as pd
import streamlit as st
from PIL import Image, ImageOps

st.set_page_config(page_title="번호판 OCR 벤치마크", layout="wide")

PADDLE_KOREAN_MOBILE = "korean_PP-OCRv5_mobile_rec"
PADDLE_GENERAL_SERVER = "PP-OCRv5_server_rec"

# [평가용 함수]

# OCR로 읽은 글자 정리
def normalize_plate(text:str) -> str:
    '''공백 및 구두점을 제외하고 유니코드 표현을 통일한 글자/숫자만 남김'''
    alnum_only = "".join(ch for ch in (text or "") if ch.isalnum())
    return unicodedata.normalize("NFKC", alnum_only)

def finite_or_none(value: Any) -> float | None:
    """결과 중 NaN과 inf를 Streamlit/Pandas에서 다루기 쉬운 None으로 바꿉니다."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None

    return value if np.isfinite(value) else None

# 문자오류율 계산
def levenshtein(a: str, b: str) -> int:
    '''Levenshtein 편집 거리 계산 -> 문자오류율(CER) 계산용'''
    if len(a) < len(b):
        a, b = b, a

    previous = list(range(len(b) + 1))

    for i, ca in enumerate(a, 1):
        current = [i]

        for j, cb in enumerate(b, 1):
            insertion = current[j - 1] + 1
            deletion = previous[j] + 1
            substitution = previous[j - 1] + (ca != cb)

            current.append(
                min(
                    insertion,
                    deletion,
                    substitution,
                )
            )

        previous = current

    return previous[-1]

def calculate_cer(reference: str, prediction: str) -> float | None:
    """CER = 편집 거리 / 정답 문자열 길이."""
    if not reference:
        return None

    return levenshtein(reference, prediction) / len(reference)


# [이미지 처리]

def decode_upload(file_bytes: bytes) -> np.ndarray:
    """업로드 이미지를 OpenCV BGR 배열로 변환합니다."""
    with Image.open(io.BytesIO(file_bytes)) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        rgb = np.asarray(image)

    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

def preprocess_plate(
    image: np.ndarray,
    target_height: int,
    padding_percent: int,
) -> np.ndarray:
    """
    번호판 전처리:

    1. Grayscale
    2. CLAHE 명암 보정
    3. 약한 샤프닝
    4. 외곽 여백 추가
    5. 비율을 유지하며 높이 기준 resize
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    clahe = cv2.createCLAHE(
        clipLimit=2.0,
        tileGridSize=(8, 8),
    )
    enhanced = clahe.apply(gray)

    blurred = cv2.GaussianBlur(
        enhanced,
        (0, 0),
        sigmaX=1.0,
    )

    sharpened = cv2.addWeighted(
        enhanced,
        1.5,
        blurred,
        -0.5,
        0,
    )

    processed = cv2.cvtColor(
        sharpened,
        cv2.COLOR_GRAY2BGR,
    )

    height, width = processed.shape[:2]

    pad_y = round(height * padding_percent / 100)
    pad_x = round(width * padding_percent / 100)

    processed = cv2.copyMakeBorder(
        processed,
        pad_y,
        pad_y,
        pad_x,
        pad_x,
        borderType=cv2.BORDER_REPLICATE,
    )

    height, width = processed.shape[:2]
    scale = target_height / height
    target_width = max(1, round(width * scale))

    interpolation = (
        cv2.INTER_CUBIC
        if scale >= 1
        else cv2.INTER_AREA
    )

    return cv2.resize(
        processed,
        (target_width, target_height),
        interpolation=interpolation,
    )


# [모델 로드]

@st.cache_resource(show_spinner=False)  # 매번 새로 로드 되는 것 방지
def load_easyocr() -> tuple[Any, float]:
    '''easyOCR 로드'''
    import easyocr

    started = time.perf_counter()

    reader = easyocr.Reader(
        ["ko", "en"],
        gpu=False,
        detector=False,
        recognizer=True,
        verbose=False,
    )

    load_ms = (time.perf_counter() - started) * 1000

    return reader, load_ms


@st.cache_resource(show_spinner=False)
def load_paddle(
    model_name: str,
) -> tuple[Any, float]:
    '''paddleOCR 로드'''
    from paddleocr import TextRecognition

    started = time.perf_counter()

    model = TextRecognition(
        model_name=model_name,
        device="cpu",
    )

    load_ms = (time.perf_counter() - started) * 1000

    return model, load_ms

def load_models() -> tuple[list[dict[str, Any]], list[str]]:
    '''모델 3종 불러오기'''
    specs = [
        (
            "easyocr",
            "EasyOCR ko+en",
            load_easyocr,
            "한국어·영어 / CPU / recognition-only",
        ),
        (
            "paddle_mobile",
            "PaddleOCR Korean PP-OCRv5 Mobile",
            lambda: load_paddle(PADDLE_KOREAN_MOBILE),
            "한국어·영어·숫자 / CPU / recognition-only",
        ),
        (
            "paddle_server",
            "PaddleOCR PP-OCRv5 Server (참고군)",
            lambda: load_paddle(PADDLE_GENERAL_SERVER),
            "공식 한글 지원 모델 아님",
        )
    ]

    models: list[dict[str, Any]] = []
    errors: list[str] = []

    for model_id, name, loader, note in specs:
        try:
            instance, load_ms = loader()

            models.append(
                {
                    "id": model_id,
                    "name": name,
                    "instance": instance,
                    "load_ms": load_ms,
                    "note": note,
                }
            )

        except Exception as exc:
            errors.append(
                f"{name} 로드 실패: "
                f"{type(exc).__name__}: {exc}"
            )

    return models, errors


# [모델 연산]

# easyOCR
def predict_easyocr(
    reader: Any,
    image: np.ndarray,
) -> tuple[str, float]:
    results = reader.recognize(
        image,
        horizontal_list=None,
        free_list=None,
        decoder="greedy",
        batch_size=1,
        workers=0,
        detail=1,
        paragraph=False,
    )

    if not results:
        return "", float("nan")

    result = results[0]

    if (
        not isinstance(result, (tuple, list))
        or len(result) < 3
    ):
        return "", float("nan")

    text = str(result[1])
    confidence = float(result[2])

    return text, confidence

# paddleOCR
def predict_paddle(
    model: Any,
    image: np.ndarray,
) -> tuple[str, float]:
    outputs = list(
        model.predict(
            input=image,
            batch_size=1,
        )
    )

    if not outputs:
        return "", float("nan")

    data = getattr(
        outputs[0],
        "json",
        None,
    )

    if callable(data):
        data = data()

    if isinstance(data, str):
        data = json.loads(data)

    elif not isinstance(data, dict):
        data = dict(data)

    payload = data.get(
        "res",
        data,
    )

    text = str(
        payload.get(
            "rec_text",
            "",
        )
    )

    confidence = float(
        payload.get(
            "rec_score",
            np.nan,
        )
    )

    return text, confidence

# 모델 종류에 맞는 OCR 예측 함수 호출
def predict(
    model: dict[str, Any],
    image: np.ndarray,
) -> tuple[str, float]:
    '''모델 종류에 맞는 OCR 예측 함수 호출'''
    model_id = model["id"]
    if model_id == "easyocr":
        return predict_easyocr(
            model["instance"],
            image,
        )
    
    if model_id in {"paddle_mobile", "paddle_server"}:
        return predict_paddle(
            model["instance"],
            image,
        )
    
    raise ValueError(f"지원하지 않는 모델 ID입니다: {model_id}")

# [시간 측정]

def timed_call(
    fn: Callable[[], tuple[str, float]],
) -> tuple[str, float, float]:
    started = time.perf_counter()

    text, confidence = fn()

    elapsed_ms = (
        time.perf_counter() - started
    ) * 1000

    return text, confidence, elapsed_ms


def warm_benchmark(
    fn: Callable[[], tuple[str, float]],
    repeats: int,
) -> tuple[str, float, list[float]]:
    text = ""
    confidence = float("nan")
    times: list[float] = []

    for _ in range(repeats):
        text, confidence, elapsed_ms = timed_call(fn)
        times.append(elapsed_ms)

    return text, confidence, times


# [Streamlit session state]

if "first_inference" not in st.session_state:
    st.session_state.first_inference = {}

if "results" not in st.session_state:
    st.session_state.results = None

if "model_times" not in st.session_state:
    st.session_state.model_times = None


# [화면]
st.title(
    "번호판 Crop OCR Recognition 벤치마크"
)

st.caption(
    "번호판 crop의 원본과 전처리본을 "
    "동일한 CPU 환경에서 비교합니다. "
    "Streamlit 렌더링과 파일 업로드 시간은 "
    "측정하지 않습니다."
)

st.info(
    "EasyOCR와 PaddleOCR의 confidence는 "
    "같은 척도로 보정된 값이 아닙니다. "
    "정답이 있다면 Exact Match와 CER을 "
    "우선해서 보세요."
)


# [사이드바 설정]
with st.sidebar:
    st.header("실험 설정")

    target_height = st.slider(
        "전처리 이미지 높이(px)",
        min_value=32,
        max_value=160,
        value=64,
        step=8,
    )

    padding_percent = st.slider(
        "전처리 외곽 여백(%)",
        min_value=0,
        max_value=20,
        value=5,
        step=1,
    )

    warm_repeats = st.slider(
        "Warm 반복 횟수",
        min_value=3,
        max_value=30,
        value=5,
        step=1,
    )

    st.divider()

    if st.button(
        "모델 캐시와 첫 추론 기록 초기화"
    ):
        st.cache_resource.clear()

        st.session_state.first_inference = {}
        st.session_state.results = None
        st.session_state.model_times = None

        st.rerun()


# [이미지 업로드]
uploads = st.file_uploader(
    "번호판 crop 이미지 업로드",
    type=[
        "png",
        "jpg",
        "jpeg",
        "bmp",
        "webp",
    ],
    accept_multiple_files=True,
)

items: list[dict[str, Any]] = []


if uploads:
    st.subheader(
        "원본·전처리 미리보기와 정답"
    )

    for index, upload in enumerate(uploads):
        try:
            file_bytes = upload.getvalue()

            original = decode_upload(
                file_bytes
            )

            processed = preprocess_plate(
                original,
                target_height,
                padding_percent,
            )

        except Exception as exc:
            st.error(
                f"{upload.name} 읽기 실패: "
                f"{type(exc).__name__}: {exc}"
            )
            continue

        key = (
            f"{index}_"
            f"{upload.name}_"
            f"{len(file_bytes)}"
        )

        with st.expander(
            f"{index + 1}. {upload.name}",
            expanded=index == 0,
        ):
            left, right = st.columns(2)

            left.image(
                original,
                caption=(
                    f"원본 · "
                    f"{original.shape[1]}"
                    f"×"
                    f"{original.shape[0]}"
                ),
                channels="BGR",
                use_container_width=True,
            )

            right.image(
                processed,
                caption=(
                    f"전처리 · "
                    f"{processed.shape[1]}"
                    f"×"
                    f"{processed.shape[0]}"
                ),
                channels="BGR",
                use_container_width=True,
            )

            ground_truth = st.text_input(
                "정답 번호판 (선택)",
                key=f"gt_{key}",
                placeholder="예: 12가3456",
            )

        items.append(
            {
                "file_name": upload.name,
                "image": original,
                "gt": ground_truth.strip(),
            }
        )


# [벤치마크 실행]
run = st.button(
    "벤치마크 실행",
    type="primary",
    disabled=not items,
    use_container_width=True,
)


if run and items:
    with st.spinner(
        "모델 로드 중입니다. "
        "최초 실행에서는 가중치를 다운로드합니다."
    ):
        models, errors = load_models()

    for error in errors:
        st.error(error)

    if not models:
        st.error(
            "로드된 모델이 없습니다."
        )

    else:
        # 첫 번째 이미지의 원본을
        # 세션 최초 추론 측정용으로 사용합니다.
        probe = items[0]["image"]

        model_time_rows: list[
            dict[str, Any]
        ] = []

        for model in models:
            if (
                model["id"]
                not in st.session_state.first_inference
            ):
                try:
                    _, _, first_ms = timed_call(
                        lambda m=model: predict(
                            m,
                            probe,
                        )
                    )

                    st.session_state.first_inference[
                        model["id"]
                    ] = first_ms

                except Exception as exc:
                    st.session_state.first_inference[
                        model["id"]
                    ] = None

                    st.error(
                        f"{model['name']} 첫 추론 실패: "
                        f"{type(exc).__name__}: {exc}"
                    )

            model_time_rows.append(
                {
                    "model": model["name"],
                    "note": model["note"],
                    "model_load_ms": round(
                        model["load_ms"],
                        3,
                    ),
                    "first_inference_ms": (
                        finite_or_none(
                            st.session_state
                            .first_inference
                            .get(model["id"])
                        )
                    ),
                }
            )

        rows: list[dict[str, Any]] = []

        total_jobs = (
            len(items)
            * 2
            * len(models)
        )

        completed = 0

        progress = st.progress(
            0,
            text="벤치마크 준비 중",
        )

        for item in items:
            prep_started = time.perf_counter()

            processed = preprocess_plate(
                item["image"],
                target_height,
                padding_percent,
            )

            preprocess_ms = (
                time.perf_counter()
                - prep_started
            ) * 1000

            gt_normalized = normalize_plate(
                item["gt"]
            )

            variants = [
                (
                    "Original",
                    item["image"],
                    0.0,
                ),
                (
                    "Preprocessed",
                    processed,
                    preprocess_ms,
                ),
            ]

            for (
                variant_name,
                image,
                prep_ms,
            ) in variants:
                for model in models:
                    completed += 1

                    progress.progress(
                        completed / total_jobs,
                        text=(
                            f"{item['file_name']} · "
                            f"{variant_name} · "
                            f"{model['name']}"
                        ),
                    )

                    common = {
                        "file_name": (
                            item["file_name"]
                        ),
                        "input_variant": (
                            variant_name
                        ),
                        "model": (
                            model["name"]
                        ),
                        "ground_truth": (
                            item["gt"]
                        ),
                        "ground_truth_normalized": (
                            gt_normalized
                        ),
                        "preprocess_ms": round(
                            prep_ms,
                            3,
                        ),
                        "model_load_ms": round(
                            model["load_ms"],
                            3,
                        ),
                        "first_inference_ms": (
                            finite_or_none(
                                st.session_state
                                .first_inference
                                .get(model["id"])
                            )
                        ),
                        "warm_repeats": (
                            warm_repeats
                        ),
                        "device": "CPU",
                    }

                    try:
                        (
                            text,
                            confidence,
                            times,
                        ) = warm_benchmark(
                            lambda m=model, img=image : predict(
                                m,
                                img,
                            ),
                            warm_repeats,
                        )

                        prediction_normalized = (
                            normalize_plate(text)
                        )

                        times_array = np.asarray(
                            times,
                            dtype=np.float64,
                        )

                        warm_mean = float(
                            times_array.mean()
                        )

                        exact_match = (
                            (
                                prediction_normalized
                                == gt_normalized
                            )
                            if gt_normalized
                            else None
                        )

                        cer_value = calculate_cer(
                            gt_normalized,
                            prediction_normalized,
                        )

                        rows.append(
                            {
                                **common,
                                "prediction": text,
                                "prediction_normalized": (
                                    prediction_normalized
                                ),
                                "confidence": (
                                    finite_or_none(
                                        confidence
                                    )
                                ),
                                "exact_match": (
                                    exact_match
                                ),
                                "cer": cer_value,
                                "warm_mean_ms": round(
                                    warm_mean,
                                    3,
                                ),
                                "warm_median_ms": round(
                                    float(
                                        np.median(
                                            times_array
                                        )
                                    ),
                                    3,
                                ),
                                "warm_p95_ms": round(
                                    float(
                                        np.percentile(
                                            times_array,
                                            95,
                                        )
                                    ),
                                    3,
                                ),
                                "end_to_end_estimated_ms": (
                                    round(
                                        prep_ms
                                        + warm_mean,
                                        3,
                                    )
                                ),
                                "error": "",
                            }
                        )

                    except Exception as exc:
                        rows.append(
                            {
                                **common,
                                "prediction": "",
                                "prediction_normalized": "",
                                "confidence": None,
                                "exact_match": None,
                                "cer": None,
                                "warm_mean_ms": None,
                                "warm_median_ms": None,
                                "warm_p95_ms": None,
                                "end_to_end_estimated_ms": (
                                    None
                                ),
                                "error": (
                                    f"{type(exc).__name__}: "
                                    f"{exc}"
                                ),
                            }
                        )

        progress.empty()

        st.session_state.model_times = (
            pd.DataFrame(
                model_time_rows
            )
        )

        st.session_state.results = (
            pd.DataFrame(
                rows
            )
        )


# [결과 표시]
model_times = (
    st.session_state.model_times
)

results = (
    st.session_state.results
)


if (
    isinstance(model_times, pd.DataFrame)
    and not model_times.empty
):
    st.subheader(
        "모델 로드 및 첫 추론"
    )

    st.dataframe(
        model_times,
        hide_index=True,
        use_container_width=True,
        column_config={
            "model_load_ms": (
                st.column_config.NumberColumn(
                    format="%.3f ms"
                )
            ),
            "first_inference_ms": (
                st.column_config.NumberColumn(
                    format="%.3f ms"
                )
            ),
        },
    )

    st.caption(
        "첫 추론은 캐시된 모델이 현재 세션에서 "
        "처음 호출될 때 한 번만 측정됩니다. "
        "재측정하려면 사이드바에서 캐시를 "
        "초기화하세요."
    )


if (
    isinstance(results, pd.DataFrame)
    and not results.empty
):
    st.subheader(
        "상세 결과"
    )

    st.dataframe(
        results,
        hide_index=True,
        use_container_width=True,
        column_config={
            "confidence": (
                st.column_config.NumberColumn(
                    format="%.4f"
                )
            ),
            "cer": (
                st.column_config.NumberColumn(
                    format="%.4f"
                )
            ),
            "preprocess_ms": (
                st.column_config.NumberColumn(
                    format="%.3f ms"
                )
            ),
            "model_load_ms": (
                st.column_config.NumberColumn(
                    format="%.3f ms"
                )
            ),
            "first_inference_ms": (
                st.column_config.NumberColumn(
                    format="%.3f ms"
                )
            ),
            "warm_mean_ms": (
                st.column_config.NumberColumn(
                    format="%.3f ms"
                )
            ),
            "warm_median_ms": (
                st.column_config.NumberColumn(
                    format="%.3f ms"
                )
            ),
            "warm_p95_ms": (
                st.column_config.NumberColumn(
                    format="%.3f ms"
                )
            ),
            "end_to_end_estimated_ms": (
                st.column_config.NumberColumn(
                    format="%.3f ms"
                )
            ),
        },
    )

    valid = results[
        results["error"]
        .fillna("")
        == ""
    ].copy()

    has_ground_truth = (
        valid[
            "ground_truth_normalized"
        ]
        .fillna("")
        .ne("")
    )

    if not valid.empty:
        if has_ground_truth.any():
            scored = valid[
                has_ground_truth
            ]

            summary = (
                scored
                .groupby(
                    [
                        "model",
                        "input_variant",
                    ]
                )
                .agg(
                    samples=(
                        "file_name",
                        "count",
                    ),
                    exact_match_accuracy=(
                        "exact_match",
                        "mean",
                    ),
                    mean_cer=(
                        "cer",
                        "mean",
                    ),
                    mean_confidence=(
                        "confidence",
                        "mean",
                    ),
                    mean_warm_ms=(
                        "warm_mean_ms",
                        "mean",
                    ),
                    mean_p95_ms=(
                        "warm_p95_ms",
                        "mean",
                    ),
                    mean_end_to_end_ms=(
                        "end_to_end_estimated_ms",
                        "mean",
                    ),
                )
                .reset_index()
            )

        else:
            summary = (
                valid
                .groupby(
                    [
                        "model",
                        "input_variant",
                    ]
                )
                .agg(
                    samples=(
                        "file_name",
                        "count",
                    ),
                    mean_confidence=(
                        "confidence",
                        "mean",
                    ),
                    mean_warm_ms=(
                        "warm_mean_ms",
                        "mean",
                    ),
                    mean_p95_ms=(
                        "warm_p95_ms",
                        "mean",
                    ),
                    mean_end_to_end_ms=(
                        "end_to_end_estimated_ms",
                        "mean",
                    ),
                )
                .reset_index()
            )

        st.subheader(
            "집계 결과"
        )

        st.dataframe(
            summary,
            hide_index=True,
            use_container_width=True,
        )

    csv_data = (
        results
        .to_csv(
            index=False
        )
        .encode(
            "utf-8-sig"
        )
    )

    st.download_button(
        "결과 CSV 다운로드",
        data=csv_data,
        file_name=(
            "plate_ocr_benchmark_results.csv"
        ),
        mime="text/csv",
        use_container_width=True,
    )
