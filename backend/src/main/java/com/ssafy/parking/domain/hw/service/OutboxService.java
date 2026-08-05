package com.ssafy.parking.domain.hw.outbox;

import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;

import java.time.LocalDateTime;

@Service
@RequiredArgsConstructor
public class OutboxService {

    private final OutboxRepository outboxRepository;
    private final ObjectMapper objectMapper;

    /** 트리거(T2~T4)에서 호출. 같은 (type:id:rev)는 중복 적재하지 않음(멱등). */
    @Transactional
    public void enqueue(OutboxCommandType type, String aggregateId, int revision,
                        Object payload, LocalDateTime deadlineAt) {
        String key = type.keyLabel() + ":" + aggregateId + ":" + revision;
        if (outboxRepository.findByIdempotencyKey(key).isPresent()) {
            return;
        }
        String json = objectMapper.writeValueAsString(payload);
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