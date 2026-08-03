package com.ssafy.parking.domain.parking.entity;

import com.ssafy.parking.common.entity.BaseEntity;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Getter
@Entity
@Table(name = "parking_zones")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class ParkingZone extends BaseEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "zone_id")
    private Long id;

    @Column(name = "zone_number", nullable = false, unique = true, length = 20)
    private String zoneNumber;

    @Enumerated(EnumType.STRING)
    @Column(name = "zone_type", length = 20)
    private ParkingZoneType zoneType;

    @Column(name = "floor", length = 20)
    private String floor;

    @Column(name = "geometry_data", columnDefinition = "TEXT")
    private String geometryData;

    @Column(name = "allowed_minutes")
    private Integer allowedMinutes;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", length = 20)
    private ParkingZoneStatus status;

    @Column(name = "hw_zone_id", unique = true)
    private Integer hwZoneId;

    @Enumerated(EnumType.STRING)
    @Column(name = "entry_exit_role", length = 10)
    private EntryExitRole entryExitRole;

    @Builder
    private ParkingZone(
            String zoneNumber,
            ParkingZoneType zoneType,
            String floor,
            String geometryData,
            Integer allowedMinutes,
            ParkingZoneStatus status,
            Integer hwZoneId,
            EntryExitRole entryExitRole
    ) {
        this.zoneNumber = zoneNumber;
        this.zoneType = zoneType;
        this.floor = floor;
        this.geometryData = geometryData;
        this.allowedMinutes = allowedMinutes;
        this.status = status;
        this.hwZoneId = hwZoneId;
        this.entryExitRole = entryExitRole;
    }

    public void updateDefinition(
            ParkingZoneType zoneType,
            Integer hwZoneId,
            EntryExitRole entryExitRole,
            Integer allowedMinutes,
            String geometryData,
            String floor
    ) {
        this.zoneType = zoneType;
        this.hwZoneId = hwZoneId;
        this.entryExitRole = entryExitRole;
        this.allowedMinutes = allowedMinutes;
        this.geometryData = geometryData;
        this.floor = floor;
    }
}