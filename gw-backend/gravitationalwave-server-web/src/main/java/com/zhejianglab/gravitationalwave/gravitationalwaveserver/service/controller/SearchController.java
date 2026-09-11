package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.controller;

import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.request.QueryGeoSearchRequest;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.response.ApiException;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.response.Response;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.service.SearchService;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.validation.CoordinateValidator;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import java.io.IOException;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.Objects;

@Component
@RestController
@RequestMapping("/api/app/gravitationalwave")
public class SearchController {

    private static final Logger log = LoggerFactory.getLogger(SearchController.class);

    @Autowired
    private SearchService searchService;

    /**
     * R6.85-A-V1MARKER: emit a recognizable startup log line so {@code build-and-deploy-jar.py}'s
     * {@code check_marker_log} AND-check can confirm the bean lifecycle completed for this
     * controller. See [[r685-summary]] for the R6.85 iron-rule convention.
     */
    @PostConstruct
    public void init() {
        log.info("R6.88: SearchController initialized");
    }

    /**
     * R6.85-A-PREDESTROY: log shutdown so a container restart leaves a visible lifecycle trace.
     * SearchController owns no RestTemplate/ExecutorService, so nothing to close; this is
     * symmetry with R6.85b (LlmController + PipelineProxyController) for the post-deploy marker
     * scanner.
     */
    @PreDestroy
    public void shutdown() {
        log.info("R6.88: SearchController shutting down");
    }

    @GetMapping("/geoSearch")
    public Response<?> geoSearch(@RequestParam(required = false) Double ra,
                                 @RequestParam(required = false) Double dec,
                                 @RequestParam(required = false, defaultValue = "1") Double radius,
                                 @RequestParam(required = false, defaultValue = "") String telescope,
                                 @RequestParam(required = false) String uuid,
                                 @RequestParam(defaultValue = "1") int page,
                                 @RequestParam(defaultValue = "-1") int page_size) throws IOException {

        // R6.85-A-NULLGUARD: if @Autowired failed (e.g., SearchService bean missing), surface a
        // 503 rather than letting the framework bubble an NPE to the caller.
        if (searchService == null) {
            log.error("SearchService not initialized — please retry in a moment");
            return Response.wrapError("503", "Search service not initialized — please retry in a moment");
        }

        String coordErr = CoordinateValidator.validate(ra, dec, radius);
        if (coordErr != null) {
            throw ApiException.badRequest(coordErr);
        }
        if (page < 1) {
            throw ApiException.badRequest("Invalid page value: must be >= 1");
        }

        QueryGeoSearchRequest request = new QueryGeoSearchRequest();
        request.setRa(ra);
        request.setDec(dec);
        request.setTelescope(telescope);
        request.setRadius(radius);

        if (Objects.nonNull(uuid) && !uuid.isEmpty()) {
            List<String> uuidList = Arrays.asList(uuid.split(","));
            request.setUuids(uuidList);
        }

        QueryGeoSearchRequest.PageInfo pageInfo = new QueryGeoSearchRequest.PageInfo();
        pageInfo.setPage(page);
        pageInfo.setPageSize(page_size);
        request.setPageInfo(pageInfo);

        return searchService.geoSearch(request);
    }

    /**
     * Export all observations as CSV. Returns all matching records with headers.
     * v4.12: Enables offline analysis, spreadsheet import, and data sharing.
     */
    @GetMapping(value = "/export/csv", produces = "text/csv;charset=UTF-8")
    public String exportCsv(@RequestParam(required = false) Double ra,
                            @RequestParam(required = false) Double dec,
                            @RequestParam(required = false, defaultValue = "1") Double radius,
                            @RequestParam(required = false, defaultValue = "") String telescope) throws IOException {
        // R6.85-A-NULLGUARD: same defense as geoSearch — surface a clear error rather than NPE.
        if (searchService == null) {
            log.error("SearchService not initialized — please retry in a moment");
            return "Search service not initialized — please retry in a moment";
        }

        QueryGeoSearchRequest request = new QueryGeoSearchRequest();
        request.setRa(ra);
        request.setDec(dec);
        request.setRadius(radius);
        request.setTelescope(telescope);
        QueryGeoSearchRequest.PageInfo pageInfo = new QueryGeoSearchRequest.PageInfo();
        pageInfo.setPage(1);
        pageInfo.setPageSize(-1);
        request.setPageInfo(pageInfo);

        Response<?> result = searchService.geoSearch(request);
        @SuppressWarnings("unchecked")
        SearchService.PageResult<com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model.GrawaveDataDO> pageResult =
            (SearchService.PageResult<com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model.GrawaveDataDO>) result.getData();
        java.util.List<com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model.GrawaveDataDO> list = pageResult.getList();
        if (list.isEmpty()) return "No data found";

        StringBuilder sb = new StringBuilder();
        sb.append("id,band,ra,dec,start_date,end_date,telescope,img_path,fits_path\r\n");
        for (com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model.GrawaveDataDO row : list) {
            sb.append(escapeCsv(row.getId())).append(",");
            sb.append(escapeCsv(row.getBand())).append(",");
            sb.append(row.getRa()).append(",");
            sb.append(row.getDec()).append(",");
            sb.append(escapeCsv(row.getStart_date())).append(",");
            sb.append(escapeCsv(row.getEnd_date())).append(",");
            sb.append(escapeCsv(row.getTelescope())).append(",");
            sb.append(escapeCsv(row.getImg_path())).append(",");
            sb.append(escapeCsv(row.getFits_path())).append("\r\n");
        }
        return sb.toString();
    }

    private String escapeCsv(Object val) {
        if (val == null) return "";
        String s = val.toString();
        if (s.contains(",") || s.contains("\"")) {
            return "\"" + s.replace("\"", "\"\"") + "\"";
        }
        return s;
    }
}
