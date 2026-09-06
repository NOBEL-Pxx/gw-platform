package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.auth.model;

import lombok.Data;

@Data
public class LoginRequest {
    private String username;
    private String password;
    private String email;  // only for registration
    private String role;   // viewer (default), editor, admin
}
