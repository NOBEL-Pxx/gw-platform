package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.service;

import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model.ErrorListDO;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model.PageInfoDTO;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.service.SearchService.PageResult;

import java.util.List;

public interface ErrorListService {
    PageResult<ErrorListDO> queryErrorList(
            String telescope,
            String band,
            List<String> anomaly_type,
            String start_date,
            String end_date,
            PageInfoDTO pageInfo);

    ErrorListDO getErrorListByErrorId(String error_id);
}