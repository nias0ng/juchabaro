package com.ssafy.parking.domain.move.repository;

import com.ssafy.parking.domain.move.entity.MoveRequest;
import com.ssafy.parking.domain.move.entity.MoveRequestStatus;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Collection;

public interface MoveRequestRepository extends JpaRepository<MoveRequest, Long> {
    boolean existsByTargetVehicle_IdAndRequestStatusIn(
            Long targetVehicleId, Collection<MoveRequestStatus> statuses);
}