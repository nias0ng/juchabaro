package com.ssafy.parking.common.response;

import com.ssafy.parking.common.exception.ErrorCode;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class ApiResponseTest {

    @Test
    void successWithData() {
        ApiResponse<String> response = ApiResponse.success("data");

        assertThat(response.success()).isTrue();
        assertThat(response.code()).isEqualTo("SUCCESS");
        assertThat(response.message()).isEqualTo("요청에 성공했습니다.");
        assertThat(response.data()).isEqualTo("data");
    }

    @Test
    void successWithoutData() {
        ApiResponse<Void> response = ApiResponse.successWithoutData();

        assertThat(response.success()).isTrue();
        assertThat(response.code()).isEqualTo("SUCCESS");
        assertThat(response.data()).isNull();
    }

    @Test
    void failureWithDefaultMessage() {
        ApiResponse<Void> response =
                ApiResponse.failure(ErrorCode.RESOURCE_NOT_FOUND);

        assertThat(response.success()).isFalse();
        assertThat(response.code()).isEqualTo("RESOURCE_NOT_FOUND");
        assertThat(response.message())
                .isEqualTo(ErrorCode.RESOURCE_NOT_FOUND.getMessage());
        assertThat(response.data()).isNull();
    }

    @Test
    void failureWithCustomMessage() {
        ApiResponse<Void> response = ApiResponse.failure(
                ErrorCode.INVALID_INPUT_VALUE,
                "차량 번호는 필수입니다."
        );

        assertThat(response.success()).isFalse();
        assertThat(response.code()).isEqualTo("INVALID_INPUT_VALUE");
        assertThat(response.message()).isEqualTo("차량 번호는 필수입니다.");
    }
}