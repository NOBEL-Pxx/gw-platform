package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.auth.util;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.util.Date;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

@Component
public class JwtUtil {

    @Value("${jwt.secret:gw-platform-default-secret-key-2026}")
    private String secret;

    @Value("${jwt.expiration:86400000}")
    private long expiration;  // default 24 hours

    @Value("${jwt.refresh-window:1800000}")
    private long refreshWindow;  // 30 min before expiry — allow silent refresh

    private SecretKey getSigningKey() {
        return Keys.hmacShaKeyFor(secret.getBytes(StandardCharsets.UTF_8));
    }

    /**
     * v4.16: Generate a JWT token with jti (JWT ID) for blacklist support.
     * The jti claim uniquely identifies this token for revocation.
     */
    public String generateToken(String userId, String username, String role) {
        Map<String, Object> claims = new HashMap<>();
        claims.put("userId", userId);
        claims.put("username", username);
        claims.put("role", role);

        Date now = new Date();
        Date expiry = new Date(now.getTime() + expiration);

        return Jwts.builder()
                .claims(claims)
                .id(UUID.randomUUID().toString())  // v4.16: jti for blacklist
                .subject(username)
                .issuedAt(now)
                .expiration(expiry)
                .signWith(getSigningKey())
                .compact();
    }

    /** Parse and validate a token. Returns claims, or null if invalid/expired. */
    public Claims validateToken(String token) {
        try {
            return Jwts.parser()
                    .verifyWith(getSigningKey())
                    .build()
                    .parseSignedClaims(token)
                    .getPayload();
        } catch (Exception e) {
            return null;
        }
    }

    /**
     * Validate a token EVEN IF EXPIRED, for refresh purposes.
     * Used by /api/auth/refresh — accepts tokens up to refreshWindow past expiry.
     */
    public Claims validateTokenLenient(String token) {
        try {
            return Jwts.parser()
                    .verifyWith(getSigningKey())
                    .clockSkewSeconds(refreshWindow / 1000)
                    .build()
                    .parseSignedClaims(token)
                    .getPayload();
        } catch (Exception e) {
            return null;
        }
    }

    /** Extract userId from a validated token. */
    public String getUserIdFromToken(String token) {
        Claims claims = validateToken(token);
        if (claims == null) return null;
        Object userId = claims.get("userId");
        return userId != null ? userId.toString() : null;
    }

    /** Extract username from a validated token. */
    public String getUsernameFromToken(String token) {
        Claims claims = validateToken(token);
        return claims != null ? claims.getSubject() : null;
    }

    /** Extract role from a token (strict validation). */
    public String getRoleFromToken(String token) {
        Claims claims = validateToken(token);
        if (claims == null) return null;
        Object role = claims.get("role");
        return role != null ? role.toString() : "observer";  // v4.16: default observer
    }
}
