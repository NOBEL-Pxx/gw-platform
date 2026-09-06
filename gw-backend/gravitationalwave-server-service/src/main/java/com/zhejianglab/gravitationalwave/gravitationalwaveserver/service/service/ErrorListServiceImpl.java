package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.service;

import co.elastic.clients.elasticsearch.ElasticsearchClient;
import co.elastic.clients.elasticsearch._types.FieldValue;
import co.elastic.clients.elasticsearch._types.SortOrder;
import co.elastic.clients.elasticsearch.core.SearchResponse;
import co.elastic.clients.elasticsearch.core.search.Hit;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model.ErrorListDO;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model.PageInfoDTO;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model.TotalInfoDTO;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.service.ErrorListService;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.service.SearchService.PageResult;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.util.CollectionUtils;
import org.springframework.util.StringUtils;

import java.io.IOException;
import java.lang.reflect.Field;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.stream.Collectors;
@Service
public class ErrorListServiceImpl implements ErrorListService {

    @Autowired
    private ElasticsearchClient elasticsearchClient;

    @Value("${es.index.errorlist:errorlist}")
    private String index_name;

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Override
    public PageResult<ErrorListDO> queryErrorList(
            String telescope, String band, List<String> anomaly_type,
            String start_date, String end_date, PageInfoDTO pageInfo) {

        int rawPage = 1;
        int rawPageSize = 10;
        try {
            Field pageField = PageInfoDTO.class.getDeclaredField("page");
            pageField.setAccessible(true);
            rawPage = (int) pageField.get(pageInfo);

            Field pageSizeField = PageInfoDTO.class.getDeclaredField("pageSize");
            pageSizeField.setAccessible(true);
            rawPageSize = (int) pageSizeField.get(pageInfo);
        } catch (NoSuchFieldException | IllegalAccessException e) {
            throw new RuntimeException("Failed to get page params", e);
        }
        final int page = rawPage;
        final int pageSize = rawPageSize;
        final int from = (page - 1) * pageSize;

        try {
            SearchResponse<Map> response = elasticsearchClient.search(s -> s
                    .index(index_name)
                    .query(q -> q.bool(b -> {
                        if (StringUtils.hasText(telescope)) {
                            b.must(m -> m.term(t -> t.field("telescope")
                                    .value(FieldValue.of(telescope))));
                        }
                        if (StringUtils.hasText(band)) {
                            b.must(m -> m.term(t -> t.field("band")
                                    .value(FieldValue.of(band))));
                        }
                        if (!CollectionUtils.isEmpty(anomaly_type)) {
                            List<FieldValue> fvs = anomaly_type.stream()
                                    .map(FieldValue::of)
                                    .collect(Collectors.toList());
                            b.must(m -> m.terms(t -> t.field("anomaly_type")
                                    .terms(tq -> tq.value(fvs))));
                        }
                        if (StringUtils.hasText(start_date)) {
                            b.filter(f -> f.range(r -> r.date(dr -> dr.field("start_date").gte(start_date))));
                        }
                        if (StringUtils.hasText(end_date)) {
                            b.filter(f -> f.range(r -> r.date(dr -> dr.field("end_date").lte(end_date))));
                        }
                        return b;
                    }))
                    .sort(sort -> sort.field(
                            f -> f.field("start_date").order(SortOrder.Desc)))
                    .from(from)
                    .size(pageSize),
                    Map.class);
            // Parse results
            List<ErrorListDO> results = new ArrayList<>();
            if (response.hits().total() != null && response.hits().total().value() > 0) {
                for (Hit<Map> hit : response.hits().hits()) {
                    Map<String, Object> source = hit.source();
                    ErrorListDO error = objectMapper.convertValue(source, ErrorListDO.class);
                    error.setId(hit.id());
                    results.add(error);
                }
            }

            TotalInfoDTO totalInfo = TotalInfoDTO.of(
                    page,
                    pageSize,
                    response.hits().total() != null ? response.hits().total().value() : 0
            );
            return new PageResult<>(results, totalInfo);

        } catch (IOException e) {
            throw new RuntimeException("查询errorlist失败", e);
        }
    }

    @Override
    public ErrorListDO getErrorListByErrorId(String error_id) {
        try {
            SearchResponse<Map> response = elasticsearchClient.search(s -> s
                    .index(index_name)
                    .query(q -> q.term(t -> t.field("error_id")
                            .value(FieldValue.of(error_id))))
                    .size(1),
                    Map.class);

            if (response.hits().total() != null && response.hits().total().value() > 0) {
                Map<String, Object> source = response.hits().hits().get(0).source();
                ErrorListDO error = objectMapper.convertValue(source, ErrorListDO.class);
                error.setId(response.hits().hits().get(0).id());
                return error;
            }
            return null;
        } catch (IOException e) {
            throw new RuntimeException("查询errorlist失败", e);
        }
    }
}