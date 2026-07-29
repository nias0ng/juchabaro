package com.ssafy.parking.domain.vehicle.repository;

import com.ssafy.parking.domain.vehicle.entity.Vehicle;
import org.springframework.data.jpa.repository.JpaRepository;

public interface VehicleRepository extends JpaRepository<Vehicle, Long> {
    boolean existsByPlateNumber(String plateNumber);
}