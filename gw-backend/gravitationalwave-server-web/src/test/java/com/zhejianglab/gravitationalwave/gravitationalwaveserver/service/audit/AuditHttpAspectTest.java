package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.audit;

import jakarta.servlet.http.HttpServletRequest;
import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.Signature;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import java.time.Instant;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.nullable;
import static org.mockito.Mockito.lenient;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * R6.67.x: Unit tests for AuditHttpAspect.
 *
 * Pure unit test: no @SpringBootTest context (Mongo/ES would need to be up).
 * We mock the AuditService and HttpServletRequest directly, bind the
 * servlet context via RequestContextHolder, and exercise the @Around advice
 * with a stubbed ProceedingJoinPoint.
 */
@ExtendWith(MockitoExtension.class)
class AuditHttpAspectTest {

    @Mock
    private AuditService auditService;

    @Mock
    private ProceedingJoinPoint pjp;

    @Mock
    private Signature signature;

    @InjectMocks
    private AuditHttpAspect aspect;

    @BeforeEach
    void setUp() {
        // These are only consulted when log.isDebugEnabled() is true in the
        // no-servlet-request branch; mark them lenient so Mockito's strict
        // stub policy doesn't complain on tests that don't hit that path.
        lenient().when(pjp.getSignature()).thenReturn(signature);
        lenient().when(signature.toString()).thenReturn("MockJoinPoint");
    }

    @Test
    void recordsSuccessfulCallAs200() throws Throwable {
        MockHttpServletRequest req = new MockHttpServletRequest("GET", "/api/auth/login");
        req.setRemoteAddr("10.1.2.3");
        req.addHeader("User-Agent", "Mozilla/5.0");
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(req));

        when(pjp.proceed()).thenReturn("ok");

        Object result = aspect.auditHttpCall(pjp);
        assertEquals("ok", result);

        ArgumentCaptor<String> method = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<String> uri = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<String> ip = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<String> ua = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<Integer> status = ArgumentCaptor.forClass(Integer.class);
        ArgumentCaptor<Long> elapsed = ArgumentCaptor.forClass(Long.class);

        verify(auditService, times(1)).recordHttpCall(
                method.capture(),
                uri.capture(),
                ip.capture(),
                ua.capture(),
                status.capture(),
                elapsed.capture(),
                any(Instant.class)
        );

        assertEquals("GET", method.getValue());
        assertEquals("/api/auth/login", uri.getValue());
        assertEquals("10.1.2.3", ip.getValue());
        assertEquals("Mozilla/5.0", ua.getValue());
        assertEquals(Integer.valueOf(200), status.getValue());
        assertEquals(true, elapsed.getValue() >= 0L);

        RequestContextHolder.resetRequestAttributes();
    }

    @Test
    void recordsFailedCallAs500() throws Throwable {
        MockHttpServletRequest req = new MockHttpServletRequest("POST", "/api/auth/login");
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(req));

        when(pjp.proceed()).thenThrow(new RuntimeException("boom"));

        RuntimeException thrown = assertThrows(RuntimeException.class,
                () -> aspect.auditHttpCall(pjp));
        assertEquals("boom", thrown.getMessage());

        verify(auditService, times(1)).recordHttpCall(
                eq("POST"), eq("/api/auth/login"),
                anyString(), nullable(String.class), eq(500), anyLong(), any(Instant.class));

        RequestContextHolder.resetRequestAttributes();
    }

    @Test
    void skipsAuditWhenNoServletRequest() throws Throwable {
        // No RequestContextHolder binding => currentRequest() returns null.
        RequestContextHolder.resetRequestAttributes();

        when(pjp.proceed()).thenReturn("ok");

        Object result = aspect.auditHttpCall(pjp);
        assertEquals("ok", result);

        verify(auditService, never()).recordHttpCall(
                anyString(), anyString(), anyString(), anyString(),
                anyInt(), anyLong(), any(Instant.class));
    }

    @Test
    void auditFailureDoesNotPropagate() throws Throwable {
        MockHttpServletRequest req = new MockHttpServletRequest("GET", "/api/x");
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(req));

        when(pjp.proceed()).thenReturn("ok");
        // Simulate audit service throwing - this must NOT escape the advice.
        org.mockito.Mockito.doThrow(new RuntimeException("audit-fail"))
                .when(auditService).recordHttpCall(
                        anyString(), anyString(), anyString(), anyString(),
                        anyInt(), anyLong(), any(Instant.class));

        // The advice must complete normally (or at least not re-throw audit-fail).
        try {
            Object result = aspect.auditHttpCall(pjp);
            assertEquals("ok", result);
        } catch (RuntimeException e) {
            // If a RuntimeException leaks, it must be 'boom', NOT 'audit-fail'.
            assertEquals(true, !"audit-fail".equals(e.getMessage()),
                    "audit failures must be swallowed, got: " + e.getMessage());
        }

        RequestContextHolder.resetRequestAttributes();
    }

}
