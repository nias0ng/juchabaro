package com.ssafy.parking.domain.hw.outbox;

public class JetsonDeliveryException extends RuntimeException {
    private final boolean retryable;

    public JetsonDeliveryException(boolean retryable, String message) {
        super(message);
        this.retryable = retryable;
    }
    public boolean isRetryable() { return retryable; }
}