package com.ssafy.parking.domain.hw.repository;

import com.ssafy.parking.domain.hw.entity.InboundReceipt;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface InboundReceiptRepository extends JpaRepository<InboundReceipt, Long> {
    Optional<InboundReceipt> findByEndpointAndIdempotencyKey(String endpoint, String idempotencyKey);
}