package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.controller;

import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model.ErrorDetailDO;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model.ErrorDetailResponseDTO;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model.ErrorListDO;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model.PageInfoDTO;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.model.TotalInfoDTO;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.response.Response;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.service.ErrorDetailService;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.service.ErrorListService;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.service.SearchService.PageResult;
import org.springframework.beans.BeanUtils;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.stream.Collectors;

@Component
@RestController
@RequestMapping("/api/app/gravitationalwave/error")
public class ErrorController {

    @Autowired
    private ErrorListService errorListService;

    @Autowired
    private ErrorDetailService errorDetailService;

    private static final int MAX_PAGE_SIZE = 1000;

    private void checkParam(boolean checkBool, String message) {
        if (!checkBool) {
            throw new RuntimeException(message);
        }
    }

    @GetMapping
    public Response<Map<String, Object>> getErrorReportList(
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "-1") int page_size) {
        checkParam(page >= 1, "Invalid page value: must be greater than or equal to 1");
        checkParam(page_size >= -1, "Invalid pageSize value: must be greater than or equal to -1");

        int size = page_size == -1 ? MAX_PAGE_SIZE : Math.min(page_size, MAX_PAGE_SIZE);
        PageInfoDTO pageInfo = new PageInfoDTO(page, size);
        PageResult<ErrorListDO> result = errorListService.queryErrorList(null, null, null, null, null, pageInfo);

        Map<String, Object> data = new LinkedHashMap<>();
        data.put("list", result.getList());
        data.put("total_info", TotalInfoDTO.of(page, size, result.getTotal_info().getTotal_count()));

        return Response.wrapSuccess(data);
    }

    @GetMapping("/{error_id}")
    public Response<Map<String, Object>> getErrorReportDetail(
            @PathVariable String error_id,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "10") int page_size) {
        checkParam(Objects.nonNull(error_id) && !error_id.isEmpty(), "Invalid error_id: must not be null or empty");
        checkParam(page >= 1, "Invalid page value: must be greater than or equal to 1");
        checkParam(page_size >= 1, "Invalid pageSize value: must be greater than or equal to 1");

        int size = Math.min(page_size, MAX_PAGE_SIZE);
        PageInfoDTO pageInfo = new PageInfoDTO(page, size);
        PageResult<ErrorDetailDO> result = errorDetailService.queryByErrorId(error_id, pageInfo);

        Map<String, Object> data = new LinkedHashMap<>();
        if (!result.getList().isEmpty()) {
            ErrorDetailDO firstDetail = result.getList().get(0);
            data.put("error_id", firstDetail.getError_id());
            data.put("logContent", firstDetail.getLogContent());
        }

        List<ErrorDetailResponseDTO> dtoList = result.getList().stream()
                .map(detail -> {
                    ErrorDetailResponseDTO dto = new ErrorDetailResponseDTO();
                    BeanUtils.copyProperties(detail, dto);
                    return dto;
                })
                .collect(Collectors.toList());

        data.put("list", dtoList);
        data.put("total_info", result.getTotal_info());

        return Response.wrapSuccess(data);
    }
}