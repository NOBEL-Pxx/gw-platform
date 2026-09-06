package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.response;
import lombok.AllArgsConstructor;
import lombok.Data;

import java.io.Serializable;
@Data
@AllArgsConstructor
public class ErrorDTO implements Serializable{
    public static ErrorDTO NO_ERROR = ErrorDTO.of("0", "");

    private String code;

    private String msg;


    public static ErrorDTO of(String code, String msg) {
        return new ErrorDTO(code, msg);
    }



}
