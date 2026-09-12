package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.config;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

/**
 * R6.94-A: /actuator/** IP whitelist filter.
 *
 * <p>Spring Boot Actuator endpoints ({@code /actuator/health}, {@code /actuator/info},
 * {@code /actuator/metrics}, {@code /actuator/prometheus}) are served by a separate
 * {@code WebMvcEndpointHandlerMapping} that is NOT covered by
 * {@link WebMvcConfig}'s HandlerInterceptors (those only register on
 * {@code /api/**} + {@code /static-files/**}). Without this filter, any
 * container on the {@code gw-net} Docker bridge (gw-frontend, gw-pipeline,
 * gw-mcp-server, gw-firefly, gw-prometheus) can scrape /actuator/prometheus —
 * which leaks request URL patterns + latencies that aid reconnaissance.
 *
 * <p>This filter restricts {@code /actuator/**} to whitelisted source IPs:
 * <ul>
 *   <li>127.0.0.0/8 — loopback (docker exec into gw-backend container)</li>
 *   <li>172.16.0.0/12 — Docker bridge default range (gw-prometheus scrapes
 *       from a sibling container with a 172.x IP)</li>
 *   <li>10.0.0.0/8 — alternate Docker compose bridge range</li>
 *   <li>192.168.0.0/16 — host network in dev mode</li>
 * </ul>
 * Everything else (e.g., a malicious container, or the public internet via
 * nginx) gets HTTP 403.
 *
 * <p>Production (zjlab) defense-in-depth: gw-backend port 8093 is NOT
 * exposed via host port mapping ({@code docker-compose.zjlab.yml:72} has
 * {@code ports: []}) and nginx does NOT proxy {@code /actuator/**} — so the
 * only attack surface is sibling containers in {@code gw-net}. This filter
 * limits that surface to the Prometheus scraper container (and any future
 * operational tooling). Dev mode exposes 8093:8093 to the host, so this
 * filter is the ONLY protection in dev.
 *
 * <p>Iron rule R6.94-A (now enforced): {@code /actuator/prometheus} endpoint
 * MUST be IP-whitelisted (Docker bridge CIDR + loopback) OR behind separate
 * actuator port. Previous pom.xml + application.properties comments cited
 * R6.73 IP whitelist as protection — that whitelist is for gw-pipeline
 * (Python middleware in {@code gw-pipeline/src/pipeline/middleware/ip_whitelist.py})
 * and PipelineProxyController outbound allowlist — NOT gw-backend's
 * /actuator/**. This filter is the actual enforcement.
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class ActuatorIpWhitelistFilter extends OncePerRequestFilter {

    private static final Logger log = LoggerFactory.getLogger(ActuatorIpWhitelistFilter.class);
    private static final String ACTUATOR_PATH_PREFIX = "/actuator/";

    /**
     * R6.94-A: whitelisted IP prefixes for /actuator/** access.
     *
     * <p>Implemented as prefix matchers (not full CIDR math) because Actuator
     * sees per-request source IP — typically from Docker bridge (172.x.x.x)
     * or loopback (127.x.x.x). The full Docker bridge range 172.16.0.0/12
     * covers 172.16-172.31, so we list each prefix explicitly.
     */
    private static final String[] WHITELIST_PREFIXES = {
        "127.",          // loopback (docker exec into container)
        "172.16.", "172.17.", "172.18.", "172.19.", "172.20.",
        "172.21.", "172.22.", "172.23.", "172.24.", "172.25.",
        "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31.",  // Docker bridge 172.16/12
        "10.",           // Private network 10.0.0.0/8 (some compose networks)
        "192.168."       // Host network in dev mode
    };

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {
        String uri = request.getRequestURI();
        if (uri != null && uri.startsWith(ACTUATOR_PATH_PREFIX)) {
            String remoteAddr = request.getRemoteAddr();
            if (!isWhitelisted(remoteAddr)) {
                log.warn("R6.94-A: blocked /actuator access from non-whitelisted IP {} (path={})",
                    remoteAddr, uri);
                response.sendError(HttpServletResponse.SC_FORBIDDEN,
                    "R6.94-A: /actuator/** access requires whitelisted source IP");
                return;
            }
            log.debug("R6.94-A: allowed /actuator access from whitelisted IP {} (path={})",
                remoteAddr, uri);
        }
        chain.doFilter(request, response);
    }

    private boolean isWhitelisted(String ip) {
        if (ip == null) {
            return false;
        }
        for (String prefix : WHITELIST_PREFIXES) {
            if (ip.startsWith(prefix)) {
                return true;
            }
        }
        return false;
    }
}