package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.favorite.service;

import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.favorite.model.Favorite;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.favorite.repository.FavoriteRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import java.util.*;

@Service
public class FavoriteService {

    @Autowired
    private FavoriteRepository favoriteRepository;

    /** Toggle favorite: add if not exists, remove if exists. Returns true=added, false=removed. */
    public Map<String, Object> toggleFavorite(String userId, String grawaveId, String band, Double ra, Double dec, String telescope) {
        Optional<Favorite> existing = favoriteRepository.findByUserIdAndGrawaveId(userId, grawaveId);
        Map<String, Object> result = new LinkedHashMap<>();
        if (existing.isPresent()) {
            favoriteRepository.delete(existing.get());
            result.put("action", "removed");
            result.put("grawaveId", grawaveId);
        } else {
            Favorite fav = new Favorite(userId, grawaveId, band, ra, dec, telescope);
            fav = favoriteRepository.save(fav);
            result.put("action", "added");
            result.put("favoriteId", fav.getId());
            result.put("grawaveId", grawaveId);
        }
        result.put("totalFavorites", favoriteRepository.countByUserId(userId));
        return result;
    }

    public Page<Favorite> getFavorites(String userId, int page, int size) {
        Pageable pageable = PageRequest.of(page - 1, size);
        return favoriteRepository.findByUserId(userId, pageable);
    }

    public List<Favorite> getAllFavorites(String userId) {
        return favoriteRepository.findByUserId(userId);
    }

    public boolean isFavorited(String userId, String grawaveId) {
        return favoriteRepository.existsByUserIdAndGrawaveId(userId, grawaveId);
    }

    public Map<String, Boolean> checkFavorites(String userId, List<String> grawaveIds) {
        Map<String, Boolean> result = new LinkedHashMap<>();
        for (String gid : grawaveIds) {
            result.put(gid, favoriteRepository.existsByUserIdAndGrawaveId(userId, gid));
        }
        return result;
    }

    public void removeFavorite(String userId, String grawaveId) {
        favoriteRepository.deleteByUserIdAndGrawaveId(userId, grawaveId);
    }

    public long countFavorites(String userId) {
        return favoriteRepository.countByUserId(userId);
    }
}
