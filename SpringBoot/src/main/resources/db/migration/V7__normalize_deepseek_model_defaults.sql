UPDATE rag_model_config legacy
LEFT JOIN rag_model_config current
  ON current.tenant_id = legacy.tenant_id
 AND current.model_name = 'deepseek-v4-pro'
 AND current.deleted = 0
 AND current.id <> legacy.id
SET legacy.model_name = 'deepseek-v4-pro'
WHERE legacy.deleted = 0
  AND LOWER(legacy.provider) = 'deepseek'
  AND legacy.model_name = 'deepseek-chat'
  AND current.id IS NULL;

UPDATE rag_model_config
SET rerank_model = 'deepseek-v4-flash'
WHERE deleted = 0
  AND LOWER(provider) = 'deepseek'
  AND LOWER(rerank_model) IN ('bge-reranker-v2-m3', 'deepseekv4flash', 'deepseek-v4flash', 'deepseek_v4_flash');
