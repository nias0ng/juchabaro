package com.ssafy.parking.domain.hw.service;

import com.ssafy.parking.domain.notification.entity.NotificationType;
import com.ssafy.parking.domain.parking.entity.ParkingEventType;

record AutoMoveRequestMessage(
        NotificationType notificationType,
        String title,
        String body,
        String requestMessage
) {
    static AutoMoveRequestMessage of(ParkingEventType type) {
        return switch (type) {
            case EV_OVERSTAY -> new AutoMoveRequestMessage(
                    NotificationType.EV_OVERSTAY,
                    "전기차 충전구역 초과",
                    "충전구역 허용 시간을 초과했습니다. 차량 이동을 부탁드립니다.",
                    "전기차 충전구역 허용 시간을 초과했습니다.");
            case DISABLED_ZONE_VIOLATION -> new AutoMoveRequestMessage(
                    NotificationType.MOVE_REQUEST, "차량 이동 요청",
                    "장애인 전용구역 주차가 감지되었습니다. 차량 이동을 부탁드립니다.",
                    "장애인 전용구역 주차가 감지되었습니다.");
            case DOUBLE_PARKING -> new AutoMoveRequestMessage(
                    NotificationType.MOVE_REQUEST, "차량 이동 요청",
                    "이중주차로 다른 차량 출차가 막혀 있습니다. 차량 이동을 부탁드립니다.",
                    "이중주차가 감지되었습니다.");
            case BAD_PARKING -> new AutoMoveRequestMessage(
                    NotificationType.MOVE_REQUEST, "차량 이동 요청",
                    "불편 주차(주차선 침범)가 감지되었습니다. 차량 이동을 부탁드립니다.",
                    "불편 주차(주차선 침범)가 감지되었습니다.");
            case OUT_OF_ZONE -> new AutoMoveRequestMessage(
                    NotificationType.MOVE_REQUEST, "차량 이동 요청",
                    "구역 외 주차가 감지되었습니다. 차량 이동을 부탁드립니다.",
                    "구역 외 주차가 감지되었습니다.");
            case ETC -> new AutoMoveRequestMessage(
                    NotificationType.MOVE_REQUEST, "차량 이동 요청",
                    "주차 위반이 감지되었습니다. 차량 이동을 부탁드립니다.",
                    "주차 위반이 감지되었습니다.");
        };
    }
}