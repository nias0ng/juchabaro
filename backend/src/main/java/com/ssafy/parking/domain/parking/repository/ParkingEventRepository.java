package com.ssafy.parking.domain.parking.repository;

import com.ssafy.parking.domain.parking.entity.ParkingEvent;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ParkingEventRepository extends JpaRepository<ParkingEvent, Long> {
}