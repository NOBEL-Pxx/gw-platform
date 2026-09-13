package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.config;

import org.apache.hc.client5.http.config.ConnectionConfig;
import org.apache.hc.client5.http.config.RequestConfig;
import org.apache.hc.client5.http.impl.classic.CloseableHttpClient;
import org.apache.hc.client5.http.impl.classic.HttpClients;
import org.apache.hc.client5.http.impl.io.PoolingHttpClientConnectionManager;
import org.apache.hc.client5.http.impl.io.PoolingHttpClientConnectionManagerBuilder;
import org.apache.hc.client5.http.ssl.SSLConnectionSocketFactory;
import org.apache.hc.core5.util.TimeValue;
import org.apache.hc.core5.util.Timeout;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import javax.net.ssl.SSLContext;
import javax.net.ssl.TrustManager;
import javax.net.ssl.TrustManagerFactory;
import javax.net.ssl.X509TrustManager;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.cert.X509Certificate;

/**
 * R6.98-A: TLS pubkey SHA-256 pinning helper for outbound HTTPS to
 * third-party services (api.deepseek.com, china-vo.org).
 *
 * <p>Builds a {@link CloseableHttpClient} whose {@link SSLContext} uses a
 * {@link TrustManager} that REJECTS any peer certificate whose SubjectPublicKeyInfo
 * SHA-256 fingerprint is NOT in the supplied allowlist. This closes the
 * R6.95/97-deferred <b>O-4 TLS pinning</b> item.
 *
 * <p>Iron rule R6.98-A (TLS variant):
 * <blockquote>
 *   All outbound HTTPS to third-party services MUST go through a pinned
 *   {@code CloseableHttpClient} built by {@link TlsPinningHttpClientFactory}.
 *   No ad-hoc {@code new RestTemplate()} or default
 *   {@code HttpClients.createSystem()} for cross-network calls.
 * </blockquote>
 *
 * <p><b>Cert capture strategy</b>: TOFU (Trust on First Use) at startup.
 * The factory takes the pinned fingerprint as a constructor argument; ops
 * is responsible for capturing the cert fingerprint on first deploy and
 * committing the hex string as a {@code @Value} config (e.g.
 * {@code deepseek.api.pinned-cert-sha256}). If the pinned fingerprint
 * doesn't match the cert returned by the server at handshake time, the
 * connection fails closed.
 *
 * <p><b>Why not just use the JVM default truststore?</b> The default
 * truststore trusts ~150 root CAs. An attacker with a misissued cert from
 * any of those CAs can MITM the connection. Pinning restricts trust to
 * exactly the certificate we expect.
 *
 * <p><b>TOFU rotation</b>: when api.deepseek.com rotates their cert, ops
 * must (1) capture the new SHA-256 from a trusted channel, (2) update the
 * config, (3) restart. There is no automatic rotation. This is acceptable
 * for the current threat model (defense-in-depth on top of TLS + CDN).
 */
public final class TlsPinningHttpClientFactory {

    private static final Logger log = LoggerFactory.getLogger(TlsPinningHttpClientFactory.class);

    /** Same pool sizing as {@code HttpClientConfig} (R6.98-B iron rule). */
    private static final int MAX_CONN_TOTAL = 100;
    private static final int MAX_CONN_PER_ROUTE = 20;

    /** Same timeouts as {@code HttpClientConfig}. */
    private static final Timeout CONNECT_TIMEOUT = Timeout.ofSeconds(10);
    private static final Timeout RESPONSE_TIMEOUT = Timeout.ofSeconds(30);
    private static final TimeValue CONN_KEEP_ALIVE = TimeValue.ofMinutes(3);

    private TlsPinningHttpClientFactory() {}

    /**
     * Build a {@link CloseableHttpClient} that pins TLS certificates to the
     * given SHA-256 fingerprints.
     *
     * @param pinnedFingerprintHex  Lowercase hex SHA-256 of the SubjectPublicKeyInfo
     *                              (SPKI) of the expected peer certificate. Must be
     *                              exactly 64 hex chars (256 bits).
     * @param hostDescription       Human-readable host name for log markers, e.g.
     *                              "api.deepseek.com". Used in V1 marker log.
     * @return a configured {@link CloseableHttpClient}
     * @throws IllegalArgumentException if the fingerprint is not 64 lowercase hex chars
     */
    public static CloseableHttpClient build(String pinnedFingerprintHex, String hostDescription) {
        validateFingerprint(pinnedFingerprintHex);
        SSLContext sslContext = buildPinnedSslContext(pinnedFingerprintHex);

        // HttpClient 5.4.x: SSLContext is wired via SSLConnectionSocketFactory
        // passed to the connection manager builder (no setSSLContext on the
        // builder itself in this version).
        SSLConnectionSocketFactory sslSf = new SSLConnectionSocketFactory(sslContext);

        PoolingHttpClientConnectionManager connManager = PoolingHttpClientConnectionManagerBuilder.create()
                .setMaxConnTotal(MAX_CONN_TOTAL)
                .setMaxConnPerRoute(MAX_CONN_PER_ROUTE)
                .setDefaultConnectionConfig(ConnectionConfig.custom()
                        .setConnectTimeout(CONNECT_TIMEOUT)
                        .setSocketTimeout(RESPONSE_TIMEOUT)
                        .setTimeToLive(CONN_KEEP_ALIVE)
                        .build())
                .setSSLSocketFactory(sslSf)
                .build();

        RequestConfig requestConfig = RequestConfig.custom()
                .setConnectionRequestTimeout(CONNECT_TIMEOUT)
                .setResponseTimeout(RESPONSE_TIMEOUT)
                .build();

        CloseableHttpClient client = HttpClients.custom()
                .setConnectionManager(connManager)
                .setDefaultRequestConfig(requestConfig)
                .setKeepAliveStrategy((response, context) -> CONN_KEEP_ALIVE)
                .build();

        log.info("R6.98: TLS pinning active for {} (cert SHA-256: {})",
                hostDescription, pinnedFingerprintHex);
        return client;
    }

    /**
     * Build an {@link SSLContext} whose {@link TrustManager} accepts ONLY
     * certificates whose SPKI SHA-256 matches the pinned fingerprint.
     */
    private static SSLContext buildPinnedSslContext(String pinnedFingerprintHex) {
        try {
            // Start from the JVM default trust manager (so we can do the
            // standard chain validation first), then post-filter by fingerprint.
            TrustManagerFactory tmf = TrustManagerFactory.getInstance(
                    TrustManagerFactory.getDefaultAlgorithm());
            tmf.init((java.security.KeyStore) null);
            TrustManager[] defaultManagers = tmf.getTrustManagers();
            X509TrustManager defaultTm = null;
            for (TrustManager tm : defaultManagers) {
                if (tm instanceof X509TrustManager) {
                    defaultTm = (X509TrustManager) tm;
                    break;
                }
            }
            if (defaultTm == null) {
                throw new IllegalStateException("no X509TrustManager found in default truststore");
            }

            final X509TrustManager capturedDefaultTm = defaultTm;
            X509TrustManager pinnedTm = new X509TrustManager() {
                @Override
                public void checkClientTrusted(X509Certificate[] chain, String authType)
                        throws java.security.cert.CertificateException {
                    // We're a client; we never accept client certs.
                    throw new java.security.cert.CertificateException(
                            "R6.98-A: client certs not trusted (server-only pinning)");
                }

                @Override
                public void checkServerTrusted(X509Certificate[] chain, String authType)
                        throws java.security.cert.CertificateException {
                    // Step 1: chain validation against JVM default truststore.
                    capturedDefaultTm.checkServerTrusted(chain, authType);

                    // Step 2: SPKI SHA-256 must match pinned fingerprint.
                    if (chain == null || chain.length == 0) {
                        throw new java.security.cert.CertificateException(
                                "R6.98-A: empty cert chain");
                    }
                    X509Certificate leaf = chain[0];
                    String fingerprint = computeSpkiSha256Hex(leaf);
                    if (!fingerprint.equalsIgnoreCase(pinnedFingerprintHex)) {
                        throw new java.security.cert.CertificateException(
                                "R6.98-A: cert SPKI SHA-256 mismatch. expected="
                                + pinnedFingerprintHex + " actual=" + fingerprint);
                    }
                }

                @Override
                public X509Certificate[] getAcceptedIssuers() {
                    return capturedDefaultTm.getAcceptedIssuers();
                }
            };

            SSLContext ctx = SSLContext.getInstance("TLS");
            ctx.init(null, new TrustManager[]{pinnedTm}, null);
            return ctx;
        } catch (Exception e) {
            throw new RuntimeException(
                    "R6.98-A: failed to build pinned SSLContext: " + e.getMessage(), e);
        }
    }

    /**
     * Compute the lowercase hex SHA-256 of the SubjectPublicKeyInfo (SPKI)
     * DER encoding. SPKI is the canonical public key representation -- if
     * the CA reissues the cert with a different validity window but the
     * same key pair, the SPKI hash is unchanged. Pinning SPKI (rather than
     * the full cert) is the modern best practice (RFC 7469, RFC 5280).
     */
    private static String computeSpkiSha256Hex(X509Certificate cert) {
        try {
            byte[] spki = cert.getPublicKey().getEncoded(); // X509 public-key format = SPKI DER
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] hash = md.digest(spki);
            StringBuilder sb = new StringBuilder(hash.length * 2);
            for (byte b : hash) sb.append(String.format("%02x", b));
            return sb.toString();
        } catch (NoSuchAlgorithmException e) {
            throw new RuntimeException("SHA-256 not available: " + e.getMessage(), e);
        }
    }

    private static void validateFingerprint(String fp) {
        if (fp == null || fp.length() != 64) {
            throw new IllegalArgumentException(
                    "R6.98-A: pinned fingerprint must be 64 hex chars (256 bits); got length="
                    + (fp == null ? "null" : fp.length()));
        }
        for (int i = 0; i < fp.length(); i++) {
            char c = fp.charAt(i);
            if (!(Character.isDigit(c) || (c >= 'a' && c <= 'f'))) {
                throw new IllegalArgumentException(
                        "R6.98-A: pinned fingerprint must be lowercase hex; got char '"
                        + c + "' at index " + i);
            }
        }
    }
}
