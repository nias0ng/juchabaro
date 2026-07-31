package com.ssafy.parking.domain.parking.repository;

import com.ssafy.parking.domain.parking.entity.ParkingZone;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface ParkingZoneRepository extends JpaRepository<ParkingZone, Long> {
    Optional<ParkingZone> findByZoneNumber(String zoneNumber);
}