package com.ssafy.parking.domain.vehicle.service;

import com.ssafy.parking.common.exception.BusinessException;
import com.ssafy.parking.common.exception.ErrorCode;
import com.ssafy.parking.domain.user.repository.UserRepository;
import com.ssafy.parking.domain.vehicle.dto.VehicleCreateRequest;
import com.ssafy.parking.domain.vehicle.dto.VehicleCreateResponse;
import com.ssafy.parking.domain.vehicle.entity.Vehicle;
import com.ssafy.parking.domain.vehicle.entity.VehicleOwnerType;
import com.ssafy.parking.domain.vehicle.entity.VehicleStatus;
import com.ssafy.parking.domain.vehicle.repository.VehicleRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

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
}