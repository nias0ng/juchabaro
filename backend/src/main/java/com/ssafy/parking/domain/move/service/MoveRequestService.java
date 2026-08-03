package com.ssafy.parking.domain.move.service;

import com.ssafy.parking.common.exception.BusinessException;
import com.ssafy.parking.common.exception.ErrorCode;
import com.ssafy.parking.common.storage.ImageStorageService;
import com.ssafy.parking.domain.move.dto.*;
import com.ssafy.parking.domain.move.entity.*;
import com.ssafy.parking.domain.move.repository.MoveRequestRepository;
import com.ssafy.parking.domain.move.repository.MoveRequestResponseRepository;
import com.ssafy.parking.domain.notification.entity.Notification;
import com.ssafy.parking.domain.notification.entity.NotificationType;
import com.ssafy.parking.domain.notification.repository.NotificationRepository;
import com.ssafy.parking.domain.parking.entity.*;
import com.ssafy.parking.domain.parking.repository.*;
import com.ssafy.parking.domain.user.repository.UserRepository;
import com.ssafy.parking.domain.vehicle.entity.Vehicle;
import com.ssafy.parking.domain.vehicle.repository.VehicleRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.*;

@Service
@RequiredArgsConstructor
public class MoveRequestService {

    private static final List<MoveRequestStatus> ACTIVE_STATUSES = List.of(
            MoveRequestStatus.SENT, MoveRequestStatus.RESPONDED,
            MoveRequestStatus.REMINDER_SENT, MoveRequestStatus.NEED_ADMIN);

    private final VehicleRepository vehicleRepository;
    private final ParkingSessionRepository parkingSessionRepository;
    private final ParkingEventRepository parkingEventRepository;
    private final EventImageRepository eventImageRepository;
    private final ParkingZoneRepository parkingZoneRepository;
    private final MoveRequestRepository moveRequestRepository;
    private final NotificationRepository notificationRepository;
    private final UserRepository userRepository;
    private final ImageStorageService imageStorageService;
    private final MoveRequestResponseRepository moveRequestResponseRepository;

    private static final Set<Integer> ALLOWED_MINUTES = Set.of(10, 30, 60, 120);

    private static final Set<MoveRequestStatus> UNRESOLVED_STATUSES = Set.of(
            MoveRequestStatus.SENT, MoveRequestStatus.RESPONDED,
            MoveRequestStatus.REMINDER_SENT, MoveRequestStatus.NEED_ADMIN);

    @Transactional
    public MoveRequestCreateResponse create(
            Long userId, String targetPlateNumber, ParkingEventType eventType,
            String reason, String zoneName, List<MultipartFile> images
    ) {
        // 400
        if (eventType == null || reason == null || reason.isBlank()
                || images == null || images.isEmpty() || images.getFirst().isEmpty()) {
            throw new BusinessException(ErrorCode.MOVE_REQUEST_INVALID);
        }

        // 404: 대상 차량 + 진행 중 세션
        Vehicle target = vehicleRepository.findByPlateNumber(targetPlateNumber)
                .orElseThrow(() -> new BusinessException(ErrorCode.MOVE_REQUEST_TARGET_NOT_FOUND));
        ParkingSession session = parkingSessionRepository
                .findFirstByVehicle_IdAndExitTimeIsNullOrderByEntryTimeDesc(target.getId())
                .orElseThrow(() -> new BusinessException(ErrorCode.MOVE_REQUEST_TARGET_NOT_FOUND));

        // 409: 처리 중인 요청 존재
        if (moveRequestRepository.existsByTargetVehicle_IdAndRequestStatusIn(target.getId(), ACTIVE_STATUSES)) {
            throw new BusinessException(ErrorCode.MOVE_REQUEST_ALREADY_EXISTS);
        }

        ParkingZone zone = (zoneName != null && !zoneName.isBlank())
                ? parkingZoneRepository.findByZoneNumber(zoneName).orElse(null) : null;

        LocalDateTime now = LocalDateTime.now();

        // 사건 생성
        ParkingEvent event = ParkingEvent.builder()
                .session(session).vehicle(target).zone(zone)
                .eventType(eventType).reason(reason)
                .eventStatus(ParkingEventStatus.REQUESTED)
                .detectedAt(now)
                .build();
        parkingEventRepository.save(event);

        // 이미지 저장
        List<EventImage> savedImages = new ArrayList<>();
        for (MultipartFile file : images) {
            String url = imageStorageService.store(file, event.getId());
            EventImage img = EventImage.builder()
                    .event(event).imageUrl(url)
                    .imageType(EventImageType.REPORT).capturedAt(now)
                    .build();
            eventImageRepository.save(img);
            savedImages.add(img);
        }

        // 이동 요청 생성
        MoveRequest moveRequest = MoveRequest.builder()
                .event(event)
                .requester(userRepository.getReferenceById(userId))
                .targetVehicle(target)
                .requestType(MoveRequestType.MANUAL)
                .requestStatus(MoveRequestStatus.SENT)
                .message(reason)
                .requestedAt(now)
                .dueAt(null)
                .build();
        moveRequestRepository.save(moveRequest);

        // 대상 차주에게 알림 레코드
        Notification notification = Notification.builder()
                .user(target.getUser())
                .event(event).request(moveRequest)
                .notificationType(NotificationType.MOVE_REQUEST)
                .title("차량 이동 요청")
                .body("등록하신 차량에 이동 요청이 도착했습니다.")
                .sentAt(now)
                .build();
        notificationRepository.save(notification);

        return MoveRequestCreateResponse.from(event, moveRequest, savedImages);
    }

    // TODO(N+1 최적화): 조회 결과 매핑 시 lazy 연관(event/targetVehicle/requester) 접근으로
    //   N+1 발생. 리포지토리에 @EntityGraph 또는 fetch join 적용 예정.
    @Transactional(readOnly = true)
    public MoveRequestListResponse getMoveRequests(
            Long userId, MoveRequestScope scope, MoveRequestStatus status, int page, int size
    ) {
        if (page < 0 || size < 1) {
            throw new BusinessException(ErrorCode.MOVE_REQUEST_QUERY_INVALID);
        }
        Pageable pageable = PageRequest.of(page, size, Sort.by(Sort.Direction.DESC, "requestedAt"));

        Page<MoveRequest> result = switch (scope) {
            case RECEIVED -> moveRequestRepository.findReceived(userId, status, pageable);
            case SENT -> moveRequestRepository.findSent(userId, status, pageable);
            case ALL -> moveRequestRepository.findAllScoped(userId, status, pageable);
        };

        List<Long> requestIds = result.getContent().stream().map(MoveRequest::getId).toList();
        Map<Long, Integer> estimatedMinutesMap = new HashMap<>();
        if (!requestIds.isEmpty()) {
            for (MoveRequestResponse r : moveRequestResponseRepository.findByRequest_IdInOrderByRespondedAtAsc(requestIds)) {
                estimatedMinutesMap.put(r.getRequest().getId(), r.getEstimatedMinutes()); // asc라 최신 응답이 덮어씀
            }
        }
        return MoveRequestListResponse.from(result, estimatedMinutesMap);
    }

    @Transactional(readOnly = true)
    public MoveRequestDetailResponse getMoveRequest(Long userId, Long requestId) {
        MoveRequest mr = moveRequestRepository.findById(requestId)
                .orElseThrow(() -> new BusinessException(ErrorCode.MOVE_REQUEST_NOT_FOUND));

        boolean isRequester = mr.getRequester() != null
                && mr.getRequester().getId().equals(userId);
        boolean isTargetOwner = mr.getTargetVehicle().getUser().getId().equals(userId);
        if (!isRequester && !isTargetOwner) {
            throw new BusinessException(ErrorCode.MOVE_REQUEST_ACCESS_DENIED);
        }

        var images = eventImageRepository.findByEvent_Id(mr.getEvent().getId());
        var responses = moveRequestResponseRepository.findByRequest_IdOrderByRespondedAtAsc(requestId);
        var history = notificationRepository.findByRequest_IdOrderBySentAtAsc(requestId);

        return MoveRequestDetailResponse.from(mr, images, responses, history);
    }

    @Transactional
    public MoveResponseCreateResponse respond(Long userId, Long requestId, MoveResponseCreateRequest request) {
        MoveRequest mr = moveRequestRepository.findById(requestId)
                .orElseThrow(() -> new BusinessException(ErrorCode.MOVE_REQUEST_NOT_FOUND));

        if (!mr.getTargetVehicle().getUser().getId().equals(userId)) {
            throw new BusinessException(ErrorCode.MOVE_REQUEST_RESPONSE_ACCESS_DENIED);
        }

        MoveRequestStatus st = mr.getRequestStatus();
        if (st == MoveRequestStatus.COMPLETED || st == MoveRequestStatus.NEED_ADMIN
                || st == MoveRequestStatus.CANCELLED) {
            throw new BusinessException(ErrorCode.MOVE_REQUEST_RESPONSE_NOT_ALLOWED);
        }

        MoveResponseType type = request.responseType();
        if (type == null) {
            throw new BusinessException(ErrorCode.MOVE_REQUEST_RESPONSE_INVALID);
        }
        Integer minutes;
        if (type == MoveResponseType.WILL_MOVE) {
            minutes = request.estimatedMinutes();
            if (minutes == null || !ALLOWED_MINUTES.contains(minutes)) {
                throw new BusinessException(ErrorCode.MOVE_REQUEST_RESPONSE_INVALID);
            }
        } else {
            minutes = null;
        }

        LocalDateTime now = LocalDateTime.now();

        MoveRequestResponse response = MoveRequestResponse.builder()
                .request(mr)
                .responder(userRepository.getReferenceById(userId))
                .responseType(type)
                .estimatedMinutes(minutes)
                .respondedAt(now)
                .build();
        moveRequestResponseRepository.save(response);

        ParkingEvent event = mr.getEvent();
        if (type == MoveResponseType.WILL_MOVE) {
            mr.markResponded(now.plusMinutes(minutes));
        } else {
            mr.markNeedAdmin();
            event.changeStatus(ParkingEventStatus.NEED_ADMIN);
        }

        // 신고자(요청자)에게 응답 도착 알림 (자동요청이면 requester가 없어 생략)
        if (mr.getRequester() != null) {
            String body = (type == MoveResponseType.WILL_MOVE)
                    ? "차주가 약 " + minutes + "분 후 이동 예정으로 응답했습니다."
                    : "차주가 지금은 이동이 어렵다고 응답했습니다.";
            Notification notification = Notification.builder()
                    .user(mr.getRequester())
                    .event(event)
                    .request(mr)
                    .notificationType(NotificationType.MOVE_RESPONSE)
                    .title("이동 요청 응답 도착")
                    .body(body)
                    .sentAt(now)
                    .build();
            notificationRepository.save(notification);
        }

        return MoveResponseCreateResponse.from(response, mr, event);
    }

    @Transactional(readOnly = true)
    public MoveRequestStatsResponse getStats(Long userId) {
        LocalDateTime since = LocalDateTime.now().minusDays(90);

        long total = moveRequestRepository
                .countByTargetVehicle_User_IdAndRequestedAtAfter(userId, since);
        long unresolved = moveRequestRepository
                .countByTargetVehicle_User_IdAndRequestStatusInAndRequestedAtAfter(
                        userId, UNRESOLVED_STATUSES, since);

        List<Object[]> timings =
                moveRequestResponseRepository.findResponseTimingsByResponder(userId, since);
        int avg = timings.isEmpty() ? 0 : (int) Math.round(
                timings.stream()
                        .mapToLong(r -> Duration.between(
                                (LocalDateTime) r[0], (LocalDateTime) r[1]).toMinutes())
                        .average().orElse(0));

        return new MoveRequestStatsResponse((int) total, (int) unresolved, avg);
    }
}