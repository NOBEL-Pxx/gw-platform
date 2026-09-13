package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.config;

import org.apache.hc.client5.http.DnsResolver;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.net.InetAddress;
import java.net.UnknownHostException;
import java.util.Arrays;
import java.util.Locale;
import java.util.stream.Collectors;

/**
 * R6.98-D: DNS pinning resolver for outbound HTTPS to china-vo.org.
 *
 * <p>At construction time, resolves {@code hips.china-vo.org} to its
 * current A/AAAA records and caches the result. Subsequent calls to
 * {@link #resolve(String)} return the cached addresses for the pinned
 * host, preventing DNS rebinding attacks that would otherwise redirect
 * the Bearer token to a different IP between TLS handshake and request
 * body transmission.
 *
 * <p>Iron rule R6.98-D (IP pinning variant):
 * <blockquote>
 *   Outbound HTTP to mutable-DNS targets MUST pin resolved IP at validation
 *   time via Apache HttpClient {@code DnsResolver} override. The shared
 *   resolver MUST NOT be used for outbound HTTPS to mutable-DNS hosts.
 * </blockquote>
 *
 * <p>V1 marker logged at construction:
 * <pre>
 *   R6.98-D: DNS resolver pinned for hips.china-vo.org -> [ip1, ip2, ...]
 * </pre>
 *
 * <p>Redirect targets ({@code *.china-vo.org} subdomains returned in
 * the {@code Location} header or {@code image_path} JSON field) are NOT
 * pinned by this resolver — they go through the system resolver and
 * are then validated at the application layer by
 * {@code ImageCutoutDataSet.validateImageUrl} (R6.95-A) and
 * {@code validateResolvedIps} (R6.96-O7), which reject private/loopback
 * addresses. This two-layer design avoids the risk of pinning IPs that
 * the china-vo.org CDN rotates independently per subdomain.
 *
 * <p>Thread-safety: stateless after construction; safe to share across
 * all HttpClient requests.
 */
public final class ChinaVoDnsResolver implements DnsResolver {

    private static final Logger log = LoggerFactory.getLogger(ChinaVoDnsResolver.class);

    /**
     * The pinned host, normalized to lowercase for case-insensitive
     * comparison in {@link #resolve(String)}.
     */
    private final String pinnedHostLower;

    /**
     * Pre-resolved IPs captured at construction time. Returned verbatim
     * (not copied) for each {@code resolve(pinnedHost)} call — the array
     * reference is safe to share because we never mutate it post-construction.
     */
    private final InetAddress[] pinnedAddresses;

    private ChinaVoDnsResolver(String pinnedHost, InetAddress[] pinnedAddresses) {
        this.pinnedHostLower = pinnedHost == null ? "" : pinnedHost.toLowerCase(Locale.ROOT);
        this.pinnedAddresses = pinnedAddresses == null ? new InetAddress[0] : pinnedAddresses;
    }

    /**
     * Production factory: resolve {@code hips.china-vo.org} at startup
     * and cache the addresses. Fails fast (RuntimeException) if DNS
     * resolution fails — the bean refuses to start rather than silently
     * fall back to the system resolver (which would re-open the DNS
     * rebinding attack surface).
     */
    public static ChinaVoDnsResolver forHipsChinaVoOrg() {
        return forHost("hips.china-vo.org");
    }

    /**
     * Generic factory: resolve the given hostname at startup and cache.
     * Visible for testing; production code should use
     * {@link #forHipsChinaVoOrg()} directly.
     */
    public static ChinaVoDnsResolver forHost(String host) {
        try {
            InetAddress[] addrs = InetAddress.getAllByName(host);
            log.info("R6.98-D: DNS resolver pinned for {} -> [{}]", host,
                    Arrays.stream(addrs)
                            .map(InetAddress::getHostAddress)
                            .collect(Collectors.joining(", ")));
            return new ChinaVoDnsResolver(host, addrs);
        } catch (UnknownHostException e) {
            throw new RuntimeException(
                    "R6.98-D: failed to resolve " + host + " for DNS pinning", e);
        }
    }

    /**
     * Test factory: caller provides pre-resolved addresses (no actual
     * DNS lookup). Used by unit tests to avoid DNS dependency.
     */
    public static ChinaVoDnsResolver withPinned(String host, InetAddress[] pinnedAddresses) {
        log.info("R6.98-D: DNS resolver pinned for {} (test mode, {} addresses)",
                host, pinnedAddresses == null ? 0 : pinnedAddresses.length);
        return new ChinaVoDnsResolver(host, pinnedAddresses);
    }

    /**
     * Returns cached IPs for the pinned host, delegates to the system
     * resolver for all other hosts.
     */
    @Override
    public InetAddress[] resolve(String host) throws UnknownHostException {
        if (host != null && host.toLowerCase(Locale.ROOT).equals(pinnedHostLower)) {
            return pinnedAddresses;
        }
        return InetAddress.getAllByName(host);
    }

    /**
     * Returns the canonical hostname. For the pinned host, returns the host
     * string verbatim (we are the authority — pinning IS the canonical answer).
     * For other hosts, resolves via system and returns the canonical name of
     * the first address (the {@code InetAddress.getCanonicalHostName()}
     * contract used by HttpClient's default resolver).
     */
    @Override
    public String resolveCanonicalHostname(String host) throws UnknownHostException {
        if (host != null && host.toLowerCase(Locale.ROOT).equals(pinnedHostLower)) {
            return host;
        }
        return InetAddress.getAllByName(host)[0].getCanonicalHostName();
    }
}
