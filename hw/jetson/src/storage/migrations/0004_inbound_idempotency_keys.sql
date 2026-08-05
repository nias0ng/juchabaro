-- Backend -> Jetson command의 transport Idempotency-Key를 domain identity와
-- 함께 보존한다. 기존 accepted_inputs는 배포 전 구현에서 key를 저장하지
-- 않았으므로 NULL을 허용하고, 재수신 시 최초 key를 한 번 연결한다.

ALTER TABLE accepted_inputs
ADD COLUMN idempotency_key TEXT;

CREATE UNIQUE INDEX uq_accepted_input_idempotency_key
ON accepted_inputs(idempotency_key)
WHERE idempotency_key IS NOT NULL;

CREATE TRIGGER accepted_input_idempotency_key_once
BEFORE UPDATE OF idempotency_key ON accepted_inputs
FOR EACH ROW
WHEN OLD.idempotency_key IS NOT NULL
    AND (
        NEW.idempotency_key IS NULL
        OR NEW.idempotency_key <> OLD.idempotency_key
    )
BEGIN
    SELECT RAISE(ABORT, 'accepted input idempotency key is immutable');
END;
