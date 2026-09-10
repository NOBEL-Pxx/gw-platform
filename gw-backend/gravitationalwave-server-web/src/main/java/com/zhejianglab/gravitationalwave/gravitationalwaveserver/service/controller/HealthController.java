package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.controller;

import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.response.Response;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.mongodb.core.MongoTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * R6.80: public-facing health check.
 *
 * <p>Returns a user-visible subset of /actuator/health:
 * <ul>
 *   <li>status: aggregated UP / DOWN</li>
 *   <li>version: app.version from version.properties (R6.80 addition)</li>
 *   <li>timestamp: ISO instant</li>
 *   <li>components: { app, elasticsearch, mongo } each with status + latency_ms</li>
 * </ul>
 *
 * <p>Excluded from RateLimitInterceptor + AuthInterceptor in WebMvcConfig
 * so it can be polled freely by external monitoring without consuming
 * the bucket4j quota or requiring JWT auth.
 *
 * <p>Why this exists:
 * <ul>
 *   <li>/actuator/health already returns 200 UP but exposes internal details
 *       (diskSpace path, ES cluster internals, ssl chains). Some external
 *       monitors want a leaner public surface.</li>
 *   <li>Earlier R6.102 bug "0 is wrong value for period tokens" was masking the absence
 *       of any /api/health controller. Now it's explicit.</li>
 * </ul>
 *
 * <p>R6.80 changes:
 * <ul>
 *   <li>Added {@code version} field at top level (read from {@code app.version} PropertySource;
 *       defaults to {@code "unknown"} if version.properties is not on the Spring PropertySource chain).</li>
 *   <li>Mongo probe now uses {@code estimatedDocumentCount()} (collection-level metadata query,
 *       no admin privileges required, bounded latency) instead of {@code executeCommand("{ping:1}")}.</li>
 *   <li>All probes wrapped in {@code checkComponent()} helper that catches exceptions per component
 *       so one failing probe does not short-circuit the others.</li>
 *   <li>Probe timeouts bounded by MongoConfig R6.80 socket/connect timeouts (5s/10s).</li>
 * </ul>
 */
@RestController
@RequestMapping("/api/health")
public class HealthController {

    private static final Logger log = LoggerFactory.getLogger(HealthController.class);

    @Autowired(required = false)
    private MongoTemplate mongoTemplate;

    @Autowired(required = false)
    private co.elastic.clients.elasticsearch.ElasticsearchClient elasticsearchClient;

    /** R6.80: read app.version from version.properties (set by R6.72 groovy-maven-plugin). */
    @Value("${app.version:unknown}")
    private String appVersion;

    @GetMapping
    public Response<Map<String, Object>> health() {
        Map<String, Object> components = new LinkedHashMap<>();
        components.put("app", componentStatus("app", true, null));

        components.put("elasticsearch", checkComponent("elasticsearch", () -> {
            if (elasticsearchClient == null) {
                return false;
            }
            try {
                // cluster.health() returns ClusterHealthResponse with status field (green/yellow/red)
                // We map any non-red status to UP. ~5-10ms over local network.
                String esStatus = elasticsearchClient.cluster().health().status().jsonValue().toString();
                return !"red".equalsIgnoreCase(esStatus);
            } catch (Exception ex) {
                log.warn("elasticsearch health probe failed: {}", ex.getMessage());
                return false;
            }
        }));

        components.put("mongo", checkComponent("mongo", () -> {
            if (mongoTemplate == null) {
                return false;
            }
            try {
                // R6.80: estimatedDocumentCount() on the database's main collection —
                // collection-level metadata query, no admin privileges required, bounded
                // latency by MongoConfig R6.80 socket/connect timeouts (5s/10s).
                Long n = mongoTemplate.getCollection(mongoTemplate.getDb().getName())
                        .estimatedDocumentCount();
                return n != null;
            } catch (Exception ex) {
                log.warn("mongo probe failed: {}", ex.getMessage());
                return false;
            }
        }));

        boolean allUp = components.values().stream()
                .allMatch(v -> v instanceof Map && "UP".equals(((Map<?, ?>) v).get("status")));

        Map<String, Object> data = new LinkedHashMap<>();
        data.put("status", allUp ? "UP" : "DOWN");
        data.put("version", appVersion);
        data.put("timestamp", Instant.now().toString());
        data.put("components", components);

        return Response.wrapSuccess(data);
    }

    /** Returns a static UP component (no probe). */
    private static Map<String, Object> componentStatus(String name, boolean up, Long latencyMs) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("status", up ? "UP" : "DOWN");
        if (latencyMs != null) {
            m.put("latency_ms", latencyMs);
        }
        return m;
    }

    /** Probe callback wrapper: measures elapsed millis + catches exceptions to DOWN. */
    private Map<String, Object> checkComponent(String name, java.util.function.BooleanSupplier probe) {
        long t0 = System.currentTimeMillis();
        boolean up = false;
        String detail = "";
        try {
            up = probe.getAsBoolean();
        } catch (Exception ex) {
            detail = ex.getClass().getSimpleName();
            log.warn("{} health probe failed: {}", name, ex.getMessage());
        }
        long elapsed = System.currentTimeMillis() - t0;
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("status", up ? "UP" : "DOWN");
        m.put("latency_ms", elapsed);
        if (!up && !detail.isEmpty()) {
            m.put("detail", detail);
        }
        return m;
    }
}