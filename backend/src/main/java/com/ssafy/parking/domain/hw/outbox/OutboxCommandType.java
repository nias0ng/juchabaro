package com.ssafy.parking.domain.hw.outbox;

public enum OutboxCommandType {
    ENTRY_REVIEW_RESOLUTION("EntryReviewResolution", "/internal/entry-review-resolutions"),
    SESSION_CONTEXT_UPDATE("SessionContextUpdate", "/internal/session-context-updates"),
    MOVE_VERIFICATION("MoveVerification", "/internal/move-verifications");

    private final String keyLabel;   // Idempotency-Key 접두어(계약 표기)
    private final String path;

    OutboxCommandType(String keyLabel, String path) {
        this.keyLabel = keyLabel;
        this.path = path;
    }
    public String keyLabel() { return keyLabel; }
    public String path() { return path; }
}