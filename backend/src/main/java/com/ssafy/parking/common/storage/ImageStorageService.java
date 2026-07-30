package com.ssafy.parking.common.storage;

import com.ssafy.parking.common.exception.BusinessException;
import com.ssafy.parking.common.exception.ErrorCode;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.UUID;

@Service
public class ImageStorageService {

    private final String uploadDir;
    private final String publicBaseUrl;

    public ImageStorageService(
            @Value("${app.upload.dir}") String uploadDir,
            @Value("${app.upload.public-base-url}") String publicBaseUrl
    ) {
        this.uploadDir = uploadDir;
        this.publicBaseUrl = publicBaseUrl;
    }

    /** 파일을 events/{eventId}/ 아래 저장하고 공개 URL 반환 */
    public String store(MultipartFile file, Long eventId) {
        try {
            // 원본 파일명 정제 (경로 순회 문자 제거)
            String cleaned = StringUtils.cleanPath(
                    file.getOriginalFilename() == null ? "" : file.getOriginalFilename());
            if (cleaned.contains("..")) {
                throw new BusinessException(ErrorCode.MOVE_REQUEST_INVALID);
            }
            String ext = cleaned.contains(".") ? cleaned.substring(cleaned.lastIndexOf('.')) : "";

            String filename = UUID.randomUUID() + ext;   // 파일명은 UUID로 강제
            Path baseDir = Paths.get(uploadDir, "events", String.valueOf(eventId))
                    .toAbsolutePath().normalize();
            Files.createDirectories(baseDir);

            Path dest = baseDir.resolve(filename).normalize();
            if (!dest.startsWith(baseDir)) {          // 최종 경로가 baseDir 밖이면 차단
                throw new BusinessException(ErrorCode.MOVE_REQUEST_INVALID);
            }
            file.transferTo(dest);

            return publicBaseUrl + "/events/" + eventId + "/" + filename;
        } catch (IOException e) {
            throw new BusinessException(ErrorCode.INTERNAL_SERVER_ERROR);
        }
    }
}