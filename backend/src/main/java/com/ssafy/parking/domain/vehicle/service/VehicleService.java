package com.ssafy.parking.domain.vehicle.service;

import com.ssafy.parking.common.exception.BusinessException;
import com.ssafy.parking.common.exception.ErrorCode;
import com.ssafy.parking.domain.user.repository.UserRepository;
import com.ssafy.parking.domain.vehicle.dto.VehicleCreateRequest;
import com.ssafy.parking.domain.vehicle.dto.VehicleCreateResponse;
import com.ssafy.parking.domain.vehicle.dto.VehicleDetailResponse;
import com.ssafy.parking.domain.vehicle.dto.VehicleListResponse;
import com.ssafy.parking.domain.vehicle.entity.Vehicle;
import com.ssafy.parking.domain.vehicle.entity.VehicleOwnerType;
import com.ssafy.parking.domain.vehicle.entity.VehicleStatus;
import com.ssafy.parking.domain.vehicle.repository.VehicleRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

@Service
@RequiredArgsConstructor
public class VehicleService {

    private final VehicleRepository vehicleRepository;
    private final UserRepository userRepository;

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
}