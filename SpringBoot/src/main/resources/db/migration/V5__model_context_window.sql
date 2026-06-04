SET @schema_name := DATABASE();

SET @sql := (
  SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE rag_model_config ADD COLUMN context_window_tokens INT NOT NULL DEFAULT 262144 AFTER max_tokens',
    'SELECT 1'
  )
  FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'rag_model_config'
    AND COLUMN_NAME = 'context_window_tokens'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

UPDATE rag_model_config
SET context_window_tokens = 262144
WHERE context_window_tokens IS NULL OR context_window_tokens < 1024;
