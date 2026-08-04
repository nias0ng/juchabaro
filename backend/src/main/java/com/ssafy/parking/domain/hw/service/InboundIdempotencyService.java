package com.ssafy.parking.domain.hw.service;

import com.ssafy.parking.common.exception.BusinessException;
import com.ssafy.parking.common.exception.ErrorCode;
import com.ssafy.parking.domain.hw.entity.InboundReceipt;
import com.ssafy.parking.domain.hw.repository.InboundReceiptRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

@Service
@RequiredArgsConstructor
public class InboundIdempotencyService {

    private final InboundReceiptRepository inboundReceiptRepository;

    /**
     * 같은 (endpoint, key)가 이미 있고 payload가 다르면 409.
     * 없으면 리시트 저장. 동일 재요청은 no-op(도메인 멱등이 ALREADY_APPLIED 처리).
     */
    @Transactional
    public void record(String endpoint, String idempotencyKey, Object payload) {
        if (idempotencyKey == null || idempotencyKey.isBlank()) {
            return;   // 키 없으면 멱등 스킵(도메인 로직만 수행)
        }
        String hash = sha256(String.valueOf(payload));   // record.toString() = 결정적 표현
        InboundReceipt existing = inboundReceiptRepository
                .findByEndpointAndIdempotencyKey(endpoint, idempotencyKey).orElse(null);
        if (existing != null) {
            if (!existing.getPayloadHash().equals(hash)) {
                throw new BusinessException(ErrorCode.HW_IDEMPOTENCY_CONFLICT);
            }
            return;
        }
        inboundReceiptRepository.save(InboundReceipt.builder()
                .endpoint(endpoint).idempotencyKey(idempotencyKey).payloadHash(hash).build());
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