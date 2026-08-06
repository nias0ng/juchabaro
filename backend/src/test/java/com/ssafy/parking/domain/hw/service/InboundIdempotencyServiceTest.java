package com.ssafy.parking.domain.hw.service;

import com.ssafy.parking.common.exception.BusinessException;
import com.ssafy.parking.common.exception.ErrorCode;
import com.ssafy.parking.domain.hw.entity.InboundReceipt;
import com.ssafy.parking.domain.hw.repository.InboundReceiptRepository;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataIntegrityViolationException;
import tools.jackson.databind.ObjectMapper;

import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class InboundIdempotencyServiceTest {

    @Test
    void concurrentInsertConflictBecomesRetryableInProgressError() {
        InboundReceiptRepository repository =
                mock(InboundReceiptRepository.class);
        ObjectMapper objectMapper = mock(ObjectMapper.class);
        InboundIdempotencyService service =
                new InboundIdempotencyService(repository, objectMapper);
        Object payload = new Object();

        when(objectMapper.writeValueAsString(payload))
                .thenReturn("{\"publicationRevision\":1}");
        when(repository.findByEndpointAndIdempotencyKey(
                "INCIDENT_TRANSITION",
                "Incident:incident-1:1"
        )).thenReturn(Optional.empty());
        doThrow(new DataIntegrityViolationException("concurrent insert"))
                .when(repository).saveAndFlush(any(InboundReceipt.class));

        BusinessException exception = assertThrows(
                BusinessException.class,
                () -> service.record(
                        "INCIDENT_TRANSITION",
                        "Incident:incident-1:1",
                        payload
                )
        );

        assertThat(exception.getErrorCode())
                .isEqualTo(ErrorCode.HW_IDEMPOTENCY_IN_PROGRESS);
        verify(repository).saveAndFlush(any(InboundReceipt.class));
    }
}
