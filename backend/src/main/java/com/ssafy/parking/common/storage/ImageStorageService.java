package com.ssafy.parking.common.storage;

import com.ssafy.parking.common.exception.BusinessException;
import com.ssafy.parking.common.exception.ErrorCode;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
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
            String original = file.getOriginalFilename();
            String ext = (original != null && original.contains("."))
                    ? original.substring(original.lastIndexOf('.')) : "";
            String filename = UUID.randomUUID() + ext;

            Path dir = Paths.get(uploadDir, "events", String.valueOf(eventId));
            Files.createDirectories(dir);
            file.transferTo(dir.resolve(filename).toAbsolutePath());

            return publicBaseUrl + "/events/" + eventId + "/" + filename;
        } catch (IOException e) {
            throw new BusinessException(ErrorCode.INTERNAL_SERVER_ERROR);
        }
    }
}