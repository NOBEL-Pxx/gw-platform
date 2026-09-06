package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.service;

import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model.ErrorDetailDO;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model.PageInfoDTO;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.service.SearchService.PageResult;

public interface ErrorDetailService {
    PageResult<ErrorDetailDO> queryByErrorId(String error_id, PageInfoDTO pageInfo);
}