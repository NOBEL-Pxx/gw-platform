FROM maven:3.9-eclipse-temurin-21 AS builder
WORKDIR /build
# v4.12: Multi-mirror fallback settings.xml + BuildKit cache for reliable CI
COPY settings.xml /root/.m2/settings.xml
COPY pom.xml .
COPY gravitationalwave-server-service gravitationalwave-server-service/
COPY gravitationalwave-server-web gravitationalwave-server-web/
COPY start start/
RUN --mount=type=cache,target=/root/.m2/repository     mvn clean package -DskipTests -q     -Dmaven.wagon.http.retryHandler.count=10     -Dmaven.wagon.http.connectionTimeout=30000     -Dmaven.wagon.http.readTimeout=120000     -Dmaven.wagon.http.pool=true     -T 2

FROM eclipse-temurin:21-jre-alpine
RUN apk add --no-cache tzdata dumb-init fontconfig ttf-dejavu ca-certificates openssl &&     cp /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && update-ca-certificates
WORKDIR /home/gravitational-wave-backend
COPY --from=builder /build/start/target/*.jar app.jar
COPY start.sh .
RUN chmod +x start.sh

# v4.37: Security hardening — non-root user (Alpine)
RUN addgroup -S gwuser && adduser -S gwuser -G gwuser \
    && chown -R gwuser:gwuser /home/gravitational-wave-backend
USER gwuser

EXPOSE 8093
ENTRYPOINT ["dumb-init", "--", "sh", "start.sh"]
