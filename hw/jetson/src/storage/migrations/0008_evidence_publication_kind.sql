ALTER TABLE evidence_artifacts
ADD COLUMN publication_kind TEXT CHECK (
    publication_kind IS NULL
    OR publication_kind IN ('UPLOAD', 'UNAVAILABLE', 'AMBIGUOUS')
);

UPDATE evidence_artifacts
SET publication_kind = 'UPLOAD'
WHERE delivery_attempt_count > 0
  AND workflow_state IN (
      'READY', 'UPLOADING', 'ACKNOWLEDGED', 'EVICTION_PENDING'
  );

UPDATE evidence_artifacts
SET publication_kind = 'AMBIGUOUS',
    delivery_state = 'FAILED_TERMINAL',
    next_delivery_attempt_at_us = NULL,
    last_delivery_error = 'LEGACY_PUBLICATION_OUTCOME_UNKNOWN',
    record_version = record_version + 1
WHERE delivery_attempt_count > 0
  AND backend_acked_at_us IS NULL
  AND workflow_state IN ('FAILED', 'EVICTED');

CREATE TRIGGER evidence_publication_kind_immutable
BEFORE UPDATE OF publication_kind
ON evidence_artifacts
FOR EACH ROW
WHEN OLD.publication_kind IS NOT NULL
 AND NEW.publication_kind IS NOT OLD.publication_kind
BEGIN
    SELECT RAISE(ABORT, 'evidence publication kind is immutable after dispatch');
END;
