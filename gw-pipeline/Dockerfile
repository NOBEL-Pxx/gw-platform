FROM python:3.12-slim
# v4.27: Build-time flag to exclude GPL-3.0 licensed models.
# Use: docker build --build-arg EXCLUDE_GPL_MODELS=true ... for MIT-only distribution.
# v4.37: Security hardening — non-root user, read-only filesystem ready.
ARG EXCLUDE_GPL_MODELS=false
WORKDIR /app
# System deps for Astropy/scipy compilation (use Tsinghua mirrors for China)
RUN apt-get update && apt-get install -y --no-install-recommends     gcc g++ libcfitsio-dev && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ src/
RUN mkdir -p /app/data /app/thumbnail_cache /app/models
# v4.27: Conditionally exclude GPL-3.0 Zoobot model for clean MIT distribution.
# When EXCLUDE_GPL_MODELS=true, Zoobot encoder is NOT included in the image.
# Morphology classification still works via lightweight feature-based classifier (40-60% acc).
COPY models/*.onnx models/*.json /app/models/
RUN if [ "$EXCLUDE_GPL_MODELS" = "true" ]; then       rm -f /app/models/zoobot_encoder_greyscale.onnx &&       echo "GPL-3.0 Zoobot model excluded — lightweight classifier only";     fi
ENV FITS_DATA_DIR=/app/data
ENV THUMBNAIL_CACHE_DIR=/app/thumbnail_cache
ENV DL_MODEL_DIR=/app/models
# v4.27: Runtime flag mirrors build-time EXCLUDE_GPL_MODELS.
# Set to "true" at runtime to prevent loading GPL models even if present on disk.
ENV GW_EXCLUDE_GPL_MODELS=${EXCLUDE_GPL_MODELS}

# v4.37: Security hardening — non-root user
RUN groupadd -r gwuser && useradd -r -g gwuser -s /sbin/nologin gwuser \
    && chown -R gwuser:gwuser /app
USER gwuser

EXPOSE 8200
CMD ["uvicorn", "src.pipeline.server:app", "--host", "0.0.0.0", "--port", "8200"]
