ALTER TABLE event_images
    MODIFY COLUMN image_url VARCHAR(500) NULL,
    ADD COLUMN evidence_id          VARCHAR(36)  NULL,
    ADD COLUMN publication_revision INT          NULL,
    ADD COLUMN availability         ENUM('AVAILABLE','UNAVAILABLE') NULL,
    ADD COLUMN unavailable_reason   VARCHAR(40)  NULL,
    ADD COLUMN checksum             VARCHAR(100) NULL,
    ADD COLUMN byte_size            BIGINT       NULL,
    ADD CONSTRAINT uk_event_images_evidence_id UNIQUE (evidence_id);