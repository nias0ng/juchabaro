"""6프레임 번호판 OCR 파이프라인의 단계별 입출력을 보여주는 앱."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

import streamlit as st


st.set_page_config(
    page_title="번호판 OCR 파이프라인 Viewer",
    layout="wide",
)


# ``streamlit run path/to/app.py`` 실행에서도 package import가 동일하게 된다.
OCR_DIR = Path(__file__).resolve().parent.parent
if str(OCR_DIR) not in sys.path:
    sys.path.insert(0, str(OCR_DIR))


from pipeline_viewer.service import (  # noqa: E402
    BurstInputError,
    DebugRun,
    DebugRuntime,
    UploadPayload,
    decode_burst,
    default_model_paths,
    load_runtime,
    model_paths_from_root,
    run_debug_pipeline,
)
from pipeline_viewer.ui import (  # noqa: E402
    render_burst_preview,
    render_debug_run,
    render_model_paths,
    render_runtime_ready,
)


SESSION_RUN_KEY = "pipeline_viewer_last_run"
DEVICE = "cpu"


@dataclass(slots=True)
class RuntimeLoadOutcome:
    """모델 준비 실패도 캐시해 Streamlit rerun마다 재시도하지 않게 한다."""

    runtime: DebugRuntime | None
    error_type: str | None = None
    error_message: str | None = None


@st.cache_resource(show_spinner=False)
def _cached_runtime(model_root: str, device: str) -> RuntimeLoadOutcome:
    """동일 모델 경로와 device 조합을 프로세스에서 한 번만 준비한다."""

    try:
        runtime = load_runtime(
            model_paths_from_root(Path(model_root)),
            device=device,
        )
    except Exception as exc:
        return RuntimeLoadOutcome(
            runtime=None,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
    return RuntimeLoadOutcome(runtime=runtime)


def _clear_runtime() -> None:
    """모델 캐시와 현재 세션의 이전 실행 결과를 함께 비운다."""

    _cached_runtime.clear()
    st.session_state.pop(SESSION_RUN_KEY, None)


def _render_sidebar(model_root: Path) -> bool:
    """고정된 PC 모델 위치와 명시적 재로드 동작을 표시한다."""

    with st.sidebar:
        st.header("Runtime")
        st.caption("Device")
        st.code(DEVICE, language="text")
        st.caption("Model root")
        st.code(str(model_root), language="text")
        st.caption(
            "모델 파일을 교체하거나 새로 배치한 뒤에만 재로드하세요."
        )
        return st.button(
            "모델 다시 로드",
            use_container_width=True,
        )


def _load_models(model_root: Path) -> RuntimeLoadOutcome:
    """화면 최초 진입 시 모델 로드와 warm-up을 실행한다."""

    with st.spinner(
        "YOLO와 PaddleOCR 모델을 로드하고 dummy warm-up을 실행합니다..."
    ):
        return _cached_runtime(str(model_root), DEVICE)


def main() -> None:
    """Streamlit 화면을 구성하고 사용자 요청 시 파이프라인을 실행한다."""

    paths = default_model_paths()
    reload_requested = _render_sidebar(paths.root)
    if reload_requested:
        _clear_runtime()
        st.rerun()

    st.title("번호판 OCR 파이프라인 Viewer")
    st.caption(
        "Raspberry Pi 운영 파이프라인을 그대로 실행하고, "
        "각 함수의 이미지·데이터 입출력과 처리 시간을 확인합니다."
    )

    outcome = _load_models(paths.root)
    runtime = outcome.runtime

    if runtime is None:
        st.error(
            "모델을 준비하지 못했습니다.\n\n"
            f"{outcome.error_type}: {outcome.error_message}"
        )
        st.info(
            "아래 경로에 모델을 배치한 뒤 사이드바의 "
            "'모델 다시 로드'를 누르세요."
        )
        render_model_paths(paths)
    else:
        render_runtime_ready(runtime)
        render_model_paths(runtime.model_paths)

    st.divider()
    st.header("연속 프레임 입력")
    uploads = st.file_uploader(
        "촬영 시간순 파일명으로 된 사진 6장을 선택하세요.",
        type=("jpg", "jpeg", "png", "bmp", "webp"),
        accept_multiple_files=True,
        help=(
            "파일명을 자연 정렬해 frame_index 0~5를 부여합니다. "
            "예: 01.jpg, 02.jpg, ..., 06.jpg"
        ),
    )

    if not uploads:
        st.info("사진 6장을 업로드하면 입력 순서와 해상도를 확인합니다.")
        return

    if len(uploads) != 6:
        st.warning(f"사진은 정확히 6장이 필요합니다: actual={len(uploads)}")
        return

    payloads = tuple(
        UploadPayload(
            file_name=upload.name,
            content=upload.getvalue(),
        )
        for upload in uploads
    )

    try:
        burst = decode_burst(payloads)
    except BurstInputError as exc:
        st.error(str(exc))
        return

    render_burst_preview(burst)

    run_requested = st.button(
        "전체 파이프라인 실행",
        type="primary",
        disabled=runtime is None,
        use_container_width=True,
    )

    if run_requested and runtime is not None:
        with st.spinner("6프레임 OCR 파이프라인을 실행합니다..."):
            try:
                debug_run = run_debug_pipeline(runtime, burst)
            except Exception as exc:
                # PlateOcrPipeline 밖에서 발생한 viewer 조립 오류만 이 경로로 온다.
                st.error(
                    "파이프라인 실행 요청을 완료하지 못했습니다: "
                    f"{type(exc).__name__}: {exc}"
                )
            else:
                st.session_state[SESSION_RUN_KEY] = debug_run

    previous_run = st.session_state.get(SESSION_RUN_KEY)
    if isinstance(previous_run, DebugRun):
        if previous_run.request_signature == burst.signature:
            render_debug_run(previous_run, burst)
        else:
            st.warning(
                "업로드 파일이 이전 실행과 달라졌습니다. "
                "현재 입력으로 파이프라인을 다시 실행하세요."
            )


if __name__ == "__main__":
    main()
