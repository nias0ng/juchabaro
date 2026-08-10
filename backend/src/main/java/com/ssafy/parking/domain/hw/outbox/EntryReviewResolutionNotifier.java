package com.ssafy.parking.domain.hw.outbox;

import com.ssafy.parking.domain.hw.entity.EntryDecision;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.time.ZoneId;

@Service
@RequiredArgsConstructor
public class EntryReviewResolutionNotifier {

    private static final ZoneId KST = ZoneId.of("Asia/Seoul");

    private final com.ssafy.parking.domain.hw.outbox.OutboxService outboxService;

    @Transactional
    public void publishExpired(EntryDecision decision) {
        LocalDateTime now = LocalDateTime.now();
        int revision = decision.resolveExpired(now);   // decisionRevision +1 + 상태 확정

        EntryReviewResolutionPayload payload = new EntryReviewResolutionPayload(
                decision.getEntryAttemptId(),
                revision,
                "REVIEW_EXPIRED",
                now.atZone(KST).toOffsetDateTime(),
                null);   // EXPIRED → sessionContext 없음

        outboxService.enqueue(
                OutboxCommandType.ENTRY_REVIEW_RESOLUTION,
                decision.getEntryAttemptId(),
                revision,
                payload,
                null);   // API 4는 deadline 없음
    }
}