package com.ssafy.parking.domain.hw.outbox;

import tools.jackson.core.JacksonException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;

import java.time.LocalDateTime;

@Slf4j
@Service
@RequiredArgsConstructor
public class OutboxService {

    private final OutboxRepository outboxRepository;
    private final ObjectMapper objectMapper;

    @Transactional
    public void enqueue(OutboxCommandType type, String aggregateId, int revision,
                        Object payload, LocalDateTime deadlineAt) {
        String key = type.keyLabel() + ":" + aggregateId + ":" + revision;
        if (outboxRepository.findByIdempotencyKey(key).isPresent()) {
            return;
        }
        String json;
        try {
            json = objectMapper.writeValueAsString(payload);
        } catch (JacksonException e) {
            log.error("Outbox 직렬화 실패 - key={}, type={}", key, type, e);
            throw new IllegalStateException("Outbox payload 직렬화 실패: " + key, e);
        }
        outboxRepository.save(OutboxMessage.builder()
                .commandType(type)
                .aggregateId(aggregateId)
                .revision(revision)
                .idempotencyKey(key)
                .endpointPath(type.path())
                .payload(json)
                .status(OutboxStatus.PENDING)
                .attempts(0)
                .nextAttemptAt(LocalDateTime.now())
                .deadlineAt(deadlineAt)
                .build());
    }
}