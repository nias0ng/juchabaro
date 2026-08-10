"""`src.` 절대 임포트가 실행 위치와 무관하게 해석되는지 고정한다.

이 테스트가 깨지면 pyproject.toml의 pythonpath 설정이 사라졌거나 rootdir이
바뀐 것이다. hw/raspberry-pi처럼 현재 디렉터리 의존으로 돌아가면 다른
디렉터리에서 pytest를 부르는 순간 전체 테스트가 임포트 에러로 죽는다.
"""

from pathlib import Path


def test_src_package_is_importable() -> None:
    from src.parking.models import ZoneVisitState

    assert ZoneVisitState.ENTERING.value == "ENTERING"


def test_tracking_models_are_importable() -> None:
    from src.tracking.models import MotionSignal

    assert MotionSignal.STATIONARY.value == "STATIONARY"


def test_rootdir_is_jetson_project_root() -> None:
    """pythonpath가 가리키는 곳이 hw/jetson인지 확인한다."""
    import src

    src_dir = Path(src.__file__).resolve().parent
    assert src_dir.name == "src"
    assert (src_dir.parent / "pyproject.toml").is_file()
