"""FastAPI composition root의 ToF warning runtime wiring 계약 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.config.settings import Settings
from src.parking.models import ZoneId


class _RuntimeRequester:
    def __init__(self) -> None:
        self.request_count = 0

    def request_after_monitoring_context_change(self) -> None:
        self.request_count += 1


class _TofOwner:
    def __init__(
        self,
        events: list[str],
        *,
        prepare_error: Exception | None = None,
        start_error: Exception | None = None,
        stop_errors: list[Exception | None] | None = None,
        close_error: Exception | None = None,
    ) -> None:
        self.events = events
        self.runtime = _RuntimeRequester()
        self.prepare_error = prepare_error
        self.start_error = start_error
        self.stop_errors = list(stop_errors or ())
        self.close_error = close_error
        self.stop_count = 0
        self.failures: tuple[object, ...] = ()

    def prepare(self) -> None:
        self.events.append("tof.prepare")
        if self.prepare_error is not None:
            raise self.prepare_error

    def start(self) -> None:
        self.events.append("tof.start")
        if self.start_error is not None:
            raise self.start_error

    def stop_workers(self) -> None:
        self.stop_count += 1
        self.events.append(f"tof.stop.{self.stop_count}")
        if self.stop_errors:
            error = self.stop_errors.pop(0)
            if error is not None:
                raise error

    def close(self) -> None:
        self.events.append("tof.close")
        if self.close_error is not None:
            raise self.close_error


class _MonitoringWorker:
    def __init__(
        self,
        events: list[str],
        *,
        frame_observer: object | None,
        prepare_error: Exception | None = None,
        start_error: Exception | None = None,
        stop_error: Exception | None = None,
    ) -> None:
        self.events = events
        self.frame_observer = frame_observer
        self.prepare_error = prepare_error
        self.start_error = start_error
        self.stop_error = stop_error
        self.running = False

    @property
    def is_running(self) -> bool:
        return self.running

    def prepare(self) -> None:
        self.events.append("monitoring.prepare")
        if self.prepare_error is not None:
            raise self.prepare_error

    def start(self) -> None:
        self.events.append("monitoring.start")
        if self.start_error is not None:
            raise self.start_error
        self.running = True

    def stop(self) -> None:
        self.events.append("monitoring.stop")
        self.running = False
        if self.stop_error is not None:
            raise self.stop_error


class _MoveWorker:
    def __init__(
        self,
        events: list[str],
        *,
        start_error: Exception | None = None,
        stop_error: Exception | None = None,
    ) -> None:
        self.events = events
        self.start_error = start_error
        self.stop_error = stop_error

    def start(self) -> None:
        self.events.append("move.start")
        if self.start_error is not None:
            raise self.start_error

    def stop(self) -> None:
        self.events.append("move.stop")
        if self.stop_error is not None:
            raise self.stop_error


class _EvidenceCoordinator:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def recover(self) -> None:
        self.events.append("evidence.recover")


class _Overlay:
    def __init__(self, calls: list[str], **_kwargs: object) -> None:
        self.calls = calls

    def __call__(self, *_args: object) -> None:
        self.calls.append("overlay")


class _TofObserver:
    def __init__(
        self,
        calls: list[str],
        *,
        requester: object,
        policy: object,
    ) -> None:
        self.calls = calls
        self.requester = requester
        self.policy = policy

    def __call__(self, *_args: object) -> None:
        self.calls.append("tof")


class _PublicationWorker:
    def __init__(self, name: str, events: list[str]) -> None:
        self.name = name
        self.events = events

    def prepare(self) -> None:
        self.events.append(f"{self.name}.prepare")

    def start(self) -> None:
        self.events.append(f"{self.name}.start")

    def stop(self) -> None:
        self.events.append(f"{self.name}.stop")


def _settings(
    tmp_path: Path,
    *,
    tof_enabled: bool = True,
    live_stream_enabled: bool = False,
    backend_hw_api_key: str = "",
) -> Settings:
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
        live_stream_enabled=live_stream_enabled,
        backend_hw_api_key=backend_hw_api_key,
        tof_enabled=tof_enabled,
        tof_disabled_zone_id=7,
        tof_ev_charging_zone_id=8,
        tof_monitoring_freshness_seconds=5.0,
    )


def _install_runtime_fakes(
    main: object,
    monkeypatch: pytest.MonkeyPatch,
    events: list[str],
    *,
    monitoring_prepare_error: Exception | None = None,
    monitoring_start_error: Exception | None = None,
    monitoring_stop_error: Exception | None = None,
    move_start_error: Exception | None = None,
    move_stop_error: Exception | None = None,
) -> dict[str, object]:
    captured: dict[str, object] = {}

    def build_monitoring_worker(
        _pipeline: object,
        *,
        frame_observer: object | None = None,
    ) -> _MonitoringWorker:
        worker = _MonitoringWorker(
            events,
            frame_observer=frame_observer,
            prepare_error=monitoring_prepare_error,
            start_error=monitoring_start_error,
            stop_error=monitoring_stop_error,
        )
        captured["monitoring_worker"] = worker
        return worker

    def build_move_worker(_executor: object) -> _MoveWorker:
        worker = _MoveWorker(
            events,
            start_error=move_start_error,
            stop_error=move_stop_error,
        )
        captured["move_worker"] = worker
        return worker

    monkeypatch.setattr(main, "MonitoringWorker", build_monitoring_worker)
    monkeypatch.setattr(main, "MoveVerificationExecutor", lambda **_kwargs: object())
    monkeypatch.setattr(main, "MoveVerificationExecutorWorker", build_move_worker)
    monkeypatch.setattr(
        main,
        "EvidenceCaptureCoordinator",
        lambda **_kwargs: _EvidenceCoordinator(events),
    )
    return captured


def test_tof_factory_receives_exact_dependencies_without_opening_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.main as main

    events: list[str] = []
    owner = _TofOwner(events)
    received: dict[str, object] = {}
    _install_runtime_fakes(main, monkeypatch, events)

    def forbidden_connection() -> None:
        raise AssertionError("factory composition must not open DB connection")

    monkeypatch.setattr(main, "connect_database", forbidden_connection)

    def factory(**kwargs: object) -> _TofOwner:
        received.update(kwargs)
        return owner

    settings = _settings(tmp_path)
    application = main.create_app(
        settings=settings,
        monitoring_pipeline_factory=lambda _context: object(),
        tof_warning_runtime_factory=factory,
    )

    with TestClient(application):
        assert application.state.tof_warning_runtime is owner
        assert received["settings"] is settings
        assert received["zones"] is application.state.zone_registry
        assert callable(received["connection_factory"])


@pytest.mark.parametrize("factory_result", [None, RuntimeError("factory failed")])
def test_tof_factory_none_or_error_keeps_monitoring_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    factory_result: object,
) -> None:
    import src.main as main

    events: list[str] = []
    _install_runtime_fakes(main, monkeypatch, events)

    def factory(**_kwargs: object) -> None:
        if isinstance(factory_result, Exception):
            raise factory_result
        return None

    application = main.create_app(
        settings=_settings(tmp_path),
        monitoring_pipeline_factory=lambda _context: object(),
        tof_warning_runtime_factory=factory,
    )

    with TestClient(application):
        assert "monitoring.start" in events
        assert application.state.tof_warning_runtime is None
        assert application.state.tof_monitoring_context_observer is None


def test_monitoring_factory_runs_before_tof_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.main as main

    events: list[str] = []
    owner = _TofOwner(events)
    _install_runtime_fakes(main, monkeypatch, events)

    application = main.create_app(
        settings=_settings(tmp_path),
        monitoring_pipeline_factory=lambda _context: (
            events.append("monitoring.factory") or object()
        ),
        tof_warning_runtime_factory=lambda **_kwargs: (
            events.append("tof.factory") or owner
        ),
    )

    with TestClient(application):
        assert events.index("monitoring.factory") < events.index("tof.factory")


def test_monitoring_factory_failure_does_not_construct_tof_owner(
    tmp_path: Path,
) -> None:
    import src.main as main

    tof_factory_called = False

    def fail_monitoring(_context: object) -> object:
        raise RuntimeError("monitoring construction failed")

    def tof_factory(**_kwargs: object) -> None:
        nonlocal tof_factory_called
        tof_factory_called = True
        return None

    application = main.create_app(
        settings=_settings(tmp_path),
        monitoring_pipeline_factory=fail_monitoring,
        tof_warning_runtime_factory=tof_factory,
    )

    with pytest.raises(RuntimeError, match="monitoring construction failed"):
        with TestClient(application):
            pass
    assert tof_factory_called is False


def test_composition_failure_after_tof_construction_cleans_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.main as main

    events: list[str] = []
    owner = _TofOwner(events)
    monkeypatch.setattr(
        main,
        "EntryEventIntake",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("intake construction failed")
        ),
    )
    application = main.create_app(
        settings=_settings(tmp_path),
        tof_warning_runtime_factory=lambda **_kwargs: owner,
    )

    with pytest.raises(RuntimeError, match="intake construction failed"):
        with TestClient(application):
            pass
    assert events == ["tof.stop.1", "tof.stop.2", "tof.close"]


def test_tof_prepare_start_and_shutdown_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.main as main

    events: list[str] = []
    owner = _TofOwner(events)
    _install_runtime_fakes(main, monkeypatch, events)
    application = main.create_app(
        settings=_settings(tmp_path),
        monitoring_pipeline_factory=lambda _context: object(),
        tof_warning_runtime_factory=lambda **_kwargs: owner,
    )

    with TestClient(application):
        assert events.index("tof.prepare") < events.index("monitoring.prepare")
        assert events.index("monitoring.start") < events.index("move.start")
        assert events.index("move.start") < events.index("tof.start")

    assert events[-5:] == [
        "tof.stop.1",
        "monitoring.stop",
        "move.stop",
        "tof.stop.2",
        "tof.close",
    ]


def test_full_publication_and_tof_lifecycle_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.main as main

    events: list[str] = []
    owner = _TofOwner(events)
    _install_runtime_fakes(main, monkeypatch, events)
    monkeypatch.setattr(main, "BackendClient", lambda **_kwargs: object())
    monkeypatch.setattr(main, "OutboxPublisher", lambda **_kwargs: object())
    monkeypatch.setattr(
        main,
        "EvidencePublicationPublisher",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        main,
        "OutboxPublisherWorker",
        lambda _publisher: _PublicationWorker("outbox publication", events),
    )
    monkeypatch.setattr(
        main,
        "EvidencePublicationWorker",
        lambda _publisher: _PublicationWorker(
            "evidence publication",
            events,
        ),
    )
    application = main.create_app(
        settings=_settings(
            tmp_path,
            backend_hw_api_key="configured-hardware-key",
        ),
        monitoring_pipeline_factory=lambda _context: object(),
        tof_warning_runtime_factory=lambda **_kwargs: owner,
    )

    with TestClient(application):
        assert events == [
            "evidence publication.prepare",
            "tof.prepare",
            "monitoring.prepare",
            "outbox publication.start",
            "evidence publication.start",
            "monitoring.start",
            "move.start",
            "tof.start",
        ]

    assert events[8:] == [
        "tof.stop.1",
        "monitoring.stop",
        "move.stop",
        "outbox publication.stop",
        "evidence publication.stop",
        "tof.stop.2",
        "tof.close",
    ]


def test_observer_policy_and_intakes_share_runtime_requester(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.main as main

    events: list[str] = []
    owner = _TofOwner(events)
    captured: dict[str, object] = {}
    _install_runtime_fakes(main, monkeypatch, events)

    def build_observer(*, requester: object, policy: object) -> _TofObserver:
        observer = _TofObserver(
            [],
            requester=requester,
            policy=policy,
        )
        captured["observer"] = observer
        return observer

    monkeypatch.setattr(main, "TofMonitoringContextObserver", build_observer)
    application = main.create_app(
        settings=_settings(tmp_path),
        monitoring_pipeline_factory=lambda _context: object(),
        tof_warning_runtime_factory=lambda **_kwargs: owner,
    )

    with TestClient(application):
        observer = captured["observer"]
        assert isinstance(observer, _TofObserver)
        assert observer.requester is owner.runtime
        assert observer.policy.target_zone_ids == (ZoneId(7), ZoneId(8))
        assert observer.policy.monitoring_freshness_seconds == 5.0
        assert (
            application.state.entry_review_resolution_intake._after_applied
            == owner.runtime.request_after_monitoring_context_change
        )
        assert (
            application.state.session_context_update_intake._after_applied
            == owner.runtime.request_after_monitoring_context_change
        )


def test_live_stream_disabled_connects_only_tof_observer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.main as main

    events: list[str] = []
    owner = _TofOwner(events)
    captured = _install_runtime_fakes(main, monkeypatch, events)
    application = main.create_app(
        settings=_settings(tmp_path, live_stream_enabled=False),
        monitoring_pipeline_factory=lambda _context: object(),
        tof_warning_runtime_factory=lambda **_kwargs: owner,
    )

    with TestClient(application):
        worker = captured["monitoring_worker"]
        assert isinstance(worker, _MonitoringWorker)
        assert (
            worker.frame_observer
            is application.state.tof_monitoring_context_observer
        )
        assert application.state.overlay_publisher is None


def test_live_stream_composes_overlay_before_tof_observer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.main as main

    events: list[str] = []
    observer_calls: list[str] = []
    owner = _TofOwner(events)
    captured = _install_runtime_fakes(main, monkeypatch, events)
    monkeypatch.setattr(
        main,
        "OverlayPublisher",
        lambda **kwargs: _Overlay(observer_calls, **kwargs),
    )
    monkeypatch.setattr(
        main,
        "TofMonitoringContextObserver",
        lambda **kwargs: _TofObserver(observer_calls, **kwargs),
    )
    application = main.create_app(
        settings=_settings(tmp_path, live_stream_enabled=True),
        monitoring_pipeline_factory=lambda _context: object(),
        tof_warning_runtime_factory=lambda **_kwargs: owner,
    )

    with TestClient(application):
        worker = captured["monitoring_worker"]
        assert isinstance(worker, _MonitoringWorker)
        assert callable(worker.frame_observer)
        worker.frame_observer(None, None, None)
        assert observer_calls == ["overlay", "tof"]


@pytest.mark.parametrize("failure_stage", ["construction", "composition"])
def test_observer_failure_preserves_overlay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    import src.main as main

    events: list[str] = []
    overlay_calls: list[str] = []
    owner = _TofOwner(events)
    captured = _install_runtime_fakes(main, monkeypatch, events)
    monkeypatch.setattr(
        main,
        "OverlayPublisher",
        lambda **kwargs: _Overlay(overlay_calls, **kwargs),
    )
    if failure_stage == "construction":
        monkeypatch.setattr(
            main,
            "TofMonitoringContextObserver",
            lambda **_kwargs: (_ for _ in ()).throw(
                RuntimeError("observer failed")
            ),
        )
    else:
        monkeypatch.setattr(
            main,
            "compose_frame_observers",
            lambda *_args: (_ for _ in ()).throw(
                RuntimeError("composition failed")
            ),
        )

    application = main.create_app(
        settings=_settings(tmp_path, live_stream_enabled=True),
        monitoring_pipeline_factory=lambda _context: object(),
        tof_warning_runtime_factory=lambda **_kwargs: owner,
    )
    with TestClient(application):
        worker = captured["monitoring_worker"]
        assert isinstance(worker, _MonitoringWorker)
        assert worker.frame_observer is application.state.overlay_publisher
        assert application.state.tof_monitoring_context_observer is None


def test_prepare_failure_skips_tof_start_but_monitoring_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.main as main

    events: list[str] = []
    owner = _TofOwner(events, prepare_error=RuntimeError("prepare failed"))
    _install_runtime_fakes(main, monkeypatch, events)
    application = main.create_app(
        settings=_settings(tmp_path),
        monitoring_pipeline_factory=lambda _context: object(),
        tof_warning_runtime_factory=lambda **_kwargs: owner,
    )

    with TestClient(application):
        assert "monitoring.start" in events
        assert "tof.start" not in events


def test_start_failure_isolated_from_monitoring(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.main as main

    events: list[str] = []
    owner = _TofOwner(events, start_error=RuntimeError("start failed"))
    _install_runtime_fakes(main, monkeypatch, events)
    application = main.create_app(
        settings=_settings(tmp_path),
        monitoring_pipeline_factory=lambda _context: object(),
        tof_warning_runtime_factory=lambda **_kwargs: owner,
    )

    with TestClient(application):
        assert events.index("monitoring.start") < events.index("tof.start")


def test_tof_runtime_runs_without_monitoring_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.main as main

    events: list[str] = []
    owner = _TofOwner(events)
    _install_runtime_fakes(main, monkeypatch, events)
    application = main.create_app(
        settings=_settings(tmp_path),
        tof_warning_runtime_factory=lambda **_kwargs: owner,
    )

    with TestClient(application):
        assert "tof.prepare" in events
        assert "tof.start" in events
        assert "monitoring.start" not in events
        assert application.state.tof_monitoring_context_observer is None


def test_enabled_without_factory_never_constructs_hardware(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import src.main as main

    events: list[str] = []
    _install_runtime_fakes(main, monkeypatch, events)
    caplog.set_level("WARNING", logger=main.__name__)
    application = main.create_app(settings=_settings(tmp_path))

    with TestClient(application):
        assert application.state.tof_warning_runtime is None
        assert application.state.tof_monitoring_context_observer is None
    assert "production factory가 없어" in caplog.text


def test_tof_cleanup_error_propagates_after_lock_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.main as main

    events: list[str] = []
    close_error = RuntimeError("tof close failed")
    owner = _TofOwner(events, close_error=close_error)
    _install_runtime_fakes(main, monkeypatch, events)
    application = main.create_app(
        settings=_settings(tmp_path),
        tof_warning_runtime_factory=lambda **_kwargs: owner,
    )

    with pytest.raises(RuntimeError, match="tof close failed"):
        with TestClient(application):
            pass
    assert application.state.publication_runtime_lock.is_acquired is False
    assert events[-4:] == ["tof.stop.1", "move.stop", "tof.stop.2", "tof.close"]


def test_initial_tof_stop_error_does_not_block_cleanup_and_is_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.main as main

    events: list[str] = []
    owner = _TofOwner(
        events,
        stop_errors=[RuntimeError("first stop failed"), None],
    )
    _install_runtime_fakes(main, monkeypatch, events)
    application = main.create_app(
        settings=_settings(tmp_path),
        monitoring_pipeline_factory=lambda _context: object(),
        tof_warning_runtime_factory=lambda **_kwargs: owner,
    )

    with pytest.raises(RuntimeError, match="first stop failed"):
        with TestClient(application):
            pass

    assert events[-5:] == [
        "tof.stop.1",
        "monitoring.stop",
        "move.stop",
        "tof.stop.2",
        "tof.close",
    ]


def test_monitoring_cleanup_error_has_priority_over_tof_cleanup_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.main as main

    events: list[str] = []
    owner = _TofOwner(events, close_error=RuntimeError("tof close failed"))
    _install_runtime_fakes(
        main,
        monkeypatch,
        events,
        monitoring_stop_error=RuntimeError("monitoring stop failed"),
    )
    application = main.create_app(
        settings=_settings(tmp_path),
        monitoring_pipeline_factory=lambda _context: object(),
        tof_warning_runtime_factory=lambda **_kwargs: owner,
    )

    with pytest.raises(RuntimeError, match="monitoring stop failed"):
        with TestClient(application):
            pass
    assert "tof.close" in events


def test_startup_error_is_not_hidden_by_tof_cleanup_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.main as main

    events: list[str] = []
    owner = _TofOwner(events, close_error=RuntimeError("tof close failed"))
    _install_runtime_fakes(
        main,
        monkeypatch,
        events,
        move_start_error=RuntimeError("move start failed"),
    )
    application = main.create_app(
        settings=_settings(tmp_path),
        monitoring_pipeline_factory=lambda _context: object(),
        tof_warning_runtime_factory=lambda **_kwargs: owner,
    )

    with pytest.raises(RuntimeError, match="move start failed"):
        with TestClient(application):
            pass
    assert "tof.close" in events


def test_monitoring_startup_failure_remains_fail_fast_and_cleans_tof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.main as main

    events: list[str] = []
    owner = _TofOwner(events)
    _install_runtime_fakes(
        main,
        monkeypatch,
        events,
        monitoring_start_error=RuntimeError("monitoring start failed"),
    )
    application = main.create_app(
        settings=_settings(tmp_path),
        monitoring_pipeline_factory=lambda _context: object(),
        tof_warning_runtime_factory=lambda **_kwargs: owner,
    )

    with pytest.raises(RuntimeError, match="monitoring start failed"):
        with TestClient(application):
            pass
    assert "tof.start" not in events
    assert events[-2:] == ["tof.stop.2", "tof.close"]
