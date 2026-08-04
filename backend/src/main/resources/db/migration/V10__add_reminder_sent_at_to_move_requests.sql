SET @exists := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'move_requests'
      AND COLUMN_NAME = 'reminder_sent_at'
);
SET @sql := IF(@exists = 0,
               'ALTER TABLE move_requests ADD COLUMN reminder_sent_at DATETIME(6) NULL',
               'SELECT 1');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;