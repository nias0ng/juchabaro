package com.ssafy.parking.domain.vehicle.entity;

import com.ssafy.parking.common.entity.BaseEntity;
import com.ssafy.parking.domain.user.entity.User;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.time.LocalDate;

@Getter
@Entity
@Table(name = "vehicles")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Vehicle extends BaseEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "vehicle_id")
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "user_id", nullable = false)
    private User user;

    @Column(name = "plate_number", nullable = false, unique = true, length = 20)
    private String plateNumber;

    @Column(name = "vehicle_model", length = 50)
    private String vehicleModel;

    @Column(name = "is_disabled_vehicle", nullable = false)
    private boolean disabledVehicle;

    @Column(name = "is_electric", nullable = false)
    private boolean electric;

    @Enumerated(EnumType.STRING)
    @Column(name = "owner_type", nullable = false, length = 20)
    private VehicleOwnerType ownerType;

    @Column(name = "visit_date")
    private LocalDate visitDate;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 20)
    private VehicleStatus status;

    @Builder
    private Vehicle(
            User user,
            String plateNumber,
            String vehicleModel,
            boolean disabledVehicle,
            boolean electric,
            VehicleOwnerType ownerType,
            LocalDate visitDate,
            VehicleStatus status
    ) {
        this.user = user;
        this.plateNumber = plateNumber;
        this.vehicleModel = vehicleModel;
        this.disabledVehicle = disabledVehicle;
        this.electric = electric;
        this.ownerType = ownerType;
        this.visitDate = visitDate;
        this.status = status;
    }

    public void changePlateNumber(String plateNumber) { this.plateNumber = plateNumber; }
    public void changeVehicleModel(String vehicleModel) { this.vehicleModel = vehicleModel; }
    public void changeDisabledVehicle(boolean disabledVehicle) { this.disabledVehicle = disabledVehicle; }
    public void changeElectric(boolean electric) { this.electric = electric; }
    public void changeOwnerType(VehicleOwnerType ownerType) { this.ownerType = ownerType; }
    public void markDeleted() { this.status = VehicleStatus.DELETED; }
}