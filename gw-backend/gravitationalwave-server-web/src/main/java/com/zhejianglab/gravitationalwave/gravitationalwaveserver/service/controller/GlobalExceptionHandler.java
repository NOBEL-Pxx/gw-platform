package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.controller;

import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.response.ApiException;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.response.Response;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    // ── v4.16: Structured exception hierarchy ──────────────────────────

    @ExceptionHandler(ApiException.class)
    public ResponseEntity<Response<Void>> handleApiException(ApiException ex) {
        log.warn("API error [{}] {}: {}", ex.getErrorCode(), ex.getHttpStatus(), ex.getMessage());
        Response<Void> body = Response.wrapError(ex.getErrorCode(), ex.getMessage());
        return ResponseEntity.status(ex.getHttpStatus()).body(body);
    }

    // ── LLM / external service errors ──

    @ExceptionHandler(java.net.ConnectException.class)
    public ResponseEntity<Response<Void>> handleConnectException(java.net.ConnectException ex) {
        log.error("External service connection refused: {}", ex.getMessage());
        Response<Void> body = Response.wrapError("0502",
            "External service (LLM/FITS server) unreachable — check network/firewall. "
            + ex.getMessage());
        return ResponseEntity.status(HttpStatus.BAD_GATEWAY).body(body);
    }

    @ExceptionHandler(java.net.SocketTimeoutException.class)
    public ResponseEntity<Response<Void>> handleSocketTimeout(java.net.SocketTimeoutException ex) {
        log.error("Socket timeout: {}", ex.getMessage());
        Response<Void> body = Response.wrapError("0504",
            "Request timed out — the external service may be slow or overloaded. "
            + "Increase LLM_READ_TIMEOUT_SEC / LLM_TOTAL_TIMEOUT_SEC. "
            + ex.getMessage());
        return ResponseEntity.status(HttpStatus.GATEWAY_TIMEOUT).body(body);
    }

    @ExceptionHandler(java.io.IOException.class)
    public ResponseEntity<Response<Void>> handleIOException(java.io.IOException ex) {
        String msg = ex.getMessage() != null ? ex.getMessage() : "";
        if (msg.contains("FITS") || msg.contains("fits") || msg.contains("SIMPLE")) {
            log.error("FITS I/O error: {}", msg);
            Response<Void> body = Response.wrapError("0422",
                "FITS file error — file may be corrupt, missing, or have invalid WCS. "
                + "Verify with /pipeline/file/integrity. " + msg);
            return ResponseEntity.status(HttpStatus.UNPROCESSABLE_ENTITY).body(body);
        }
        if (msg.contains("timeout") || msg.contains("Timeout")) {
            log.error("I/O timeout: {}", msg);
            Response<Void> body = Response.wrapError("0504", "I/O timeout: " + msg);
            return ResponseEntity.status(HttpStatus.GATEWAY_TIMEOUT).body(body);
        }
        log.error("I/O error", ex);
        Response<Void> body = Response.wrapError("0500", "I/O error: " + msg);
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(body);
    }

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Response<Void>> handleIllegalArgument(IllegalArgumentException ex) {
        log.warn("Bad request: {}", ex.getMessage());
        Response<Void> body = Response.wrapError("0400",
            "Invalid parameter: " + (ex.getMessage() != null ? ex.getMessage() : "check input values"));
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(body);
    }

    // ── Fallback handlers ──

    @ExceptionHandler(RuntimeException.class)
    public ResponseEntity<Response<Void>> handleRuntimeException(RuntimeException ex) {
        // v4.16: Include exception type in error message for faster triage
        String detail = ex.getClass().getSimpleName() + ": "
            + (ex.getMessage() != null ? ex.getMessage().replace("\n", " ").trim() : "(no message)");
        if (detail.length() > 300) detail = detail.substring(0, 297) + "...";
        log.error("Runtime error: {}", detail, ex);
        Response<Void> body = Response.wrapError("0500", detail);
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(body);
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<Response<Void>> handleException(Exception ex) {
        String detail = ex.getClass().getSimpleName() + ": "
            + (ex.getMessage() != null ? ex.getMessage().replace("\n", " ").trim() : "(no message)");
        if (detail.length() > 300) detail = detail.substring(0, 297) + "...";
        log.error("Unexpected error: {}", detail, ex);
        Response<Void> body = Response.wrapError("0500", detail);
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(body);
    }
}
