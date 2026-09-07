package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.audit;

import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.HttpStatusCodeException;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestTemplate;

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

    private final RestTemplate restTemplate;

    /** Records dropped because BACKEND_AUDIT_TOKEN is not configured. */
    private final AtomicLong droppedDisabled = new AtomicLong(0);
    /** Records dropped because the POST failed (network / non-2xx). */
    private final AtomicLong droppedFailed = new AtomicLong(0);
    /** Records accepted by the pipeline (HTTP 2xx response). */
    private final AtomicLong sentOk = new AtomicLong(0);

    public AuditService() {
        // RestTemplate and its request factory are constructed here; timeout
        // values are bound from @Value AFTER this constructor returns, so we
        // apply them in init() (a @PostConstruct method below).
        this.restTemplate = new RestTemplate();
    }

    @PostConstruct
    public void init() {
        // Apply timeouts now that @Value fields have been injected.
        SimpleClientHttpRequestFactory rf =
                (SimpleClientHttpRequestFactory) this.restTemplate.getRequestFactory();
        rf.setConnectTimeout(timeoutMs);
        rf.setReadTimeout(timeoutMs);

        if (auditToken == null || auditToken.isEmpty()) {
            log.warn("[AuditService] backend.audit.token is EMPTY - audit ingest is DISABLED (fail-closed)");
        } else {
            log.info("[AuditService] audit ingest enabled -> {} (timeout={}ms)", auditUrl, timeoutMs);
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

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.set("X-Audit-Token", auditToken);

        HttpEntity<Map<String, Object>> entity = new HttpEntity<>(body, headers);

        try {
            ResponseEntity<String> resp = restTemplate.exchange(
                    auditUrl, HttpMethod.POST, entity, String.class);
            sentOk.incrementAndGet();
            if (log.isDebugEnabled()) {
                log.debug("[AuditService] {} {} -> {} (status={})",
                        method, uri, auditUrl, resp.getStatusCode());
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
