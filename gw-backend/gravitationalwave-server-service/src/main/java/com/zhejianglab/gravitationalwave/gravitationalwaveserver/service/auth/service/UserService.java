package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.auth.service;

import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.auth.model.LoginRequest;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.auth.model.LoginResponse;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.auth.model.User;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.auth.repository.UserRepository;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.auth.util.JwtUtil;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;

import jakarta.annotation.Resource;
import java.util.*;

@Service
public class UserService {

    private static final Logger log = LoggerFactory.getLogger(UserService.class);

    @Resource
    private UserRepository userRepository;

    @Resource
    private JwtUtil jwtUtil;

    private final BCryptPasswordEncoder encoder = new BCryptPasswordEncoder();

    // ── v4.16: Brute-force config ──
    private static final int MAX_FAILED_ATTEMPTS = 5;
    private static final int LOCK_MINUTES = 30;

    /** v4.16: Expanded roles. Default: observer (lowest privilege). */
    private static final Set<String> VALID_ROLES = Set.of("observer", "analyst", "admin");

    /**
     * Register a new user. Default role is "observer" (least privilege).
     */
    public LoginResponse register(LoginRequest req) {
        if (req.getUsername() == null || req.getUsername().trim().isEmpty()) return null;
        if (req.getPassword() == null || req.getPassword().length() < 8) return null;
        if (userRepository.existsByUsername(req.getUsername().trim())) return null;

        String hashed = encoder.encode(req.getPassword());
        String role = (req.getRole() != null && VALID_ROLES.contains(req.getRole()))
                ? req.getRole() : "observer";
        User user = new User(req.getUsername().trim(), hashed,
                req.getEmail() != null ? req.getEmail().trim() : "");
        user.setRole(role);
        user = userRepository.save(user);

        String token = jwtUtil.generateToken(user.getId(), user.getUsername(), user.getRole());
        return new LoginResponse(token, user.getUsername(), user.getId(), user.getRole());
    }

    /**
     * Login with brute-force protection (v4.16).
     * After 5 failed attempts, account is locked for 30 minutes.
     */
    public LoginResponse login(LoginRequest req) {
        if (req.getUsername() == null || req.getPassword() == null) return null;
        Optional<User> opt = userRepository.findByUsername(req.getUsername().trim());
        if (!opt.isPresent()) return null;

        User user = opt.get();

        // ── Brute-force: check lock status ──
        if (user.isLocked()) {
            if (user.getLockedUntil() != null && new Date().before(user.getLockedUntil())) {
                log.warn("Login blocked: account {} is locked until {}", user.getUsername(), user.getLockedUntil());
                return null;  // Don't reveal whether account exists
            }
            // Lock expired — reset
            user.setStatus("active");
            user.setFailedLoginAttempts(0);
            user.setLockedUntil(null);
        }

        if (!encoder.matches(req.getPassword(), user.getPassword())) {
            // ── Track failed attempts ──
            user.setFailedLoginAttempts(user.getFailedLoginAttempts() + 1);
            if (user.getFailedLoginAttempts() >= MAX_FAILED_ATTEMPTS) {
                user.setStatus("locked");
                user.setLockedUntil(new Date(System.currentTimeMillis() + LOCK_MINUTES * 60 * 1000L));
                log.warn("Account {} locked after {} failed attempts", user.getUsername(), user.getFailedLoginAttempts());
            }
            userRepository.save(user);
            return null;
        }

        // Login success — reset counters
        user.setFailedLoginAttempts(0);
        user.setLockedUntil(null);
        user.setStatus("active");
        user.setUpdatedAt(new Date());
        userRepository.save(user);

        String token = jwtUtil.generateToken(user.getId(), user.getUsername(), user.getRole());
        return new LoginResponse(token, user.getUsername(), user.getId(), user.getRole());
    }

    // ── v4.16: Password management ────────────────────────────────────

    public boolean changePassword(String userId, String oldPassword, String newPassword) {
        Optional<User> opt = userRepository.findById(userId);
        if (!opt.isPresent()) return false;

        User user = opt.get();
        if (!encoder.matches(oldPassword, user.getPassword())) return false;

        user.setPassword(encoder.encode(newPassword));
        user.setPasswordChangedAt(new Date());
        user.setUpdatedAt(new Date());
        userRepository.save(user);
        log.info("Password changed for user {}", user.getUsername());
        return true;
    }

    public Map<String, Object> getAccountInfo(String userId) {
        Optional<User> opt = userRepository.findById(userId);
        if (!opt.isPresent()) return null;
        User user = opt.get();

        Map<String, Object> info = new LinkedHashMap<>();
        info.put("userId", user.getId());
        info.put("username", user.getUsername());
        info.put("email", user.getEmail());
        info.put("role", user.getRole());
        info.put("status", user.getStatus());
        info.put("createdAt", user.getCreatedAt());
        info.put("passwordChangedAt", user.getPasswordChangedAt());
        return info;
    }

    // ── v4.16: Role management (admin-only) ────────────────────────────

    public boolean setUserRole(String adminUserId, String targetUserId, String newRole) {
        Optional<User> adminOpt = userRepository.findById(adminUserId);
        if (!adminOpt.isPresent() || !adminOpt.get().isAdmin()) {
            throw new SecurityException("Only admins can change roles");
        }
        if (!VALID_ROLES.contains(newRole)) {
            throw new IllegalArgumentException("Invalid role: " + newRole + ". Valid: " + VALID_ROLES);
        }
        Optional<User> targetOpt = userRepository.findById(targetUserId);
        if (!targetOpt.isPresent()) return false;

        User target = targetOpt.get();
        target.setRole(newRole);
        target.setUpdatedAt(new Date());
        userRepository.save(target);
        log.info("Role changed: {} {} → {}", target.getUsername(), target.getRole(), newRole);
        return true;
    }

    public User findById(String id) {
        return userRepository.findById(id).orElse(null);
    }
}
