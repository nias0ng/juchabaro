package com.ssafy.parking.domain.parking.repository;

import com.ssafy.parking.domain.parking.entity.ParkingEvent;
import com.ssafy.parking.domain.parking.entity.ParkingEventStatus;
import com.ssafy.parking.domain.parking.entity.ParkingEventType;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.LocalDateTime;
import java.util.Collection;
import java.util.Optional;
import java.util.Set;

public interface ParkingEventRepository extends JpaRepository<ParkingEvent, Long> {

    @Query("""
        select distinct e.session.id from ParkingEvent e
        where e.eventStatus in :statuses and e.session.exitTime is null
        """)
    Set<Long> findActiveViolationSessionIds(@Param("statuses") Collection<ParkingEventStatus> statuses);

    Optional<ParkingEvent> findByIncidentId(String incidentId);

    @Query("""
        select e from ParkingEvent e
        where (:from is null or e.detectedAt >= :from)
              and (:to   is null or e.detectedAt <  :to)
              and (:status is null or e.eventStatus = :status)
              and (:type   is null or e.eventType   = :type)
        order by e.detectedAt desc
        """)
    Page<ParkingEvent> findForAdmin(@Param("from") LocalDateTime from,
                                    @Param("to") LocalDateTime to,
                                    @Param("status") ParkingEventStatus status,
                                    @Param("type") ParkingEventType type,
                                    Pageable pageable);
}