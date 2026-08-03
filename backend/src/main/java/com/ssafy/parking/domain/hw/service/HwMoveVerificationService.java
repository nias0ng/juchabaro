package com.ssafy.parking.domain.hw.service;

import com.ssafy.parking.common.exception.BusinessException;
import com.ssafy.parking.common.exception.ErrorCode;
import com.ssafy.parking.domain.hw.dto.HwPublicationAck;
import com.ssafy.parking.domain.hw.dto.MoveVerificationResultRequest;
import com.ssafy.parking.domain.move.entity.MoveRequest;
import com.ssafy.parking.domain.move.entity.MoveRequestStatus;
import com.ssafy.parking.domain.move.repository.MoveRequestRepository;
import com.ssafy.parking.domain.parking.entity.ParkingEvent;
import com.ssafy.parking.domain.parking.entity.ParkingEventStatus;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.HashMap;
import java.util.Map;

@Service
@RequiredArgsConstructor
public class HwMoveVerificationService {

    private final MoveRequestRepository moveRequestRepository;

    @Transactional
    public HwPublicationAck handle(Long requestId, MoveVerificationResultRequest req) {
        MoveRequest mr = moveRequestRepository.findById(requestId)
                .orElseThrow(() -> new BusinessException(ErrorCode.MOVE_REQUEST_NOT_FOUND));

        String result;
        if ("RESOLVED".equals(req.result())) {
            if (mr.getRequestStatus() == MoveRequestStatus.COMPLETED) {
                result = "ALREADY_APPLIED";
            } else {
                mr.markCompleted();                 // 이동요청 완료
                ParkingEvent event = mr.getEvent(); // 연관 이벤트도 해소
                if (event.getEventStatus() != ParkingEventStatus.RESOLVED) {
                    event.resolve(toKst(req.completedAt()));
                }
                result = "APPLIED";
            }
        } else {
            // STILL_ACTIVE / UNKNOWN → 상태 변경 없음 (재알림/에스컬레이션은 스케줄러가 담당)
            result = "APPLIED";
        }

        Map<String, Object> corr = new HashMap<>();
        corr.put("requestId", mr.getId());
        corr.put("eventId", mr.getEvent().getId());
        return new HwPublicationAck(
                "MoveVerificationAttempt",
                mr.getId() + ":" + req.verificationAttempt(),
                req.publicationRevision(), result, corr);
    }

    private LocalDateTime toKst(OffsetDateTime t) {
        return (t != null)
                ? t.atZoneSameInstant(ZoneId.of("Asia/Seoul")).toLocalDateTime()
                : LocalDateTime.now();
    }
}