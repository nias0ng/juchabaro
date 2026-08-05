package com.ssafy.parking.domain.hw.outbox;

public record JetsonAck(String applicationResult) {}   // APPLIED | ALREADY_APPLIED | STALE