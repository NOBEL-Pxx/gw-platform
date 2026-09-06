package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.controller;

import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.HttpServerErrorException;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestTemplate;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Enumeration;
import java.util.List;
import java.util.Map;

/**
 * R6.66.2: Pipeline Proxy Controller.
 *
 * Forwards /pipeline/** to http://gw-pipeline:8000 (Docker DNS, both on gw-net).
 *
 * Used by:
 *   - /pipeline/admin/audit/{unified,anomalies,ship}     (audit endpoints, R6.52 #1)
 *   - /pipeline/observability/{font-errors,health,...}   (observability dashboard)
 *   - /pipeline/batch/{submit,status,queue,cancel}       (batch processing)
 *   - /pipeline/admin/secrets/{status,rotate,alerts}     (secrets management)
 *   - /pipeline/pdf/{sign,verify,...}                   (PDF signing/verify)
 *   - /pipeline/hips-{tile-resolve,cache-invalidate,cache-stats}  (HiPS CDN mgmt)
 *
 * All methods proxied: GET/POST/PUT/PATCH/HEAD/OPTIONS. Body + headers forwarded.
 * Body returned as raw byte[] to preserve binary safety (FITS files, ZIP, PDF).
 *
 * R6.66.2 motivation: Without this proxy, gw-backend returns 500
 * "No static resource api/audit" for /api/audit, even though gw-pipeline container
 * owns the audit endpoint. Auth: callers must present a valid Bearer JWT.
 */
@RestController
@RequestMapping("/pipeline")
public class PipelineProxyController {

    private static final Logger log = LoggerFactory.getLogger(PipelineProxyController.class);

    /** Upstream URL. gw-pipeline is the Docker service name on gw-net. */
    private static final String UPSTREAM = "http://gw-pipeline:8200";

    /** Request timeout in milliseconds. */
    private static final int TIMEOUT_MS = 30000;

    private final RestTemplate restTemplate;

    public PipelineProxyController() {
        this.restTemplate = new RestTemplate();
        // Configure timeouts (default RestTemplate uses SimpleClientHttpRequestFactory)
        ((org.springframework.http.client.SimpleClientHttpRequestFactory)
            this.restTemplate.getRequestFactory())
            .setConnectTimeout(TIMEOUT_MS);
        ((org.springframework.http.client.SimpleClientHttpRequestFactory)
            this.restTemplate.getRequestFactory())
            .setReadTimeout(TIMEOUT_MS);
    }

    @RequestMapping(value = "/**", method = RequestMethod.GET)
    public ResponseEntity<byte[]> proxyGet(HttpServletRequest req) throws IOException {
        return forward(HttpMethod.GET, req);
    }

    @RequestMapping(value = "/**", method = RequestMethod.POST)
    public ResponseEntity<byte[]> proxyPost(HttpServletRequest req) throws IOException {
        return forward(HttpMethod.POST, req);
    }

    @RequestMapping(value = "/**", method = RequestMethod.PUT)
    public ResponseEntity<byte[]> proxyPut(HttpServletRequest req) throws IOException {
        return forward(HttpMethod.PUT, req);
    }

    @RequestMapping(value = "/**", method = RequestMethod.DELETE)
    public ResponseEntity<byte[]> proxyDelete(HttpServletRequest req) throws IOException {
        return forward(HttpMethod.DELETE, req);
    }

    @RequestMapping(value = "/**", method = RequestMethod.PATCH)
    public ResponseEntity<byte[]> proxyPatch(HttpServletRequest req) throws IOException {
        return forward(HttpMethod.PATCH, req);
    }

    @RequestMapping(value = "/**", method = RequestMethod.HEAD)
    public ResponseEntity<byte[]> proxyHead(HttpServletRequest req) throws IOException {
        return forward(HttpMethod.HEAD, req);
    }

    @RequestMapping(value = "/**", method = RequestMethod.OPTIONS)
    public ResponseEntity<byte[]> proxyOptions(HttpServletRequest req) throws IOException {
        return forward(HttpMethod.OPTIONS, req);
    }

    private ResponseEntity<byte[]> forward(HttpMethod method, HttpServletRequest req) throws IOException {
        String fullPath = req.getRequestURI();
        // fullPath is /pipeline/audit/unified (no prefix stripping; gw-pipeline expects /pipeline/...)
        String url = UPSTREAM + fullPath;
        String query = req.getQueryString();
        if (query != null) {
            url = url + "?" + query;
        }

        HttpHeaders headers = copyHeaders(req);
        byte[] body = readBody(req);

        HttpEntity<byte[]> entity = new HttpEntity<>(body, headers);

        try {
            log.info("[proxy] {} {} -> {} (body={}B)", method, fullPath, url, body.length);
            ResponseEntity<byte[]> resp = restTemplate.exchange(
                url, method, entity, byte[].class
            );
            log.info("[proxy] {} {} -> {} (resp={}B, status={})",
                method, fullPath, url,
                resp.getBody() == null ? 0 : resp.getBody().length,
                resp.getStatusCode());
            return ResponseEntity.status(resp.getStatusCode())
                .headers(filterResponseHeaders(resp.getHeaders()))
                .body(resp.getBody());
        } catch (HttpClientErrorException e) {
            log.warn("[proxy] {} {} -> client error {}: {}",
                method, fullPath, e.getStatusCode(), e.getMessage());
            return ResponseEntity.status(e.getStatusCode())
                .headers(filterResponseHeaders(e.getResponseHeaders()))
                .body(e.getResponseBodyAsByteArray());
        } catch (HttpServerErrorException e) {
            log.error("[proxy] {} {} -> server error {}: {}",
                method, fullPath, e.getStatusCode(), e.getMessage());
            return ResponseEntity.status(e.getStatusCode())
                .headers(filterResponseHeaders(e.getResponseHeaders()))
                .body(e.getResponseBodyAsByteArray());
        } catch (ResourceAccessException e) {
            log.error("[proxy] {} {} -> upstream unreachable: {}",
                method, fullPath, e.getMessage());
            byte[] errBody = ("{\"error\":\"pipeline upstream unreachable: "
                + e.getMessage().replace("\"", "'") + "\"}").getBytes(StandardCharsets.UTF_8);
            return ResponseEntity.status(HttpStatus.BAD_GATEWAY)
                .header("Content-Type", "application/json")
                .body(errBody);
        } catch (Exception e) {
            log.error("[proxy] {} {} -> unexpected error: {}",
                method, fullPath, e.getMessage(), e);
            byte[] errBody = ("{\"error\":\"proxy error: "
                + e.getClass().getSimpleName() + "\"}").getBytes(StandardCharsets.UTF_8);
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                .header("Content-Type", "application/json")
                .body(errBody);
        }
    }

    private HttpHeaders copyHeaders(HttpServletRequest req) {
        HttpHeaders out = new HttpHeaders();
        Enumeration<String> names = req.getHeaderNames();
        while (names.hasMoreElements()) {
            String name = names.nextElement();
            String lname = name.toLowerCase();
            // Skip hop-by-hop headers and Content-Length (Spring will set it)
            if (lname.equals("host") || lname.equals("content-length")
                || lname.equals("transfer-encoding") || lname.equals("connection")) {
                continue;
            }
            Enumeration<String> values = req.getHeaders(name);
            while (values.hasMoreElements()) {
                out.add(name, values.nextElement());
            }
        }
        return out;
    }

    private HttpHeaders filterResponseHeaders(HttpHeaders in) {
        HttpHeaders out = new HttpHeaders();
        for (Map.Entry<String, List<String>> e : in.entrySet()) {
            String lname = e.getKey().toLowerCase();
            // Skip hop-by-hop response headers
            if (lname.equals("transfer-encoding") || lname.equals("connection")
                || lname.equals("keep-alive")) {
                continue;
            }
            out.put(e.getKey(), e.getValue());
        }
        return out;
    }

    private byte[] readBody(HttpServletRequest req) throws IOException {
        try {
            return req.getInputStream().readAllBytes();
        } catch (IOException e) {
            // Some methods (GET, HEAD, OPTIONS) have no body; this is expected
            return new byte[0];
        }
    }
}
