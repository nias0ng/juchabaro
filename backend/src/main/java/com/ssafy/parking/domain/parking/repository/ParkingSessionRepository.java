package com.ssafy.parking.domain.parking.repository;

import com.ssafy.parking.domain.parking.entity.ParkingSession;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface ParkingSessionRepository extends JpaRepository<ParkingSession, Long> {

    Optional<ParkingSession> findFirstByVehicle_IdAndExitTimeIsNullOrderByEntryTimeDesc(Long vehicleId);

    Optional<ParkingSession> findByIdempotencyKey(String idempotencyKey);
    List<ParkingSession> findByVehicle_User_IdAndExitTimeIsNullOrderByEntryTimeDesc(Long userId);
    List<ParkingSession> findByExitTimeIsNull();
}