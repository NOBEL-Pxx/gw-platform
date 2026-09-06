package com.zhejianglab.gravitationalwave.gravitationalwaveserver.service.validation;

public final class PageNormalizer {

    public static final int DEFAULT_PAGE = 1;
    public static final int DEFAULT_SIZE = 20;
    public static final int MAX_SIZE = 1000;

    public final int page;
    public final int size;
    public final int from;
    public final int querySize;
    public final boolean fetchAll;

    private PageNormalizer(int rawPage, int rawSize) {
        this.page = Math.max(rawPage, 1);
        this.fetchAll = (rawSize <= 0);
        this.size = this.fetchAll ? MAX_SIZE : Math.min(rawSize, MAX_SIZE);
        this.from = (this.page - 1) * this.size;
        this.querySize = this.size;
    }

    public static PageNormalizer normalize(int page, int size) {
        return new PageNormalizer(page, size);
    }

    public static PageNormalizer normalizeOrNull(int page, int size) {
        if (page < 1) return null;
        return new PageNormalizer(page, size);
    }

    public static PageNormalizer fetchAll() {
        return new PageNormalizer(1, -1);
    }
}
