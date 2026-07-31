"""테스트 전역 설정.

Settings에 기본값 없는 필수 필드가 있어 .env 없이 get_settings()를 부르면
ValidationError가 난다. 순수 로직 테스트가 환경 파일 존재에 의존하지 않도록
여기서 값을 주입한다. 실제 임계값은 .env로 주며 이 값은 테스트용이다.

(436 병합) 이 파일에 있던 sys.path 조작은 제거했다. 420이 추가했을 당시에는
`src.` 임포트를 해결할 유일한 수단이었으나, 421의 pyproject.toml이
`pythonpath = ["."]`로 같은 일을 하므로 중복이 됐다.
"""

import pytest

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
