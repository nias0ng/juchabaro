package com.ssafy.parking.common.exception;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class BusinessExceptionTest {

    @Test
    void createWithErrorCode() {
        ErrorCode errorCode = ErrorCode.RESOURCE_NOT_FOUND;

        BusinessException exception =
                new BusinessException(errorCode);

        assertThat(exception.getErrorCode()).isEqualTo(errorCode);
        assertThat(exception.getMessage())
                .isEqualTo(errorCode.getMessage());
    }
}