package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.favorite.repository;

import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.favorite.model.Favorite;
import org.springframework.data.mongodb.repository.MongoRepository;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import java.util.List;
import java.util.Optional;

public interface FavoriteRepository extends MongoRepository<Favorite, String> {
    Page<Favorite> findByUserId(String userId, Pageable pageable);
    List<Favorite> findByUserId(String userId);
    Optional<Favorite> findByUserIdAndGrawaveId(String userId, String grawaveId);
    boolean existsByUserIdAndGrawaveId(String userId, String grawaveId);
    void deleteByUserIdAndGrawaveId(String userId, String grawaveId);
    long countByUserId(String userId);
}
