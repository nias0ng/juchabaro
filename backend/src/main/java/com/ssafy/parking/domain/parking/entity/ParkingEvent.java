package com.ssafy.parking.domain.parking.entity;

import com.ssafy.parking.common.entity.BaseEntity;
import com.ssafy.parking.domain.vehicle.entity.Vehicle;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
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
@Table(name = "parking_events")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class ParkingEvent extends BaseEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "event_id")
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "session_id", nullable = false)
    private ParkingSession session;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "vehicle_id", nullable = false)
    private Vehicle vehicle;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "zone_id")
    private ParkingZone zone;

    @Enumerated(EnumType.STRING)
    @Column(name = "event_type", nullable = false, length = 40)
    private ParkingEventType eventType;

    @Column(name = "reason", columnDefinition = "TEXT")
    private String reason;

    @Column(name = "violation_ratio")
    private Integer violationRatio;

    @Enumerated(EnumType.STRING)
    @Column(name = "event_status", nullable = false, length = 30)
    private ParkingEventStatus eventStatus;

    @Column(name = "detected_at", nullable = false)
    private LocalDateTime detectedAt;

    @Column(name = "resolved_at")
    private LocalDateTime resolvedAt;

    @Column(name = "incident_id", unique = true, length = 36)
    private String incidentId;

    @Column(name = "publication_revision")
    private Integer publicationRevision;

    @Column(name = "rule_code", length = 40)
    private String ruleCode;

    @Column(name = "physical_vehicle_id", length = 36)
    private String physicalVehicleId;

    @Column(name = "entry_attempt_id", length = 100)
    private String entryAttemptId;

    @Builder
    private ParkingEvent(
            ParkingSession session,
            Vehicle vehicle,
            ParkingZone zone,
            ParkingEventType eventType,
            String reason,
            Integer violationRatio,
            ParkingEventStatus eventStatus,
            LocalDateTime detectedAt,
            LocalDateTime resolvedAt,
            String incidentId,
            Integer publicationRevision,
            String ruleCode,
            String physicalVehicleId,
            String entryAttemptId
    ) {
        this.session = session;
        this.vehicle = vehicle;
        this.zone = zone;
        this.eventType = eventType;
        this.reason = reason;
        this.violationRatio = violationRatio;
        this.eventStatus = eventStatus;
        this.detectedAt = detectedAt;
        this.resolvedAt = resolvedAt;
        this.incidentId = incidentId;
        this.publicationRevision = publicationRevision;
        this.ruleCode = ruleCode;
        this.physicalVehicleId = physicalVehicleId;
        this.entryAttemptId = entryAttemptId;
    }

    public void changeStatus(ParkingEventStatus eventStatus) {
        this.eventStatus = eventStatus;
    }

    public void resolve(LocalDateTime resolvedAt) {
        this.eventStatus = ParkingEventStatus.RESOLVED;
        this.resolvedAt = resolvedAt;
    }
}