package com.ssafy.parking.domain.vehicle.service;

import com.ssafy.parking.domain.parking.repository.ParkingSessionRepository;
import com.ssafy.parking.domain.vehicle.entity.Vehicle;
import com.ssafy.parking.domain.vehicle.entity.VehicleOwnerType;
import com.ssafy.parking.domain.vehicle.entity.VehicleStatus;
import com.ssafy.parking.domain.vehicle.repository.VehicleRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDate;
import java.util.List;

@Component
@RequiredArgsConstructor
public class VisitorVehicleExpiryScheduler {

    private final VehicleRepository vehicleRepository;
    private final ParkingSessionRepository parkingSessionRepository;

    @Scheduled(cron = "0 0 0 * * *", zone = "Asia/Seoul")
    @Transactional
    public void expireVisitors() {
        LocalDate today = LocalDate.now();
        List<Vehicle> targets = vehicleRepository.findByOwnerTypeAndStatusAndVisitDateBefore(
                VehicleOwnerType.VISITOR, VehicleStatus.ACTIVE, today);
        for (Vehicle v : targets) {
            boolean parking = parkingSessionRepository
                    .findFirstByVehicle_IdAndExitTimeIsNullOrderByEntryTimeDesc(v.getId())
                    .isPresent();
            if (parking) continue;
            v.markDeleted();
        }
    }
}