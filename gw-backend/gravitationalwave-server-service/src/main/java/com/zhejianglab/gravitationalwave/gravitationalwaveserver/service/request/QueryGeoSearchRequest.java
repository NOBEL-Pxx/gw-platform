package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.request;

import lombok.Data;

import java.util.List;

@Data
public class QueryGeoSearchRequest {

    private Double ra;
    private Double dec;
    private Double radius;
    private String telescope;
    private PageInfo pageInfo;
    private List<String> uuids;

    @Data
    public static class PageInfo {
        private int page;
        private int pageSize;
    }
}
