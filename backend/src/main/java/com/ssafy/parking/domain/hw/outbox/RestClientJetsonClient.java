package com.ssafy.parking.domain.hw.outbox;

import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.HttpServerErrorException;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.time.Duration;

@Slf4j
public class RestClientJetsonClient implements JetsonClient {

    private static final int MAX_ATTEMPTS = 3;              // 최초 1 + 재시도 2
    private static final long[] BACKOFF_MS = {1000L, 2000L}; // 1s → 2s

    private final RestClient client;
    private final String apiKey;
    private final ObjectMapper objectMapper;

    public RestClientJetsonClient(String baseUrl, String apiKey, int timeoutMs, ObjectMapper objectMapper) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(Duration.ofMillis(timeoutMs));
        factory.setReadTimeout(Duration.ofMillis(timeoutMs));
        this.client = RestClient.builder().baseUrl(baseUrl).requestFactory(factory).build();
        this.apiKey = apiKey;
        this.objectMapper = objectMapper;
    }

    @Override
    public JetsonAck send(String path, String idempotencyKey, String jsonPayload) {
        int attempt = 0;
        while (true) {
            try {
                return doSend(path, idempotencyKey, jsonPayload);
            } catch (JetsonDeliveryException e) {
                if (!e.isRetryable() || attempt >= MAX_ATTEMPTS - 1) {
                    throw e;
                }
                sleep(BACKOFF_MS[attempt]);
                attempt++;
            }
        }
    }

    private JetsonAck doSend(String path, String idempotencyKey, String jsonPayload) {
        try {
            ResponseEntity<String> resp = client.post()
                    .uri(path)
                    .header("X-Internal-API-Key", apiKey)
                    .header("Idempotency-Key", idempotencyKey)
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(jsonPayload)
                    .retrieve()
                    .toEntity(String.class);
            return new JetsonAck(parseApplicationResult(resp.getBody()));
        } catch (HttpClientErrorException e) {                 // 4xx → 재시도 불가
            throw new JetsonDeliveryException(false, "4xx " + e.getStatusCode() + " " + e.getResponseBodyAsString());
        } catch (HttpServerErrorException e) {                 // 5xx → 재시도
            throw new JetsonDeliveryException(true, "5xx " + e.getStatusCode());
        } catch (ResourceAccessException e) {                  // timeout/connection → 재시도
            throw new JetsonDeliveryException(true, "IO " + e.getMessage());
        }
    }

    private String parseApplicationResult(String body) {
        try {
            JsonNode node = objectMapper.readTree(body);
            return node.path("result").path("applicationResult").asText("APPLIED");
        } catch (Exception e) {
            return "APPLIED";   // 파싱 실패해도 2xx는 성공으로 간주
        }
    }

    private void sleep(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException ie) {
            Thread.currentThread().interrupt();
            throw new JetsonDeliveryException(true, "interrupted");
        }
    }
}