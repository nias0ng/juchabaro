-- Requeue only legacy evidence that was terminalized by the pre-ACK ordering race.
-- The parent-ACK claim gate keeps each repaired row blocked until Incident OPEN
-- has actually been applied by the Backend.
UPDATE evidence_artifacts
SET delivery_state = 'RETRY_WAIT',
    next_delivery_attempt_at_us = updated_at_us,
    record_version = record_version + 1
WHERE delivery_state = 'FAILED_TERMINAL'
  AND backend_acked_at_us IS NULL
  AND publication_revision IS NOT NULL
  AND workflow_state IN ('READY', 'FAILED', 'EVICTED')
  AND last_delivery_error =
      'TerminalBackendPublicationError: Backend returned HTTP 404';
