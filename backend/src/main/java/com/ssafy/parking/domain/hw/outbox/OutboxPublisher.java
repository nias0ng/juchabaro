package com.ssafy.parking.domain.hw.outbox;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.domain.PageRequest;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;

@Slf4j
@Component
@RequiredArgsConstructor
public class OutboxPublisher {

    private final OutboxRepository outboxRepository;
    private final JetsonClient jetsonClient;

    @Value("${app.jetson.enabled:false}")
    private boolean enabled;

    @Scheduled(fixedDelay = 10_000) // 10초 주기
    @Transactional
    public void dispatch() {
        if (!enabled) {
            return;   // host 미정 시 발신 보류(PENDING 누적)
        }
        LocalDateTime now = LocalDateTime.now();
        List<OutboxMessage> batch = outboxRepository
                .findByStatusAndNextAttemptAtLessThanEqualOrderByNextAttemptAtAsc(
                        OutboxStatus.PENDING, now, PageRequest.of(0, 50));

        for (OutboxMessage m : batch) {
            if (m.getDeadlineAt() != null && m.getDeadlineAt().isBefore(now)) {
                m.markExpired();       // API11 deadline 경과
                continue;
            }
            try {
                JetsonAck ack = jetsonClient.send(m.getEndpointPath(), m.getIdempotencyKey(), m.getPayload());
                m.markSucceeded(ack.applicationResult());   // APPLIED/ALREADY_APPLIED/STALE 모두 성공
            } catch (JetsonDeliveryException e) {
                if (e.isRetryable()) {
                    m.reschedule(now.plusSeconds(backoffSeconds(m.getAttempts() + 1)), e.getMessage());
                } else {
                    m.markDead(e.getMessage());   // 4xx 종료
                    log.warn("Outbox DEAD id={} key={} err={}", m.getId(), m.getIdempotencyKey(), e.getMessage());
                }
            }
        }
    }

    private long backoffSeconds(int attempts) {
        return Math.min(300L, 15L * attempts);   // durable 재시도 backoff (최대 5분)
    }
}