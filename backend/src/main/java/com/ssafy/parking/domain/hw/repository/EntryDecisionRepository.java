package com.ssafy.parking.domain.hw.repository;

import com.ssafy.parking.domain.hw.dto.AccessDecision;
import com.ssafy.parking.domain.hw.entity.EntryDecision;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

public interface EntryDecisionRepository extends JpaRepository<EntryDecision, Long> {

    Optional<EntryDecision> findByIdempotencyKey(String idempotencyKey);

    @Query("""
        select d from EntryDecision d
        where d.accessDecision = :decision
          and d.resolution is null
          and d.createdAt <= :threshold
        """)
    List<EntryDecision> findExpirableReviews(
            @Param("decision") AccessDecision decision,
            @Param("threshold") LocalDateTime threshold,
            Pageable pageable);
}