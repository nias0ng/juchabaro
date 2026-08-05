package com.ssafy.parking.domain.hw.outbox;

import com.ssafy.parking.common.entity.BaseEntity;
import jakarta.persistence.*;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

@Getter
@Entity
@Table(name = "outbox",
        uniqueConstraints = @UniqueConstraint(name = "uk_outbox_idem", columnNames = "idempotency_key"))
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class OutboxMessage extends BaseEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "outbox_id")
    private Long id;

    @Enumerated(EnumType.STRING)
    @Column(name = "command_type", nullable = false, length = 40)
    private OutboxCommandType commandType;

    @Column(name = "aggregate_id", nullable = false, length = 100)
    private String aggregateId;

    @Column(name = "revision", nullable = false)
    private int revision;

    @Column(name = "idempotency_key", nullable = false, length = 200)
    private String idempotencyKey;

    @Column(name = "endpoint_path", nullable = false, length = 100)
    private String endpointPath;

    @Column(name = "payload", nullable = false, columnDefinition = "TEXT")
    private String payload;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 20)
    private OutboxStatus status;

    @Column(name = "attempts", nullable = false)
    private int attempts;

    @Column(name = "next_attempt_at", nullable = false)
    private LocalDateTime nextAttemptAt;

    @Column(name = "deadline_at")
    private LocalDateTime deadlineAt;

    @Column(name = "application_result", length = 20)
    private String applicationResult;

    @Column(name = "last_error", columnDefinition = "TEXT")
    private String lastError;

    @Builder
    private OutboxMessage(OutboxCommandType commandType, String aggregateId, int revision,
                          String idempotencyKey, String endpointPath, String payload,
                          OutboxStatus status, int attempts, LocalDateTime nextAttemptAt,
                          LocalDateTime deadlineAt) {
        this.commandType = commandType;
        this.aggregateId = aggregateId;
        this.revision = revision;
        this.idempotencyKey = idempotencyKey;
        this.endpointPath = endpointPath;
        this.payload = payload;
        this.status = status;
        this.attempts = attempts;
        this.nextAttemptAt = nextAttemptAt;
        this.deadlineAt = deadlineAt;
    }

    public void markSucceeded(String applicationResult) {
        this.status = OutboxStatus.SUCCEEDED;
        this.applicationResult = applicationResult;
    }

    public void markDead(String error) {
        this.status = OutboxStatus.DEAD;
        this.lastError = error;
    }

    public void markExpired() {
        this.status = OutboxStatus.EXPIRED;
    }

    public void reschedule(LocalDateTime nextAttemptAt, String error) {
        this.attempts += 1;
        this.nextAttemptAt = nextAttemptAt;
        this.lastError = error;
    }
}