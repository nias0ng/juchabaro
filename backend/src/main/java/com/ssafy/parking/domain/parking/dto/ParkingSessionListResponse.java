package com.ssafy.parking.domain.parking.dto;

import java.util.List;

public record ParkingSessionListResponse(
        List<ParkingSessionResponse> sessions
) {}