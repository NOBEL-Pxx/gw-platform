package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.auth.model;

import lombok.Data;
import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.index.Indexed;
import org.springframework.data.mongodb.core.mapping.Document;

import java.util.Date;

/**
 * User entity with expanded RBAC roles (v4.16).
 *
 * Role hierarchy:
 *   "admin"    — Full access: manage users, export data, delete records
 *   "analyst"  — Scientific operations: source detection, SNR, AI chat, batch processing
 *   "observer" — Read operations: search, view FITS, browse errors, post comments
 *
 * Default: "observer" (lowest privilege). Upgraded by admin.
 */
@Data
@Document(collection = "users")
public class User {
    @Id
    private String id;

    @Indexed(unique = true)
    private String username;

    private String password;  // bcrypt hashed

    private String email;

    /**
     * v4.16: Expanded roles.
     * "admin" | "analyst" | "observer"
     * Default: "observer"
     */
    private String role;

    /** v4.16: Timestamp of last password change (used with TokenBlacklist). */
    private Date passwordChangedAt;

    /** v4.16: Account status. "active" | "locked" */
    private String status;

    /** v4.16: Failed login attempts (for brute-force protection). */
    private int failedLoginAttempts;

    /** v4.16: Timestamp until which the account is locked. */
    private Date lockedUntil;

    private Date createdAt;
    private Date updatedAt;

    public User() {}

    public User(String username, String password, String email) {
        this.username = username;
        this.password = password;
        this.email = email;
        this.role = "observer";  // v4.16: lowest privilege by default
        this.status = "active";
        this.failedLoginAttempts = 0;
        this.createdAt = new Date();
        this.updatedAt = new Date();
        this.passwordChangedAt = new Date();
    }

    // ── v4.16: Role helpers ──

    public boolean isAdmin() { return "admin".equals(role); }
    public boolean isAnalyst() { return "analyst".equals(role) || isAdmin(); }
    public boolean isObserver() { return "observer".equals(role) || isAnalyst(); }
    public boolean isLocked() { return "locked".equals(status); }

    /** Check if user has at least the required role level. */
    public boolean hasRole(String required) {
        if (required == null) return true;
        return switch (required) {
            case "admin" -> isAdmin();
            case "analyst" -> isAnalyst();
            case "observer" -> isObserver();
            default -> false;
        };
    }
}
