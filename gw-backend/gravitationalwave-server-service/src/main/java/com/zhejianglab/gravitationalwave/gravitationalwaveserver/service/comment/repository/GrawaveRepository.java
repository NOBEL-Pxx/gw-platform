package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.comment.repository;



import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model.ErrorDetailDO;
import org.springframework.data.elasticsearch.repository.ElasticsearchRepository;

public interface GrawaveRepository extends ElasticsearchRepository<ErrorDetailDO, String> {
}
