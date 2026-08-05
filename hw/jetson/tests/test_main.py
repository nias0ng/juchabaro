"""main composition root의 migration·구역 로딩·worker 종료 테스트."""

from pathlib import Path
from threading import Event

from fastapi.testclient import TestClient

from src.config.settings import Settings
from src.storage.database import connect_database


class _BlockingPipeline:
    def __init__(self) -> None:
        self.opened = False
        self.entered_run = Event()
        self.closed = Event()

    def open(self) -> None:
        self.opened = True

    def run(self, *, stop_requested) -> int:
        self.entered_run.set()
        while not stop_requested():
            self.closed.wait(0.01)
        return 0

    def close(self) -> None:
        self.closed.set()


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_path=tmp_path / "runtime.db",
        evidence_spool_path=tmp_path / "evidence",
        evidence_spool_cap_bytes=8 * 1024 * 1024,
        zone_definition_path=(
            Path(__file__).parents[1]
            / "config"
            / "zone_definition.pilot.json"
        ),
        zone_entry_confirm_seconds=3.0,
        zone_exit_confirm_seconds=3.0,
        absence_confirmation_seconds=5.0,
        trusted_sample_max_gap_seconds=1.0,
        motion_window_seconds=0.75,
        motion_min_observation_span_seconds=0.20,
        motion_max_sample_gap_seconds=0.50,
        motion_stationary_threshold=0.03,
        motion_moving_threshold=0.10,
        motion_min_samples=3,
        motion_min_trend_consistency=0.60,
        parking_confirm_seconds=600.0,
        parking_move_confirm_seconds=3.0,
    )


def test_lifespan_prepares_runtime_and_stops_monitoring_worker(tmp_path) -> None:
    # src.main은 배포용 module-level app도 제공하므로, 필수
    # Settings env가 적용된 test 실행 시점에 import한다.
    from src.main import RuntimeContext, create_app

    settings = _settings(tmp_path)
    pipeline = _BlockingPipeline()
    received_contexts: list[RuntimeContext] = []

    def build_pipeline(context: RuntimeContext):
        received_contexts.append(context)
        return pipeline

    application = create_app(
        settings=settings,
        monitoring_pipeline_factory=build_pipeline,
    )

    with TestClient(application) as client:
        assert pipeline.entered_run.wait(timeout=1.0)
        assert client.get("/health").status_code == 200
        assert application.state.zone_registry.zone_definition_version == 3
        assert application.state.monitoring_worker.is_running is True

        connection = connect_database(settings.database_path)
        try:
            assert connection.execute(
                "SELECT COUNT(*) FROM schema_migrations"
            ).fetchone()[0] == 3
        finally:
            connection.close()

    assert len(received_contexts) == 1
    assert received_contexts[0].zones is application.state.zone_registry
    assert pipeline.opened is True
    assert pipeline.closed.is_set()
    assert application.state.monitoring_worker.is_running is False


def test_lifespan_keeps_monitoring_disabled_without_exact_wire_factory(
    tmp_path,
) -> None:
    from src.main import create_app

    application = create_app(settings=_settings(tmp_path))

    with TestClient(application) as client:
        assert client.get("/health").status_code == 200
        assert application.state.monitoring_worker is None
