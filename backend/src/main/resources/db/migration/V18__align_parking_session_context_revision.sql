-- Align existing Backend session revisions with the authoritative entry decision
-- revision already accepted by Jetson.
UPDATE parking_sessions ps
JOIN entry_decision ed
    ON ed.session_id = ps.session_id
SET ps.context_revision = ed.decision_revision
WHERE ps.context_revision < ed.decision_revision;
