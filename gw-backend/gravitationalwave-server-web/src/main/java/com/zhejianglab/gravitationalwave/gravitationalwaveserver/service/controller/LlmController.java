package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.controller;

import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.response.Response;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.ResponseErrorHandler;
import org.springframework.web.client.RestClient;

import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.LocalDate;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import java.time.Instant;

/**
 * LLM Proxy Controller — proxies AI chat requests to DeepSeek API.
 *
 * v4.12: Added query-fingerprint cache (identical astronomy queries skip API call),
 *        daily request quota, and usage statistics endpoint.
 *
 * <p><b>R6.98-D migration</b>: replaced {@code RestTemplate} with a DEDICATED
 * TLS-pinned {@link RestClient} bean (from {@code HttpClientConfig.llmRestClient()}).
 * The LLM channel is isolated from the shared client because api.deepseek.com
 * requires SPKI SHA-256 pinning via {@code TlsPinningHttpClientFactory} —
 * pinning must not bleed into other consumers.
 *
 * <p><b>Iron rules applied</b>:
 * <ul>
 *   <li><b>R6.98-A</b>: all outbound HTTP MUST use a Spring-managed {@link RestClient}
 *       bean — no ad-hoc {@code new RestTemplate()} per-service. LlmController
 *       uses a dedicated {@code llmRestClient} bean (TLS-pinned).</li>
 *   <li><b>R6.98-B</b> (response variant): upstream response MUST have
 *       {@code Content-Type: application/json}. HTML error pages from a CDN
 *       or misconfigured proxy MUST be rejected (returns 0500). Otherwise
 *       {@code Map.class} parsing would throw {@code HttpMessageNotReadableException}
 *       deep in Spring and mask the real failure.</li>
 * </ul>
 */
@RestController
@RequestMapping("/api/llm")
public class LlmController {

    private static final Logger auditLog = LoggerFactory.getLogger("llm-audit");
    private static final Logger log = LoggerFactory.getLogger(LlmController.class);

    @Value("${deepseek.api.key:}")
    private String apiKey;

    @Value("${deepseek.api.url:https://api.deepseek.com/v1/chat/completions}")
    private String apiUrl;

    @Value("${deepseek.api.model:deepseek-chat}")
    private String model;

    @Value("${deepseek.api.daily-quota:500}")
    private int dailyQuota;

    @Value("${deepseek.api.cache-ttl-minutes:30}")
    private int cacheTtlMinutes;

    /**
     * R6.98-D: dedicated TLS-pinned {@link RestClient} bean (from
     * {@code HttpClientConfig.llmRestClient()}). Replaces the per-instance
     * {@code RestTemplate} previously constructed here.
     */
    private final RestClient restClient;

    // ── Query cache (fingerprint → response) ──
    private final ConcurrentHashMap<String, CacheEntry> queryCache = new ConcurrentHashMap<>();

    // ── Daily usage tracking ──
    private volatile LocalDate currentDate = LocalDate.now();
    private final AtomicInteger dailyCount = new AtomicInteger(0);

    private static class CacheEntry {
        final Map<String, Object> response;
        final long expiresAt;
        CacheEntry(Map<String, Object> r, long ttlMs) {
            this.response = r;
            this.expiresAt = System.currentTimeMillis() + ttlMs;
        }
        boolean isExpired() { return System.currentTimeMillis() > expiresAt; }
    }

    /** Write an audit log entry for each LLM request. */
    private void audit(String outcome, String fingerprint, String queryPreview, long latencyMs) {
        auditLog.info("outcome={} fp={} latency_ms={} query_preview=[{}]",
            outcome, fingerprint, latencyMs, queryPreview);
    }

    /**
     * R6.98-D constructor: injects the dedicated TLS-pinned {@link RestClient}
     * bean. Spring auto-injects from {@code HttpClientConfig.llmRestClient()}.
     */
    public LlmController(RestClient llmRestClient) {
        this.restClient = llmRestClient;
    }

    /**
     * R6.98-D: init marker. Logs that the dedicated llmRestClient bean is wired.
     * The TLS pinning itself is logged by {@code TlsPinningHttpClientFactory.build()}
     * when the bean is constructed (see {@code HttpClientConfig.llmRestClient()}).
     */
    @PostConstruct
    public void init() {
        log.info("R6.98-D: LlmController RestClient initialized (dedicated bean for api.deepseek.com)");
        if (apiKey == null || apiKey.isEmpty()) {
            log.warn("LlmController: deepseek.api.key is not configured");
        } else {
            log.info("LlmController: DeepSeek API configured. Model={}, daily-quota={}, cache-ttl={}min",
                model, dailyQuota, cacheTtlMinutes);
        }
    }

    @PreDestroy
    public void shutdown() {
        log.info("R6.85b: LlmController shutdown complete");
    }

    /** Compute a SHA-256 fingerprint of the messages array for cache lookup. */
    private String fingerprint(List<Map<String, String>> messages) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            for (Map<String, String> m : messages) {
                md.update(Objects.toString(m.get("role"), "").getBytes(StandardCharsets.UTF_8));
                md.update(Objects.toString(m.get("content"), "").getBytes(StandardCharsets.UTF_8));
            }
            byte[] hash = md.digest();
            StringBuilder sb = new StringBuilder();
            for (byte b : hash) sb.append(String.format("%02x", b));
            return sb.toString();
        } catch (NoSuchAlgorithmException e) {
            return String.valueOf(Objects.hash(messages.toString()));
        }
    }

    /** Reset daily counter if the date changed. */
    private synchronized void rollDaily() {
        LocalDate today = LocalDate.now();
        if (!today.equals(currentDate)) {
            currentDate = today;
            dailyCount.set(0);
        }
    }

    @PostMapping("/chat")
    public Response<Map<String, Object>> chat(@RequestBody Map<String, Object> request) {
        // R6.85b R6.83-D iron rule: null-guard against @PostConstruct failure (returns 503 not NPE).
        if (restClient == null) {
            return Response.wrapError("0503", "LLM service not initialized — please retry in a moment");
        }
        rollDaily();

        if (apiKey == null || apiKey.isEmpty()) {
            return Response.wrapError("0500", "LLM service not configured: missing API key");
        }

        @SuppressWarnings("unchecked")
        List<Map<String, String>> messages = (List<Map<String, String>>) request.get("messages");
        if (messages == null || messages.isEmpty()) {
            return Response.wrapError("0400", "Missing 'messages' field in request body");
        }

        // ── Daily quota check ──
        if (dailyCount.get() >= dailyQuota) {
            return Response.wrapError("0429",
                String.format("Daily LLM request quota exceeded (%d/%d). Resets at midnight UTC.",
                    dailyCount.get(), dailyQuota));
        }

        // ── Query cache check ──
        String fp = fingerprint(messages);
        CacheEntry cached = queryCache.get(fp);
        if (cached != null && !cached.isExpired()) {
            dailyCount.incrementAndGet();
            Map<String, Object> result = new HashMap<>(cached.response);
            result.put("cached", true);
            String preview = messages.size() > 0 ? messages.get(messages.size()-1).getOrDefault("content","") : "";
            audit("CACHE_HIT", fp, preview.length() > 200 ? preview.substring(0,200)+"..." : preview, 0);
            return Response.wrapSuccess(result);
        }
        // Periodic cache cleanup (lazy, on miss)
        if (queryCache.size() > 1000) {
            queryCache.entrySet().removeIf(e -> e.getValue().isExpired());
        }

        try {
            // Build DeepSeek API request body
            Map<String, Object> deepseekBody = new HashMap<>();
            deepseekBody.put("model", model);
            deepseekBody.put("messages", messages);
            deepseekBody.put("temperature", 0.7);
            deepseekBody.put("max_tokens", 2000);
            deepseekBody.put("stream", false);

            // R6.98-D: call via dedicated TLS-pinned RestClient bean.
            // Default retrieve() behavior throws on 4xx/5xx — we catch and map below.
            long t0 = System.currentTimeMillis();
            ResponseEntity<Map> response = restClient.post()
                .uri(apiUrl)
                .headers(h -> {
                    h.set("Authorization", "Bearer " + apiKey);
                    h.setContentType(MediaType.APPLICATION_JSON);
                })
                .body(deepseekBody)
                .retrieve()
                .toEntity(Map.class);
            long latency = System.currentTimeMillis() - t0;

            // R6.98-B (response variant): Content-Type guard. Reject HTML error
            // pages masquerading as 200 OK before attempting to parse as Map.
            MediaType ct = response.getHeaders().getContentType();
            if (ct == null || !ct.includes(MediaType.APPLICATION_JSON)) {
                String preview = messages.size() > 0 ? messages.get(messages.size()-1).getOrDefault("content","") : "";
                audit("ERROR", fp, preview.length() > 200 ? preview.substring(0,200)+"..." : preview, latency);
                log.warn("R6.98-D: rejected non-JSON Content-Type from DeepSeek: {}", ct);
                return Response.wrapError("0500",
                    "Unexpected response content-type from LLM API: " + ct
                    + " (expected application/json)");
            }

            Map<String, Object> result = new HashMap<>();
            if (response.getBody() != null) {
                @SuppressWarnings("unchecked")
                List<Map<String, Object>> choices = (List<Map<String, Object>>) response.getBody().get("choices");
                if (choices != null && !choices.isEmpty()) {
                    @SuppressWarnings("unchecked")
                    Map<String, Object> message = (Map<String, Object>) choices.get(0).get("message");
                    if (message != null) {
                        result.put("content", message.get("content"));
                        result.put("model", model);
                        result.put("cached", false);

                        // Cache the response
                        queryCache.put(fp, new CacheEntry(
                            new HashMap<>(result), cacheTtlMinutes * 60_000L));

                        dailyCount.incrementAndGet();
                        String preview = messages.size() > 0 ? messages.get(messages.size()-1).getOrDefault("content","") : "";
                        audit("SUCCESS", fp, preview.length() > 200 ? preview.substring(0,200)+"..." : preview, latency);
                        return Response.wrapSuccess(result);
                    }
                }
            }

            String preview = messages.size() > 0 ? messages.get(messages.size()-1).getOrDefault("content","") : "";
            audit("EMPTY_RESPONSE", fp, preview.length() > 200 ? preview.substring(0,200)+"..." : preview, latency);
            return Response.wrapError("0502", "Empty response from LLM API — please try again or rephrase your query");

        } catch (HttpClientErrorException e) {
            String msg = e.getMessage();
            String preview = messages.size() > 0 ? messages.get(messages.size()-1).getOrDefault("content","") : "";
            if (e.getStatusCode().value() == 401 || (msg != null && msg.contains("401"))) {
                audit("AUTH_FAILURE", fp, preview.length() > 200 ? preview.substring(0,200)+"..." : preview, 0);
                return Response.wrapError("0501", "LLM API authentication failed — check API key configuration. You can still use Keyword mode for offline analysis.");
            }
            if (e.getStatusCode().value() == 429 || (msg != null && msg.contains("429"))) {
                audit("RATE_LIMITED", fp, preview.length() > 200 ? preview.substring(0,200)+"..." : preview, 0);
                return Response.wrapError("0429", "LLM API rate limit exceeded — please wait a moment. Try Keyword mode for immediate offline analysis.");
            }
            audit("ERROR", fp, preview.length() > 200 ? preview.substring(0,200)+"..." : preview, 0);
            return Response.wrapError("0500", "LLM API error (" + e.getStatusCode().value() + "): "
                + (msg != null ? msg : "unknown") + ". Try Keyword mode for offline analysis.");
        } catch (ResourceAccessException e) {
            String msg = e.getMessage();
            String preview = messages.size() > 0 ? messages.get(messages.size()-1).getOrDefault("content","") : "";
            // Network errors (timeout, unreachable, DNS) → offline suggestion.
            // Match BOTH "timeout" (Spring wrapper) AND "timed out" (raw IOException message).
            String lower = msg == null ? "" : msg.toLowerCase();
            if (lower.contains("timeout") || lower.contains("timed out")
                    || lower.contains("refused") || lower.contains("unknownhost")
                    || lower.contains("unreachable") || lower.contains("i/o error")) {
                audit("OFFLINE", fp, preview.length() > 200 ? preview.substring(0,200)+"..." : preview, 0);
                return Response.wrapError("0503", "LLM service is currently unreachable (network or API outage). You can use Keyword mode for offline analysis. The AI assistant will automatically resume when connectivity is restored.");
            }
            audit("ERROR", fp, preview.length() > 200 ? preview.substring(0,200)+"..." : preview, 0);
            return Response.wrapError("0500", "LLM API error: " + (msg != null ? msg : "unknown") + ". Try Keyword mode for offline analysis.");
        } catch (Exception e) {
            String msg = e.getMessage();
            String preview = messages.size() > 0 ? messages.get(messages.size()-1).getOrDefault("content","") : "";
            // Network errors (timeout, unreachable, DNS) → offline suggestion.
            // Match BOTH "timeout" (Spring wrapper) AND "timed out" (raw IOException message).
            String lower = msg == null ? "" : msg.toLowerCase();
            if (lower.contains("timeout") || lower.contains("timed out")
                    || lower.contains("refused") || lower.contains("unknownhost")
                    || lower.contains("unreachable") || lower.contains("i/o error")) {
                audit("OFFLINE", fp, preview.length() > 200 ? preview.substring(0,200)+"..." : preview, 0);
                return Response.wrapError("0503", "LLM service is currently unreachable (network or API outage). You can use Keyword mode for offline analysis. The AI assistant will automatically resume when connectivity is restored.");
            }
            audit("ERROR", fp, preview.length() > 200 ? preview.substring(0,200)+"..." : preview, 0);
            return Response.wrapError("0500", "LLM API error: " + (msg != null ? msg : "unknown") + ". Try Keyword mode for offline analysis.");
        }
    }

    /** Health check — returns API configuration status (masked key). */
    @GetMapping("/status")
    public Response<Map<String, Object>> status() {
        Map<String, Object> status = new HashMap<>();
        boolean configured = apiKey != null && !apiKey.isEmpty();
        status.put("configured", configured);
        status.put("model", model);
        if (configured && apiKey.length() >= 8) {
            status.put("keyPreview", apiKey.substring(0, 7) + "...");
        }
        return Response.wrapSuccess(status);
    }

    /** Usage statistics — daily count, quota, cache size. */
    @GetMapping("/usage")
    public Response<Map<String, Object>> usage() {
        rollDaily();
        Map<String, Object> stats = new HashMap<>();
        stats.put("dailyCount", dailyCount.get());
        stats.put("dailyQuota", dailyQuota);
        stats.put("dailyRemaining", Math.max(0, dailyQuota - dailyCount.get()));
        stats.put("cacheEntries", queryCache.size());
        stats.put("cacheTtlMinutes", cacheTtlMinutes);
        stats.put("model", model);
        return Response.wrapSuccess(stats);
    }
}
