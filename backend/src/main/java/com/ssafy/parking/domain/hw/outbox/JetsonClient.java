package com.ssafy.parking.domain.hw.outbox;

public interface JetsonClient {
    JetsonAck send(String path, String idempotencyKey, String jsonPayload);
}