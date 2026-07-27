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

    @Column(name = "tracking_id", length = 100)
    private String trackingId;

    @Column(name = "entry_time", nullable = false)
    private LocalDateTime entryTime;

    @Column(name = "parked_at")
    private LocalDateTime parkedAt;

    @Column(name = "exit_time")
    private LocalDateTime exitTime;

    @Builder
    private ParkingSession(
            Vehicle vehicle,
            ParkingZone zone,
            String recognizedPlateNumber,
            String trackingId,
            LocalDateTime entryTime,
            LocalDateTime parkedAt,
            LocalDateTime exitTime
    ) {
        this.vehicle = vehicle;
        this.zone = zone;
        this.recognizedPlateNumber = recognizedPlateNumber;
        this.trackingId = trackingId;
        this.entryTime = entryTime;
        this.parkedAt = parkedAt;
        this.exitTime = exitTime;
    }
}