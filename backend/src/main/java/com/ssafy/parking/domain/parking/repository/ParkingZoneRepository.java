package com.ssafy.parking.domain.parking.repository;

import com.ssafy.parking.domain.parking.entity.ParkingZone;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface ParkingZoneRepository extends JpaRepository<ParkingZone, Long> {
    Optional<ParkingZone> findByZoneNumber(String zoneNumber);
    List<ParkingZone> findAllByOrderByHwZoneIdAsc();
    Optional<ParkingZone> findByHwZoneId(Integer hwZoneId);
}