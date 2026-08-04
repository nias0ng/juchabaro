package com.ssafy.parking.domain.hw.service;

import com.ssafy.parking.common.exception.BusinessException;
import com.ssafy.parking.common.exception.ErrorCode;
import com.ssafy.parking.domain.hw.entity.InboundReceipt;
import com.ssafy.parking.domain.hw.repository.InboundReceiptRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

@Service
@RequiredArgsConstructor
public class InboundIdempotencyService {

    private final InboundReceiptRepository inboundReceiptRepository;
    private final ObjectMapper objectMapper;   // Boot 4 기본 Jackson 3 매퍼

    @Transactional
    public void record(String endpoint, String idempotencyKey, Object payload) {
        if (idempotencyKey == null || idempotencyKey.isBlank()) {
            return;   // 키 없으면 멱등 스킵(도메인 로직만)
        }
        String hash = sha256(serialize(payload));

        InboundReceipt existing = inboundReceiptRepository
                .findByEndpointAndIdempotencyKey(endpoint, idempotencyKey).orElse(null);
        if (existing != null) {
            ensureSamePayload(existing, hash);
            return;   // 동일 재요청 → 도메인 멱등이 ALREADY_APPLIED 처리
        }

        try {
            inboundReceiptRepository.saveAndFlush(InboundReceipt.builder()
                    .endpoint(endpoint).idempotencyKey(idempotencyKey).payloadHash(hash).build());
        } catch (DataIntegrityViolationException e) {
            // 동시 요청 경쟁: 다른 트랜잭션이 같은 키를 먼저 삽입함 → 500 대신 재시도 신호(409)
            throw new BusinessException(ErrorCode.HW_IDEMPOTENCY_IN_PROGRESS);
        }
    }

    private void ensureSamePayload(InboundReceipt receipt, String hash) {
        if (!receipt.getPayloadHash().equals(hash)) {
            throw new BusinessException(ErrorCode.HW_IDEMPOTENCY_CONFLICT);
        }
    }

    private String serialize(Object payload) {
        return objectMapper.writeValueAsString(payload);   // 실제 필드 값 기반 결정적 문자열
    }

    private String sha256(String s) {
        try {
            byte[] h = MessageDigest.getInstance("SHA-256").digest(s.getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder(64);
            for (byte b : h) sb.append(String.format("%02x", b));
            return sb.toString();
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }
}