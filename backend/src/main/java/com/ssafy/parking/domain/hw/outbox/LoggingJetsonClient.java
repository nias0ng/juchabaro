package com.ssafy.parking.domain.hw.outbox;

import lombok.extern.slf4j.Slf4j;

@Slf4j
public class LoggingJetsonClient implements JetsonClient {
    @Override
    public JetsonAck send(String path, String idempotencyKey, String jsonPayload) {
        log.info("[JETSON:log] POST {} Idempotency-Key={} body={}", path, idempotencyKey, jsonPayload);
        return new JetsonAck("APPLIED");
    }
}