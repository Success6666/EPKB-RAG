SET @schema_name := DATABASE();

SET @sql := (
  SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE rag_model_config ADD COLUMN embedding_provider VARCHAR(64) NOT NULL DEFAULT ''SentenceTransformers'' AFTER api_key',
    'SELECT 1'
  )
  FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'rag_model_config'
    AND COLUMN_NAME = 'embedding_provider'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @sql := (
  SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE rag_model_config ADD COLUMN embedding_base_url VARCHAR(512) NULL AFTER embedding_model',
    'SELECT 1'
  )
  FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'rag_model_config'
    AND COLUMN_NAME = 'embedding_base_url'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @sql := (
  SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE rag_model_config ADD COLUMN embedding_api_key VARCHAR(1024) NULL AFTER embedding_base_url',
    'SELECT 1'
  )
  FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'rag_model_config'
    AND COLUMN_NAME = 'embedding_api_key'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @sql := (
  SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE rag_model_config ADD COLUMN embedding_input_type VARCHAR(16) NULL AFTER embedding_api_key',
    'SELECT 1'
  )
  FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'rag_model_config'
    AND COLUMN_NAME = 'embedding_input_type'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @sql := (
  SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE rag_model_config ADD COLUMN embedding_truncate VARCHAR(16) NOT NULL DEFAULT ''NONE'' AFTER embedding_input_type',
    'SELECT 1'
  )
  FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'rag_model_config'
    AND COLUMN_NAME = 'embedding_truncate'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
