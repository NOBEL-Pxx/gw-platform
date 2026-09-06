package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.collection.controller;

import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.collection.model.Collection;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.collection.model.CollectionItem;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.collection.service.CollectionService;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.response.ApiException;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.response.Response;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.validation.PageNormalizer;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.data.domain.Page;
import java.util.*;

@RestController
@RequestMapping("/api/app/gravitationalwave/collections")
public class CollectionController {

    @Autowired
    private CollectionService collectionService;

    // ── CRUD ──

    @PostMapping
    public Response<Map<String, Object>> create(@RequestBody CreateRequest req, HttpServletRequest httpReq) {
        String userId = getUserId(httpReq);
        try {
            Collection c = collectionService.createCollection(userId, req.getName(), req.getDescription());
            return Response.wrapSuccess(collectionService.enrichWithItems(c));
        } catch (IllegalArgumentException e) {
            throw ApiException.badRequest(e.getMessage());
        }
    }

    @PutMapping("/{id}")
    public Response<Map<String, Object>> update(@PathVariable String id, @RequestBody CreateRequest req,
                                                 HttpServletRequest httpReq) {
        String userId = getUserId(httpReq);
        try {
            Collection c = collectionService.updateCollection(id, userId, req.getName(), req.getDescription());
            if (c == null) throw ApiException.notFound("Collection not found");
            return Response.wrapSuccess(collectionService.enrichWithItems(c));
        } catch (SecurityException e) {
            throw ApiException.forbidden(e.getMessage());
        }
    }

    @DeleteMapping("/{id}")
    public Response<Map<String, Object>> delete(@PathVariable String id, HttpServletRequest httpReq) {
        String userId = getUserId(httpReq);
        try {
            collectionService.deleteCollection(id, userId);
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("deleted", true);
            result.put("id", id);
            return Response.wrapSuccess(result);
        } catch (SecurityException e) {
            throw ApiException.forbidden(e.getMessage());
        }
    }

    @GetMapping
    public Response<Map<String, Object>> listMine(HttpServletRequest httpReq,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int size) {
        String userId = getUserId(httpReq);
        PageNormalizer pn = PageNormalizer.normalizeOrNull(page, size);
        if (pn == null) throw ApiException.badRequest("Invalid page");
        Page<Collection> colPage = collectionService.getUserCollections(userId, pn.page, pn.size);
        List<Map<String, Object>> enriched = new ArrayList<>();
        for (Collection c : colPage.getContent()) {
            Map<String, Object> e = new LinkedHashMap<>(collectionService.enrichWithItems(c));
            e.remove("items");
            enriched.add(e);
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("list", enriched);
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("page", pn.page);
        info.put("page_size", pn.size);
        info.put("total_count", colPage.getTotalElements());
        result.put("total_info", info);
        return Response.wrapSuccess(result);
    }

    @GetMapping("/public")
    public Response<Map<String, Object>> listPublic(
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int size) {
        PageNormalizer pn = PageNormalizer.normalizeOrNull(page, size);
        if (pn == null) throw ApiException.badRequest("Invalid page");
        Page<Collection> colPage = collectionService.getPublicCollections(pn.page, pn.size);
        List<Map<String, Object>> enriched = new ArrayList<>();
        for (Collection c : colPage.getContent()) {
            enriched.add(collectionService.enrichWithItems(c));
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("list", enriched);
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("page", pn.page);
        info.put("page_size", pn.size);
        info.put("total_count", colPage.getTotalElements());
        result.put("total_info", info);
        return Response.wrapSuccess(result);
    }

    // ── Items ──

    @PostMapping("/{id}/items")
    public Response<Map<String, Object>> addItem(@PathVariable String id, @RequestBody ItemRequest req,
                                                  HttpServletRequest httpReq) {
        String userId = getUserId(httpReq);
        try {
            CollectionItem item = collectionService.addItem(id, userId, req.getGrawaveId(),
                req.getBand(), req.getRa(), req.getDec(), req.getTelescope());
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("added", true);
            result.put("itemId", item.getId());
            return Response.wrapSuccess(result);
        } catch (IllegalArgumentException | SecurityException e) {
            if (e instanceof SecurityException) throw ApiException.forbidden(e.getMessage());
            throw ApiException.badRequest(e.getMessage());
        }
    }

    @DeleteMapping("/{id}/items/{grawaveId}")
    public Response<Map<String, Object>> removeItem(@PathVariable String id, @PathVariable String grawaveId,
                                                     HttpServletRequest httpReq) {
        String userId = getUserId(httpReq);
        try {
            collectionService.removeItem(id, userId, grawaveId);
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("removed", true);
            return Response.wrapSuccess(result);
        } catch (SecurityException e) {
            throw ApiException.forbidden(e.getMessage());
        }
    }

    // ── Sharing ──

    @PostMapping("/{id}/share")
    public Response<Map<String, Object>> share(@PathVariable String id, HttpServletRequest httpReq) {
        String userId = getUserId(httpReq);
        try {
            String token = collectionService.generateShareToken(id, userId);
            if (token == null) throw ApiException.notFound("Collection not found");
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("shareToken", token);
            result.put("shareUrl", "/collections/shared/" + token);
            return Response.wrapSuccess(result);
        } catch (SecurityException e) {
            throw ApiException.forbidden(e.getMessage());
        }
    }

    @GetMapping("/shared/{shareToken}")
    public Response<Map<String, Object>> getByToken(@PathVariable String shareToken) {
        Collection c = collectionService.getByShareToken(shareToken);
        if (c == null) throw ApiException.notFound("Shared collection not found");
        return Response.wrapSuccess(collectionService.enrichWithItems(c));
    }

    // ── Helpers ──

    private String getUserId(HttpServletRequest req) {
        String uid = (String) req.getAttribute("currentUserId");
        if (uid == null) throw ApiException.unauthorized("Login required");
        return uid;
    }

    public static class CreateRequest {
        private String name;
        private String description;
        public String getName() { return name; }
        public void setName(String n) { this.name = n; }
        public String getDescription() { return description; }
        public void setDescription(String d) { this.description = d; }
    }

    public static class ItemRequest {
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
}
