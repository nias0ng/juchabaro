package com.ssafy.parking.domain.move.repository;

import com.ssafy.parking.domain.move.entity.MoveRequest;
import com.ssafy.parking.domain.move.entity.MoveRequestStatus;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.LocalDateTime;
import java.util.Collection;

public interface MoveRequestRepository extends JpaRepository<MoveRequest, Long> {

    boolean existsByTargetVehicle_IdAndRequestStatusIn(
            Long targetVehicleId, Collection<MoveRequestStatus> statuses);

    long countByTargetVehicle_User_IdAndRequestedAtAfter(Long userId, LocalDateTime since);

    long countByTargetVehicle_User_IdAndRequestStatusInAndRequestedAtAfter(
            Long userId, Collection<MoveRequestStatus> statuses, LocalDateTime since);

    @Query("""
        select mr from MoveRequest mr
        where (mr.targetVehicle.user.id = :userId or mr.requester.id = :userId)
          and (:status is null or mr.requestStatus = :status)
        """)
    Page<MoveRequest> findAllScoped(@Param("userId") Long userId,
                                    @Param("status") MoveRequestStatus status,
                                    Pageable pageable);

    @Query("""
        select mr from MoveRequest mr
        where mr.targetVehicle.user.id = :userId
          and (:status is null or mr.requestStatus = :status)
        """)
    Page<MoveRequest> findReceived(@Param("userId") Long userId,
                                   @Param("status") MoveRequestStatus status,
                                   Pageable pageable);

    @Query("""
        select mr from MoveRequest mr
        where mr.requester.id = :userId
          and (:status is null or mr.requestStatus = :status)
        """)
    Page<MoveRequest> findSent(@Param("userId") Long userId,
                               @Param("status") MoveRequestStatus status,
                               Pageable pageable);
}