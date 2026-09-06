package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.comment.controller;

import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.comment.model.Comment;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.comment.service.CommentService;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.response.ApiException;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.response.Response;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.validation.PageNormalizer;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.data.domain.Page;

import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/api/app/gravitationalwave/comments")
public class CommentController {

    @Autowired
    private CommentService commentService;

    @PostMapping
    public Response<Map<String, Object>> createComment(@RequestBody CommentRequest request,
                                                        HttpServletRequest httpRequest) {
        if (request.getGrawaveId() == null || request.getGrawaveId().trim().isEmpty()) {
            throw ApiException.badRequest("grawaveId can not be null or empty");
        }

        String userId = (String) httpRequest.getAttribute("currentUserId");
        if (userId == null || userId.trim().isEmpty()) {
            throw ApiException.unauthorized("Authentication required to post comments. Please login first.");
        }
        // v4.13: Use login username (not MongoDB ID) for display
        String username = (String) httpRequest.getAttribute("currentUsername");
        if (username == null || username.trim().isEmpty()) {
            username = userId; // fallback to userId if username not available
        }

        Comment comment = commentService.addComment(
                request.getGrawaveId(),
                request.getContent(),
                userId,
                username,
                request.getCategory()
        );

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("id", comment.getId());
        result.put("content", comment.getContent());
        result.put("grawaveId", comment.getGrawaveId());
        result.put("userId", comment.getUserId());
        result.put("username", comment.getUsername());
        result.put("category", comment.getCategory());
        result.put("createdAt", comment.getCreatedAt());
        return Response.wrapSuccess(result);
    }

    @DeleteMapping("/{commentId}")
    public Response<Map<String, Object>> deleteComment(@PathVariable String commentId,
                                                        HttpServletRequest httpRequest) {
        String userId = (String) httpRequest.getAttribute("currentUserId");
        String role = (String) httpRequest.getAttribute("currentRole");
        if (userId == null) {
            throw ApiException.unauthorized("Authentication required to delete comments");
        }
        try {
            Comment deleted = commentService.deleteComment(commentId, userId, role != null ? role : "viewer");
            if (deleted == null) {
                throw ApiException.notFound("Comment not found: " + commentId);
            }
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("id", deleted.getId());
            result.put("deleted", true);
            return Response.wrapSuccess(result);
        } catch (SecurityException e) {
            throw ApiException.forbidden(e.getMessage());
        }
    }

    @GetMapping("/{grawaveId}")
    public Response<Map<String, Object>> getComments(
            @PathVariable String grawaveId,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "10") int size) {
        PageNormalizer pn = PageNormalizer.normalizeOrNull(page, size);
        if (pn == null) throw ApiException.badRequest("page number can not be less than 1");
        return buildPageResponse(commentService.getComments(grawaveId, pn.page, pn.size), pn);
    }

    @GetMapping("/user/{userId}")
    public Response<Map<String, Object>> getCommentsByUserId(
            @PathVariable String userId,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "10") int size) {
        PageNormalizer pn = PageNormalizer.normalizeOrNull(page, size);
        if (pn == null) throw ApiException.badRequest("page number can not be less than 1");
        return buildPageResponse(commentService.getCommentsByUserId(userId, pn.page, pn.size), pn);
    }

    @GetMapping("/category/{category}")
    public Response<Map<String, Object>> getCommentsByCategory(
            @PathVariable String category,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "10") int size) {
        PageNormalizer pn = PageNormalizer.normalizeOrNull(page, size);
        if (pn == null) throw ApiException.badRequest("page number can not be less than 1");
        return buildPageResponse(commentService.getCommentsByCategory(category, pn.page, pn.size), pn);
    }

    @GetMapping
    public Response<Map<String, Object>> getAllComments(
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "9000") int size) {
        PageNormalizer pn = PageNormalizer.normalizeOrNull(page, size);
        if (pn == null) throw ApiException.badRequest("page number can not be less than 1");
        return buildPageResponse(commentService.getAllComments(pn.page, pn.size), pn);
    }

    /**
     * Export comments as CSV. Optional filters: grawaveId, userId, category.
     * v4.13: Enables offline analysis, reporting, and data sharing of comments.
     */
    @GetMapping(value = "/export/csv", produces = "text/csv;charset=UTF-8")
    public String exportCommentsCsv(
            @RequestParam(required = false) String grawaveId,
            @RequestParam(required = false) String userId,
            @RequestParam(required = false) String category) {
        java.util.List<Comment> list;
        if (grawaveId != null && !grawaveId.isEmpty()) {
            list = commentService.getComments(grawaveId, 1, 10000).getContent();
        } else if (userId != null && !userId.isEmpty()) {
            list = commentService.getCommentsByUserId(userId, 1, 10000).getContent();
        } else if (category != null && !category.isEmpty()) {
            list = commentService.getCommentsByCategory(category, 1, 10000).getContent();
        } else {
            list = commentService.getAllComments(1, 10000).getContent();
        }
        if (list.isEmpty()) return "No comments found";

        StringBuilder sb = new StringBuilder();
        sb.append("id,grawave_id,user_id,username,category,content,created_at\r\n");
        java.text.SimpleDateFormat sdf = new java.text.SimpleDateFormat("yyyy-MM-dd HH:mm:ss");
        for (Comment c : list) {
            sb.append(escapeCsv(c.getId())).append(",");
            sb.append(escapeCsv(c.getGrawaveId())).append(",");
            sb.append(escapeCsv(c.getUserId())).append(",");
            sb.append(escapeCsv(c.getUsername())).append(",");
            sb.append(escapeCsv(c.getCategory())).append(",");
            sb.append(escapeCsv(c.getContent())).append(",");
            sb.append(c.getCreatedAt() != null ? sdf.format(c.getCreatedAt()) : "").append("\r\n");
        }
        return sb.toString();
    }

    private String escapeCsv(String val) {
        if (val == null) return "";
        if (val.contains(",") || val.contains("\"") || val.contains("\n")) {
            return "\"" + val.replace("\"", "\"\"") + "\"";
        }
        return val;
    }

    private Response<Map<String, Object>> buildPageResponse(Page<Comment> commentPage, PageNormalizer pn) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("list", commentPage.getContent());
        Map<String, Object> totalInfo = new LinkedHashMap<>();
        totalInfo.put("page", pn.page);
        totalInfo.put("page_size", pn.size);
        totalInfo.put("total_count", commentPage.getTotalElements());
        result.put("total_info", totalInfo);
        return Response.wrapSuccess(result);
    }

    public static class CommentRequest {
        private String grawaveId;
        private String content;
        private String userId;
        private String category;

        public String getGrawaveId() { return grawaveId; }
        public void setGrawaveId(String grawaveId) { this.grawaveId = grawaveId; }
        public String getContent() { return content; }
        public void setContent(String content) { this.content = content; }
        public String getUserId() { return userId; }
        public void setUserId(String userId) { this.userId = userId; }
        public String getCategory() { return category; }
        public void setCategory(String category) { this.category = category; }
    }
}
