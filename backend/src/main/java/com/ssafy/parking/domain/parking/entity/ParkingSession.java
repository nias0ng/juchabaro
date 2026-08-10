package com.ssafy.parking.domain.parking.entity;

import com.ssafy.parking.common.entity.BaseEntity;
import com.ssafy.parking.domain.vehicle.entity.Vehicle;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

@Getter
@Entity
@Table(name = "parking_sessions")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class ParkingSession extends BaseEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "session_id")
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "vehicle_id", nullable = false)
    private Vehicle vehicle;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "zone_id")
    private ParkingZone zone;

    @Column(name = "recognized_plate_number", nullable = false, length = 20)
    private String recognizedPlateNumber;

    @Column(name = "entry_attempt_id", length = 100)
    private String entryAttemptId;

    @Column(name = "entry_time", nullable = false)
    private LocalDateTime entryTime;

    @Column(name = "parked_at")
    private LocalDateTime parkedAt;

    @Column(name = "exit_time")
    private LocalDateTime exitTime;

    @Column(name = "idempotency_key", unique = true, length = 100)
    private String idempotencyKey;

    @Column(name = "context_revision", nullable = false)
    private int contextRevision;

    @Builder
    private ParkingSession(
            Vehicle vehicle,
            ParkingZone zone,
            String recognizedPlateNumber,
            String entryAttemptId,
            LocalDateTime entryTime,
            LocalDateTime parkedAt,
            LocalDateTime exitTime,
            String idempotencyKey,
            int contextRevision
    ) {
        if (contextRevision < 1) {
            throw new IllegalArgumentException("contextRevision은 1 이상이어야 합니다.");
        }

        this.vehicle = vehicle;
        this.zone = zone;
        this.recognizedPlateNumber = recognizedPlateNumber;
        this.entryAttemptId = entryAttemptId;
        this.entryTime = entryTime;
        this.parkedAt = parkedAt;
        this.exitTime = exitTime;
        this.idempotencyKey = idempotencyKey;
        this.contextRevision = contextRevision;
    }

    public void assignZone(ParkingZone zone, LocalDateTime parkedAt) {
        this.zone = zone;
        this.parkedAt = parkedAt;
    }

    public void unassign() {
        this.zone = null;
        this.parkedAt = null;
    }

    public void markExit(LocalDateTime exitTime) {
        this.exitTime = exitTime;
    }

    public int bumpContextRevision() {
        this.contextRevision += 1;
        return this.contextRevision;
    }
}