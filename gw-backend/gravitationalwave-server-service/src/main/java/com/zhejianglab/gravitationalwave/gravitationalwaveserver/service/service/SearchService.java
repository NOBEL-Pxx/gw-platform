package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.service;

import co.elastic.clients.elasticsearch.ElasticsearchClient;
import co.elastic.clients.elasticsearch._types.FieldValue;
import co.elastic.clients.elasticsearch._types.SortOrder;
import co.elastic.clients.elasticsearch.core.SearchResponse;
import co.elastic.clients.elasticsearch.core.search.Hit;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model.GrawaveDataDO;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model.TotalInfoDTO;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.request.QueryGeoSearchRequest;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.response.Response;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.util.ConnectionCheckUtil;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.NoSuchFileException;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.concurrent.ConcurrentHashMap;
import java.util.stream.Collectors;
@Service
public class SearchService {

    @Autowired
    private ElasticsearchClient elasticsearchClient;

    @Autowired
    private ConnectionCheckUtil connectionCheckUtil;

    @Value("${es.index.grawave:alicptabnormal}")
    private String index_name;

    private static final double EARTH_RADIUS = 6378.0;
    private static final String LOCATION_COLUMN_NAME = "mapping_location";
    private static final String IMG_URI_PREFIX = "/api/app/gravitationalwave/static-files/fits-images?imgPath=";

    // v4.54-r4d: same base directory the StaticFileController serves from.
    // Used for Files.exists() probe — if the FITS image is missing on disk,
    // we mark the geoSearch hit isBlank=true so the frontend can badge the
    // tile as "No substantive data" without false-positive canvas heuristics.
    private static final String STATIC_FILES_BASE = "/app/Ali_PW";
    private static final String IMAGE_PATH_PREFIX = "imagefile/";

    // ── Geo-search result cache (meridian-crossing + high-radius optimisation) ──
    // Astronomy data is static (FITS files immutable at runtime), so same
    // (RA, Dec, radius) always returns the same ES result set within a session.
    // This eliminates redundant 2×/3× SHOULD geo-queries on meridian crossings
    // and benefits all repeated searches (e.g. users clicking between pages).
    private final ConcurrentHashMap<String, CacheEntry> geoCache = new ConcurrentHashMap<>();
    private static final int MAX_CACHE_SIZE = 500;
    private static final long CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes

    private static class CacheEntry {
        final Response response;
        final long timestamp;
        CacheEntry(Response response) {
            this.response = response;
            this.timestamp = System.currentTimeMillis();
        }
        boolean isExpired() {
            return System.currentTimeMillis() - timestamp > CACHE_TTL_MS;
        }
    }

    private String cacheKey(QueryGeoSearchRequest req) {
        double ra = req.getRa() != null ? req.getRa() : Double.NaN;
        double dec = req.getDec() != null ? req.getDec() : Double.NaN;
        double rad = req.getRadius() != null ? req.getRadius() : 0;
        String tel = req.getTelescope() != null ? req.getTelescope() : "";
        int page = req.getPageInfo().getPage();
        int size = req.getPageInfo().getPageSize();
        String uuids = req.getUuids() != null ? String.join(",", req.getUuids()) : "";
        return String.format("%.6f_%.6f_%.6f_%s_%d_%d_%s", ra, dec, rad, tel, page, size, uuids);
    }

    private void evictStale() {
        geoCache.entrySet().removeIf(e -> e.getValue().isExpired());
        if (geoCache.size() >= MAX_CACHE_SIZE) {
            // Remove oldest entry to make room
            String oldest = geoCache.keys().nextElement();
            geoCache.remove(oldest);
        }
    }

    public Response geoSearch(QueryGeoSearchRequest request) throws IOException {
        // ── Cache hit? Return immediately (meridian-crossing avoids 2×–3× ES load) ──
        String cacheKey = cacheKey(request);
        CacheEntry cached = geoCache.get(cacheKey);
        if (cached != null && !cached.isExpired()) {
            return cached.response;
        }

        boolean isUp = connectionCheckUtil.isElasticsearchUp();
        if (!isUp) {
            throw new RuntimeException("Elasticsearch is down or connection failed.");
        }
        List<GrawaveDataDO> results = new ArrayList<>();
        final int from = request.getPageInfo().getPageSize() > 0
                ? (request.getPageInfo().getPage() - 1) * request.getPageInfo().getPageSize()
                : 0;
        final int size = request.getPageInfo().getPageSize() > 0
                ? request.getPageInfo().getPageSize()
                : 1000;
        Double dist = null;
        Double lon = null;
        Double radiusDeg = null;
        if (request.getRadius() != null && request.getRadius() > 0
                && request.getRa() != null && request.getDec() != null) {
            dist = calculateGeoDistance(request.getRadius());
            lon = request.getRa() - 180;
            radiusDeg = request.getRadius();
        }
        final Double fDist = dist;
        final Double fLon = lon;
        final Double fRadius = radiusDeg;
        final double dec = request.getDec() != null ? request.getDec() : 0;

        // v4.16: Meridian and pole crossing flags (extracted for scope)
        final boolean meridianCross = fRadius != null
            && ((fLon - fRadius <= -180) || (fLon + fRadius >= 180));
        final boolean crossesNorthPole = fRadius != null && (dec + fRadius) > 90;
        final boolean crossesSouthPole = fRadius != null && (dec - fRadius) < -90;
        final boolean crossesPole = crossesNorthPole || crossesSouthPole;

        SearchResponse<Map> sr = elasticsearchClient.search(s -> s
                .index(index_name)
                .query(q -> q.bool(b -> {
                    if (fDist != null && fLon != null && fRadius != null) {
                        if (!meridianCross) {
                            b.must(m -> m.geoDistance(g -> g
                                    .field(LOCATION_COLUMN_NAME)
                                    .distance(fDist + "km")
                                    .location(l -> l.latlon(
                                            ll -> ll.lat(dec).lon(fLon)))));
                        } else {
                            b.must(m -> m.bool(mb -> {
                                if (fLon - fRadius <= -180) {
                                    double wLon = fLon + 360;
                                    mb.should(ms -> ms.geoDistance(g -> g
                                            .field(LOCATION_COLUMN_NAME)
                                            .distance(fDist + "km")
                                            .location(l -> l.latlon(
                                                    ll -> ll.lat(dec).lon(wLon)))));
                                }
                                if (fLon + fRadius >= 180) {
                                    double eLon = fLon - 360;
                                    mb.should(ms -> ms.geoDistance(g -> g
                                            .field(LOCATION_COLUMN_NAME)
                                            .distance(fDist + "km")
                                            .location(l -> l.latlon(
                                                    ll -> ll.lat(dec).lon(eLon)))));
                                }
                                mb.should(ms -> ms.geoDistance(g -> g
                                        .field(LOCATION_COLUMN_NAME)
                                        .distance(fDist + "km")
                                        .location(l -> l.latlon(
                                                ll -> ll.lat(dec).lon(fLon)))));
                                mb.minimumShouldMatch("1");
                                return mb;
                            }));
                        }
                    }
                    // v4.16: Pole search — bounding box covers the celestial pole
                    if (!meridianCross && crossesPole) {
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
                    if (!StringUtils.isEmpty(request.getTelescope())) {
                        b.must(m -> m.term(t -> t.field("telescope")
                                .value(v -> v.stringValue(request.getTelescope()))));
                    }
                    List<String> uuids = request.getUuids();
                    if (Objects.nonNull(uuids) && !uuids.isEmpty()) {
                        List<FieldValue> fvs = uuids.stream()
                                .map(FieldValue::of)
                                .collect(Collectors.toList());
                        b.must(m -> m.terms(t -> t.field("uuid")
                                .terms(tq -> tq.value(fvs))));
                    }
                    return b;
                }))
                .sort(sort -> sort.field(
                        f -> f.field("start_date").order(SortOrder.Desc)))
                .from(from)
                .size(size),
                Map.class);

        ObjectMapper om = new ObjectMapper();
        long totalHits = sr.hits().total() != null
                ? sr.hits().total().value() : 0;
        if (totalHits > 0) {
            for (Hit<Map> hit : sr.hits().hits()) {
                Map<String, Object> source = hit.source();
                GrawaveDataDO dataDO = om.convertValue(source, GrawaveDataDO.class);
                dataDO.setId(hit.id());
                if (dataDO.getImg_path() != null) {
                    dataDO.setImg_path(dataDO.getImg_path()
                            .replace("imagefile/", "/static-files/image/"));
                }
                if (dataDO.getFits_path() != null) {
                    dataDO.setFits_path(dataDO.getFits_path()
                            .replace("fitsfile/", "/static-files/fits/"));
                }
                // v4.54-r4d: probe disk for the image file. After the path
                // rewrite above, img_path is something like
                //   /static-files/image/<rest-of-path>
                // The on-disk path is /app/Ali_PW/imagefile/<rest-of-path>.
                dataDO.setIsBlank(isImageMissingOnDisk(dataDO.getImg_path()));
                results.add(dataDO);
            }
        }
        TotalInfoDTO ti = TotalInfoDTO.of(
                request.getPageInfo().getPage(),
                request.getPageInfo().getPageSize(),
                totalHits);
        if (request.getPageInfo().getPageSize() == -1) {
            ti = TotalInfoDTO.of(1, (int) totalHits, totalHits);
        }
        Response resp = Response.wrapSuccess(new PageResult<>(results, ti));
        // v4.54-r4d-perf: cache the result BEFORE evicting so the new entry
        // can't be transiently evicted if it happens to be the oldest.
        geoCache.put(cacheKey, new CacheEntry(resp));
        evictStale();
        return resp;
    }

    private double calculateGeoDistance(double deg) {
        return 2 * Math.abs(Math.sin(deg * (Math.PI / 360))) * EARTH_RADIUS;
    }

    // v4.54-r5d: tightened threshold back to 1500. Returns true when the
    // img_path rewritten by SearchService points to a file that does NOT exist
    // on disk OR is a tiny placeholder stub (NVSS 15x15 postage-stamp @ 905B).
    // Real LEGACY g/r/i/z uploaded files (5369-6599 B, valid 554x554 PNGs) now
    // display normally — they were falsely hidden under the 20K r4d threshold.
    //   v4.54-r4d-perf: single Files.size() syscall instead of Files.exists +
    //   Files.size (saves ~50% syscalls). NoSuchFileException catches the
    //   missing-file case cleanly.
    // v4.54-r5d: tightened threshold. Previous 20K falsely flagged LEGACY g/r/i/z
    // (5369-6599 bytes — valid 554x554 PNGs, just faint on disk). Real "missing"
    // signals are sub-1500B placeholders (NVSS postage-stamp @ 905B). Below 1500
    // we hide; above 1500 we show whatever the file is (faint is still data).
    private static final long MIN_BLANK_BYTES = 1_500L;

    private boolean isImageMissingOnDisk(String rewrittenImgPath) {
        if (rewrittenImgPath == null || rewrittenImgPath.isEmpty()) {
            return true;
        }
        // rewrittenImgPath example: "/static-files/image/LEGACY/.../x_g.png"
        // -> on-disk:            "/app/Ali_PW/imagefile/LEGACY/.../x_g.png"
        String relative = rewrittenImgPath.replaceFirst("^/static-files/image/", "");
        if (relative.equals(rewrittenImgPath)) {
            return true;  // unexpected shape -> treat as missing
        }
        Path resolved = Paths.get(STATIC_FILES_BASE, IMAGE_PATH_PREFIX, relative).normalize();
        if (!resolved.startsWith(Paths.get(STATIC_FILES_BASE))) {
            return true;  // path traversal guard
        }
        try {
            return Files.size(resolved) < MIN_BLANK_BYTES;
        } catch (NoSuchFileException nsfe) {
            return true;  // file truly missing
        } catch (IOException ioe) {
            return true;  // any other I/O error -> conservative blank
        }
    }

    public static class PageResult<T> {
        private List<T> list;
        private TotalInfoDTO total_info;
        public PageResult(List<T> list, TotalInfoDTO total_info) {
            this.list = list;
            this.total_info = total_info;
        }
        public List<T> getList() { return list; }
        public TotalInfoDTO getTotal_info() { return total_info; }
    }
}