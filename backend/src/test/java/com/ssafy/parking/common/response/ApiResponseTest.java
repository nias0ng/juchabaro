package com.ssafy.parking.common.response;

import com.ssafy.parking.common.exception.ErrorCode;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class ApiResponseTest {

    @Test
    void successWithData() {
        ApiResponse<String> response = ApiResponse.success("data");

        assertThat(response.isSuccess()).isTrue();
        assertThat(response.httpStatus()).isEqualTo("OK");
        assertThat(response.code()).isEqualTo(200);
        assertThat(response.message()).isEqualTo("요청에 성공했습니다.");
        assertThat(response.result()).isEqualTo("data");
    }

    @Test
    void successWithoutData() {
        ApiResponse<Void> response = ApiResponse.successWithoutData();

        assertThat(response.isSuccess()).isTrue();
        assertThat(response.httpStatus()).isEqualTo("OK");
        assertThat(response.code()).isEqualTo(200);
        assertThat(response.result()).isNull();
    }

    @Test
    void failureWithDefaultMessage() {
        ApiResponse<Void> response =
                ApiResponse.failure(ErrorCode.RESOURCE_NOT_FOUND);

        assertThat(response.isSuccess()).isFalse();
        assertThat(response.httpStatus()).isEqualTo("NOT_FOUND");
        assertThat(response.code()).isEqualTo(404);
        assertThat(response.message())
                .isEqualTo(ErrorCode.RESOURCE_NOT_FOUND.getMessage());
        assertThat(response.result()).isNull();
    }

    @Test
    void failureWithCustomMessage() {
        ApiResponse<Void> response = ApiResponse.failure(
                ErrorCode.INVALID_INPUT_VALUE,
                "차량 번호는 필수입니다."
        );

        assertThat(response.isSuccess()).isFalse();
        assertThat(response.httpStatus()).isEqualTo("BAD_REQUEST");
        assertThat(response.code()).isEqualTo(400);
        assertThat(response.message()).isEqualTo("차량 번호는 필수입니다.");
    }
}