package com.ssafy.parking.domain.vehicle.repository;

import com.ssafy.parking.domain.vehicle.entity.Vehicle;
import com.ssafy.parking.domain.vehicle.entity.VehicleOwnerType;
import com.ssafy.parking.domain.vehicle.entity.VehicleStatus;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface VehicleRepository extends JpaRepository<Vehicle, Long> {

    boolean existsByPlateNumber(String plateNumber);

    List<Vehicle> findByUser_IdAndStatus(Long userId, VehicleStatus status);

    List<Vehicle> findByUser_IdAndOwnerTypeAndStatus(
            Long userId,
            VehicleOwnerType ownerType,
            VehicleStatus status
    );
}