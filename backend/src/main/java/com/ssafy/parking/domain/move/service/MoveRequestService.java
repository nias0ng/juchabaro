package com.ssafy.parking.domain.move.service;

import com.ssafy.parking.common.exception.BusinessException;
import com.ssafy.parking.common.exception.ErrorCode;
import com.ssafy.parking.common.storage.ImageStorageService;
import com.ssafy.parking.domain.move.dto.MoveRequestCreateResponse;
import com.ssafy.parking.domain.move.dto.MoveRequestListResponse;
import com.ssafy.parking.domain.move.entity.MoveRequest;
import com.ssafy.parking.domain.move.entity.MoveRequestScope;
import com.ssafy.parking.domain.move.entity.MoveRequestStatus;
import com.ssafy.parking.domain.move.entity.MoveRequestType;
import com.ssafy.parking.domain.move.repository.MoveRequestRepository;
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

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

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

    @Transactional
    public MoveRequestCreateResponse create(
            Long userId, String targetPlateNumber, ParkingEventType eventType,
            String reason, Long zoneId, List<MultipartFile> images
    ) {
        // 400
        if (eventType == null || reason == null || reason.isBlank()
                || images == null || images.isEmpty() || images.get(0).isEmpty()) {
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

        ParkingZone zone = (zoneId != null)
                ? parkingZoneRepository.findById(zoneId).orElse(null) : null;

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
        return MoveRequestListResponse.from(result);
    }
}