package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.controller;

import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.auth.model.LoginRequest;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.auth.model.LoginResponse;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.auth.service.UserService;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.auth.util.JwtUtil;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.auth.util.TokenBlacklist;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.response.ApiException;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.response.Response;
import io.jsonwebtoken.Claims;
import org.springframework.web.bind.annotation.*;

import jakarta.annotation.Resource;
import jakarta.servlet.http.HttpServletRequest;
import java.util.*;

@RestController
@RequestMapping("/api/auth")
public class AuthController {

    @Resource
    private UserService userService;

    @Resource
    private JwtUtil jwtUtil;

    @Resource
    private TokenBlacklist tokenBlacklist;

    @PostMapping("/register")
    public Response<LoginResponse> register(@RequestBody LoginRequest req) {
        LoginResponse result = userService.register(req);
        if (result == null) {
            return Response.wrapError("0400", "Registration failed: username taken or invalid input");
        }
        return Response.wrapSuccess(result);
    }

    @PostMapping("/login")
    public Response<LoginResponse> login(@RequestBody LoginRequest req) {
        LoginResponse result = userService.login(req);
        if (result == null) {
            return Response.wrapError("0401", "Invalid username or password");
        }
        return Response.wrapSuccess(result);
    }

    /** Verify token validity — used by frontend to restore session on refresh. */
    @GetMapping("/verify")
    public Response<LoginResponse> verify(HttpServletRequest request) {
        String userId = (String) request.getAttribute("currentUserId");
        String username = (String) request.getAttribute("currentUsername");
        String role = (String) request.getAttribute("currentRole");
        if (userId == null) {
            return Response.wrapError("0401", "Invalid token");
        }
        return Response.wrapSuccess(new LoginResponse("", username, userId, role != null ? role : "viewer"));
    }

    /**
     * Silent token refresh — accepts a still-valid (or recently-expired) token
     * and returns a fresh 24h token without requiring re-login.
     */
    @PostMapping("/refresh")
    public Response<LoginResponse> refresh(HttpServletRequest request) {
        String authHeader = request.getHeader("Authorization");
        if (authHeader == null || !authHeader.startsWith("Bearer ")) {
            throw ApiException.unauthorized("Missing or invalid Authorization header");
        }
        String token = authHeader.substring(7);
        Claims claims = jwtUtil.validateTokenLenient(token);
        if (claims == null) {
            throw ApiException.unauthorized("Token expired or invalid — please re-login");
        }
        String userId = claims.get("userId", String.class);
        String username = claims.getSubject();
        String role = claims.get("role", String.class);
        if (userId == null || username == null) {
            throw ApiException.unauthorized("Token payload incomplete");
        }

        // Check blacklist before refreshing
        long issuedAt = claims.getIssuedAt() != null
                ? claims.getIssuedAt().toInstant().toEpochMilli() : 0;
        if (tokenBlacklist.isBlacklisted(claims.getId(), userId, issuedAt)) {
            throw ApiException.unauthorized("Token has been revoked — please login again");
        }

        String newToken = jwtUtil.generateToken(userId, username, role != null ? role : "viewer");
        return Response.wrapSuccess(new LoginResponse(newToken, username, userId, role != null ? role : "viewer"));
    }

    /**
     * v4.16: Logout — blacklists the current token so it cannot be reused.
     * After logout, the token is invalid even if not yet expired.
     */
    @PostMapping("/logout")
    public Response<Map<String, Object>> logout(HttpServletRequest request) {
        String jti = (String) request.getAttribute("currentTokenJti");
        Long expiry = (Long) request.getAttribute("currentTokenExpiry");

        if (jti != null && expiry != null) {
            tokenBlacklist.blacklistToken(jti, expiry);
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("logged_out", true);
        result.put("message", "Token has been revoked");
        return Response.wrapSuccess(result);
    }

    /**
     * v4.16: Change password — invalidates ALL existing tokens for this user.
     * After password change, the user must re-login on all devices.
     */
    @PostMapping("/change-password")
    public Response<Map<String, Object>> changePassword(
            @RequestBody ChangePasswordRequest req,
            HttpServletRequest request) {
        String userId = (String) request.getAttribute("currentUserId");
        if (userId == null) {
            throw ApiException.unauthorized("Authentication required");
        }
        if (req.getOldPassword() == null || req.getNewPassword() == null) {
            throw ApiException.badRequest("oldPassword and newPassword are required");
        }
        if (req.getNewPassword().length() < 8) {
            throw ApiException.badRequest("New password must be at least 8 characters");
        }

        boolean changed = userService.changePassword(userId, req.getOldPassword(), req.getNewPassword());
        if (!changed) {
            throw ApiException.unauthorized("Current password is incorrect");
        }

        // Invalidate all existing tokens — user must re-login
        tokenBlacklist.invalidateAllUserTokens(userId);

        // Issue a new token for the current session
        String username = (String) request.getAttribute("currentUsername");
        String role = (String) request.getAttribute("currentRole");
        String newToken = jwtUtil.generateToken(userId, username, role != null ? role : "user");

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("changed", true);
        result.put("message", "Password changed. All other sessions have been invalidated.");
        result.put("token", newToken);
        return Response.wrapSuccess(result);
    }

    /**
     * v4.16: Get current user's account info (role, email, created date).
     */
    @GetMapping("/account")
    public Response<Map<String, Object>> accountInfo(HttpServletRequest request) {
        String userId = (String) request.getAttribute("currentUserId");
        if (userId == null) {
            throw ApiException.unauthorized("Authentication required");
        }
        Map<String, Object> info = userService.getAccountInfo(userId);
        if (info == null) {
            throw ApiException.notFound("User not found");
        }
        return Response.wrapSuccess(info);
    }

    // ── Request DTOs ──

    public static class ChangePasswordRequest {
        private String oldPassword;
        private String newPassword;
        public String getOldPassword() { return oldPassword; }
        public void setOldPassword(String v) { this.oldPassword = v; }
        public String getNewPassword() { return newPassword; }
        public void setNewPassword(String v) { this.newPassword = v; }
    }
}
