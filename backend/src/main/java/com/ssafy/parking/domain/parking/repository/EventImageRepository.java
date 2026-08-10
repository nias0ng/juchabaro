package com.ssafy.parking.domain.parking.repository;

import com.ssafy.parking.domain.parking.entity.EventImage;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface EventImageRepository extends JpaRepository<EventImage, Long> {
    List<EventImage> findByEvent_Id(Long eventId);
    Optional<EventImage> findByEvidenceId(String evidenceId);
}