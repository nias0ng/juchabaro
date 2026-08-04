package com.ssafy.parking.domain.hw.entity;

import com.ssafy.parking.common.entity.BaseEntity;
import jakarta.persistence.*;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Getter
@Entity
@Table(name = "inbound_receipt",
        uniqueConstraints = @UniqueConstraint(
                name = "uk_inbound_receipt", columnNames = {"endpoint", "idempotency_key"}))
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class InboundReceipt extends BaseEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "inbound_receipt_id")
    private Long id;

    @Column(name = "endpoint", nullable = false, length = 40)
    private String endpoint;           // PARKING_TRANSITION | SESSION_EXIT | INCIDENT_TRANSITION

    @Column(name = "idempotency_key", nullable = false, length = 100)
    private String idempotencyKey;

    @Column(name = "payload_hash", nullable = false, length = 64)
    private String payloadHash;

    @Builder
    private InboundReceipt(String endpoint, String idempotencyKey, String payloadHash) {
        this.endpoint = endpoint;
        this.idempotencyKey = idempotencyKey;
        this.payloadHash = payloadHash;
    }
}