package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.config;

import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.auth.util.JwtUtil;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.auth.util.TokenBlacklist;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.response.ApiException;
import io.jsonwebtoken.Claims;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

import jakarta.annotation.Resource;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.util.Arrays;
import java.util.List;
import java.util.Set;

/**
 * JWT authentication interceptor with RBAC enforcement (v4.16).
 *
 * Changes from v4.15:
 *  - Token blacklist check (logout + password-change invalidation)
 *  - Write-protected prefix list: all POST/PUT/DELETE to comment/favorite/collection
 *    require authentication (previously only /api/auth/verify was protected)
 *  - Role-based gating: admin-only operations (export, batch delete) checked here
 */
@Component
public class AuthInterceptor implements HandlerInterceptor {

    private static final Logger log = LoggerFactory.getLogger(AuthInterceptor.class);

    @Resource
    private JwtUtil jwtUtil;

    @Resource
    private TokenBlacklist tokenBlacklist;

    /** Paths that NEVER require authentication (public data APIs, static resources). */
    private static final List<String> PUBLIC_PREFIXES = Arrays.asList(
            "/api/auth/login",
            "/api/auth/register",
            "/api/auth/refresh",
            "/api/app/gravitationalwave/geoSearch",
            "/api/app/gravitationalwave/error",
            // Public collection read endpoints — the share chain must be unauthenticated
            "/api/app/gravitationalwave/collections/public",
            "/api/app/gravitationalwave/collections/shared",
            "/static-files/",
            "/error"
    );

    /**
     * v4.16: Write-protected prefixes — ALL mutating operations require a valid JWT.
     * Previously only /api/auth/verify was protected. Now all comments, favorites,
     * and collections mutations are gated at the interceptor level.
     */
    private static final List<String> WRITE_PROTECTED_PREFIXES = Arrays.asList(
            // Comments
            "/api/app/gravitationalwave/comments",     // POST + DELETE
            // Favorites
            "/api/app/gravitationalwave/favorites",    // all methods
            // Collections
            "/api/app/gravitationalwave/collections",  // POST/PUT/DELETE
            // Auth
            "/api/auth/verify",
            "/api/auth/logout",
            "/api/auth/change-password",
            "/api/auth/account"
    );

    /** HTTP methods that require auth on write-protected paths. */
    private static final Set<String> WRITE_METHODS = Set.of("POST", "PUT", "DELETE", "PATCH");

    /** GET methods that still require auth (user-specific data). */
    private static final List<String> AUTH_REQUIRED_GET_PREFIXES = Arrays.asList(
            "/api/app/gravitationalwave/favorites",   // user's own favorites
            "/api/app/gravitationalwave/collections"  // user's own collections (listMine)
    );

    /** Admin-only paths (require role="admin" in addition to valid JWT). */
    private static final List<String> ADMIN_PREFIXES = Arrays.asList(
            "/api/app/gravitationalwave/comments/export",
            "/api/app/gravitationalwave/error/delete"
    );

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response,
                             Object handler) throws Exception {
        String path = request.getRequestURI();
        String method = request.getMethod();

        // 1) Public paths — skip JWT processing entirely (fast path)
        for (String prefix : PUBLIC_PREFIXES) {
            if (path.startsWith(prefix)) return true;
        }

        // 2) OPTIONS preflight — always allow
        if ("OPTIONS".equalsIgnoreCase(method)) return true;

        // 3) Extract and validate JWT (for ALL non-public paths)
        String authHeader = request.getHeader("Authorization");
        Claims claims = null;
        String token = null;

        if (authHeader != null && authHeader.startsWith("Bearer ")) {
            token = authHeader.substring(7);
            claims = jwtUtil.validateToken(token);
            if (claims != null) {
                // ── Token blacklist check (v4.16) ──
                String jti = claims.getId();
                String userId = claims.get("userId", String.class);
                long issuedAt = claims.getIssuedAt() != null
                        ? claims.getIssuedAt().toInstant().toEpochMilli()
                        : 0;

                if (tokenBlacklist.isBlacklisted(jti, userId, issuedAt)) {
                    log.warn("Blacklisted token rejected: user={}, path={}", userId, path);
                    throw ApiException.unauthorized("Token has been revoked — please login again");
                }

                // Inject user attributes into request
                request.setAttribute("currentUserId", userId);
                request.setAttribute("currentUsername", claims.get("username"));
                request.setAttribute("currentRole", claims.get("role"));
                request.setAttribute("currentTokenJti", jti);
                request.setAttribute("currentTokenExpiry", claims.getExpiration() != null
                        ? claims.getExpiration().toInstant().toEpochMilli() : 0L);
            }
        }

        // 4) Check if this path REQUIRES authentication (v4.16: expanded)
        boolean needsAuth = false;

        // Write methods on write-protected paths
        if (WRITE_METHODS.contains(method)) {
            for (String prefix : WRITE_PROTECTED_PREFIXES) {
                if (path.startsWith(prefix)) {
                    needsAuth = true;
                    break;
                }
            }
        }

        // Auth-required GET endpoints
        if ("GET".equalsIgnoreCase(method)) {
            for (String prefix : AUTH_REQUIRED_GET_PREFIXES) {
                if (path.startsWith(prefix)) {
                    needsAuth = true;
                    break;
                }
            }
        }

        if (needsAuth) {
            String userId = (String) request.getAttribute("currentUserId");
            if (userId == null) {
                throw ApiException.unauthorized("Authentication required — please login");
            }
        }

        // 5) Admin-only paths (v4.16: role-based)
        for (String prefix : ADMIN_PREFIXES) {
            if (path.startsWith(prefix)) {
                String role = (String) request.getAttribute("currentRole");
                if (!"admin".equals(role)) {
                    throw ApiException.forbidden("Admin role required for this operation");
                }
                break;
            }
        }

        return true;
    }
}
