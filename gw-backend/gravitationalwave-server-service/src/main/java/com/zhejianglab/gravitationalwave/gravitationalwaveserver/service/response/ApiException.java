package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.response;

/**
 * Unified API exception with HTTP status and error code.
 * Caught by GlobalExceptionHandler to produce consistent JSON error responses.
 */
public class ApiException extends RuntimeException {

    private final int httpStatus;
    private final String errorCode;

    public ApiException(int httpStatus, String errorCode, String message) {
        super(message);
        this.httpStatus = httpStatus;
        this.errorCode = errorCode;
    }

    public ApiException(int httpStatus, String errorCode, String message, Throwable cause) {
        super(message, cause);
        this.httpStatus = httpStatus;
        this.errorCode = errorCode;
    }

    public int getHttpStatus() { return httpStatus; }
    public String getErrorCode() { return errorCode; }

    public static ApiException badRequest(String msg) {
        return new ApiException(400, "0400", msg);
    }
    public static ApiException unauthorized(String msg) {
        return new ApiException(401, "0401", msg);
    }
    public static ApiException forbidden(String msg) {
        return new ApiException(403, "0403", msg);
    }
    public static ApiException notFound(String msg) {
        return new ApiException(404, "0404", msg);
    }
    public static ApiException tooManyRequests(String msg) {
        return new ApiException(429, "0429", msg);
    }
    public static ApiException unprocessable(String msg) {
        return new ApiException(422, "0422", msg);
    }
    public static ApiException internal(String msg) {
        return new ApiException(500, "0500", msg);
    }
}
