package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.comment.service;

import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.comment.model.Comment;
import com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.comment.repository.CommentRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import java.util.Date;
import java.util.Optional;

@Service
public class CommentService {

    @Autowired
    private CommentRepository commentRepository;

    public Comment addComment(String grawaveId, String content, String userId, String username, String category) {
        if (grawaveId == null || grawaveId.trim().isEmpty()) {
            throw new IllegalArgumentException("grawaveId must not be null or empty");
        }
        Comment comment = new Comment();
        comment.setGrawaveId(grawaveId);
        comment.setContent(content);
        comment.setUserId(userId);
        comment.setUsername(username);
        comment.setCategory(category);
        comment.setCreatedAt(new Date());
        return commentRepository.save(comment);
    }

    /**
     * Delete a comment. Only the comment author or an admin may delete.
     * @return the deleted comment, or null if not found.
     * @throws SecurityException if the requester is not the owner and not an admin.
     */
    public Comment deleteComment(String commentId, String requesterId, String requesterRole) {
        Optional<Comment> opt = commentRepository.findById(commentId);
        if (!opt.isPresent()) return null;
        Comment comment = opt.get();
        boolean isOwner = comment.getUserId() != null && comment.getUserId().equals(requesterId);
        boolean isAdmin = "admin".equals(requesterRole);
        if (!isOwner && !isAdmin) {
            throw new SecurityException("You can only delete your own comments");
        }
        commentRepository.delete(comment);
        return comment;
    }

    public Page<Comment> getComments(String grawaveId, int page, int size) {
        Pageable pageable = PageRequest.of(page-1, size);
        return commentRepository.findByGrawaveId(grawaveId, pageable);
    }

    public Page<Comment> getCommentsByUserId(String userId, int page, int size) {
        Pageable pageable = PageRequest.of(page-1, size);
        return commentRepository.findByUserId(userId, pageable);
    }

    public Page<Comment> getCommentsByCategory(String category, int page, int size) {
        Pageable pageable = PageRequest.of(page-1, size);
        return commentRepository.findByCategory(category, pageable);
    }

    public Page<Comment> getAllComments(int page, int size) {
        Pageable pageable = PageRequest.of(page-1, size);
        return commentRepository.findAll(pageable);
    }
}
