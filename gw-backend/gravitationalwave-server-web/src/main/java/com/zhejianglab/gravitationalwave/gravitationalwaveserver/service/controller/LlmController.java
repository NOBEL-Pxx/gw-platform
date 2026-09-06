package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.controller;

import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.response.Response;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestTemplate;

import jakarta.annotation.PostConstruct;
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
 */
@RestController
@RequestMapping("/api/llm")
public class LlmController {

    private static final Logger auditLog = LoggerFactory.getLogger("llm-audit");

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

    private final RestTemplate restTemplate = new RestTemplate();

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

    @PostConstruct
    public void init() {
        if (apiKey == null || apiKey.isEmpty()) {
            System.err.println("[LlmController] WARNING: deepseek.api.key is not configured!");
        } else {
            System.out.println("[LlmController] DeepSeek API configured. Model: " + model
                + ", daily-quota: " + dailyQuota + ", cache-ttl: " + cacheTtlMinutes + "min");
        }
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

            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            headers.set("Authorization", "Bearer " + apiKey);

            HttpEntity<Map<String, Object>> entity = new HttpEntity<>(deepseekBody, headers);

            // Call DeepSeek API
            long t0 = System.currentTimeMillis();
            ResponseEntity<Map> response = restTemplate.exchange(
                apiUrl, HttpMethod.POST, entity, Map.class
            );
            long latency = System.currentTimeMillis() - t0;

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

        } catch (Exception e) {
            String msg = e.getMessage();
            String preview = messages.size() > 0 ? messages.get(messages.size()-1).getOrDefault("content","") : "";
            if (msg != null && msg.contains("401")) {
                audit("AUTH_FAILURE", fp, preview.length() > 200 ? preview.substring(0,200)+"..." : preview, 0);
                return Response.wrapError("0501", "LLM API authentication failed — check API key configuration. You can still use Keyword mode for offline analysis.");
            }
            if (msg != null && msg.contains("429")) {
                audit("RATE_LIMITED", fp, preview.length() > 200 ? preview.substring(0,200)+"..." : preview, 0);
                return Response.wrapError("0429", "LLM API rate limit exceeded — please wait a moment. Try Keyword mode for immediate offline analysis.");
            }
            // Network errors (timeout, unreachable, DNS) → offline suggestion
            if (msg != null && (msg.contains("timeout") || msg.contains("refused") || msg.contains("UnknownHost") || msg.contains("unreachable"))) {
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
