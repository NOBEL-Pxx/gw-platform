package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.favorite.controller;

import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.favorite.model.Favorite;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.favorite.service.FavoriteService;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.response.ApiException;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.response.Response;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.validation.PageNormalizer;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.data.domain.Page;
import java.util.*;

@RestController
@RequestMapping("/api/app/gravitationalwave/favorites")
public class FavoriteController {

    @Autowired
    private FavoriteService favoriteService;

    /** Toggle favorite (add/remove). Requires auth. */
    @PostMapping("/toggle")
    public Response<Map<String, Object>> toggleFavorite(@RequestBody FavoriteRequest request,
                                                         HttpServletRequest httpRequest) {
        String userId = (String) httpRequest.getAttribute("currentUserId");
        if (userId == null) throw ApiException.unauthorized("Login required to manage favorites");
        if (request.getGrawaveId() == null || request.getGrawaveId().trim().isEmpty()) {
            throw ApiException.badRequest("grawaveId is required");
        }
        try {
            Map<String, Object> result = favoriteService.toggleFavorite(
                userId, request.getGrawaveId(), request.getBand(),
                request.getRa(), request.getDec(), request.getTelescope());
            return Response.wrapSuccess(result);
        } catch (IllegalArgumentException e) {
            throw ApiException.notFound(e.getMessage());
        }
    }

    /** List favorites for the current user. */
    @GetMapping
    public Response<Map<String, Object>> listFavorites(
            HttpServletRequest httpRequest,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int size) {
        String userId = (String) httpRequest.getAttribute("currentUserId");
        if (userId == null) throw ApiException.unauthorized("Login required to view favorites");
        PageNormalizer pn = PageNormalizer.normalizeOrNull(page, size);
        if (pn == null) throw ApiException.badRequest("Invalid page number");
        Page<Favorite> favPage = favoriteService.getFavorites(userId, pn.page, pn.size);
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("list", favPage.getContent());
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("page", pn.page);
        info.put("page_size", pn.size);
        info.put("total_count", favPage.getTotalElements());
        info.put("total_favorites", favoriteService.countFavorites(userId));
        result.put("total_info", info);
        return Response.wrapSuccess(result);
    }

    /** Check if specific observations are favorited. */
    @PostMapping("/check")
    public Response<Map<String, Boolean>> checkFavorites(@RequestBody CheckRequest request,
                                                          HttpServletRequest httpRequest) {
        String userId = (String) httpRequest.getAttribute("currentUserId");
        if (userId == null) throw ApiException.unauthorized("Login required");
        if (request.getGrawaveIds() == null || request.getGrawaveIds().isEmpty()) {
            return Response.wrapSuccess(new LinkedHashMap<>());
        }
        return Response.wrapSuccess(favoriteService.checkFavorites(userId, request.getGrawaveIds()));
    }

    /** Remove a specific favorite. */
    @DeleteMapping("/{grawaveId}")
    public Response<Map<String, Object>> removeFavorite(@PathVariable String grawaveId,
                                                         HttpServletRequest httpRequest) {
        String userId = (String) httpRequest.getAttribute("currentUserId");
        if (userId == null) throw ApiException.unauthorized("Login required");
        favoriteService.removeFavorite(userId, grawaveId);
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("removed", true);
        result.put("grawaveId", grawaveId);
        return Response.wrapSuccess(result);
    }

    /** Get favorite count for current user. */
    @GetMapping("/count")
    public Response<Map<String, Object>> countFavorites(HttpServletRequest httpRequest) {
        String userId = (String) httpRequest.getAttribute("currentUserId");
        if (userId == null) throw ApiException.unauthorized("Login required");
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("count", favoriteService.countFavorites(userId));
        return Response.wrapSuccess(result);
    }

    public static class FavoriteRequest {
        private String grawaveId;
        private String band;
        private Double ra;
        private Double dec;
        private String telescope;
        public String getGrawaveId() { return grawaveId; }
        public void setGrawaveId(String id) { this.grawaveId = id; }
        public String getBand() { return band; }
        public void setBand(String b) { this.band = b; }
        public Double getRa() { return ra; }
        public void setRa(Double r) { this.ra = r; }
        public Double getDec() { return dec; }
        public void setDec(Double d) { this.dec = d; }
        public String getTelescope() { return telescope; }
        public void setTelescope(String t) { this.telescope = t; }
    }

    public static class CheckRequest {
        private List<String> grawaveIds;
        public List<String> getGrawaveIds() { return grawaveIds; }
        public void setGrawaveIds(List<String> ids) { this.grawaveIds = ids; }
    }
}
