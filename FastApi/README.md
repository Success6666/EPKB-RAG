# 多租户企业私有知识库 RAG 中台 Python 服务骨架

本目录是 `E:\AI\FastApi` 下的 FastAPI 服务骨架，只负责 Python RAG 能力，不依赖或修改 SpringBoot 工程。

## 能力范围

- FastAPI HTTP 服务：健康检查、文档入库、RAG 检索。
- MQ 异步入库入口：RabbitMQ consumer 接收上游 Java 投递的文档处理任务。
- 文档处理：使用 LangChain `TextLoader`、`PyPDFLoader`、`Docx2txtLoader` 和 `RecursiveCharacterTextSplitter` 读取、清洗、切片、生成 chunk metadata。
- Embedding：使用 LangChain `HuggingFaceEmbeddings`，可切换 LangChain `OllamaEmbeddings`。
- Vector Store：使用 LangChain Chroma/Milvus VectorStore 适配层，默认 Chroma 本地持久化，Milvus 可选。
- 多租户隔离：所有入库和检索都以 `tenantId + kbId` 为 scope，Chroma/Milvus 使用按知识库隔离的 collection。
- RAG 检索：支持 `hybrid`、`vector`、`keyword`，返回引用溯源字段。
- 生成：`includeAnswer=true` 时使用 LangChain `PromptTemplate + LLMChain + Ollama` 基于召回 chunk 生成带引用回答。

## 目录结构

```text
app/
  api/routes/          # HTTP routes
  core/config.py       # 环境变量配置
  langchain_modules/   # 按 LangChain 模块心智拆分的 RAG 主实现
    prompts/           # RAG PromptTemplate 与 prompt 组装
    model_io/          # LLM/Embedding provider 与模型路由
    retrieval/         # 文档加载、切片、向量库、关键词评分
    chains/            # RAG chain 编排
    memory/            # 历史对话、摘要、上下文预算格式化
    agents/            # Agent 可复用工具入口
    callbacks/         # 流式输出与 reasoning 事件解析
  schemas/             # Pydantic request/response
  services/            # FastAPI 集成服务；旧 RAG 路径保留为兼容转发层
  workers/             # RabbitMQ consumer
```

## 本地启动

建议使用 Python 3.11 或 Docker 运行。当前 Dockerfile 已固定 `python:3.11-slim`。

```powershell
cd E:\AI\FastApi
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

健康检查：

```powershell
curl http://localhost:8000/api/v1/health
```

## HTTP 入库示例

上游正式流程建议通过 RabbitMQ 投递任务；HTTP 入库接口便于联调。

```powershell
curl -X POST http://localhost:8000/api/v1/documents/ingest `
  -H "Content-Type: application/json" `
  -d '{
    "tenantId": "tenant-a",
    "kbId": "kb-001",
    "docId": "doc-001",
    "filePath": "E:/AI/FastApi/samples/demo.txt",
    "fileName": "demo.txt",
    "sourceUri": "oss://tenant-a/kb-001/demo.txt",
    "metadata": {"category": "policy"}
  }'
```

也可以直接传文本：

```json
{
  "tenantId": "tenant-a",
  "kbId": "kb-001",
  "docId": "doc-text-001",
  "content": "这里是需要入库的文档正文。",
  "metadata": {"category": "faq"}
}
```

## RabbitMQ consumer

启动消费者：

```powershell
cd E:\AI\FastApi
pip install -r requirements.txt -r requirements.worker.txt
python -m app.workers.rabbitmq_consumer
```

消费者使用异步 RabbitMQ 连接，并通过 `RAG_INGEST_CONCURRENCY` 限制并发入库任务数。`RABBITMQ_PREFETCH_COUNT` 应不小于并发数，Docker Compose 默认两者都是 `1`，低内存机器可保持该默认值。

消息体契约：

```json
{
  "tenantId": "tenant-a",
  "kbId": "kb-001",
  "docId": "doc-001",
  "filePath": "E:/data/uploads/demo.pdf",
  "fileName": "demo.pdf",
  "sourceUri": "oss://tenant-a/kb-001/demo.pdf",
  "metadata": {
    "category": "policy"
  }
}
```

字段说明：

- `tenantId`：租户 ID，由上游 Java 传入。
- `kbId`：知识库 ID，由上游 Java 传入。
- `docId`：文档 ID，可不传，不传时 Python 生成。
- `filePath`：Python 服务可访问的本地文件路径。
- `content`：可替代 `filePath` 的直接文本内容。
- `metadata`：可用于后续 `metadataFilter` 的标量字段。

## RAG 检索示例

```powershell
curl -X POST http://localhost:8000/api/v1/rag/query `
  -H "Content-Type: application/json" `
  -d '{
    "tenantId": "tenant-a",
    "kbId": "kb-001",
    "query": "报销政策是什么？",
    "topK": 5,
    "mode": "hybrid",
    "includeAnswer": false,
    "metadataFilter": {"category": "policy"}
  }'
```

响应中的 `hits[].citation` 会返回：

- `docId`
- `chunkId`
- `fileName`
- `sourceUri`
- `page`

## RAG 召回评测

召回效果不要只靠主观问答判断，建议维护一份离线 gold set，并持续观察 `Recall@K`、`MRR`、`NDCG` 和无答案误召率。

样例文件：

- `eval/samples/retrieval_gold_sample.jsonl`：标准答案集，每行一个问题。
- `eval/samples/retrieval_results_sample.jsonl`：检索结果样例，每行对应一个问题。
- `tools/evaluate_retrieval.py`：离线评测脚本。

使用已有结果文件评测：

```powershell
cd E:\AI\FastApi
python tools/evaluate_retrieval.py `
  --gold eval/samples/retrieval_gold_sample.jsonl `
  --results eval/samples/retrieval_results_sample.jsonl `
  --output eval/retrieval_report.json `
  --failures eval/retrieval_failures.csv `
  --failure-jsonl eval/retrieval_failures.jsonl `
  --fail-under recall@5=0.85 `
  --fail-under mrr=0.70
```

直接调用正在运行的 FastAPI 评测：

```powershell
cd E:\AI\FastApi
python tools/evaluate_retrieval.py `
  --gold eval/samples/retrieval_gold_sample.jsonl `
  --endpoint http://localhost:8000/api/v1/rag/query `
  --top-k 40 `
  --mode hybrid `
  --internal-token $env:JAVA_CALLBACK_TOKEN `
  --output eval/retrieval_report.json `
  --failures eval/retrieval_failures.csv `
  --failure-jsonl eval/retrieval_failures.jsonl
```

`--fail-under` 会在指标低于阈值时返回非 0 退出码，适合放到发布前检查或 CI；`--failure-jsonl`
会保留漏召回/误召回问题的期望文档、Top hits、分数和证据预览，方便定位是哪类问题拖低召回。

运行中的 FastAPI 端到端烟测：
```powershell
cd E:\AI\FastApi
python tools/smoke_rag_e2e.py `
  --base-url http://localhost:8000 `
  --internal-token $env:JAVA_CALLBACK_TOKEN `
  --tenant-id smoke-tenant `
  --kb-id smoke-kb
```

gold set 每行建议包含：

```json
{"id":"policy-duty-001","tenantId":"1","kbId":"10","query":"基层教学组织的主要职责是什么？","answerable":true,"relevant":{"docIds":["doc-policy-2026"],"chunkIds":["chunk-duty-01"],"parentIds":["parent-duty"]},"tags":["heading","policy"]}
```

评测样本至少覆盖：精确条款、标题章节、同义问法、跨段答案、合同/模板整文、表格/Excel、OCR PDF、长文档、多相似文档和无答案问题。调参前后分别保存报告，重点看失败 CSV 中的漏召问题和无答案误召问题。

## 配置

复制 `.env.example` 到 `.env` 后按环境调整。

常用配置：

```env
VECTOR_STORE=chroma
CHROMA_PERSIST_DIR=./data/chroma

EMBEDDING_PROVIDER=sentence_transformers
SENTENCE_TRANSFORMER_MODEL=BAAI/bge-small-zh-v1.5

RABBITMQ_URL=amqp://guest:guest@localhost:5672/%2F
RABBITMQ_QUEUE=rag.document.ingest
RABBITMQ_DOCUMENT_EXCHANGE=rag.document.exchange
RABBITMQ_DOCUMENT_ROUTING_KEY=rag.document.index
RABBITMQ_DOCUMENT_DLX=rag.document.dlx
RABBITMQ_DOCUMENT_DLQ_ROUTING_KEY=rag.document.dead
RABBITMQ_DOCUMENT_DLQ=rag.document.ingest.dlq

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_GENERATION_MODEL=qwen2.5:7b
```

Messages rejected with `requeue=False` are routed to `rag.document.ingest.dlq`. If an old local queue was created before DLX support, recreate `rag.document.ingest` so RabbitMQ can apply the dead-letter arguments.

切换 Milvus：

```env
VECTOR_STORE=milvus
MILVUS_URI=http://localhost:19530
MILVUS_TOKEN=
MILVUS_DB_NAME=default
```

切换 Ollama embedding：

```env
EMBEDDING_PROVIDER=ollama
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
```

## Docker

```powershell
cd E:\AI\FastApi
docker build -t private-kb-rag-fastapi .
docker run --rm -p 8000:8000 --env-file .env private-kb-rag-fastapi
```

如果容器内需要读取上游上传文件，请把上传目录挂载进容器，并保证 RabbitMQ 消息里的 `filePath` 是容器内路径。
