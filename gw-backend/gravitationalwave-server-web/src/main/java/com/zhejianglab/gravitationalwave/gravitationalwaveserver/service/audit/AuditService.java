package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.audit;

import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.client.HttpStatusCodeException;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;

/**
 * R6.67.x: AuditService pushes gw-backend REST events to gw-pipeline's
 *          /pipeline/audit/ingest HTTP endpoint (added in commit 660e6fd,
 *          R6.67.4).
 *
 * Pipeline owns Mongo + indexes + TTL (R6.67.5); gw-backend just submits JSON
 * via HTTP. Authentication is via the shared BACKEND_AUDIT_TOKEN HMAC secret
 * in the X-Audit-Token header.
 *
 * Behavior:
 *   - Fail-closed: when backend.audit.token is empty, recordHttpCall() is a
 *     no-op with a counter so we can detect misconfiguration in production
 *     logs without flooding them.
 *   - Fire-and-forget: the caller (AuditHttpAspect) wraps in finally, so
 *     a slow / failing ingest NEVER blocks or fails the user-facing request.
 *     Errors are logged at WARN and counted for observability.
 *
 * The endpoint contract (see gw-pipeline routes_v437.py:audit_ingest):
 *   body must be a JSON object; arbitrary keys accepted.
 *   Pipeline defaults: source=backend, ingested_ts=now (ISO 8601).
 *
 * <p><b>R6.98-B migration</b>: replaced {@code RestTemplate} with the shared
 * {@link RestClient} bean from {@code HttpClientConfig}. Iron rule R6.98-A:
 * all outbound HTTP MUST use the shared {@code CloseableHttpClient} bean via
 * {@link RestClient} -- no ad-hoc {@code new RestTemplate()} per-service.
 */
@Service
public class AuditService {

    private static final Logger log = LoggerFactory.getLogger(AuditService.class);

    /** Upstream URL for the audit ingest endpoint. */
    @Value("${backend.audit.url:http://gw-pipeline:8200/pipeline/audit/ingest}")
    private String auditUrl;

    /** Shared HMAC token. Empty = endpoint disabled (fail-closed). */
    @Value("${backend.audit.token:}")
    private String auditToken;

    /** Timeout for the ingest POST. Short - fire-and-forget pattern. */
    @Value("${backend.audit.timeout-ms:3000}")
    private int timeoutMs;

    /**
     * R6.98-B: shared {@link RestClient} bean (from {@code HttpClientConfig}).
     * Replaces the per-instance {@code RestTemplate} previously constructed
     * in this service's constructor. Spring auto-injects from the
     * {@code sharedRestClient} bean.
     */
    private final RestClient restClient;

    /** Records dropped because BACKEND_AUDIT_TOKEN is not configured. */
    private final AtomicLong droppedDisabled = new AtomicLong(0);
    /** Records dropped because the POST failed (network / non-2xx). */
    private final AtomicLong droppedFailed = new AtomicLong(0);
    /** Records accepted by the pipeline (HTTP 2xx response). */
    private final AtomicLong sentOk = new AtomicLong(0);

    /**
     * R6.98-B: constructor injection of shared {@link RestClient} bean.
     * Replaces the prior {@code new RestTemplate()} pattern (R6.85b).
     */
    public AuditService(RestClient sharedRestClient) {
        this.restClient = sharedRestClient;
    }

    @PostConstruct
    public void init() {
        // The shared RestClient has timeouts configured at the HttpClient
        // level (connect=10s, response=30s per HttpClientConfig). The audit
        // endpoint is fire-and-forget so its inherent timeouts are acceptable.
        // The legacy {@code backend.audit.timeout-ms} setting is preserved
        // for backward compatibility (audit ops may reference it in runbooks)
        // but no longer applied per-call -- the shared pool governs.

        if (auditToken == null || auditToken.isEmpty()) {
            log.warn("[AuditService] backend.audit.token is EMPTY - audit ingest is DISABLED (fail-closed)");
        } else {
            log.info("[AuditService] audit ingest enabled -> {} (timeoutMs config={}ms; shared client connect=10000ms/response=30000ms)",
                    auditUrl, timeoutMs);
        }
    }

    /**
     * R6.67.x: record an HTTP call event. Called from AuditHttpAspect
     *          inside a finally so it never blocks the caller.
     *
     * @param method     HTTP method (GET/POST/PUT/DELETE/...)
     * @param uri        request URI (path only, no query)
     * @param ip         client IP (X-Forwarded-For aware via servlet API)
     * @param userAgent  raw User-Agent header (may be null)
     * @param status     HTTP response status; 200 on success, 500 on throw
     * @param elapsedMs  measured wall-clock latency of the controller method
     * @param ts         audit event timestamp (server clock, may be future-skewed)
     */
    public void recordHttpCall(String method, String uri, String ip, String userAgent,
                               int status, long elapsedMs, Instant ts) {
        // Fail-closed: if token missing, drop event silently with counter.
        if (auditToken == null || auditToken.isEmpty()) {
            long n = droppedDisabled.incrementAndGet();
            if (n == 1 || n % 1000 == 0) {
                log.warn("[AuditService] dropped audit event (token unset) total={}", n);
            }
            return;
        }

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("timestamp", ts != null ? ts.toString() : Instant.now().toString());
        body.put("method", method);
        body.put("request_path", uri);
        body.put("status_code", status);
        body.put("latency_ms", elapsedMs);
        if (ip != null) body.put("ip", ip);
        if (userAgent != null) body.put("user_agent", userAgent);

        // Mark source = backend so downstream consumers can filter.
        body.put("source", "backend");

        try {
            restClient.post()
                    .uri(auditUrl)
                    .header(HttpHeaders.CONTENT_TYPE, MediaType.APPLICATION_JSON_VALUE)
                    .header("X-Audit-Token", auditToken)
                    .body(body)
                    .retrieve()
                    .toBodilessEntity();
            sentOk.incrementAndGet();
            if (log.isDebugEnabled()) {
                log.debug("[AuditService] {} {} -> {} (sent_ok)", method, uri, auditUrl);
            }
        } catch (HttpStatusCodeException e) {
            long n = droppedFailed.incrementAndGet();
            String bodyStr = e.getResponseBodyAsString();
            log.warn("[AuditService] ingest non-2xx {} ({}). body={} dropped_total={}",
                    e.getStatusCode(), method + " " + uri,
                    bodyStr != null ? bodyStr.substring(0, Math.min(200, bodyStr.length())) : "(none)",
                    n);
        } catch (ResourceAccessException e) {
            long n = droppedFailed.incrementAndGet();
            if (n == 1 || n % 100 == 0) {
                log.warn("[AuditService] ingest unreachable {} {}: {} dropped_total={}",
                        method, uri, e.getMessage(), n);
            }
        } catch (Exception e) {
            long n = droppedFailed.incrementAndGet();
            log.error("[AuditService] unexpected error recording {} {}: {} dropped_total={}",
                    method, uri, e.getMessage(), n, e);
        }
    }

    /** Snapshot of counters for the Actuator / health endpoint if needed. */
    public Map<String, Long> counters() {
        Map<String, Long> out = new LinkedHashMap<>();
        out.put("sent_ok", sentOk.get());
        out.put("dropped_disabled", droppedDisabled.get());
        out.put("dropped_failed", droppedFailed.get());
        return out;
    }
}
