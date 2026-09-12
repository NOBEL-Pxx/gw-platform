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
import java.net.InetAddress;
import java.net.UnknownHostException;
import java.util.List;

/**
 * R6.94-A: /actuator/** IP whitelist filter (extended by R6.96-O3 to IPv6).
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
 *   <li>::1/128 — IPv6 loopback (docker exec)</li>
 *   <li>fd00::/8 — IPv6 ULA (Docker Compose v2 IPv6 bridge default)</li>
 *   <li>fe80::/10 — IPv6 link-local</li>
 *   <li>::ffff:172.16.0.0/104 + ::ffff:10.0.0.0/104 + ::ffff:192.168.0.0/112 —
 *       IPv4-mapped IPv6 representations (covered automatically because
 *       {@link InetAddress#getByName(String)} returns the underlying 4-byte
 *       IPv4 address when the input is IPv4-mapped — which matches the
 *       IPv4 CIDRs above byte-for-byte)</li>
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
 *
 * <p>R6.96-O3: IPv6 support — R6.94-A baseline only matched IPv4 prefixes
 * (String.startsWith on dotted-decimal). Docker Compose v2 enables IPv6
 * by default and K8s pod networking is dual-stack; the previous filter
 * silently let every IPv6 client through. Replaced String-prefix matching
 * with CIDR byte comparison via {@link CidrRange} (works for both v4 + v6).
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class ActuatorIpWhitelistFilter extends OncePerRequestFilter {

    private static final Logger log = LoggerFactory.getLogger(ActuatorIpWhitelistFilter.class);
    private static final String ACTUATOR_PATH_PREFIX = "/actuator/";

    /**
     * R6.96-O3: CIDR ranges covering loopback + Docker bridge + private + host,
     * for BOTH IPv4 and IPv6. Implemented as a list of {@link CidrRange} for
     * byte-level matching (R6.94-A's String.startsWith was IPv4-only).
     */
    private static final List<CidrRange> WHITELIST_CIDRS = List.of(
        // ── IPv4 (R6.94-A baseline) ──
        CidrRange.of("127.0.0.0/8"),       // loopback v4 (docker exec into container)
        CidrRange.of("172.16.0.0/12"),     // Docker bridge v4 (172.16-172.31)
        CidrRange.of("10.0.0.0/8"),        // private v4 (alternate Docker compose range)
        CidrRange.of("192.168.0.0/16"),    // host network in dev mode
        // ── IPv6 (R6.96-O3) ──
        CidrRange.of("::1/128"),           // loopback v6 (docker exec into container)
        CidrRange.of("fd00::/8"),          // ULA v6 (Docker Compose v2 IPv6 bridge default)
        CidrRange.of("fe80::/10")          // link-local v6
        // Note: IPv4-mapped IPv6 CIDRs (::ffff:172.16.0.0/104 etc.) are NOT needed
        // because InetAddress.getByName("::ffff:172.16.0.0") returns a 4-byte IPv4
        // address in Java, which byte-matches the IPv4 CIDRs above. So the IPv4
        // entries cover both pure IPv4 AND IPv4-mapped IPv6 inputs.
    );

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
        // remoteAddr from servlet API can be a dotted-decimal ("192.168.1.5"),
        // an IPv6 text form ("0:0:0:0:0:0:0:1" or "::1"), or bracketed
        // ("[::1]:1234" if port suffix is present). Strip brackets if present.
        String normalized = ip;
        if (normalized.startsWith("[") && normalized.contains("]")) {
            normalized = normalized.substring(1, normalized.indexOf(']'));
        }
        InetAddress addr;
        try {
            addr = InetAddress.getByName(normalized);
        } catch (UnknownHostException e) {
            // UnknownHostException means invalid input — fail-closed.
            return false;
        }
        for (CidrRange range : WHITELIST_CIDRS) {
            if (range.contains(addr)) {
                return true;
            }
        }
        return false;
    }

    /**
     * R6.96-O3: minimal CIDR matcher for {@link InetAddress} (supports both
     * IPv4 and IPv6).
     *
     * <p>Stores the network bytes (after applying the mask) and the prefix
     * length. Match is computed by AND-ing the candidate address bytes with
     * the network mask and comparing against the stored network.
     *
     * <p>Example: {@code CidrRange.of("172.16.0.0/12")} matches {@code 172.16.0.1}
     * through {@code 172.31.255.255}.
     */
    private static final class CidrRange {
        private final byte[] network;
        private final int prefixLength;

        static CidrRange of(String cidr) {
            try {
                int slash = cidr.indexOf('/');
                if (slash < 0) {
                    throw new IllegalArgumentException("CIDR must contain '/': " + cidr);
                }
                String addrPart = cidr.substring(0, slash);
                int prefix = Integer.parseInt(cidr.substring(slash + 1));
                InetAddress net = InetAddress.getByName(addrPart);
                byte[] networkBytes = net.getAddress();
                int maxPrefix = networkBytes.length * 8;
                if (prefix < 0 || prefix > maxPrefix) {
                    throw new IllegalArgumentException(
                        "CIDR prefix " + prefix + " out of range [0, " + maxPrefix + "] for " + cidr);
                }
                byte[] masked = applyMask(networkBytes, prefix);
                return new CidrRange(masked, prefix);
            } catch (UnknownHostException e) {
                throw new IllegalArgumentException("Invalid CIDR address: " + cidr, e);
            } catch (NumberFormatException e) {
                throw new IllegalArgumentException("Invalid CIDR prefix length: " + cidr, e);
            }
        }

        private CidrRange(byte[] network, int prefixLength) {
            this.network = network;
            this.prefixLength = prefixLength;
        }

        boolean contains(InetAddress addr) {
            byte[] candidate = addr.getAddress();
            // Mismatched address families (IPv4 vs IPv6) can never match.
            if (candidate.length != network.length) {
                return false;
            }
            byte[] masked = applyMask(candidate, prefixLength);
            for (int i = 0; i < masked.length; i++) {
                if (masked[i] != network[i]) {
                    return false;
                }
            }
            return true;
        }

        /**
         * Apply a CIDR prefix mask to a byte array. The first {@code prefix / 8}
         * bytes are kept as-is; the byte at position {@code prefix / 8} has its
         * upper {@code prefix % 8} bits kept and lower bits zeroed; remaining
         * bytes are zeroed.
         */
        private static byte[] applyMask(byte[] bytes, int prefixLength) {
            byte[] masked = bytes.clone();
            int fullBytes = prefixLength / 8;
            int remainingBits = prefixLength % 8;
            // Zero bytes AFTER the partial byte (if any).
            for (int i = fullBytes + (remainingBits > 0 ? 1 : 0); i < masked.length; i++) {
                masked[i] = 0;
            }
            // Mask the partial byte (if any). e.g. prefixLength=12, fullBytes=1,
            // remainingBits=4 -> keep upper 4 bits, zero lower 4 bits.
            if (remainingBits > 0 && fullBytes < masked.length) {
                int mask = (0xFF << (8 - remainingBits)) & 0xFF;
                masked[fullBytes] = (byte) (masked[fullBytes] & mask);
            }
            return masked;
        }
    }
}