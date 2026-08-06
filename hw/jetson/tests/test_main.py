"""main composition root의 migration·구역 로딩·worker 종료 테스트."""

from pathlib import Path
from threading import Event

import pytest
from fastapi import FastAPI
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

    def run(self, *, stop_requested, frame_observer=None) -> int:
        del frame_observer
        self.entered_run.set()
        while not stop_requested():
            self.closed.wait(0.01)
        return 0

    def close(self) -> None:
        self.closed.set()


class _LifecycleWorker:
    def __init__(
        self,
        *,
        name: str,
        stop_calls: list[str],
        fail_on_start: bool,
        fail_on_stop: bool,
    ) -> None:
        self.name = name
        self.stop_calls = stop_calls
        self.fail_on_start = fail_on_start
        self.fail_on_stop = fail_on_stop
        self.start_count = 0
        self.stop_count = 0

    @property
    def is_running(self) -> bool:
        return self.start_count == 1 and self.stop_count == 0

    def start(self) -> None:
        self.start_count += 1
        if self.fail_on_start:
            raise RuntimeError(f"{self.name} start failed")

    def stop(self) -> None:
        self.stop_count += 1
        self.stop_calls.append(self.name)
        if self.fail_on_stop:
            raise RuntimeError(f"{self.name} stop failed")


def _install_lifecycle_worker_spies(
    main,
    monkeypatch: pytest.MonkeyPatch,
    *,
    stop_calls: list[str],
    failing_start_worker: str | None = None,
    failing_stop_worker: str | None = None,
) -> dict[str, _LifecycleWorker]:
    workers: dict[str, _LifecycleWorker] = {}

    def worker_constructor(name: str):
        def construct(_owner) -> _LifecycleWorker:
            worker = _LifecycleWorker(
                name=name,
                stop_calls=stop_calls,
                fail_on_start=name == failing_start_worker,
                fail_on_stop=name == failing_stop_worker,
            )
            workers[name] = worker
            return worker

        return construct

    monkeypatch.setattr(
        main,
        "MonitoringWorker",
        worker_constructor("monitoring"),
    )
    monkeypatch.setattr(
        main,
        "MoveVerificationExecutorWorker",
        worker_constructor("move verification"),
    )
    monkeypatch.setattr(
        main,
        "OutboxPublisherWorker",
        worker_constructor("outbox publication"),
    )
    monkeypatch.setattr(
        main,
        "EvidencePublicationWorker",
        worker_constructor("evidence publication"),
    )

    # HTTP client나 실제 publisher를 만들 필요가 없는 composition spy다.
    monkeypatch.setattr(main, "BackendClient", lambda **_kwargs: object())
    monkeypatch.setattr(
        main,
        "OutboxPublisher",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        main,
        "EvidencePublicationPublisher",
        lambda **_kwargs: object(),
    )
    return workers


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_path=tmp_path / "runtime.db",
        evidence_spool_path=tmp_path / "evidence",
        evidence_spool_cap_bytes=8 * 1024 * 1024,
        zone_definition_path=(
            Path(__file__).parents[1]
            / "config"
            / "zone_definition.json"
        ),
        egress_aisle_path=(
            Path(__file__).parents[1]
            / "config"
            / "egress_aisle.json"
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


def test_create_runtime_app_binds_concrete_monitoring_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.main as main

    expected_app = FastAPI()
    received: dict[str, object] = {}

    def fake_create_app(
        *,
        settings: Settings | None = None,
        monitoring_pipeline_factory: (
            main.MonitoringPipelineFactory | None
        ) = None,
    ) -> FastAPI:
        received["settings"] = settings
        received["monitoring_pipeline_factory"] = (
            monitoring_pipeline_factory
        )
        return expected_app

    monkeypatch.setattr(main, "create_app", fake_create_app)

    application = main._create_runtime_app()

    assert application is expected_app
    assert received == {
        "settings": None,
        "monitoring_pipeline_factory": (
            main.build_runtime_monitoring_pipeline
        ),
    }


def test_lifespan_stops_producers_before_publication_consumers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.main as main

    stop_calls: list[str] = []
    workers = _install_lifecycle_worker_spies(
        main,
        monkeypatch,
        stop_calls=stop_calls,
    )
    settings = _settings(tmp_path).model_copy(
        update={"backend_hw_api_key": "configured-hardware-key"}
    )
    application = main.create_app(
        settings=settings,
        monitoring_pipeline_factory=lambda _context: object(),
    )

    with TestClient(application) as client:
        assert client.get("/health").status_code == 200
        assert all(
            worker.start_count == 1
            for worker in workers.values()
        )

    assert stop_calls == [
        "monitoring",
        "move verification",
        "outbox publication",
        "evidence publication",
    ]
    assert all(worker.start_count == 1 for worker in workers.values())
    assert all(worker.stop_count == 1 for worker in workers.values())


def test_lifespan_continues_cleanup_after_worker_stop_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.main as main

    stop_calls: list[str] = []
    workers = _install_lifecycle_worker_spies(
        main,
        monkeypatch,
        stop_calls=stop_calls,
        failing_stop_worker="monitoring",
    )
    settings = _settings(tmp_path).model_copy(
        update={"backend_hw_api_key": "configured-hardware-key"}
    )
    application = main.create_app(
        settings=settings,
        monitoring_pipeline_factory=lambda _context: object(),
    )

    with pytest.raises(RuntimeError, match="monitoring stop failed"):
        with TestClient(application) as client:
            assert client.get("/health").status_code == 200

    assert stop_calls == [
        "monitoring",
        "move verification",
        "outbox publication",
        "evidence publication",
    ]
    assert all(worker.start_count == 1 for worker in workers.values())
    assert all(worker.stop_count == 1 for worker in workers.values())


def test_lifespan_preserves_startup_error_during_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.main as main

    stop_calls: list[str] = []
    workers = _install_lifecycle_worker_spies(
        main,
        monkeypatch,
        stop_calls=stop_calls,
        failing_start_worker="outbox publication",
        failing_stop_worker="monitoring",
    )
    settings = _settings(tmp_path).model_copy(
        update={"backend_hw_api_key": "configured-hardware-key"}
    )
    application = main.create_app(
        settings=settings,
        monitoring_pipeline_factory=lambda _context: object(),
    )

    with pytest.raises(
        RuntimeError,
        match="outbox publication start failed",
    ):
        with TestClient(application):
            pass

    assert stop_calls == [
        "monitoring",
        "move verification",
        "outbox publication",
        "evidence publication",
    ]
    assert all(worker.start_count == 1 for worker in workers.values())
    assert all(worker.stop_count == 1 for worker in workers.values())


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
        assert application.state.zone_registry.zone_definition_version == 1
        assert (
            application.state.egress_aisle_registry.zone_definition_version
            == 1
        )
        assert application.state.monitoring_worker.is_running is True
        assert application.state.move_verification_worker.is_running is True
        assert application.state.publication_preparer is (
            received_contexts[0].publication_preparer
        )
        assert application.state.outbox_publisher_worker is None

        connection = connect_database(settings.database_path)
        try:
            assert connection.execute(
                "SELECT COUNT(*) FROM schema_migrations"
            ).fetchone()[0] == 5
        finally:
            connection.close()

    assert len(received_contexts) == 1
    assert received_contexts[0].zones is application.state.zone_registry
    assert (
        received_contexts[0].egress_aisles
        is application.state.egress_aisle_registry
    )
    assert pipeline.opened is True
    assert pipeline.closed.is_set()
    assert application.state.monitoring_worker.is_running is False
    assert application.state.move_verification_worker.is_running is False


def test_lifespan_keeps_monitoring_disabled_without_exact_wire_factory(
    tmp_path,
) -> None:
    from src.main import create_app

    application = create_app(settings=_settings(tmp_path))

    with TestClient(application) as client:
        assert client.get("/health").status_code == 200
        assert application.state.monitoring_worker is None
        assert application.state.move_verification_worker.is_running is True
        assert application.state.evidence_publication_worker is None
        assert application.state.outbox_publisher_worker is None

    assert application.state.move_verification_worker.is_running is False


def test_lifespan_runs_outbox_publisher_when_backend_hw_api_key_is_configured(
    tmp_path,
) -> None:
    from src.main import create_app

    settings = _settings(tmp_path).model_copy(
        update={"backend_hw_api_key": "configured-hardware-key"}
    )
    application = create_app(settings=settings)

    with TestClient(application) as client:
        assert client.get("/health").status_code == 200
        assert application.state.evidence_publication_worker.is_running is True
        assert application.state.outbox_publisher_worker.is_running is True

    assert application.state.evidence_publication_worker.is_running is False
    assert application.state.outbox_publisher_worker.is_running is False
