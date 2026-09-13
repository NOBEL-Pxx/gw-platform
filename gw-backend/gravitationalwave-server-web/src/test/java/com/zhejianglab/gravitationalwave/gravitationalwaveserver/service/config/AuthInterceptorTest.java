package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.config;

import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.auth.util.JwtUtil;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.auth.util.TokenBlacklist;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.response.ApiException;
import io.jsonwebtoken.Claims;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import java.lang.reflect.Field;
import java.util.Date;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * R6.97-A: unit tests for {@link AuthInterceptor} image-cutout write-protection.
 *
 * <p>Test goals (R6.97-A — closes JWT bypass on image-cutout endpoints):
 * <ol>
 *   <li>POST /api/app/gravitationalwave/image-cutout/auth WITHOUT Bearer token
 *       throws {@link ApiException#unauthorized} (was: silent access pre-R6.97-A)</li>
 *   <li>POST /api/app/gravitationalwave/image-cutout/download WITHOUT Bearer token
 *       throws {@link ApiException#unauthorized}</li>
 *   <li>GET /api/app/gravitationalwave/image-cutout/datasets WITHOUT Bearer token
 *       is allowed (read-only listing, public)</li>
 *   <li>POST /api/app/gravitationalwave/image-cutout/auth WITH valid Bearer token
 *       is allowed (currentUserId attribute injected)</li>
 *   <li>Pre-existing WRITE_PROTECTED_PREFIXES (comments/favorites/collections) still work
 *       — guards against regression during R6.97-A's WRITE_PROTECTED_PREFIXES extension</li>
 * </ol>
 *
 * <p>This test uses Mockito mocks for {@link JwtUtil} + {@link TokenBlacklist} +
 * reflection to inject them into the @Resource-decorated fields (no Spring context).
 * Mirrors the lightweight pattern established by {@code ActuatorIpWhitelistFilterTest}
 * (R6.95-C + R6.96-O3) and {@code ImageCutoutDataSetDownloadTest} (R6.96-O1).
 *
 * <p>Background: Pre-R6.97-A, {@code AuthInterceptor.WRITE_PROTECTED_PREFIXES} did
 * NOT include {@code /api/app/gravitationalwave/image-cutout}. A POST to
 * {@code /api/app/gravitationalwave/image-cutout/auth} (china-vo.org token exchange)
 * reached {@link com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.controller.ImageCutoutController#auth}
 * WITHOUT JWT validation, allowing the china-vo.org service-account credentials to be
 * initialized for an unauthenticated user. This test pins the fix so a future
 * "cleanup" cannot silently revert the protection.
 */
class AuthInterceptorTest {

    private AuthInterceptor interceptor;
    private JwtUtil jwtUtil;
    private TokenBlacklist tokenBlacklist;

    @BeforeEach
    void setUp() throws Exception {
        interceptor = new AuthInterceptor();
        jwtUtil = mock(JwtUtil.class);
        tokenBlacklist = mock(TokenBlacklist.class);

        // Reflection-inject @Resource fields (no Spring context).
        Field f1 = AuthInterceptor.class.getDeclaredField("jwtUtil");
        f1.setAccessible(true);
        f1.set(interceptor, jwtUtil);

        Field f2 = AuthInterceptor.class.getDeclaredField("tokenBlacklist");
        f2.setAccessible(true);
        f2.set(interceptor, tokenBlacklist);
    }

    private MockHttpServletRequest req(String method, String uri) {
        MockHttpServletRequest r = new MockHttpServletRequest(method, uri);
        r.setRequestURI(uri);
        return r;
    }

    private MockHttpServletResponse res() {
        return new MockHttpServletResponse();
    }

    @Test
    @DisplayName("R6.97-A #1: POST /image-cutout/auth WITHOUT token → ApiException.unauthorized")
    void imageCutoutAuthRequiresJwt() throws Exception {
        // jwtUtil.validateToken returns null for any token (or is not called when no header)
        when(jwtUtil.validateToken(anyString())).thenReturn(null);
        when(tokenBlacklist.isBlacklisted(anyString(), anyString(), anyLong())).thenReturn(false);

        MockHttpServletRequest r = req("POST", "/api/app/gravitationalwave/image-cutout/auth");
        MockHttpServletResponse resp = res();

        ApiException ex = assertThrows(ApiException.class,
            () -> interceptor.preHandle(r, resp, new Object()));
        // Iron rule: must be 401 (unauthorized), not 403 (forbidden) — no credentials at all
        assertEquals(401, ex.getHttpStatus(), "expected 401 unauthorized; got: " + ex.getHttpStatus());
        assertTrue(ex.getMessage().contains("Authentication required"),
            "message must mention auth required; got: " + ex.getMessage());
    }

    @Test
    @DisplayName("R6.97-A #2: POST /image-cutout/download WITHOUT token → ApiException.unauthorized")
    void imageCutoutDownloadRequiresJwt() throws Exception {
        when(jwtUtil.validateToken(anyString())).thenReturn(null);
        when(tokenBlacklist.isBlacklisted(anyString(), anyString(), anyLong())).thenReturn(false);

        MockHttpServletRequest r = req("POST", "/api/app/gravitationalwave/image-cutout/download");
        MockHttpServletResponse resp = res();

        ApiException ex = assertThrows(ApiException.class,
            () -> interceptor.preHandle(r, resp, new Object()));
        assertEquals(401, ex.getHttpStatus(),
            "expected 401 unauthorized; got: " + ex.getHttpStatus());
    }

    @Test
    @DisplayName("R6.97-A #3: GET /image-cutout/datasets WITHOUT token → allowed (public read)")
    void imageCutoutDatasetsGetIsPublic() throws Exception {
        when(jwtUtil.validateToken(anyString())).thenReturn(null);
        when(tokenBlacklist.isBlacklisted(anyString(), anyString(), anyLong())).thenReturn(false);

        MockHttpServletRequest r = req("GET", "/api/app/gravitationalwave/image-cutout/datasets");
        MockHttpServletResponse resp = res();

        // Read-only listing must NOT require auth.
        boolean allowed = interceptor.preHandle(r, resp, new Object());
        assertTrue(allowed, "GET /image-cutout/datasets must be public");
    }

    @Test
    @DisplayName("R6.97-A #4: POST /image-cutout/auth WITH valid token → allowed, currentUserId injected")
    void imageCutoutAuthWithValidJwtAllows() throws Exception {
        // Stub valid token -> Claims with userId + role + jti
        Claims claims = mock(Claims.class);
        when(claims.getId()).thenReturn("test-jti-001");
        when(claims.get("userId", String.class)).thenReturn("user-123");
        when(claims.get("username")).thenReturn("alice");
        when(claims.get("role")).thenReturn("user");
        when(claims.getIssuedAt()).thenReturn(new Date(System.currentTimeMillis() - 60_000));
        when(claims.getExpiration()).thenReturn(new Date(System.currentTimeMillis() + 3_600_000));
        when(jwtUtil.validateToken(anyString())).thenReturn(claims);
        when(tokenBlacklist.isBlacklisted(anyString(), anyString(), anyLong())).thenReturn(false);

        MockHttpServletRequest r = req("POST", "/api/app/gravitationalwave/image-cutout/auth");
        r.addHeader("Authorization", "Bearer fake-valid-token");
        MockHttpServletResponse resp = res();

        boolean allowed = interceptor.preHandle(r, resp, new Object());
        assertTrue(allowed, "valid JWT must allow access");
        assertEquals("user-123", r.getAttribute("currentUserId"),
            "currentUserId attribute must be injected on valid JWT");
    }

    @Test
    @DisplayName("R6.97-A #5: pre-existing write-protected paths still protected (no regression)")
    void existingWriteProtectedPathsStillWork() throws Exception {
        when(jwtUtil.validateToken(anyString())).thenReturn(null);
        when(tokenBlacklist.isBlacklisted(anyString(), anyString(), anyLong())).thenReturn(false);

        // Comments POST without auth must still be blocked
        MockHttpServletRequest r = req("POST", "/api/app/gravitationalwave/comments");
        MockHttpServletResponse resp = res();
        ApiException ex = assertThrows(ApiException.class,
            () -> interceptor.preHandle(r, resp, new Object()));
        assertEquals(401, ex.getHttpStatus(),
            "existing write-protected path must still 401; got: " + ex.getHttpStatus());
    }

    @Test
    @DisplayName("R6.97-A #6: PUT/DELETE/PATCH on /image-cutout/* also require JWT (write-method coverage)")
    void imageCutoutAllWriteMethodsRequireJwt() throws Exception {
        when(jwtUtil.validateToken(anyString())).thenReturn(null);
        when(tokenBlacklist.isBlacklisted(anyString(), anyString(), anyLong())).thenReturn(false);

        for (String method : new String[]{"PUT", "DELETE", "PATCH"}) {
            MockHttpServletRequest r = req(method, "/api/app/gravitationalwave/image-cutout/something");
            MockHttpServletResponse resp = res();
            ApiException ex = assertThrows(ApiException.class,
                () -> interceptor.preHandle(r, resp, new Object()),
                "expected 401 for method=" + method);
            assertEquals(401, ex.getHttpStatus(),
                "expected 401 for method=" + method + "; got: " + ex.getHttpStatus());
        }
    }
}