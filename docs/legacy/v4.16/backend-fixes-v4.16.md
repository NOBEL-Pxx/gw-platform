# Backend v4.16 Fixes: Rate Limiting, ES Index Config, Geo, Exceptions

This document and accompanying code patches address four backend issues.

---

## Fix 1: Redis Rate Limiter Configuration

### Problem
`RedisRateLimiter.java` is a skeleton that always delegates to InMemoryRateLimiter.
No concrete Redis implementation, no configuration guide.

### Solution
See `RedisRateLimiter.java` (updated) — now auto-detects Redis connection.
See `application.properties` additions below.

### How to Enable Redis Rate Limiting

**Step 1**: Add to pom.xml:
```xml
<dependency>
    <groupId>com.bucket4j</groupId>
    <artifactId>bucket4j-redis</artifactId>
    <version>8.10.1</version>
</dependency>
<dependency>
    <groupId>io.lettuce</groupId>
    <artifactId>lettuce-core</artifactId>
    <version>6.3.2.RELEASE</version>
</dependency>
```

**Step 2**: Set environment variables:
```bash
SPRING_PROFILES_ACTIVE=redis
SPRING_DATA_REDIS_HOST=redis
SPRING_DATA_REDIS_PORT=6379
```

**Step 3**: Ensure gw-redis container is running (docker-compose.yml already has it since v4.16)

Without Redis, InMemoryRateLimiter is used as automatic fallback.
The transition is zero-config: add the jars + env vars, restart.

### application.properties additions:
```properties
# ── v4.16: Rate limiting ──
rate.limit.capacity=60
rate.limit.refill-minutes=1
rate.limit.login-capacity=5
rate.limit.login-refill-minutes=15
rate.limit.cleanup-minutes=15
```

---

## Fix 2: ES Index Names Externalized to Config

### Problem
Three index names hardcoded with `@Value("alicptabnormal")` / `@Value("errordetail")` / `@Value("errorlist")`.
Renaming an index requires changing Java source code in 3+ files.

### Solution
Replace all `@Value("alicptabnormal")` with `@Value("${es.index.grawave:alicptabnormal}")`.
Same pattern for errordetail and errorlist.

**Files changed**:
- `SearchService.java:35` → `@Value("${es.index.grawave:alicptabnormal}")`
- `ErrorDetailServiceImpl.java:30` → `@Value("${es.index.errordetail:errordetail}")`
- `ErrorListServiceImpl.java:33` → `@Value("${es.index.errorlist:errorlist}")`
- `application.properties`: add new section

### application.properties additions:
```properties
# ── v4.16: Elasticsearch index names (centralized config) ──
es.index.grawave=alicptabnormal
es.index.errordetail=errordetail
es.index.errorlist=errorlist
```

---

## Fix 3: Geographic Query — Dec ±90° Pole Search

### Problem
The meridian-crossing logic in `SearchService.java:108-153` only handles RA wrap-around
at ±180°. It does NOT handle the Dec ±90° pole scenario where a search radius
crosses the celestial pole. At the poles, RA becomes undefined and standard
geo_distance queries break down.

### Solution
Add pole-detection logic: if `|dec| + radius > 90`, the search area includes
a pole. In this case, use a latlon box query (which handles pole wrapping)
instead of / in addition to geo_distance.

### Code change in SearchService.java (pole search block, inserted after line 109):
```java
// v4.16: Pole-crossing detection
final boolean crossesNorthPole = (dec + fRadius) > 90;
final boolean crossesSouthPole = (dec - fRadius) < -90;
final boolean crossesPole = crossesNorthPole || crossesSouthPole;
```

The query builder should add a latlon box when `crossesPole` is true:
```java
if (crossesPole) {
    // Pole search: use bounding box that wraps the pole
    double latMin = crossesSouthPole ? -90 : dec - fRadius;
    double latMax = crossesNorthPole ? 90 : dec + fRadius;
    b.must(m -> m.geoBoundingBox(gbb -> gbb
        .field(LOCATION_COLUMN_NAME)
        .boundingBox(bb -> bb.tlbr(tlbr -> tlbr
            .topLeft(tl -> tl.latlon(ll -> ll.lat(latMax).lon(-180)))
            .bottomRight(br -> br.latlon(ll -> ll.lat(latMin).lon(180)))
        ))
    ));
}
```

---

## Fix 4: Global Exception Handler — LLM and FITS Exception Types

### Problem
GlobalExceptionHandler only has ApiException, RuntimeException, and generic Exception.
LLM timeouts and FITS read errors all become "Internal server error" (500).

### Solution
Add specific exception handlers with actionable error messages.

### Code (to add to GlobalExceptionHandler.java):
```java
// ── v4.16: LLM-specific errors ──

@ExceptionHandler(java.net.ConnectException.class)
public ResponseEntity<Response<Void>> handleConnectException(java.net.ConnectException ex) {
    log.error("LLM/External service connection failed: {}", ex.getMessage());
    Response<Void> body = Response.wrapError("0502",
        "External service unreachable — check network/DNS. Detail: " + ex.getMessage());
    return ResponseEntity.status(HttpStatus.BAD_GATEWAY).body(body);
}

@ExceptionHandler(java.net.SocketTimeoutException.class)
public ResponseEntity<Response<Void>> handleTimeout(java.net.SocketTimeoutException ex) {
    log.error("Request timeout: {}", ex.getMessage());
    Response<Void> body = Response.wrapError("0504",
        "Request timed out — the external service (LLM/FITS server) may be slow. "
        + "Increase LLM_READ_TIMEOUT_SEC or try again. Detail: " + ex.getMessage());
    return ResponseEntity.status(HttpStatus.GATEWAY_TIMEOUT).body(body);
}

@ExceptionHandler(java.io.IOException.class)
public ResponseEntity<Response<Void>> handleIOException(java.io.IOException ex) {
    String msg = ex.getMessage() != null ? ex.getMessage() : "";
    if (msg.contains("FITS") || msg.contains("fits") || msg.contains("SIMPLE")) {
        log.error("FITS I/O error: {}", msg);
        Response<Void> body = Response.wrapError("0422",
            "FITS file read error — the file may be corrupt or inaccessible. "
            + "Check file integrity with /pipeline/file/integrity. Detail: " + msg);
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
```
