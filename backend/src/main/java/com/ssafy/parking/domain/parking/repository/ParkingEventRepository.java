package com.ssafy.parking.domain.parking.repository;

import com.ssafy.parking.domain.parking.entity.ParkingEvent;
import com.ssafy.parking.domain.parking.entity.ParkingEventStatus;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

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
}