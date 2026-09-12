package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model;

import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.HttpServerErrorException;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.util.UriComponentsBuilder;

@Component
public class ImageCutoutDataSet extends DataSet {
    private static final Logger logger = LoggerFactory.getLogger(ImageCutoutDataSet.class);

    // R6.94d: shared RestTemplate + ObjectMapper (R6.85-A-REST pattern from LlmController / PipelineProxyController).
    // Previously each of auth()/download()/getDatasets() did `new RestTemplate()` + `new ObjectMapper()` per call —
    // that's 3 RestTemplate allocations + 2 ObjectMapper allocations per request cycle, defeating connection pooling
    // (SimpleClientHttpRequestFactory is created fresh each time so connections cannot be reused).
    //
    // Iron rule R6.94-B: any @Component with RestTemplate usage MUST use instance-level `final RestTemplate` field
    // (shared connection pool, single ObjectMapper for thread-safety). NO `new RestTemplate()` inside hot-path methods.
    //
    // Thread-safety notes:
    //   RestTemplate: thread-safe for execute() once configured (per Spring docs).
    //   ObjectMapper: thread-safe for read operations after construction (no per-request reconfiguration here).
    private final RestTemplate restTemplate = new RestTemplate();
    private final ObjectMapper objectMapper = new ObjectMapper();

    // R6.90 B5: token + auth-in-progress tracking for idempotency.
    // Volatile visibility is sufficient for token (single-writer pattern: read in
    // authorized(), write in auth() under synchronized). The AtomicBoolean
    // prevents two concurrent auth() calls from racing the network round-trip.
    private volatile String token = "";
    private final AtomicBoolean authInProgress = new AtomicBoolean(false);

    @Value("${imagecutout.username}")
    private String username;

    @Value("${imagecutout.password}")
    private String password;

    // Not used, but required by abstract base class
    @Override
    public void auth(String username, String password) {
        // No-op
    }

    @Override
    public void auth(String token) {
        // Not used. Authentication is handled by auth() with properties.
    }

    /**
     * R6.90 B5: auth() is now IDEMPOTENT.
     *
     * <p>If a valid token is already cached, the call returns immediately without
     * a network round-trip. This protects against:
     * <ul>
     *   <li>Frontend retry storms (e.g., a click on "download" being doubled-tapped
     *       produces two auth() calls — only the first hits the network).</li>
     *   <li>Concurrent auth() invocations from different threads (e.g., the
     *       async ImageCutoutService + a parallel manual retry). The
     *       {@code authInProgress} AtomicBoolean ensures only one in-flight
     *       login at a time.</li>
     *   <li>Upstream rate-limiting: china-vo.org's /generate/login endpoint
     *       throttles aggressively; skipping the call when the token is still
     *       valid saves quota.</li>
     * </ul>
     *
     * <p>Iron rule R6.90-C: any side-effecting method on a @Component MUST be
     * idempotent on retry, OR must use an in-progress flag to coalesce
     * concurrent invocations. The existing rest of the codebase (LlmController
     * query-cache) follows the same pattern.
     */
    public void auth() {
        // Fast path: already authenticated, skip the network call.
        if (!token.isEmpty() && authorized()) {
            logger.debug("B5: auth() idempotent — token already valid, skipping login");
            return;
        }

        // Coalesce concurrent auth() invocations. If another thread is already
        // authenticating, return immediately and let that thread complete the login.
        if (!authInProgress.compareAndSet(false, true)) {
            logger.debug("B5: auth() idempotent — another thread is already authenticating");
            return;
        }

        try {
            String apiBaseUrl = "https://hips.china-vo.org";
            String loginUrl = apiBaseUrl + "/generate/login";
            try {
                Map<String, String> loginData = new HashMap<>();
                loginData.put("username", username);
                loginData.put("password", password);
                HttpHeaders headers = new HttpHeaders();
                headers.set("Content-Type", "application/json");
                HttpEntity<String> entity = new HttpEntity<>(objectMapper.writeValueAsString(loginData), headers);
                // R6.94d: getStatusCode().value() (not deprecated getStatusCodeValue())
                ResponseEntity<String> response = restTemplate.postForEntity(loginUrl, entity, String.class);
                if (response.getStatusCode().value() == 200) {
                    JsonNode json = objectMapper.readTree(response.getBody());
                    this.token = json.path("token").asText();
                    logger.info("Login successful, token obtained");
                } else {
                    logger.error("Login failed: HTTP {}", response.getStatusCode().value());
                    this.token = "";
                }
            } catch (Exception e) {
                logger.error("Failed to authenticate with username/password", e);
                this.token = "";
            }
        } finally {
            authInProgress.set(false);
        }
    }

    @Override
    public void download(String output, String datatype, Metadata metadata) throws IOException {
        if (metadata.getDataset_name() == null || metadata.getDataset_name().isEmpty()) {
            throw new IllegalArgumentException("Dataset name is required");
        }
        Map<String, Object> metadataMap = metadata.toMap();
        logger.info("Metadata: {}", metadataMap);

        String baseUrl = "https://hips.china-vo.org/generate";
        UriComponentsBuilder builder = UriComponentsBuilder.fromHttpUrl(baseUrl)
                .queryParam("dataset_name", metadata.getDataset_name())
                .queryParam("format", datatype)
                .queryParam("ra", metadata.getRa())
                .queryParam("dec", metadata.getDec())
                .queryParam("fov", metadata.getFov())
                .queryParam("width", metadata.getWidth())
                .queryParam("height", metadata.getHeight());

        String url = builder.toUriString();
        logger.info("Request URL: {}", url);

        HttpHeaders headers = new HttpHeaders();
        headers.set("Authorization", "Bearer " + this.token);
        headers.set("User-Agent", "Java-Spring RestClient");
        HttpEntity<String> entity = new HttpEntity<>(headers);

        try {
            ResponseEntity<String> response = restTemplate.exchange(
                    url,
                    HttpMethod.GET,
                    entity,
                    String.class
            );
            if (response.getStatusCode().value() != 200) {
                logger.error("Failed to generate image: HTTP Status {}", response.getStatusCode().value());
                throw new IOException("Failed to generate image: " + response.getStatusCode().value());
            }
            JsonNode jsonResponse = objectMapper.readTree(response.getBody());
            String imagePath = jsonResponse.path("image_path").asText();
            if (imagePath.isEmpty()) {
                logger.error("Failed to retrieve image path from response.");
                throw new IOException("Failed to retrieve image path from response.");
            }
            String locationHeader = response.getHeaders().getLocation() != null ? response.getHeaders().getLocation().toString() : null;
            if (locationHeader != null) {
                logger.info("Redirected to: {}", locationHeader);
                imagePath = locationHeader;
            }
            ResponseEntity<byte[]> imageResponse = restTemplate.exchange(
                    imagePath,
                    HttpMethod.GET,
                    entity,
                    byte[].class
            );
            if (imageResponse.getStatusCode().value() != 200) {
                String errorMessage = new String(imageResponse.getBody(), StandardCharsets.UTF_8);
                logger.error("Failed to download image/fits: {} - {}", imageResponse.getStatusCode().value(), errorMessage);
                throw new IOException("Failed to download image/fits: " + errorMessage);
            }
            byte[] imageContent = imageResponse.getBody();
            if (imageContent == null || imageContent.length == 0) {
                throw new IOException("Failed to download image/fits content. The response body is empty.");
            }
            try (FileOutputStream fos = new FileOutputStream(output)) {
                fos.write(imageContent);
                logger.info("Downloaded image/fits size: {} bytes", imageContent.length);
            }
        } catch (HttpClientErrorException | HttpServerErrorException e) {
            logger.error("HTTP error during image/fits download: {} - {}", e.getStatusCode(), e.getResponseBodyAsString());
            throw new IOException("HTTP error during image/fits download: " + e.getMessage(), e);
        } catch (Exception e) {
            logger.error("Error during image/fits download", e);
            throw new IOException("Error during image/fits download: " + e.getMessage(), e);
        }
    }

    @Override
    public boolean authorized() {
        return !token.isEmpty();
    }

    @Override
    public String[] getDatatypes() {
        return new String[]{"PNG", "FITS"};
    }

    public String[] getDatasets() {
        String url = "https://hips.china-vo.org/generate/list-dataset";
        return restTemplate.getForObject(url, String[].class);
    }
}
