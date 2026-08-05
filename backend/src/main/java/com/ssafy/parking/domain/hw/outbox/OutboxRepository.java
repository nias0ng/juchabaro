package com.ssafy.parking.domain.hw.outbox;

import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

public interface OutboxRepository extends JpaRepository<OutboxMessage, Long> {

    Optional<OutboxMessage> findByIdempotencyKey(String idempotencyKey);

    List<OutboxMessage> findByStatusAndNextAttemptAtLessThanEqualOrderByNextAttemptAtAsc(
            OutboxStatus status, LocalDateTime now, Pageable pageable);
}