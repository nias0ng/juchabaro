package com.ssafy.parking.domain.hw.outbox;

import com.ssafy.parking.domain.hw.dto.AccessDecision;
import com.ssafy.parking.domain.hw.entity.EntryDecision;
import com.ssafy.parking.domain.hw.repository.EntryDecisionRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.domain.PageRequest;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;

@Component
@RequiredArgsConstructor
public class EntryReviewExpiryScheduler {

    private final EntryDecisionRepository entryDecisionRepository;
    private final EntryReviewResolutionNotifier notifier;

    @Value("${app.review.expire-minutes:30}")
    private long expireMinutes;

    @Scheduled(fixedDelay = 60_000) // 1분 주기
    @Transactional
    public void expireStaleReviews() {
        LocalDateTime threshold = LocalDateTime.now().minusMinutes(expireMinutes);
        List<EntryDecision> targets = entryDecisionRepository.findExpirableReviews(
                AccessDecision.REVIEW, threshold, PageRequest.of(0, 50));
        for (EntryDecision d : targets) {
            notifier.publishExpired(d);
        }
    }
}