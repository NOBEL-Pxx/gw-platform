package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.service.impl;

import co.elastic.clients.elasticsearch.ElasticsearchClient;
import co.elastic.clients.elasticsearch._types.FieldValue;
import co.elastic.clients.elasticsearch._types.SortOrder;
import co.elastic.clients.elasticsearch.core.SearchResponse;
import co.elastic.clients.elasticsearch.core.search.Hit;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model.ErrorDetailDO;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model.PageInfoDTO;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model.TotalInfoDTO;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.service.ErrorDetailService;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.service.SearchService.PageResult;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.lang.reflect.Field;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

@Service
public class ErrorDetailServiceImpl implements ErrorDetailService {

    @Autowired
    private ElasticsearchClient elasticsearchClient;

    @Value("${es.index.errordetail:errordetail}")
    private String index_name;

    private final ObjectMapper objectMapper = new ObjectMapper();

    // 最大返回条数限制（避免ES分页超限）
    private static final int MAX_PAGE_SIZE = 1000;

    @Override
    public PageResult<ErrorDetailDO> queryByErrorId(String error_id, PageInfoDTO pageInfo) {
        // 1. Parse pagination params
        int page = 1;
        int pageSize = 10;
        try {
            Field pageField = PageInfoDTO.class.getDeclaredField("page");
            pageField.setAccessible(true);
            page = (int) pageField.get(pageInfo);

            Field pageSizeField = PageInfoDTO.class.getDeclaredField("pageSize");
            pageSizeField.setAccessible(true);
            pageSize = (int) pageSizeField.get(pageInfo);
        } catch (NoSuchFieldException | IllegalAccessException e) {
            throw new RuntimeException("获取分页参数失败", e);
        }

        // 2. Clamp page size
        int finalPageSize = Math.min(pageSize, MAX_PAGE_SIZE);
        int from = (page - 1) * finalPageSize;

        // 3. Execute ES 8.x query — unified client (migrated from RestHighLevelClient)
        try {
            SearchResponse<Map> response = elasticsearchClient.search(s -> s
                    .index(index_name)
                    .query(q -> q.term(t -> t.field("error_id")
                            .value(FieldValue.of(error_id))))
                    .sort(sort -> sort.field(
                            f -> f.field("anomaly_type").order(SortOrder.Asc)))
                    .from(from)
                    .size(finalPageSize),
                    Map.class);

            List<ErrorDetailDO> results = new ArrayList<>();

            // 4. Parse hits
            if (response.hits().total() != null && response.hits().total().value() > 0) {
                for (Hit<Map> hit : response.hits().hits()) {
                    Map<String, Object> source = hit.source();
                    ErrorDetailDO detail = objectMapper.convertValue(source, ErrorDetailDO.class);
                    detail.setId(hit.id());
                    results.add(detail);
                }
            }

            // 5. Build pagination info
            TotalInfoDTO totalInfo = TotalInfoDTO.of(
                    page,
                    finalPageSize,
                    response.hits().total() != null ? response.hits().total().value() : 0
            );
            return new PageResult<>(results, totalInfo);

        } catch (IOException e) {
            throw new RuntimeException("查询errordetail失败", e);
        }
    }
}
