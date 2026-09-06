package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.auth.model;

import lombok.AllArgsConstructor;
import lombok.Data;

@Data
@AllArgsConstructor
public class LoginResponse {
    private String token;
    private String username;
    private String userId;
    private String role;
}
