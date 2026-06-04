UPDATE rag_model_config
SET embedding_provider = 'SentenceTransformers',
    embedding_model = 'BAAI/bge-small-zh-v1.5',
    embedding_base_url = NULL,
    embedding_input_type = NULL,
    embedding_truncate = 'NONE'
WHERE deleted = 0
  AND LOWER(embedding_provider) IN ('ollama', 'local')
  AND (embedding_base_url IS NULL OR embedding_base_url LIKE '%host.docker.internal:11434%')
  AND embedding_model IN ('bge-m3', 'nomic-embed-text', 'nomic-embed-text:latest');
