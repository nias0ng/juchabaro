package com.ssafy.parking.domain.vehicle.service;

import com.ssafy.parking.common.exception.BusinessException;
import com.ssafy.parking.common.exception.ErrorCode;
import com.ssafy.parking.domain.user.repository.UserRepository;
import com.ssafy.parking.domain.vehicle.dto.*;
import com.ssafy.parking.domain.vehicle.entity.Vehicle;
import com.ssafy.parking.domain.vehicle.entity.VehicleOwnerType;
import com.ssafy.parking.domain.vehicle.entity.VehicleStatus;
import com.ssafy.parking.domain.vehicle.repository.VehicleRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.ssafy.parking.domain.hw.outbox.SessionContextNotifier;
import com.ssafy.parking.domain.parking.repository.ParkingSessionRepository;

import java.util.List;

@Service
@RequiredArgsConstructor
public class VehicleService {

    private final VehicleRepository vehicleRepository;
    private final UserRepository userRepository;
    private final ParkingSessionRepository parkingSessionRepository;
    private final SessionContextNotifier sessionContextNotifier;

    @Transactional
    public VehicleCreateResponse register(Long userId, VehicleCreateRequest request) {
        if (vehicleRepository.existsByPlateNumber(request.plateNumber())) {
            throw new BusinessException(ErrorCode.DUPLICATE_PLATE_NUMBER);
        }

        boolean resident = request.ownerType() == VehicleOwnerType.RESIDENT;

        Vehicle vehicle = Vehicle.builder()
                .user(userRepository.getReferenceById(userId))   // FK만 설정 (조회 X)
                .plateNumber(request.plateNumber())
                .vehicleModel(resident ? request.vehicleModel() : null)   // RESIDENT만 모델
                .disabledVehicle(Boolean.TRUE.equals(request.isDisabledVehicle()))
                .electric(Boolean.TRUE.equals(request.isElectric()))
                .ownerType(request.ownerType())
                .visitDate(resident ? null : request.visitDate())          // VISITOR만 방문일
                .status(VehicleStatus.ACTIVE)
                .build();

        vehicleRepository.save(vehicle);
        return VehicleCreateResponse.from(vehicle, userId);
    }

    @Transactional(readOnly = true)
    public VehicleListResponse getMyVehicles(Long userId, VehicleOwnerType ownerType, VehicleStatus status) {
        VehicleStatus effectiveStatus = (status != null) ? status : VehicleStatus.ACTIVE;
        List<Vehicle> vehicles = (ownerType == null)
                ? vehicleRepository.findByUser_IdAndStatus(userId, effectiveStatus)
                : vehicleRepository.findByUser_IdAndOwnerTypeAndStatus(userId, ownerType, effectiveStatus);
        return VehicleListResponse.from(vehicles);
    }

    @Transactional(readOnly = true)
    public VehicleDetailResponse getVehicle(Long userId, Long vehicleId) {
        Vehicle vehicle = vehicleRepository.findById(vehicleId)
                .orElseThrow(() -> new BusinessException(ErrorCode.VEHICLE_NOT_FOUND));
        if (!vehicle.getUser().getId().equals(userId)) {
            throw new BusinessException(ErrorCode.VEHICLE_ACCESS_DENIED);
        }
        return VehicleDetailResponse.from(vehicle);
    }

    @Transactional
    public VehicleUpdateResponse update(Long userId, Long vehicleId, VehicleUpdateRequest request) {
        if (request.isEmpty()) {
            throw new BusinessException(ErrorCode.VEHICLE_UPDATE_INVALID);
        }

        Vehicle vehicle = vehicleRepository.findById(vehicleId)
                .orElseThrow(() -> new BusinessException(ErrorCode.VEHICLE_NOT_FOUND));
        if (!vehicle.getUser().getId().equals(userId)) {
            throw new BusinessException(ErrorCode.VEHICLE_UPDATE_ACCESS_DENIED);
        }

        if (request.plateNumber() != null
                && !request.plateNumber().equals(vehicle.getPlateNumber())) {
            if (vehicleRepository.existsByPlateNumber(request.plateNumber())) {
                throw new BusinessException(ErrorCode.DUPLICATE_PLATE_NUMBER);
            }
            vehicle.changePlateNumber(request.plateNumber());
        }
        if (request.vehicleModel() != null) vehicle.changeVehicleModel(request.vehicleModel());

        // (A) 변경 '전' 자격 값을 저장해둔다 (나중에 실제로 바뀌었는지 비교용)
        boolean beforeDisabled = vehicle.isDisabledVehicle();
        boolean beforeElectric = vehicle.isElectric();

        if (request.isDisabledVehicle() != null) vehicle.changeDisabledVehicle(request.isDisabledVehicle());
        if (request.isElectric() != null) vehicle.changeElectric(request.isElectric());
        if (request.ownerType() != null) vehicle.changeOwnerType(request.ownerType());

        vehicleRepository.saveAndFlush(vehicle);

        boolean capabilityChanged = vehicle.isDisabledVehicle() != beforeDisabled
                || vehicle.isElectric() != beforeElectric;
        if (capabilityChanged) {
            parkingSessionRepository
                    .findFirstByVehicle_IdAndExitTimeIsNullOrderByEntryTimeDesc(vehicleId)
                    .ifPresent(session -> sessionContextNotifier.publish(session, "ACTIVE"));
        }

        return VehicleUpdateResponse.from(vehicle);
    }

    @Transactional
    public VehicleDeleteResponse delete(Long userId, Long vehicleId) {
        Vehicle vehicle = vehicleRepository.findById(vehicleId)
                .orElseThrow(() -> new BusinessException(ErrorCode.VEHICLE_NOT_FOUND));
        if (vehicle.getStatus() == VehicleStatus.DELETED) {
            throw new BusinessException(ErrorCode.VEHICLE_NOT_FOUND);   // 이미 삭제됨 → 404
        }
        if (!vehicle.getUser().getId().equals(userId)) {
            throw new BusinessException(ErrorCode.VEHICLE_DELETE_ACCESS_DENIED);
        }

        // 진행 중(미출차) 주차 세션이 있으면 삭제 거부 (409)
        boolean hasActiveSession = parkingSessionRepository
                .findFirstByVehicle_IdAndExitTimeIsNullOrderByEntryTimeDesc(vehicleId)
                .isPresent();
        if (hasActiveSession) {
            throw new BusinessException(ErrorCode.VEHICLE_HAS_ACTIVE_RECORD);
        }

        vehicle.markDeleted();                     // 소프트 삭제 (status = DELETED)
        vehicleRepository.saveAndFlush(vehicle);
        return VehicleDeleteResponse.from(vehicle);
    }
}