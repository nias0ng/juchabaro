package com.ssafy.parking.domain.hw.entity;

import com.ssafy.parking.common.entity.BaseEntity;
import com.ssafy.parking.domain.hw.dto.AccessDecision;
import jakarta.persistence.*;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Getter
@Entity
@Table(name = "entry_decision",
        uniqueConstraints = @UniqueConstraint(
                name = "uk_entry_decision_idem", columnNames = "idempotency_key"))
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class EntryDecision extends BaseEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "entry_decision_id")
    private Long id;

    @Column(name = "idempotency_key", nullable = false, length = 100)
    private String idempotencyKey;

    @Column(name = "entry_attempt_id", nullable = false, length = 100)
    private String entryAttemptId;

    @Column(name = "payload_hash", nullable = false, length = 64)
    private String payloadHash;

    @Enumerated(EnumType.STRING)
    @Column(name = "access_decision", nullable = false, length = 10)
    private AccessDecision accessDecision;

    @Column(name = "decision_revision", nullable = false)
    private int decisionRevision;

    @Column(name = "vehicle_id")
    private Long vehicleId;   // 매칭 차량(REVIEW 후보 포함). DENY는 null

    @Column(name = "session_id")
    private Long sessionId;   // ALLOW만 값, REVIEW/DENY는 null

    @Builder
    private EntryDecision(String idempotencyKey, String entryAttemptId, String payloadHash,
                          AccessDecision accessDecision, int decisionRevision,
                          Long vehicleId, Long sessionId) {
        this.idempotencyKey = idempotencyKey;
        this.entryAttemptId = entryAttemptId;
        this.payloadHash = payloadHash;
        this.accessDecision = accessDecision;
        this.decisionRevision = decisionRevision;
        this.vehicleId = vehicleId;
        this.sessionId = sessionId;
    }
}