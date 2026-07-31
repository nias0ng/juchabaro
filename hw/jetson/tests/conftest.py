"""테스트 전역 설정.

Settings에 기본값 없는 필수 필드가 있어 .env 없이 get_settings()를 부르면
ValidationError가 난다. 순수 로직 테스트가 환경 파일 존재에 의존하지 않도록
여기서 값을 주입한다. 실제 임계값은 .env로 주며 이 값은 테스트용이다.
"""

import sys
from pathlib import Path

import pytest

# (병합 주석) 아래 sys.path 조작은 420이 추가한 것이다. 그 브랜치에는 421의
# pyproject.toml(`pythonpath = ["."]`)이 없어 `src.` 임포트를 이 방법으로만
# 해결할 수 있었다. 이 브랜치에는 둘 다 있어 중복 경로가 되지만 무해하다.
# 421이 develop에 병합되면 이 두 줄은 지워도 된다.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

REQUIRED_ENV = {
    "ZONE_ENTRY_CONFIRM_SECONDS": "3.0",
    "ZONE_EXIT_CONFIRM_SECONDS": "3.0",
}


@pytest.fixture(autouse=True)
def _required_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    # get_settings가 lru_cache라 앞선 테스트의 캐시가 남으면 주입이 무시된다.
    from src.config.settings import get_settings

    get_settings.cache_clear()
