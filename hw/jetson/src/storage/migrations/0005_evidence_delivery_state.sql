-- API 8·9 evidence publication의 재시도와 terminal 실패를 domain state와 분리한다.
ALTER TABLE evidence_artifacts
ADD COLUMN delivery_state TEXT CHECK (
    delivery_state IS NULL OR delivery_state IN (
        'PENDING', 'IN_FLIGHT', 'RETRY_WAIT', 'DELIVERED', 'FAILED_TERMINAL'
    )
);

ALTER TABLE evidence_artifacts
ADD COLUMN delivery_attempt_count INTEGER NOT NULL DEFAULT 0
CHECK (delivery_attempt_count >= 0);

ALTER TABLE evidence_artifacts
ADD COLUMN next_delivery_attempt_at_us INTEGER;

ALTER TABLE evidence_artifacts
ADD COLUMN last_delivery_error TEXT;

CREATE INDEX ix_evidence_delivery_queue
ON evidence_artifacts(
    delivery_state,
    next_delivery_attempt_at_us,
    updated_at_us,
    evidence_id
);
