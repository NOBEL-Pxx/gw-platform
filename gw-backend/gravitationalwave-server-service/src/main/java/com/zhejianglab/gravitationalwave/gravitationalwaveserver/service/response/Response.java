package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.response;

import lombok.Data;

import java.io.Serializable;

@Data
public class Response<T> implements Serializable {

    private ErrorDTO error;

    private T data;

    public static <T> Response wrapSuccess(T data) {
        Response<T> response = new Response<>();
        response.setError(ErrorDTO.NO_ERROR);
        response.setData(data);
        return response;
    }

    public static <T> Response wrapError(ErrorDTO error) {
        Response<T> response = new Response<>();
        response.setError(error);
        return response;
    }

    public static <T> Response wrapError(String code, String msg) {
        Response<T> response = new Response<>();
        response.setError(ErrorDTO.of(code, msg));
        return response;
    }
}

