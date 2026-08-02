-- Jetson durable-state schema. Raw frame, bbox, 반복 inference signal과
-- TrackSegment record는 의도적으로 저장하지 않는다.

CREATE TABLE deployment_metadata (
    metadata_key TEXT PRIMARY KEY,
    metadata_value BLOB NOT NULL,
    updated_at_us INTEGER NOT NULL,
    record_version INTEGER NOT NULL DEFAULT 1 CHECK (record_version >= 1)
);

CREATE TABLE physical_vehicles (
    physical_vehicle_id TEXT PRIMARY KEY,
    domain_state TEXT NOT NULL CHECK (
        domain_state IN ('CANDIDATE', 'ACTIVE', 'RETIRED', 'CANCELED')
    ),
    observation_state TEXT NOT NULL CHECK (
        observation_state IN ('OBSERVED', 'DEGRADED', 'UNKNOWN')
    ),
    observation_reason TEXT,
    last_reliable_observed_at_us INTEGER,
    absence_trusted_duration_us INTEGER NOT NULL DEFAULT 0 CHECK (
        absence_trusted_duration_us >= 0
    ),
    absence_confirmation_duration_us INTEGER NOT NULL CHECK (
        absence_confirmation_duration_us >= 0
    ),
    motion_anchor_payload BLOB,
    termination_reason TEXT,
    terminated_at_us INTEGER,
    record_version INTEGER NOT NULL DEFAULT 1 CHECK (record_version >= 1),
    created_at_us INTEGER NOT NULL,
    updated_at_us INTEGER NOT NULL,
    CHECK (
        (observation_state = 'OBSERVED'
            AND observation_reason IS NULL
            AND last_reliable_observed_at_us IS NOT NULL)
        OR observation_state <> 'OBSERVED'
    ),
    CHECK (
        (domain_state IN ('RETIRED', 'CANCELED')
            AND termination_reason IS NOT NULL
            AND terminated_at_us IS NOT NULL)
        OR (domain_state NOT IN ('RETIRED', 'CANCELED')
            AND termination_reason IS NULL
            AND terminated_at_us IS NULL)
    )
);

CREATE TABLE entry_match_attempts (
    entry_attempt_id TEXT PRIMARY KEY,
    match_state TEXT NOT NULL CHECK (
        match_state IN ('PENDING', 'MATCHED', 'EXPIRED', 'FAILED', 'CANCELED')
    ),
    decision_state TEXT NOT NULL CHECK (
        decision_state IN (
            'ALLOW', 'DENY', 'REVIEW_PENDING', 'REVIEW_ALLOW',
            'REVIEW_DENY', 'REVIEW_EXPIRED'
        )
    ),
    decision_revision INTEGER NOT NULL CHECK (decision_revision >= 0),
    session_id INTEGER,
    physical_vehicle_id TEXT,
    authoritative_context_payload BLOB,
    match_deadline_at_us INTEGER,
    termination_reason TEXT,
    match_terminated_at_us INTEGER,
    record_version INTEGER NOT NULL DEFAULT 1 CHECK (record_version >= 1),
    created_at_us INTEGER NOT NULL,
    updated_at_us INTEGER NOT NULL,
    CHECK (
        (match_state = 'MATCHED' AND physical_vehicle_id IS NOT NULL)
        OR (match_state <> 'MATCHED' AND physical_vehicle_id IS NULL)
    ),
    CHECK (
        (match_state = 'PENDING' AND match_terminated_at_us IS NULL)
        OR (match_state <> 'PENDING' AND match_terminated_at_us IS NOT NULL)
    ),
    CHECK (
        (match_state IN ('EXPIRED', 'FAILED', 'CANCELED')
            AND termination_reason IS NOT NULL)
        OR (match_state NOT IN ('EXPIRED', 'FAILED', 'CANCELED')
            AND termination_reason IS NULL)
    ),
    CHECK (
        (decision_state IN ('ALLOW', 'REVIEW_ALLOW')
            AND session_id IS NOT NULL
            AND authoritative_context_payload IS NOT NULL)
        OR (decision_state NOT IN ('ALLOW', 'REVIEW_ALLOW')
            AND session_id IS NULL
            AND authoritative_context_payload IS NULL)
    ),
    FOREIGN KEY (physical_vehicle_id) REFERENCES physical_vehicles(physical_vehicle_id)
);

CREATE UNIQUE INDEX uq_entry_match_attempt_session
ON entry_match_attempts(session_id)
WHERE session_id IS NOT NULL;

CREATE TABLE parking_session_mirrors (
    session_id INTEGER PRIMARY KEY,
    entry_attempt_id TEXT UNIQUE,
    physical_vehicle_id TEXT,
    administrative_state TEXT NOT NULL CHECK (
        administrative_state IN ('ACTIVE', 'CLOSED')
    ),
    physical_presence_state TEXT NOT NULL CHECK (
        physical_presence_state IN ('UNCONFIRMED', 'INSIDE', 'EXITED')
    ),
    physical_observation_state TEXT NOT NULL CHECK (
        physical_observation_state IN ('OBSERVED', 'DEGRADED', 'UNKNOWN')
    ),
    physical_observation_reason TEXT,
    last_reliable_observed_at_us INTEGER,
    physical_termination_origin TEXT CHECK (
        physical_termination_origin IS NULL
        OR physical_termination_origin = 'JETSON_EXIT_CONFIRMED'
    ),
    physical_exit_evidence TEXT CHECK (
        physical_exit_evidence IS NULL
        OR physical_exit_evidence IN ('ENTRY_EXIT_TRAVERSAL', 'FULL_AREA_ABSENCE')
    ),
    exit_correlation_enabled INTEGER NOT NULL DEFAULT 1 CHECK (
        exit_correlation_enabled IN (0, 1)
    ),
    context_revision INTEGER NOT NULL DEFAULT 0 CHECK (context_revision >= 0),
    last_context_payload BLOB,
    exited_at_us INTEGER,
    termination_reason TEXT,
    terminated_at_us INTEGER,
    record_version INTEGER NOT NULL DEFAULT 1 CHECK (record_version >= 1),
    publication_revision INTEGER NOT NULL DEFAULT 0 CHECK (publication_revision >= 0),
    created_at_us INTEGER NOT NULL,
    updated_at_us INTEGER NOT NULL,
    CHECK (
        (physical_presence_state = 'EXITED'
            AND physical_vehicle_id IS NOT NULL
            AND physical_termination_origin IS NOT NULL
            AND physical_exit_evidence IS NOT NULL
            AND exited_at_us IS NOT NULL)
        OR (physical_presence_state <> 'EXITED'
            AND physical_termination_origin IS NULL
            AND physical_exit_evidence IS NULL
            AND exited_at_us IS NULL)
    ),
    CHECK (
        physical_presence_state = 'UNCONFIRMED'
        OR physical_vehicle_id IS NOT NULL
    ),
    CHECK (
        (physical_observation_state = 'OBSERVED'
            AND physical_observation_reason IS NULL
            AND last_reliable_observed_at_us IS NOT NULL)
        OR physical_observation_state <> 'OBSERVED'
    ),
    CHECK ((termination_reason IS NULL) = (terminated_at_us IS NULL)),
    FOREIGN KEY (entry_attempt_id) REFERENCES entry_match_attempts(entry_attempt_id),
    FOREIGN KEY (physical_vehicle_id) REFERENCES physical_vehicles(physical_vehicle_id)
);

CREATE UNIQUE INDEX uq_exit_enabled_mirror_per_physical_vehicle
ON parking_session_mirrors(physical_vehicle_id)
WHERE physical_vehicle_id IS NOT NULL
  AND exit_correlation_enabled = 1
  AND physical_presence_state <> 'EXITED';

CREATE TABLE context_bindings (
    context_binding_id TEXT PRIMARY KEY,
    entry_attempt_id TEXT NOT NULL UNIQUE,
    session_id INTEGER NOT NULL,
    physical_vehicle_id TEXT NOT NULL,
    domain_state TEXT NOT NULL CHECK (domain_state IN ('BOUND', 'ENDED')),
    context_revision INTEGER NOT NULL CHECK (context_revision >= 0),
    context_payload BLOB NOT NULL,
    termination_reason TEXT,
    ended_at_us INTEGER,
    record_version INTEGER NOT NULL DEFAULT 1 CHECK (record_version >= 1),
    bound_at_us INTEGER NOT NULL,
    updated_at_us INTEGER NOT NULL,
    CHECK (
        (domain_state = 'ENDED'
            AND termination_reason IS NOT NULL
            AND ended_at_us IS NOT NULL)
        OR (domain_state = 'BOUND'
            AND termination_reason IS NULL
            AND ended_at_us IS NULL)
    ),
    FOREIGN KEY (entry_attempt_id) REFERENCES entry_match_attempts(entry_attempt_id),
    FOREIGN KEY (session_id) REFERENCES parking_session_mirrors(session_id),
    FOREIGN KEY (physical_vehicle_id) REFERENCES physical_vehicles(physical_vehicle_id)
);

CREATE UNIQUE INDEX uq_active_context_binding_session
ON context_bindings(session_id)
WHERE domain_state = 'BOUND';

CREATE UNIQUE INDEX uq_active_context_binding_physical_vehicle
ON context_bindings(physical_vehicle_id)
WHERE domain_state = 'BOUND';

CREATE TABLE zone_visits (
    zone_visit_id TEXT PRIMARY KEY,
    physical_vehicle_id TEXT NOT NULL,
    zone_id INTEGER NOT NULL,
    zone_definition_version INTEGER NOT NULL CHECK (zone_definition_version >= 1),
    domain_state TEXT NOT NULL CHECK (
        domain_state IN ('ENTERING', 'INSIDE', 'EXITING', 'ENDED', 'CANCELED')
    ),
    observation_state TEXT NOT NULL CHECK (
        observation_state IN ('OBSERVED', 'DEGRADED', 'UNKNOWN')
    ),
    observation_reason TEXT,
    last_reliable_observed_at_us INTEGER,
    entry_trusted_duration_us INTEGER NOT NULL DEFAULT 0 CHECK (
        entry_trusted_duration_us >= 0
    ),
    exit_trusted_duration_us INTEGER NOT NULL DEFAULT 0 CHECK (
        exit_trusted_duration_us >= 0
    ),
    entry_confirmation_duration_us INTEGER NOT NULL CHECK (
        entry_confirmation_duration_us >= 0
    ),
    exit_confirmation_duration_us INTEGER NOT NULL CHECK (
        exit_confirmation_duration_us >= 0
    ),
    entered_candidate_at_us INTEGER,
    entered_at_us INTEGER,
    exit_candidate_at_us INTEGER,
    termination_reason TEXT,
    ended_at_us INTEGER,
    record_version INTEGER NOT NULL DEFAULT 1 CHECK (record_version >= 1),
    created_at_us INTEGER NOT NULL,
    updated_at_us INTEGER NOT NULL,
    CHECK (domain_state <> 'ENTERING' OR entered_candidate_at_us IS NOT NULL),
    CHECK (domain_state <> 'EXITING' OR exit_candidate_at_us IS NOT NULL),
    CHECK (
        (observation_state = 'OBSERVED'
            AND observation_reason IS NULL
            AND last_reliable_observed_at_us IS NOT NULL)
        OR observation_state <> 'OBSERVED'
    ),
    CHECK (
        domain_state NOT IN ('INSIDE', 'EXITING', 'ENDED')
        OR entered_at_us IS NOT NULL
    ),
    CHECK (
        (domain_state IN ('ENDED', 'CANCELED')
            AND termination_reason IS NOT NULL
            AND ended_at_us IS NOT NULL)
        OR (domain_state NOT IN ('ENDED', 'CANCELED')
            AND termination_reason IS NULL
            AND ended_at_us IS NULL)
    ),
    FOREIGN KEY (physical_vehicle_id) REFERENCES physical_vehicles(physical_vehicle_id)
);

CREATE UNIQUE INDEX uq_nonterminal_zone_visit
ON zone_visits(physical_vehicle_id, zone_id)
WHERE domain_state IN ('ENTERING', 'INSIDE', 'EXITING');

CREATE TABLE parking_episodes (
    parking_episode_id TEXT PRIMARY KEY,
    physical_vehicle_id TEXT NOT NULL,
    domain_state TEXT NOT NULL CHECK (
        domain_state IN ('STOP_PENDING', 'PARKED', 'MOVE_PENDING', 'ENDED', 'CANCELED')
    ),
    observation_state TEXT NOT NULL CHECK (
        observation_state IN ('OBSERVED', 'DEGRADED', 'UNKNOWN')
    ),
    observation_reason TEXT,
    last_reliable_observed_at_us INTEGER,
    stationary_trusted_duration_us INTEGER NOT NULL DEFAULT 0 CHECK (
        stationary_trusted_duration_us >= 0
    ),
    movement_trusted_duration_us INTEGER NOT NULL DEFAULT 0 CHECK (
        movement_trusted_duration_us >= 0
    ),
    parking_confirmation_duration_us INTEGER NOT NULL CHECK (
        parking_confirmation_duration_us > 0
    ),
    movement_confirmation_duration_us INTEGER NOT NULL CHECK (
        movement_confirmation_duration_us >= 0
    ),
    last_motion_signal TEXT NOT NULL CHECK (
        last_motion_signal IN ('MOVING', 'STATIONARY', 'UNKNOWN')
    ),
    session_id INTEGER,
    assignment_state TEXT CHECK (
        assignment_state IS NULL
        OR assignment_state IN ('ASSIGNED', 'AMBIGUOUS', 'UNASSIGNED')
    ),
    assignment_zone_id INTEGER,
    assignment_unassigned_reason TEXT,
    representative_footprint BLOB,
    assignment_confidence REAL CHECK (
        assignment_confidence IS NULL
        OR (assignment_confidence >= 0.0 AND assignment_confidence <= 1.0)
    ),
    assignment_last_stable_at_us INTEGER,
    parked_at_us INTEGER,
    movement_candidate_at_us INTEGER,
    termination_reason TEXT,
    ended_at_us INTEGER,
    record_version INTEGER NOT NULL DEFAULT 1 CHECK (record_version >= 1),
    publication_revision INTEGER NOT NULL DEFAULT 0 CHECK (publication_revision >= 0),
    created_at_us INTEGER NOT NULL,
    updated_at_us INTEGER NOT NULL,
    CHECK (domain_state <> 'MOVE_PENDING' OR movement_candidate_at_us IS NOT NULL),
    CHECK (
        (observation_state = 'OBSERVED'
            AND observation_reason IS NULL
            AND last_reliable_observed_at_us IS NOT NULL)
        OR observation_state <> 'OBSERVED'
    ),
    CHECK (
        domain_state NOT IN ('PARKED', 'MOVE_PENDING', 'ENDED')
        OR (parked_at_us IS NOT NULL AND assignment_state IS NOT NULL)
    ),
    CHECK (
        (assignment_state IS NULL
            AND assignment_zone_id IS NULL
            AND assignment_unassigned_reason IS NULL
            AND representative_footprint IS NULL
            AND assignment_confidence IS NULL
            AND assignment_last_stable_at_us IS NULL)
        OR (assignment_state = 'ASSIGNED'
            AND assignment_zone_id IS NOT NULL
            AND assignment_unassigned_reason IS NULL
            AND representative_footprint IS NOT NULL
            AND assignment_confidence IS NOT NULL
            AND assignment_last_stable_at_us IS NOT NULL)
        OR (assignment_state IN ('AMBIGUOUS', 'UNASSIGNED')
            AND assignment_zone_id IS NULL
            AND assignment_unassigned_reason IS NOT NULL
            AND representative_footprint IS NOT NULL
            AND assignment_confidence IS NOT NULL
            AND assignment_last_stable_at_us IS NOT NULL)
    ),
    CHECK (
        (domain_state IN ('ENDED', 'CANCELED')
            AND termination_reason IS NOT NULL
            AND ended_at_us IS NOT NULL)
        OR (domain_state NOT IN ('ENDED', 'CANCELED')
            AND termination_reason IS NULL
            AND ended_at_us IS NULL)
    ),
    FOREIGN KEY (physical_vehicle_id) REFERENCES physical_vehicles(physical_vehicle_id)
);

CREATE UNIQUE INDEX uq_nonterminal_parking_episode
ON parking_episodes(physical_vehicle_id)
WHERE domain_state IN ('STOP_PENDING', 'PARKED', 'MOVE_PENDING');

CREATE TABLE blocking_relations (
    blocking_relation_id TEXT PRIMARY KEY,
    subject_physical_vehicle_id TEXT NOT NULL,
    victim_physical_vehicle_id TEXT NOT NULL,
    egress_zone_id INTEGER NOT NULL,
    source_parking_episode_id TEXT,
    domain_state TEXT NOT NULL CHECK (
        domain_state IN (
            'CANDIDATE', 'BLOCKING', 'CLEAR_PENDING', 'RESOLVED', 'CANCELED'
        )
    ),
    observation_state TEXT NOT NULL CHECK (
        observation_state IN ('OBSERVED', 'DEGRADED', 'UNKNOWN')
    ),
    observation_reason TEXT,
    last_reliable_observed_at_us INTEGER,
    confirm_trusted_duration_us INTEGER NOT NULL DEFAULT 0 CHECK (
        confirm_trusted_duration_us >= 0
    ),
    clear_trusted_duration_us INTEGER NOT NULL DEFAULT 0 CHECK (
        clear_trusted_duration_us >= 0
    ),
    confirm_duration_us INTEGER NOT NULL CHECK (confirm_duration_us >= 0),
    clear_duration_us INTEGER NOT NULL CHECK (clear_duration_us >= 0),
    confirmed_at_us INTEGER,
    resolved_at_us INTEGER,
    termination_reason TEXT,
    terminated_at_us INTEGER,
    record_version INTEGER NOT NULL DEFAULT 1 CHECK (record_version >= 1),
    created_at_us INTEGER NOT NULL,
    updated_at_us INTEGER NOT NULL,
    CHECK (subject_physical_vehicle_id <> victim_physical_vehicle_id),
    CHECK (
        (observation_state = 'OBSERVED'
            AND observation_reason IS NULL
            AND last_reliable_observed_at_us IS NOT NULL)
        OR observation_state <> 'OBSERVED'
    ),
    CHECK (
        (domain_state IN ('BLOCKING', 'CLEAR_PENDING', 'RESOLVED')
            AND confirmed_at_us IS NOT NULL)
        OR (domain_state IN ('CANDIDATE', 'CANCELED')
            AND confirmed_at_us IS NULL)
    ),
    CHECK (
        (domain_state = 'RESOLVED' AND resolved_at_us IS NOT NULL)
        OR (domain_state <> 'RESOLVED' AND resolved_at_us IS NULL)
    ),
    CHECK (
        (domain_state IN ('RESOLVED', 'CANCELED')
            AND termination_reason IS NOT NULL
            AND terminated_at_us IS NOT NULL)
        OR (domain_state NOT IN ('RESOLVED', 'CANCELED')
            AND termination_reason IS NULL
            AND terminated_at_us IS NULL)
    ),
    FOREIGN KEY (subject_physical_vehicle_id)
        REFERENCES physical_vehicles(physical_vehicle_id),
    FOREIGN KEY (victim_physical_vehicle_id)
        REFERENCES physical_vehicles(physical_vehicle_id),
    FOREIGN KEY (source_parking_episode_id)
        REFERENCES parking_episodes(parking_episode_id)
);

CREATE UNIQUE INDEX uq_nonterminal_blocking_relation
ON blocking_relations(
    subject_physical_vehicle_id, victim_physical_vehicle_id, egress_zone_id
)
WHERE domain_state IN ('CANDIDATE', 'BLOCKING', 'CLEAR_PENDING');

CREATE TABLE incidents (
    incident_id TEXT PRIMARY KEY,
    rule_code TEXT NOT NULL,
    key_scope_type TEXT NOT NULL CHECK (
        key_scope_type IN ('ZONE_VISIT', 'PHYSICAL_VEHICLE', 'BLOCKING_RELATION')
    ),
    key_scope_id TEXT NOT NULL,
    subject_physical_vehicle_id TEXT NOT NULL,
    entry_attempt_id TEXT,
    session_id INTEGER,
    zone_id INTEGER,
    victim_physical_vehicle_id TEXT,
    domain_state TEXT NOT NULL CHECK (
        domain_state IN ('CANDIDATE', 'OPEN', 'CLEAR_PENDING', 'RESOLVED', 'CANCELED')
    ),
    observation_state TEXT NOT NULL CHECK (
        observation_state IN ('OBSERVED', 'DEGRADED', 'UNKNOWN')
    ),
    observation_reason TEXT,
    last_reliable_observed_at_us INTEGER,
    confirm_trusted_duration_us INTEGER NOT NULL DEFAULT 0 CHECK (
        confirm_trusted_duration_us >= 0
    ),
    clear_trusted_duration_us INTEGER NOT NULL DEFAULT 0 CHECK (
        clear_trusted_duration_us >= 0
    ),
    confirm_duration_us INTEGER NOT NULL CHECK (confirm_duration_us >= 0),
    clear_duration_us INTEGER NOT NULL CHECK (clear_duration_us >= 0),
    first_observed_at_us INTEGER NOT NULL,
    confirmed_at_us INTEGER,
    resolved_at_us INTEGER,
    termination_reason TEXT,
    terminated_at_us INTEGER,
    record_version INTEGER NOT NULL DEFAULT 1 CHECK (record_version >= 1),
    publication_revision INTEGER NOT NULL DEFAULT 0 CHECK (publication_revision >= 0),
    created_at_us INTEGER NOT NULL,
    updated_at_us INTEGER NOT NULL,
    CHECK (
        (observation_state = 'OBSERVED'
            AND observation_reason IS NULL
            AND last_reliable_observed_at_us IS NOT NULL)
        OR observation_state <> 'OBSERVED'
    ),
    CHECK (
        (domain_state IN ('OPEN', 'CLEAR_PENDING', 'RESOLVED')
            AND confirmed_at_us IS NOT NULL)
        OR (domain_state IN ('CANDIDATE', 'CANCELED')
            AND confirmed_at_us IS NULL)
    ),
    CHECK (
        (domain_state = 'RESOLVED' AND resolved_at_us IS NOT NULL)
        OR (domain_state <> 'RESOLVED' AND resolved_at_us IS NULL)
    ),
    CHECK (
        (domain_state IN ('RESOLVED', 'CANCELED')
            AND termination_reason IS NOT NULL
            AND terminated_at_us IS NOT NULL)
        OR (domain_state NOT IN ('RESOLVED', 'CANCELED')
            AND termination_reason IS NULL
            AND terminated_at_us IS NULL)
    ),
    CHECK (
        (domain_state IN ('CANDIDATE', 'CANCELED') AND publication_revision = 0)
        OR domain_state NOT IN ('CANDIDATE', 'CANCELED')
    ),
    CHECK (
        publication_revision = 0
        OR entry_attempt_id IS NOT NULL
        OR session_id IS NOT NULL
    ),
    FOREIGN KEY (subject_physical_vehicle_id)
        REFERENCES physical_vehicles(physical_vehicle_id),
    FOREIGN KEY (victim_physical_vehicle_id)
        REFERENCES physical_vehicles(physical_vehicle_id)
);

CREATE UNIQUE INDEX uq_nonterminal_incident_key
ON incidents(rule_code, key_scope_type, key_scope_id)
WHERE domain_state IN ('CANDIDATE', 'OPEN', 'CLEAR_PENDING');

CREATE TABLE move_verification_attempts (
    request_id INTEGER NOT NULL,
    verification_attempt INTEGER NOT NULL CHECK (verification_attempt >= 1),
    subject_physical_vehicle_id TEXT NOT NULL,
    target_incident_ids_payload BLOB NOT NULL,
    command_payload_hash TEXT NOT NULL,
    domain_state TEXT NOT NULL CHECK (
        domain_state IN ('ACCEPTED', 'CHECKING', 'COMPLETED', 'CANCELED', 'FAILED')
    ),
    result TEXT CHECK (
        result IS NULL OR result IN ('RESOLVED', 'STILL_ACTIVE', 'UNKNOWN')
    ),
    per_incident_results_payload BLOB,
    deadline_at_us INTEGER,
    termination_reason TEXT,
    record_version INTEGER NOT NULL DEFAULT 1 CHECK (record_version >= 1),
    publication_revision INTEGER NOT NULL DEFAULT 0 CHECK (publication_revision >= 0),
    accepted_at_us INTEGER NOT NULL,
    updated_at_us INTEGER NOT NULL,
    completed_at_us INTEGER,
    CHECK (
        (domain_state IN ('COMPLETED', 'CANCELED', 'FAILED')
            AND completed_at_us IS NOT NULL)
        OR (domain_state IN ('ACCEPTED', 'CHECKING')
            AND completed_at_us IS NULL)
    ),
    CHECK (
        (domain_state = 'COMPLETED'
            AND result IS NOT NULL
            AND per_incident_results_payload IS NOT NULL
            AND publication_revision >= 1)
        OR (domain_state <> 'COMPLETED'
            AND result IS NULL
            AND per_incident_results_payload IS NULL
            AND publication_revision = 0)
    ),
    CHECK (
        (domain_state IN ('CANCELED', 'FAILED') AND termination_reason IS NOT NULL)
        OR (domain_state NOT IN ('CANCELED', 'FAILED') AND termination_reason IS NULL)
    ),
    PRIMARY KEY (request_id, verification_attempt),
    FOREIGN KEY (subject_physical_vehicle_id)
        REFERENCES physical_vehicles(physical_vehicle_id)
);

CREATE TABLE accepted_inputs (
    input_type TEXT NOT NULL,
    input_identity TEXT NOT NULL,
    input_revision INTEGER NOT NULL CHECK (input_revision >= 0),
    payload_hash TEXT NOT NULL,
    request_payload BLOB NOT NULL,
    workflow_state TEXT NOT NULL,
    result_payload BLOB,
    accepted_at_us INTEGER NOT NULL,
    updated_at_us INTEGER NOT NULL,
    record_version INTEGER NOT NULL DEFAULT 1 CHECK (record_version >= 1),
    PRIMARY KEY (input_type, input_identity, input_revision)
);

CREATE TRIGGER accepted_input_immutable_identity
BEFORE UPDATE OF
    input_type, input_identity, input_revision, payload_hash,
    request_payload, accepted_at_us
ON accepted_inputs
FOR EACH ROW
WHEN
    NEW.input_type <> OLD.input_type
    OR NEW.input_identity <> OLD.input_identity
    OR NEW.input_revision <> OLD.input_revision
    OR NEW.payload_hash <> OLD.payload_hash
    OR NEW.request_payload <> OLD.request_payload
    OR NEW.accepted_at_us <> OLD.accepted_at_us
BEGIN
    SELECT RAISE(ABORT, 'accepted input identity and payload are immutable');
END;

CREATE TABLE pending_handoffs (
    handoff_id TEXT PRIMARY KEY,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    transition_type TEXT NOT NULL,
    original_occurred_at_us INTEGER NOT NULL,
    workflow_state TEXT NOT NULL CHECK (
        workflow_state IN ('WAITING_CORRELATION', 'MATERIALIZED', 'EXPIRED')
    ),
    disposition_reason TEXT,
    materialized_delivery_id TEXT,
    expires_at_us INTEGER NOT NULL,
    record_version INTEGER NOT NULL DEFAULT 1 CHECK (record_version >= 1),
    created_at_us INTEGER NOT NULL,
    updated_at_us INTEGER NOT NULL,
    UNIQUE (aggregate_type, aggregate_id, transition_type, original_occurred_at_us)
);

CREATE TABLE outbox (
    delivery_id TEXT PRIMARY KEY,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    destination TEXT NOT NULL,
    publication_revision INTEGER NOT NULL CHECK (publication_revision >= 1),
    transition_type TEXT NOT NULL,
    payload BLOB NOT NULL,
    payload_hash TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    delivery_state TEXT NOT NULL CHECK (
        delivery_state IN (
            'PENDING', 'IN_FLIGHT', 'RETRY_WAIT', 'DELIVERED', 'FAILED_TERMINAL'
        )
    ),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    next_attempt_at_us INTEGER,
    last_error TEXT,
    created_at_us INTEGER NOT NULL,
    updated_at_us INTEGER NOT NULL,
    confirmed_at_us INTEGER,
    record_version INTEGER NOT NULL DEFAULT 1 CHECK (record_version >= 1),
    UNIQUE (aggregate_type, aggregate_id, destination, publication_revision),
    UNIQUE (destination, idempotency_key)
);

CREATE INDEX ix_outbox_delivery_queue
ON outbox(destination, delivery_state, next_attempt_at_us, created_at_us);

CREATE TRIGGER outbox_immutable_publication
BEFORE UPDATE OF
    delivery_id, aggregate_type, aggregate_id, destination,
    publication_revision, transition_type, payload, payload_hash, idempotency_key
ON outbox
FOR EACH ROW
WHEN
    NEW.delivery_id <> OLD.delivery_id
    OR NEW.aggregate_type <> OLD.aggregate_type
    OR NEW.aggregate_id <> OLD.aggregate_id
    OR NEW.destination <> OLD.destination
    OR NEW.publication_revision <> OLD.publication_revision
    OR NEW.transition_type <> OLD.transition_type
    OR NEW.payload <> OLD.payload
    OR NEW.payload_hash <> OLD.payload_hash
    OR NEW.idempotency_key <> OLD.idempotency_key
BEGIN
    SELECT RAISE(ABORT, 'outbox publication fields are immutable');
END;

CREATE TABLE delivery_receipts (
    delivery_id TEXT PRIMARY KEY,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    destination TEXT NOT NULL,
    publication_revision INTEGER NOT NULL CHECK (publication_revision >= 1),
    payload_hash TEXT NOT NULL,
    application_status TEXT NOT NULL CHECK (
        application_status IN ('APPLIED', 'ALREADY_APPLIED')
    ),
    backend_correlation_payload BLOB,
    confirmed_at_us INTEGER NOT NULL,
    expires_at_us INTEGER NOT NULL,
    UNIQUE (aggregate_type, aggregate_id, destination, publication_revision)
);

CREATE TABLE tombstones (
    scope_type TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    final_state TEXT NOT NULL,
    final_reason TEXT,
    occurred_at_us INTEGER NOT NULL,
    final_publication_revision INTEGER NOT NULL DEFAULT 0 CHECK (
        final_publication_revision >= 0
    ),
    final_payload_hash TEXT,
    backend_correlation_payload BLOB,
    confirmed_at_us INTEGER,
    expires_at_us INTEGER NOT NULL,
    created_at_us INTEGER NOT NULL,
    PRIMARY KEY (scope_type, scope_id)
);

-- Evidence metadata는 축약된 Incident snapshot보다 오래 남을 수 있으므로
-- incidents에 lifecycle foreign key를 두지 않는다.
CREATE TABLE evidence_artifacts (
    evidence_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL,
    publication_revision INTEGER CHECK (publication_revision >= 1),
    captured_at_us INTEGER NOT NULL,
    image_type TEXT NOT NULL,
    local_path TEXT,
    byte_size INTEGER CHECK (byte_size IS NULL OR byte_size >= 0),
    checksum TEXT,
    workflow_state TEXT NOT NULL CHECK (
        workflow_state IN (
            'RESERVED', 'WRITING', 'READY', 'UPLOADING', 'ACKNOWLEDGED', 'FAILED',
            'EVICTION_PENDING', 'EVICTED'
        )
    ),
    last_error TEXT,
    backend_ack_payload BLOB,
    backend_acked_at_us INTEGER,
    retention_disposition TEXT,
    evicted_at_us INTEGER,
    record_version INTEGER NOT NULL DEFAULT 1 CHECK (record_version >= 1),
    created_at_us INTEGER NOT NULL,
    updated_at_us INTEGER NOT NULL
);

CREATE INDEX ix_evidence_incident_revision
ON evidence_artifacts(incident_id, publication_revision);
