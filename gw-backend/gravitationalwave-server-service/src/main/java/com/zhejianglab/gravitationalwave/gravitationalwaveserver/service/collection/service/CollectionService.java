package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.collection.service;

import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.collection.model.Collection;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.collection.model.CollectionItem;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.collection.repository.CollectionRepository;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.collection.repository.CollectionItemRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import java.util.*;

@Service
public class CollectionService {

    @Autowired
    private CollectionRepository collectionRepository;

    @Autowired
    private CollectionItemRepository itemRepository;

    // ── Collection CRUD ──

    public Collection createCollection(String ownerId, String name, String description) {
        if (name == null || name.trim().isEmpty()) throw new IllegalArgumentException("Name is required");
        Collection c = new Collection(ownerId, name.trim(), description);
        return collectionRepository.save(c);
    }

    public Collection updateCollection(String collectionId, String userId, String name, String description) {
        Collection c = collectionRepository.findById(collectionId).orElse(null);
        if (c == null) return null;
        if (!c.getOwnerId().equals(userId)) throw new SecurityException("Only owner can edit this collection");
        if (name != null && !name.trim().isEmpty()) c.setName(name.trim());
        if (description != null) c.setDescription(description);
        c.setUpdatedAt(new Date());
        return collectionRepository.save(c);
    }

    public void deleteCollection(String collectionId, String userId) {
        Collection c = collectionRepository.findById(collectionId).orElse(null);
        if (c == null) return;
        if (!c.getOwnerId().equals(userId)) throw new SecurityException("Only owner can delete this collection");
        itemRepository.deleteAllByCollectionId(collectionId);
        collectionRepository.delete(c);
    }

    public Page<Collection> getUserCollections(String ownerId, int page, int size) {
        Pageable pageable = PageRequest.of(page - 1, size);
        return collectionRepository.findByOwnerId(ownerId, pageable);
    }

    public Page<Collection> getPublicCollections(int page, int size) {
        Pageable pageable = PageRequest.of(page - 1, size);
        return collectionRepository.findByIsPublicTrue(pageable);
    }

    // ── Items ──

    public CollectionItem addItem(String collectionId, String userId, String grawaveId, String band, Double ra, Double dec, String telescope) {
        Collection c = collectionRepository.findById(collectionId).orElse(null);
        if (c == null) throw new IllegalArgumentException("Collection not found");
        if (!c.getOwnerId().equals(userId)) throw new SecurityException("Only owner can modify this collection");
        CollectionItem item = new CollectionItem(collectionId, grawaveId, band, ra, dec, telescope);
        return itemRepository.save(item);
    }

    public void removeItem(String collectionId, String userId, String grawaveId) {
        Collection c = collectionRepository.findById(collectionId).orElse(null);
        if (c == null) return;
        if (!c.getOwnerId().equals(userId)) throw new SecurityException("Only owner can modify this collection");
        itemRepository.deleteByCollectionIdAndGrawaveId(collectionId, grawaveId);
    }

    public List<CollectionItem> getItems(String collectionId) {
        return itemRepository.findByCollectionId(collectionId);
    }

    public long countItems(String collectionId) {
        return itemRepository.countByCollectionId(collectionId);
    }

    // ── Sharing ──

    public String generateShareToken(String collectionId, String userId) {
        Collection c = collectionRepository.findById(collectionId).orElse(null);
        if (c == null) return null;
        if (!c.getOwnerId().equals(userId)) throw new SecurityException("Only owner can share this collection");
        String token = UUID.randomUUID().toString().replace("-", "").substring(0, 12);
        c.setShareToken(token);
        c.setPublic(true);
        collectionRepository.save(c);
        return token;
    }

    public void revokeShareToken(String collectionId, String userId) {
        Collection c = collectionRepository.findById(collectionId).orElse(null);
        if (c == null) return;
        if (!c.getOwnerId().equals(userId)) throw new SecurityException("Only owner can revoke share");
        c.setShareToken(null);
        collectionRepository.save(c);
    }

    public Collection getByShareToken(String shareToken) {
        return collectionRepository.findByShareToken(shareToken).orElse(null);
    }

    public Map<String, Object> enrichWithItems(Collection c) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("id", c.getId());
        result.put("name", c.getName());
        result.put("description", c.getDescription());
        result.put("ownerId", c.getOwnerId());
        result.put("isPublic", c.isPublic());
        result.put("shareToken", c.getShareToken());
        result.put("createdAt", c.getCreatedAt());
        result.put("updatedAt", c.getUpdatedAt());
        result.put("itemCount", countItems(c.getId()));
        result.put("items", getItems(c.getId()));
        return result;
    }
}
