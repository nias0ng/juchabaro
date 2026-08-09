package com.ssafy.parking.domain.move.repository;

import com.ssafy.parking.domain.move.entity.MoveRequest;
import com.ssafy.parking.domain.move.entity.MoveRequestStatus;
import com.ssafy.parking.domain.move.entity.MoveRequestType;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.LocalDateTime;
import java.util.Collection;
import java.util.List;
import java.util.Optional;

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

    @Query("""
        select mr from MoveRequest mr
        where mr.reminderCount = 0
          and (
            (mr.requestStatus = :sent and mr.requestedAt <= :sentThreshold)
            or (mr.requestStatus = :responded and mr.dueAt <= :now)
          )
        """)
    List<MoveRequest> findReminderTargets(
            @Param("sent") MoveRequestStatus sent,
            @Param("responded") MoveRequestStatus responded,
            @Param("sentThreshold") LocalDateTime sentThreshold,
            @Param("now") LocalDateTime now);

    @Query("""
        select mr from MoveRequest mr
        where mr.reminderCount >= 1
          and mr.reminderSentAt <= :escalateThreshold
          and mr.requestStatus not in :terminal
        """)
    List<MoveRequest> findEscalationTargets(
            @Param("escalateThreshold") LocalDateTime escalateThreshold,
            @Param("terminal") java.util.Collection<MoveRequestStatus> terminal);

    Optional<MoveRequest> findByEvent_Id(Long eventId);
    List<MoveRequest> findByEvent_IdIn(Collection<Long> eventIds);

    List<MoveRequest> findByEvent_Session_IdAndRequestTypeAndRequestStatusInAndRequestedAtLessThanEqual(
            Long sessionId,
            MoveRequestType requestType,
            Collection<MoveRequestStatus> statuses,
            LocalDateTime occurredAt);
}
