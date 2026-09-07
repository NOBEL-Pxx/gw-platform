package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.audit;

import jakarta.servlet.http.HttpServletRequest;
import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.aspectj.lang.annotation.Pointcut;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import java.time.Duration;
import java.time.Instant;

/**
 * R6.67.x: AuditHttpAspect - intercepts every public method on every
 *          @RestController bean and forwards a one-line summary to
 *          AuditService.recordHttpCall(...), which POSTs to gw-pipeline's
 *          /pipeline/audit/ingest (R6.67.4).
 *
 * Design notes:
 *   - Pointcut is on the TYPE annotated with @RestController (not @RequestMapping),
 *     so we don't double-fire on methods that themselves have @RequestMapping
 *     annotations (which are themselves @RestController by transitivity).
 *   - The advice runs in a finally{} so:
 *       1. We always emit one event per incoming request.
 *       2. The AuditService call NEVER affects the controller's response
 *          (failures are swallowed by AuditService internally and counted).
 *   - HttpServletRequest is pulled from RequestContextHolder; falls back
 *     gracefully to null (no-op) if invoked outside an HTTP request context
 *     (e.g., a scheduled task that also happens to be a @RestController method,
 *     which we don't have today but defensive coding doesn't hurt).
 */
@Aspect
@Component
public class AuditHttpAspect {

    private static final Logger log = LoggerFactory.getLogger(AuditHttpAspect.class);

    private final AuditService auditService;

    public AuditHttpAspect(AuditService auditService) {
        this.auditService = auditService;
    }

    /**
     * All methods (any visibility, any signature) on any bean that is annotated
     * with @RestController. Using within() ensures we don't match the
     * @RestController annotation on inner methods (a small Spring AOP gotcha).
     */
    @Pointcut("within(@org.springframework.web.bind.annotation.RestController *)")
    public void restControllerMethods() {}

    @Around("restControllerMethods()")
    public Object auditHttpCall(ProceedingJoinPoint pjp) throws Throwable {
        Instant start = Instant.now();
        Object result = null;
        Throwable thrown = null;
        try {
            result = pjp.proceed();
            return result;
        } catch (Throwable t) {
            thrown = t;
            throw t;
        } finally {
            try {
                long elapsedMs = Duration.between(start, Instant.now()).toMillis();
                HttpServletRequest req = currentRequest();
                if (req != null) {
                    int status = thrown == null ? 200 : 500;
                    auditService.recordHttpCall(
                            req.getMethod(),
                            req.getRequestURI(),
                            req.getRemoteAddr(),
                            req.getHeader("User-Agent"),
                            status,
                            elapsedMs,
                            Instant.now()
                    );
                } else {
                    // Outside an HTTP request context - log once per call, don't spam.
                    if (log.isDebugEnabled()) {
                        log.debug("[AuditHttpAspect] no HttpServletRequest for {}", pjp.getSignature());
                    }
                }
            } catch (Exception e) {
                // Never let auditing failures propagate.
                log.warn("[AuditHttpAspect] audit recording failed: {}", e.getMessage());
            }
        }
    }

    private HttpServletRequest currentRequest() {
        try {
            ServletRequestAttributes attrs =
                    (ServletRequestAttributes) RequestContextHolder.getRequestAttributes();
            return attrs != null ? attrs.getRequest() : null;
        } catch (Exception e) {
            return null;
        }
    }
}
