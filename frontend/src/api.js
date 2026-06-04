import axios from 'axios'

const runtimeConfig = window.__RAG_CONFIG__ || {}

export const config = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL || runtimeConfig.API_BASE_URL || '/api',
  demoMode: String(import.meta.env.VITE_DEMO_MODE ?? runtimeConfig.DEMO_MODE ?? 'false') === 'true'
}

const api = axios.create({
  baseURL: config.apiBaseUrl,
  timeout: 120000
})

const authContext = {
  token: '',
  tenantId: ''
}

export function setAuthContext({ token, tenantId }) {
  authContext.token = token || ''
  authContext.tenantId = tenantId || ''
  if (token) {
    api.defaults.headers.common.Authorization = `Bearer ${token}`
    api.defaults.headers.common.satoken = token
  } else {
    delete api.defaults.headers.common.Authorization
    delete api.defaults.headers.common.satoken
  }
  if (tenantId) {
    api.defaults.headers.common['X-Tenant-Id'] = tenantId
  } else {
    delete api.defaults.headers.common['X-Tenant-Id']
  }
}

const sleep = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms))

function apiUrl(path) {
  const base = config.apiBaseUrl.endsWith('/') ? config.apiBaseUrl.slice(0, -1) : config.apiBaseUrl
  return `${base}${path}`
}

function streamHeaders() {
  const headers = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream, application/json'
  }
  if (authContext.token) {
    headers.Authorization = `Bearer ${authContext.token}`
    headers.satoken = authContext.token
  }
  if (authContext.tenantId) {
    headers['X-Tenant-Id'] = authContext.tenantId
  }
  return headers
}

async function readSseStream(response, handlers = {}) {
  const reader = response.body?.getReader()
  if (!reader) {
    throw new Error('浏览器不支持流式读取')
  }
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  const processFrame = (frame) => {
    const data = frame
      .split(/\r?\n/)
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trimStart())
      .join('\n')
    if (!data) {
      return
    }
    const event = JSON.parse(data)
    handlers.onEvent?.(event)
    if (event.type === 'session') {
      handlers.onSession?.(event.sessionId)
    } else if (event.type === 'delta') {
      handlers.onDelta?.(event.delta || '', event)
    } else if (event.type === 'reasoning') {
      handlers.onReasoning?.(event.reasoning || '', event)
    } else if (event.type === 'status') {
      handlers.onStatus?.(event.message || '', event)
    } else if (event.type === 'done') {
      handlers.onDone?.(event)
    } else if (event.type === 'error') {
      throw createHttpError(event.message || '流式问答失败', event.status || 502, 'Streaming Error', event)
    }
  }
  while (true) {
    const { done, value } = await reader.read()
    if (done) {
      break
    }
    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split(/\r?\n\r?\n/)
    buffer = frames.pop() || ''
    for (const frame of frames) {
      processFrame(frame)
    }
  }
  if (buffer.trim()) {
    processFrame(buffer)
  }
}

function createHttpError(message, status, statusText, data = null) {
  const error = new Error(message || statusText || '请求失败')
  error.response = {
    status,
    statusText,
    data: data || { message: message || statusText }
  }
  return error
}

function parseErrorPayload(text) {
  if (!text) {
    return null
  }
  try {
    return JSON.parse(text)
  } catch {
    return { message: text }
  }
}

function createAbortError() {
  const error = new Error('请求已取消')
  error.name = 'AbortError'
  return error
}

const mockTenants = [
  { id: '1', name: '默认租户', code: 'demo', role: 'tenant_owner', quota: '120 GB' },
  { id: '2', name: '法务知识库', code: 'ENT-LEGAL01', role: 'tenant_admin', quota: '80 GB' },
  { id: '3', name: '研发知识库', code: 'ENT-RD00001', role: 'employee', quota: '160 GB' }
]

const mockEmployees = [
  {
    userId: 'u-demo',
    username: 'admin@example.com',
    displayName: '平台管理员',
    role: 'tenant_owner',
    joinedAt: '2026-05-31T09:00:00'
  },
  {
    userId: 'u-employee-1',
    username: 'member@example.com',
    displayName: '普通员工',
    role: 'employee',
    joinedAt: '2026-05-31T09:20:00'
  }
]

const mockCompanies = [
  {
    id: '1',
    name: '默认租户',
    code: 'demo',
    status: 1,
    createdAt: '2026-05-31T09:00:00'
  },
  {
    id: '2',
    name: '新乡学院',
    code: 'ENT-XIANG01',
    status: 1,
    createdAt: '2026-05-31T10:00:00'
  }
]

const mockTasks = [
  {
    id: 'job-20260531-001',
    fileName: '供应商准入制度.pdf',
    knowledgeBase: '制度与流程',
    status: 'running',
    progress: 68,
    chunks: 214,
    errorMessage: '',
    updatedAt: '2026-05-31 10:20'
  },
  {
    id: 'job-20260531-002',
    fileName: '项目复盘.docx',
    knowledgeBase: '项目经验库',
    status: 'success',
    progress: 100,
    chunks: 86,
    errorMessage: '',
    updatedAt: '2026-05-31 09:48'
  },
  {
    id: 'job-20260531-003',
    fileName: '年度预算扫描件.pdf',
    knowledgeBase: '合同档案',
    status: 'failed',
    progress: 100,
    chunks: 0,
    errorMessage: '文件解析失败：PDF 文本为空，请确认文件未加密且包含可提取文本。',
    updatedAt: '2026-05-31 09:35'
  }
]

const mockChatSessions = [
  {
    sessionId: 'demo-session-1',
    title: '供应商准入制度怎么执行？',
    createdAt: '2026-05-31T09:10:00',
    updatedAt: '2026-05-31T09:16:00'
  },
  {
    sessionId: 'demo-session-2',
    title: '项目复盘模板在哪里？',
    createdAt: '2026-05-30T17:20:00',
    updatedAt: '2026-05-30T17:25:00'
  }
]

const mockChatMessages = {
  'demo-session-1': [
    {
      id: 'demo-msg-1',
      sessionId: 'demo-session-1',
      role: 'user',
      content: '供应商准入制度怎么执行？',
      citationsJson: null,
      createdAt: '2026-05-31T09:10:00'
    },
    {
      id: 'demo-msg-2',
      sessionId: 'demo-session-1',
      role: 'assistant',
      content: '供应商准入需要完成资质、信用、履约能力和合规风险审查，并保留审批记录。',
      citationsJson: JSON.stringify([
        {
          id: 'cite-1',
          title: '供应商准入制度.pdf',
          page: 8,
          score: 0.91,
          text: '供应商准入需完成资质、信用、履约能力和合规风险审查。'
        }
      ]),
      createdAt: '2026-05-31T09:16:00'
    }
  ],
  'demo-session-2': [
    {
      id: 'demo-msg-3',
      sessionId: 'demo-session-2',
      role: 'user',
      content: '项目复盘模板在哪里？',
      citationsJson: null,
      createdAt: '2026-05-30T17:20:00'
    }
  ]
}

const mockModels = [
  {
    id: 'qwen2.5:7b',
    provider: 'Ollama',
    enabled: true,
    baseUrl: 'http://host.docker.internal:11434',
    apiKeyConfigured: false,
    temperature: 0.2,
    topP: 0.8,
    maxTokens: 2048,
    contextWindowTokens: 262144,
    embeddingProvider: 'sentence_transformers',
    embeddingModel: 'BAAI/bge-small-zh-v1.5',
    embeddingBaseUrl: '',
    embeddingApiKeyConfigured: false,
    embeddingInputType: '',
    embeddingTruncate: 'NONE',
    rerankModel: 'none'
  },
  {
    id: 'deepseek-v4-pro',
    provider: 'DeepSeek',
    enabled: false,
    baseUrl: 'https://api.deepseek.com',
    apiKeyConfigured: true,
    temperature: 0.3,
    topP: 0.9,
    maxTokens: 8192,
    contextWindowTokens: 262144,
    embeddingProvider: 'sentence_transformers',
    embeddingModel: 'BAAI/bge-small-zh-v1.5',
    embeddingBaseUrl: '',
    embeddingApiKeyConfigured: false,
    embeddingInputType: 'passage',
    embeddingTruncate: 'NONE',
    rerankModel: 'deepseek-v4-flash'
  }
]

async function withFallback(request, fallback) {
  try {
    const response = await request()
    return response.data
  } catch (error) {
    if (!config.demoMode) {
      throw error
    }
    await sleep(240)
    return typeof fallback === 'function' ? fallback(error) : fallback
  }
}

export const ragClient = {
  login(payload) {
    return withFallback(
      () => api.post('/auth/login', payload),
      {
        token: 'demo-token',
        user: {
          id: 'u-demo',
          name: payload.username || '平台管理员',
          email: 'admin@example.com',
          role: 'admin'
        },
        tenants: mockTenants
      }
    )
  },

  register(payload) {
    const createdTenant = {
      id: `tenant-${Date.now()}`,
      name: payload.mode === 'createCompany' ? payload.companyName : '已加入企业',
      code: payload.mode === 'createCompany' ? 'ENT-DEMO123' : payload.companyCode,
      role: payload.mode === 'createCompany' ? 'tenant_owner' : 'employee',
      quota: '100 GB'
    }
    return withFallback(
      () => api.post('/auth/register', payload),
      {
        token: 'demo-token',
        user: {
          id: `user-${Date.now()}`,
          name: payload.displayName,
          email: payload.username,
          role: 'user'
        },
        tenants: [createdTenant]
      }
    )
  },

  listTenants() {
    return withFallback(() => api.get('/tenants'), { items: mockTenants })
  },

  listEmployees() {
    return withFallback(() => api.get('/tenants/employees'), { items: mockEmployees })
  },

  updateEmployeeRole(userId, role) {
    return withFallback(() => api.put(`/tenants/employees/${encodeURIComponent(userId)}/role`, { role }), {})
  },

  listCompanies() {
    return withFallback(() => api.get('/tenants/companies'), { items: mockCompanies })
  },

  uploadDocument({ file, tenantId, knowledgeBase, tags }) {
    const form = new FormData()
    form.append('file', file)
    form.append('tenantId', tenantId)
    form.append('knowledgeBase', knowledgeBase)
    form.append('tags', tags)

    return withFallback(
      () =>
        api.post('/documents/upload', form, {
          headers: { 'Content-Type': 'multipart/form-data' },
          timeout: 300000
        }),
      {
        id: `job-${Date.now()}`,
        fileName: file.name,
        knowledgeBase,
        status: 'queued',
        progress: 0,
        chunks: 0,
        errorMessage: '',
        updatedAt: new Date().toLocaleString('zh-CN', { hour12: false })
      }
    )
  },

  listTasks(tenantId) {
    return withFallback(() => api.get('/documents/tasks', { params: { tenantId } }), { items: mockTasks })
  },

  deleteDocument(documentId) {
    return withFallback(() => api.delete(`/documents/${encodeURIComponent(documentId)}`), {})
  },

  listChatHistory({ page = 1, size = 30 } = {}) {
    return withFallback(() => api.get('/chat/history', { params: { page, size } }), {
      items: mockChatSessions,
      total: mockChatSessions.length,
      page,
      size
    })
  },

  listChatMessages({ sessionId, page = 1, size = 200 } = {}) {
    return withFallback(
      () => api.get('/chat/messages', { params: { sessionId, page, size } }),
      {
        items: mockChatMessages[sessionId] || [],
        total: mockChatMessages[sessionId]?.length || 0,
        page,
        size
      }
    )
  },

  deleteChatSession(sessionId) {
    return withFallback(() => api.delete(`/chat/sessions/${encodeURIComponent(sessionId)}`), {})
  },

  ask(payload) {
    return withFallback(
      () => api.post('/chat/ask', payload),
      {
        sessionId: payload.sessionId || `demo-session-${Date.now()}`,
        answer:
          '这是演示回答：正式环境会从当前租户的文档切片、关键词索引和多轮上下文中检索证据，再交给启用的模型生成回答。',
        citations: [
          {
            id: 'cite-1',
            title: '供应商准入制度.pdf',
            page: 8,
            score: 0.91,
            text: '供应商准入需完成资质、信用、履约能力和合规风险审查。'
          }
        ],
        trace: {
          retrievalMs: 312,
          rerankMs: 0,
          generationMs: 1280,
          topK: payload.topK
        }
      }
    )
  },

  async askStream(payload, handlers = {}) {
    try {
      const response = await fetch(apiUrl('/chat/ask/stream'), {
        method: 'POST',
        headers: streamHeaders(),
        signal: handlers.signal,
        body: JSON.stringify(payload)
      })
      if (!response.ok) {
        const message = await response.text()
        const data = parseErrorPayload(message)
        throw createHttpError(data?.message || data?.msg || data?.error || message, response.status, response.statusText, data)
      }
      await readSseStream(response, handlers)
    } catch (error) {
      if (error?.name === 'AbortError' || handlers.signal?.aborted) {
        throw error
      }
      if (!config.demoMode) {
        throw error
      }
      const fallback = await this.ask(payload)
      handlers.onSession?.(fallback.sessionId)
      const answer = fallback.answer || ''
      if (payload.deepThinking) {
        handlers.onReasoning?.('正在检索当前企业知识库，并梳理与问题相关的证据。\n', {
          type: 'reasoning',
          sessionId: fallback.sessionId,
          reasoning: '正在检索当前企业知识库，并梳理与问题相关的证据。\n'
        })
        await sleep(120)
      }
      handlers.onStatus?.('正在调用模型生成回答...', {
        type: 'status',
        sessionId: fallback.sessionId,
        message: '正在调用模型生成回答...'
      })
      for (let index = 0; index < answer.length; index += 6) {
        if (handlers.signal?.aborted) {
          throw createAbortError()
        }
        const delta = answer.slice(index, index + 6)
        handlers.onDelta?.(delta, { type: 'delta', sessionId: fallback.sessionId, delta })
        await sleep(30)
      }
      handlers.onDone?.({
        type: 'done',
        sessionId: fallback.sessionId,
        answer,
        citations: fallback.citations || [],
        trace: fallback.trace
      })
    }
  },

  listModels() {
    return withFallback(() => api.get('/models'), { items: mockModels })
  },

  saveModel(payload) {
    return withFallback(() => api.post('/models', payload), {
      id: payload.modelName,
      provider: payload.provider,
      enabled: payload.enabled,
      baseUrl: payload.baseUrl,
      apiKeyConfigured: Boolean(payload.apiKey),
      temperature: payload.temperature,
      topP: payload.topP,
      maxTokens: payload.maxTokens,
      contextWindowTokens: payload.contextWindowTokens,
      embeddingProvider: payload.embeddingProvider,
      embeddingModel: payload.embeddingModel,
      embeddingBaseUrl: payload.embeddingBaseUrl,
      embeddingApiKeyConfigured: Boolean(payload.embeddingApiKey),
      embeddingInputType: payload.embeddingInputType,
      embeddingTruncate: payload.embeddingTruncate,
      rerankModel: payload.rerankModel
    })
  },

  switchModel(modelId) {
    return withFallback(() => api.put(`/models/${encodeURIComponent(modelId)}/activate`), { activeModelId: modelId })
  },

  deleteModel(modelId) {
    return withFallback(() => api.delete(`/models/${encodeURIComponent(modelId)}`), {})
  },

  health() {
    return withFallback(
      () => api.get('/health'),
      {
        status: 'degraded-demo',
        components: {
          mysql: 'unknown',
          redis: 'unknown',
          rabbitmq: 'unknown',
          vectorStore: 'unknown',
          ollama: 'unknown'
        }
      }
    )
  }
}
