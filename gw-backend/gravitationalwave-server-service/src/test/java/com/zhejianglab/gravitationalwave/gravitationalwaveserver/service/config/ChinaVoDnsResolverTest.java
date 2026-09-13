package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.config;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.net.InetAddress;
import java.net.UnknownHostException;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * R6.98-D: unit tests for {@link ChinaVoDnsResolver} DNS pinning behavior.
 *
 * <p>Approach: use {@link ChinaVoDnsResolver#withPinned(String, InetAddress[])}
 * to construct the resolver with synthetic InetAddress arrays (no actual
 * DNS lookup), then exercise the {@link ChinaVoDnsResolver#resolve(String)}
 * method.
 *
 * <p>The {@link ChinaVoDnsResolver#forHost(String)} factory is covered by
 * a single smoke test that skips if DNS is unreachable in the test env.
 */
class ChinaVoDnsResolverTest {

    @Test
    @DisplayName("R6.98-D: resolve() returns cached addresses for pinned host (case-insensitive)")
    void resolveReturnsCachedAddressesForPinnedHost() throws UnknownHostException {
        InetAddress[] pinned = new InetAddress[]{
                InetAddress.getByAddress(new byte[]{(byte) 202, (byte) 127, (byte) 0, 1}),
                InetAddress.getByAddress(new byte[]{(byte) 202, (byte) 127, (byte) 0, 2})
        };
        ChinaVoDnsResolver resolver = ChinaVoDnsResolver.withPinned("hips.china-vo.org", pinned);

        // Exact match
        InetAddress[] resolved = resolver.resolve("hips.china-vo.org");
        assertNotNull(resolved, "must return non-null array for pinned host");
        assertArrayEquals(pinned, resolved, "must return the same cached addresses");

        // Case-insensitive
        InetAddress[] resolvedUpper = resolver.resolve("HIPS.CHINA-VO.ORG");
        assertArrayEquals(pinned, resolvedUpper,
                "must match pinned host case-insensitively");
    }

    @Test
    @DisplayName("R6.98-D: resolve() delegates to system resolver for non-pinned hosts")
    void resolveDelegatesToSystemForOtherHosts() throws UnknownHostException {
        InetAddress[] pinned = new InetAddress[]{
                InetAddress.getByAddress(new byte[]{(byte) 202, (byte) 127, (byte) 0, 1})
        };
        ChinaVoDnsResolver resolver = ChinaVoDnsResolver.withPinned("hips.china-vo.org", pinned);

        // localhost should resolve via system (returns loopback) — NOT pinned addresses.
        InetAddress[] resolved = resolver.resolve("localhost");
        assertNotNull(resolved, "must return non-null for system-resolved hosts");
        assertTrue(resolved.length > 0, "system resolver should return at least one address");
        // The cached pinned IP must NOT leak into non-pinned resolution.
        for (InetAddress addr : resolved) {
            byte[] bytes = addr.getAddress();
            boolean isPinned = bytes.length == 4
                    && bytes[0] == (byte) 202 && bytes[1] == (byte) 127
                    && bytes[2] == 0 && bytes[3] == 1;
            assertTrue(!isPinned,
                    "non-pinned host must NOT return pinned IP; got " + addr.getHostAddress());
        }
    }

    @Test
    @DisplayName("R6.98-D: resolve() returns empty array when pinned addresses is null/empty")
    void resolveReturnsEmptyArrayWhenPinnedIsEmpty() throws UnknownHostException {
        ChinaVoDnsResolver resolver = ChinaVoDnsResolver.withPinned("hips.china-vo.org", null);
        InetAddress[] resolved = resolver.resolve("hips.china-vo.org");
        assertNotNull(resolved, "must return non-null even when pinned array is null");
        assertTrue(resolved.length == 0,
                "must return empty array when pinned array is null; got length=" + resolved.length);
    }

    @Test
    @DisplayName("R6.98-D: withPinned() handles null host gracefully")
    void withPinnedHandlesNullHost() throws UnknownHostException {
        // Should not throw — null host becomes "" in pinnedHostLower, no host matches "".
        ChinaVoDnsResolver resolver = ChinaVoDnsResolver.withPinned(null,
                new InetAddress[]{InetAddress.getByAddress(new byte[]{127, 0, 0, 1})});
        InetAddress[] resolved = resolver.resolve("hips.china-vo.org");
        // "hips.china-vo.org".toLowerCase() = "hips.china-vo.org" != "" (pinnedHostLower)
        // → delegates to system resolver
        assertNotNull(resolved);
    }

    @Test
    @DisplayName("R6.98-D: forHost() throws RuntimeException on unresolvable host")
    void forHostFailsFastOnUnresolvable() {
        // A hostname that does not resolve → RuntimeException wrapping UnknownHostException.
        RuntimeException ex = assertThrows(RuntimeException.class,
                () -> ChinaVoDnsResolver.forHost(
                        "this-host-definitely-does-not-exist.invalid-tld-9999"));
        assertTrue(ex.getMessage().contains("R6.98-D"),
                "error must mention R6.98-D marker; got: " + ex.getMessage());
    }
}
