FROM eclipse-temurin:21-jdk-jammy AS builder

WORKDIR /workspace

COPY gradlew gradlew
COPY gradle gradle
COPY build.gradle settings.gradle ./

RUN chmod +x gradlew
RUN ./gradlew dependencies --no-daemon

COPY src src

RUN ./gradlew clean bootJar --no-daemon \
    && find build/libs -maxdepth 1 -type f \
       -name '*.jar' ! -name '*-plain.jar' \
       -exec cp {} app.jar \;


FROM eclipse-temurin:21-jre-jammy

WORKDIR /app

RUN groupadd --system spring \
    && useradd --system --gid spring spring

COPY --from=builder --chown=spring:spring /workspace/app.jar app.jar

RUN mkdir -p /app/uploads && chown -R spring:spring /app/uploads

USER spring:spring

EXPOSE 8080

ENTRYPOINT ["java", "-jar", "app.jar"]