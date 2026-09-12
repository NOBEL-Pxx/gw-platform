package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.config;

import io.micrometer.core.instrument.MeterRegistry;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;
import org.springframework.web.servlet.HandlerMapping;

import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;

/**
 * R6.90 B2: MetricsInterceptor — counter + timer for production controller requests.
 *
 * <p>Applied to the 3 production controllers per the R6.90 B2 spec:
 * StaticFileController, SearchController, ImageCutoutController. Tags each metric
 * with {@code controller=<ClassName>}, {@code uri=<URL pattern>}, {@code method=<GET|POST>},
 * {@code status=<code>}. Exposed via {@code /actuator/metrics/http.server.requests}.
 *
 * <h3>Why a HandlerInterceptor (not @Timed annotation on each method)</h3>
 * <ul>
 *   <li>3 controllers x N public methods = many @Timed annotations; interceptor
 *       applies uniformly to all paths under the registered patterns.</li>
 *   <li>The interceptor records both the timer AND the counter, with consistent
 *       tag names, without per-method boilerplate.</li>
 *   <li>Easy to extend to additional controllers via the WebMvcConfig pattern list.</li>
 * </ul>
 *
 * <h3>URI tag uses URL pattern (R6.90 security fix)</h3>
 * Uses {@link HandlerMapping#BEST_MATCHING_PATTERN_ATTRIBUTE} instead of
 * {@code request.getRequestURI()}. The pattern (e.g., {@code /static-files/fits/**})
 * is bounded — same pattern regardless of path-variable values. Raw URI was a
 * Prometheus cardinality bomb: an attacker could craft many unique paths and
 * create 1M+ unique time-series, blowing up TSDB. (R6.90 security review M1.)
 *
 * <h3>Why not Spring Boot Actuator's built-in HttpRequestsMetric</h3>
 * Spring Boot Actuator's default {@code http.server.requests} timer already uses
 * the URL pattern correctly. Our interceptor DUPLICATES that with explicit
 * controller + counter tagging. The default timer still runs in parallel via
 * {@code WebMvcMetricsFilter}.
 *
 * <p>Iron rule R6.90-B: production controller metrics MUST be tagged with a stable
 * {@code controller} class-name tag AND a stable {@code uri} URL-pattern tag
 * (NOT the raw URI, which is too high-cardinality for Prometheus).
 */
@Component
public class MetricsInterceptor implements HandlerInterceptor {

    private static final Logger log = LoggerFactory.getLogger(MetricsInterceptor.class);

    private static final String START_TIME_ATTR = "r690.metrics.startTime";
    private static final String CONTROLLER_NAME_ATTR = "r690.metrics.controllerName";

    private final MeterRegistry registry;

    /** Cache to avoid recomputing tag names per request. */
    private final ConcurrentHashMap<String, String> tagCache = new ConcurrentHashMap<>();

    public MetricsInterceptor(MeterRegistry registry) {
        this.registry = registry;
    }

    @Override
    public boolean preHandle(HttpServletRequest req, HttpServletResponse res, Object handler) {
        req.setAttribute(START_TIME_ATTR, System.nanoTime());
        if (handler instanceof org.springframework.web.method.HandlerMethod hm) {
            String name = hm.getBeanType().getSimpleName();
            tagCache.computeIfAbsent(name, k -> k);
            req.setAttribute(CONTROLLER_NAME_ATTR, name);
        } else {
            req.setAttribute(CONTROLLER_NAME_ATTR, "unknown");
        }
        return true;
    }

    @Override
    public void afterCompletion(HttpServletRequest req, HttpServletResponse res,
                                 Object handler, Exception ex) {
        Long startNs = (Long) req.getAttribute(START_TIME_ATTR);
        if (startNs == null) return;
        long elapsedNs = System.nanoTime() - startNs;

        String controller = (String) req.getAttribute(CONTROLLER_NAME_ATTR);
        if (controller == null) controller = "unknown";
        // R6.90 security fix M1: use URL pattern (e.g., "/static-files/fits/**"), NOT
        // the raw request URI. Pattern is bounded regardless of path-variable values.
        // Falls back to "unknown" if Spring did not set the attribute (e.g., 404).
        Object patternObj = req.getAttribute(HandlerMapping.BEST_MATCHING_PATTERN_ATTRIBUTE);
        String uri = patternObj instanceof String ? (String) patternObj : "unknown";
        String method = req.getMethod();
        String status = String.valueOf(res.getStatus());

        try {
            // Counter — request count by controller + uri + method + status
            registry.counter(
                "r690.controller.requests",
                "controller", controller,
                "uri", uri,
                "method", method,
                "status", status
            ).increment();

            // Timer — request latency (seconds) by controller + uri + method
            registry.timer(
                "r690.controller.latency",
                "controller", controller,
                "uri", uri,
                "method", method
            ).record(elapsedNs, TimeUnit.NANOSECONDS);
        } catch (Exception e) {
            // Never let metrics break the request path. Log + swallow.
            log.warn("MetricsInterceptor failed: {}", e.getMessage());
        }
    }
}
