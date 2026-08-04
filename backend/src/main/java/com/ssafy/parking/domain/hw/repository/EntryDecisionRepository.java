package com.ssafy.parking.domain.hw.repository;

import com.ssafy.parking.domain.hw.entity.EntryDecision;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface EntryDecisionRepository extends JpaRepository<EntryDecision, Long> {
    Optional<EntryDecision> findByIdempotencyKey(String idempotencyKey);
}