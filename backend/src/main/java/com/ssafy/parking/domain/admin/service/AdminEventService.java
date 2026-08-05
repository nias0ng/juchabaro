package com.ssafy.parking.domain.admin.service;

import com.ssafy.parking.common.exception.BusinessException;
import com.ssafy.parking.common.exception.ErrorCode;
import com.ssafy.parking.domain.admin.dto.*;
import com.ssafy.parking.domain.admin.entity.AdminActionLog;
import com.ssafy.parking.domain.admin.repository.AdminActionLogRepository;
import com.ssafy.parking.domain.move.entity.MoveRequest;
import com.ssafy.parking.domain.move.repository.MoveRequestRepository;
import com.ssafy.parking.domain.move.repository.MoveRequestResponseRepository;
import com.ssafy.parking.domain.notification.entity.NotificationType;
import com.ssafy.parking.domain.notification.service.NotificationDispatcher;
import com.ssafy.parking.domain.parking.entity.EventImage;
import com.ssafy.parking.domain.parking.entity.ParkingEvent;
import com.ssafy.parking.domain.parking.entity.ParkingEventStatus;
import com.ssafy.parking.domain.parking.entity.ParkingEventType;
import com.ssafy.parking.domain.parking.repository.EventImageRepository;
import com.ssafy.parking.domain.parking.repository.ParkingEventRepository;
import com.ssafy.parking.domain.user.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
public class AdminEventService {

    private static final ZoneId KST = ZoneId.of("Asia/Seoul");

    private final ParkingEventRepository parkingEventRepository;
    private final MoveRequestRepository moveRequestRepository;
    private final MoveRequestResponseRepository moveRequestResponseRepository;
    private final EventImageRepository eventImageRepository;
    private final AdminActionLogRepository adminActionLogRepository;
    private final UserRepository userRepository;
    private final NotificationDispatcher notificationDispatcher;

    @Transactional(readOnly = true)
    public AdminEventListResponse getEvents(LocalDate date, ParkingEventStatus status,
                                            ParkingEventType type, int page, int size) {
        LocalDateTime from = (date != null) ? date.atStartOfDay() : null;
        LocalDateTime to   = (date != null) ? date.plusDays(1).atStartOfDay() : null;
        Pageable pageable = PageRequest.of(page, size);

        Page<ParkingEvent> events = parkingEventRepository.findForAdmin(from, to, status, type, pageable);

        List<Long> eventIds = events.getContent().stream().map(ParkingEvent::getId).toList();
        Map<Long, MoveRequest> mrByEvent = moveRequestRepository.findByEvent_IdIn(eventIds).stream()
                .collect(Collectors.toMap(mr -> mr.getEvent().getId(), mr -> mr, (a, b) -> a));

        List<AdminEventSummary> items = events.getContent().stream().map(e -> {
            MoveRequest mr = mrByEvent.get(e.getId());
            return new AdminEventSummary(
                    e.getId(),
                    e.getVehicle().getPlateNumber(),
                    e.getEventType().name(),
                    (mr != null) ? mr.getRequestStatus().name() : null,
                    (e.getZone() != null) ? e.getZone().getZoneNumber() : null,
                    kst(e.getDetectedAt()),
                    e.getViolationRatio(),
                    e.getEventStatus().name());
        }).toList();

        return new AdminEventListResponse(items, events.getNumber(), events.getSize(),
                events.getTotalElements(), events.getTotalPages());
    }

    @Transactional(readOnly = true)
    public AdminEventDetailResponse getEvent(Long eventId) {
        ParkingEvent e = parkingEventRepository.findById(eventId)
                .orElseThrow(() -> new BusinessException(ErrorCode.PARKING_EVENT_NOT_FOUND));
        MoveRequest mr = moveRequestRepository.findByEvent_Id(eventId).orElse(null);

        List<AdminEventDetailResponse.Image> images = eventImageRepository.findByEvent_Id(eventId).stream()
                .map(img -> new AdminEventDetailResponse.Image(img.getId(), img.getImageUrl(), kst(img.getCapturedAt())))
                .toList();

        List<AdminEventDetailResponse.Response> responses = (mr != null)
                ? moveRequestResponseRepository.findByRequest_IdOrderByRespondedAtAsc(mr.getId()).stream()
                .map(r -> new AdminEventDetailResponse.Response(
                        r.getResponseType().name(), r.getEstimatedMinutes(), kst(r.getRespondedAt())))
                .toList()
                : List.of();

        List<AdminEventDetailResponse.ActionLog> logs = adminActionLogRepository
                .findByEvent_IdOrderByCreatedAtDesc(eventId).stream()
                .map(l -> new AdminEventDetailResponse.ActionLog(
                        l.getId(), l.getActionType(), l.getAdminUser().getName(), kst(l.getCreatedAt()), l.getMemo()))
                .toList();

        return new AdminEventDetailResponse(
                e.getId(), e.getVehicle().getPlateNumber(), e.getEventType().name(),
                e.getEventStatus().name(), (mr != null) ? mr.getRequestStatus().name() : null,
                (e.getZone() != null) ? e.getZone().getZoneNumber() : null,
                (e.getZone() != null) ? e.getZone().getFloor() : null,
                kst(e.getDetectedAt()), kst(e.getResolvedAt()),
                e.getViolationRatio(), e.getReason(),
                (mr != null) ? mr.getReminderCount() : null,
                (mr != null) ? kst(mr.getRequestedAt()) : null,
                images, responses, logs);
    }

    @Transactional
    public void complete(Long eventId, Long adminId, String memo) {
        ParkingEvent e = loadEvent(eventId);
        ParkingEventStatus before = e.getEventStatus();
        e.resolve(LocalDateTime.now());                        // RESOLVED + resolvedAt
        moveRequestRepository.findByEvent_Id(eventId).ifPresent(MoveRequest::markCompleted);
        log(e, adminId, "COMPLETE", before, e.getEventStatus(), memo);
    }

    @Transactional
    public void dismiss(Long eventId, Long adminId, String memo) {
        ParkingEvent e = loadEvent(eventId);
        ParkingEventStatus before = e.getEventStatus();
        e.changeStatus(ParkingEventStatus.DISMISSED);          // 단방향 확정
        log(e, adminId, "DISMISS", before, e.getEventStatus(), memo);
    }

    @Transactional
    public void acknowledge(Long eventId, Long adminId, String memo) {
        ParkingEvent e = loadEvent(eventId);
        log(e, adminId, "ACKNOWLEDGE", e.getEventStatus(), e.getEventStatus(), memo);  // 상태 변경 없음
    }

    @Transactional
    public void sendReminder(Long eventId, Long adminId) {
        ParkingEvent e = loadEvent(eventId);
        MoveRequest mr = moveRequestRepository.findByEvent_Id(eventId)
                .orElseThrow(() -> new BusinessException(ErrorCode.ADMIN_REMINDER_NOT_APPLICABLE));
        LocalDateTime now = LocalDateTime.now();
        mr.markReminderSent(now);                              // 스케줄러와 동일 카운터 +1
        notificationDispatcher.dispatch(
                mr.getTargetVehicle().getUser(), NotificationType.REMINDER,
                "차량 이동 재요청(관리자)",
                "관리자가 차량 이동을 다시 요청했습니다.",
                e, mr, now);
        log(e, adminId, "REMINDER", e.getEventStatus(), e.getEventStatus(), "관리자 수동 재알림");
    }

    @Transactional(readOnly = true)
    public AdminHistoryResponse getHistory(LocalDate startDate, LocalDate endDate,
                                           String actionType, int page, int size) {
        LocalDate s = (startDate != null) ? startDate : LocalDate.now();
        LocalDate en = (endDate != null) ? endDate : s;
        LocalDateTime from = s.atStartOfDay();
        LocalDateTime to = en.plusDays(1).atStartOfDay();
        Pageable pageable = PageRequest.of(page, size);

        Page<AdminActionLog> logs = adminActionLogRepository.findForHistory(
                from, to, (actionType != null && !actionType.isBlank()) ? actionType : null, pageable);

        List<AdminHistoryItem> items = logs.getContent().stream()
                .map(l -> new AdminHistoryItem(
                        l.getId(), l.getEvent().getId(),
                        l.getEvent().getVehicle().getPlateNumber(),
                        l.getActionType(), l.getAdminUser().getName(),
                        kst(l.getCreatedAt()), l.getMemo()))
                .toList();

        return new AdminHistoryResponse(items, logs.getNumber(), logs.getSize(),
                logs.getTotalElements(), logs.getTotalPages());
    }

    private ParkingEvent loadEvent(Long eventId) {
        return parkingEventRepository.findById(eventId)
                .orElseThrow(() -> new BusinessException(ErrorCode.PARKING_EVENT_NOT_FOUND));
    }

    private void log(ParkingEvent event, Long adminId, String actionType,
                     ParkingEventStatus before, ParkingEventStatus after, String memo) {
        adminActionLogRepository.save(AdminActionLog.builder()
                .adminUser(userRepository.getReferenceById(adminId))
                .event(event)
                .actionType(actionType)
                .beforeStatus(before)
                .afterStatus(after)
                .memo(memo)
                .build());
    }

    private OffsetDateTime kst(LocalDateTime t) {
        return (t == null) ? null : t.atZone(KST).toOffsetDateTime();
    }
}