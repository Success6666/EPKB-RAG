<template>
  <el-config-provider>
    <section v-if="view === 'chat'" class="chat-page">
      <header class="chat-header">
        <button class="brand-button" type="button" @click="resetConversation">
          <span class="brand-dot">R</span>
          <span>知识库问答</span>
        </button>
      </header>

      <div class="chat-layout">
        <aside class="chat-sidebar" aria-label="历史对话">
          <div class="chat-sidebar-head">
            <strong>历史对话</strong>
            <button class="sidebar-action" type="button" @click="resetConversation">新对话</button>
          </div>
          <div v-if="!session.token" class="history-empty">登录后显示历史对话</div>
          <div v-else-if="loading.history" class="history-empty">正在加载...</div>
          <div v-else-if="chatHistory.length === 0" class="history-empty">暂无历史对话</div>
          <nav v-else class="history-list">
            <div
              v-for="item in chatHistory"
              :key="item.sessionId"
              :class="{ active: String(item.sessionId) === String(chatForm.sessionId) }"
              class="history-row"
            >
              <button type="button" class="history-item" @click="loadConversation(item.sessionId)">
                <span>{{ item.title || '未命名对话' }}</span>
                <time>{{ formatChatTime(item.updatedAt) }}</time>
              </button>
              <div class="history-actions">
                <button
                  type="button"
                  class="history-more"
                  title="更多"
                  :aria-expanded="String(historyMenuSessionId) === String(item.sessionId) ? 'true' : 'false'"
                  @click.stop="toggleHistoryMenu(item.sessionId)"
                >
                  <el-icon><MoreFilled /></el-icon>
                </button>
                <div v-if="String(historyMenuSessionId) === String(item.sessionId)" class="history-menu" @click.stop>
                  <button
                    type="button"
                    class="history-menu-item danger"
                    :disabled="loading.deleteChatSession === String(item.sessionId)"
                    @click="deleteChatSession(item.sessionId)"
                  >
                    <el-icon><Delete /></el-icon>
                    <span>删除</span>
                  </button>
                </div>
              </div>
            </div>
          </nav>

          <div class="sidebar-account">
            <div v-if="session.token" class="account-menu-wrap">
              <div v-if="userMenuOpen" class="account-popover">
                <div class="account-popover-head">
                  <strong>{{ userDisplayName }}</strong>
                  <span>{{ session.user?.username || session.user?.email || '-' }}</span>
                </div>
                <div class="account-meta">
                  <span>{{ currentTenant?.name || '未选择企业' }}</span>
                  <strong>{{ permissionSummary }}</strong>
                </div>
                <button
                  v-if="hasAdminAccess"
                  class="account-menu-item"
                  type="button"
                  @click="enterAdmin"
                >
                  <el-icon><Setting /></el-icon>
                  <span>进入后台</span>
                </button>
                <button class="account-menu-item danger" type="button" @click="logout">
                  <el-icon><SwitchButton /></el-icon>
                  <span>退出账号</span>
                </button>
              </div>
              <button
                class="account-button"
                type="button"
                :aria-expanded="userMenuOpen ? 'true' : 'false'"
                @click="userMenuOpen = !userMenuOpen"
              >
                <span class="account-avatar">{{ userInitial }}</span>
                <span class="account-text">
                  <strong>{{ userDisplayName }}</strong>
                  <small>{{ permissionSummary }}</small>
                </span>
              </button>
            </div>
            <button v-else class="account-button" type="button" @click="openLogin">
              <span class="account-avatar">R</span>
              <span class="account-text">
                <strong>登录账号</strong>
                <small>查看历史对话和企业权限</small>
              </span>
            </button>
          </div>
        </aside>

        <main ref="chatMainRef" class="chat-main">
          <section v-if="messages.length === 0" class="welcome">
            <h1>有什么需要查询？</h1>
            <p>基于企业文档、知识库和多轮上下文回答问题；模型、知识库、导入任务等配置由管理员在后台维护。</p>
          </section>

          <section v-else class="message-list" aria-live="polite">
            <article v-for="message in messages" :key="message.id" class="message-row" :class="message.role">
              <div class="message-bubble">
                <div
                  v-if="message.role === 'assistant' && message.deepThinking && (message.reasoning || message.reasoningStreaming)"
                  class="reasoning-panel"
                  :class="{ streaming: message.reasoningStreaming }"
                >
                  <button
                    type="button"
                    class="reasoning-header"
                    :aria-expanded="message.reasoningOpen ? 'true' : 'false'"
                    @click="message.reasoningOpen = !message.reasoningOpen"
                  >
                    <span class="thinking-pulse" :class="{ active: message.reasoningStreaming }">
                      <span></span>
                      <span></span>
                      <span></span>
                    </span>
                    <span>{{ message.reasoningStreaming ? '正在深度思考' : '深度思考' }}</span>
                    <span v-if="message.reasoning" class="reasoning-count">{{ estimateReasoningLength(message.reasoning) }}</span>
                    <span class="reasoning-caret">{{ message.reasoningOpen ? '收起' : '展开' }}</span>
                  </button>
                  <Transition name="reasoning">
                    <div v-show="message.reasoningOpen" class="reasoning-content">
                      <p
                        v-if="message.reasoning"
                        :ref="(el) => setReasoningContentRef(message.id, el)"
                      >
                        {{ message.reasoning }}
                      </p>
                      <p v-else class="reasoning-placeholder">{{ reasoningPlaceholder(message) }}</p>
                    </div>
                  </Transition>
                </div>
                <div
                  v-if="message.role === 'assistant' && message.streaming && !message.content && message.statusText"
                  class="model-status"
                >
                  <span class="thinking-pulse active">
                    <span></span>
                    <span></span>
                    <span></span>
                  </span>
                  <span>{{ message.statusText }}</span>
                </div>
                <div
                  v-if="message.role === 'assistant' && message.content"
                  class="markdown-body"
                  v-html="renderMarkdown(message.content)"
                ></div>
                <p v-else-if="message.content">{{ message.content }}</p>
                <div v-if="message.citations?.length" class="citation-panel">
                  <button
                    v-for="citation in message.citations"
                    :key="citation.id"
                    type="button"
                    class="citation-chip"
                    :title="citation.text"
                  >
                    {{ citation.title }}<span v-if="citation.page"> p.{{ citation.page }}</span>
                  </button>
                </div>
              </div>
            </article>
          </section>
        </main>
      </div>

      <form class="composer-wrap" @submit.prevent="askQuestion">
        <div class="composer">
          <div class="composer-tools">
            <button
              class="thinking-toggle"
              :class="{ active: chatForm.deepThinking }"
              type="button"
              :aria-pressed="chatForm.deepThinking ? 'true' : 'false'"
              title="深度思考"
              @click="chatForm.deepThinking = !chatForm.deepThinking"
            >
              <el-icon><Cpu /></el-icon>
              <span>深度思考</span>
            </button>
          </div>
          <textarea
            v-model="chatForm.question"
            rows="1"
            placeholder="给知识库发消息"
            @input="resizeComposer"
            @keydown.enter.exact.prevent="askQuestion"
          />
          <button
            class="send-button"
            :class="{ stopping: isActiveConversationStreaming }"
            :type="isActiveConversationStreaming ? 'button' : 'submit'"
            :disabled="!isActiveConversationStreaming && !chatForm.question.trim()"
            :title="isActiveConversationStreaming ? '停止生成' : '发送'"
            @click="isActiveConversationStreaming && stopActiveConversationStream()"
          >
            <el-icon v-if="isActiveConversationStreaming"><VideoPause /></el-icon>
            <el-icon v-else><ArrowUp /></el-icon>
          </button>
        </div>
        <p class="subtle-note">回答可能来自已入库文档和历史对话，请以原始资料为准。</p>
      </form>
    </section>

    <section v-else-if="view === 'login'" class="login-page">
      <button class="text-button back-link" type="button" @click="view = 'chat'">返回对话</button>
      <div class="login-card">
        <div class="login-title">
          <span class="brand-dot">R</span>
          <div>
            <h1>账号登录</h1>
            <p>登录后按企业角色进入对话、文档或平台管理。</p>
          </div>
        </div>
        <el-form class="login-form" :model="loginForm" label-position="top" @submit.prevent="login">
          <el-form-item label="账号">
            <el-input v-model="loginForm.username" autocomplete="username" placeholder="admin@example.com" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input
              v-model="loginForm.password"
              autocomplete="current-password"
              placeholder="请输入密码"
              show-password
              @keyup.enter="login"
            />
          </el-form-item>
          <el-button type="primary" native-type="submit" :loading="loading.login" class="full-button">登录</el-button>
          <button class="text-button auth-switch" type="button" @click="view = 'register'">没有账号，去注册</button>
        </el-form>
      </div>
    </section>

    <section v-else-if="view === 'register'" class="login-page">
      <button class="text-button back-link" type="button" @click="view = 'chat'">返回对话</button>
      <div class="login-card">
        <div class="login-title">
          <span class="brand-dot">R</span>
          <div>
            <h1>注册账号</h1>
            <p>创建企业会生成唯一识别码，员工可用识别码加入。</p>
          </div>
        </div>
        <el-form class="login-form" :model="registerForm" label-position="top" @submit.prevent="register">
          <el-form-item label="账号">
            <el-input v-model="registerForm.username" autocomplete="username" placeholder="name@example.com" />
          </el-form-item>
          <el-form-item label="姓名">
            <el-input v-model="registerForm.displayName" autocomplete="name" placeholder="请输入姓名" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input
              v-model="registerForm.password"
              autocomplete="new-password"
              placeholder="至少 6 位"
              show-password
              @keyup.enter="register"
            />
          </el-form-item>
          <el-form-item label="企业方式">
            <el-radio-group v-model="registerForm.mode">
              <el-radio-button label="createCompany">创建企业</el-radio-button>
              <el-radio-button label="joinCompany">加入企业</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item v-if="registerForm.mode === 'createCompany'" label="公司名称">
            <el-input v-model="registerForm.companyName" placeholder="例如：新乡学院" />
          </el-form-item>
          <el-form-item v-else label="企业识别码">
            <el-input v-model="registerForm.companyCode" placeholder="例如：ENT-1A2B3C4D" />
          </el-form-item>
          <el-button type="primary" native-type="submit" :loading="loading.register" class="full-button">
            注册并进入
          </el-button>
          <button class="text-button auth-switch" type="button" @click="view = 'login'">已有账号，去登录</button>
        </el-form>
      </div>
    </section>

    <div v-else class="admin-shell">
      <aside class="admin-nav">
        <button class="admin-brand" type="button" @click="activeSection = 'dashboard'">
          <span class="brand-dot">R</span>
          <span>管理后台</span>
        </button>
        <nav>
          <button
            v-for="item in navItems"
            :key="item.key"
            type="button"
            :class="{ active: activeSection === item.key }"
            @click="activeSection = item.key"
          >
            <el-icon><component :is="item.icon" /></el-icon>
            <span>{{ item.label }}</span>
          </button>
        </nav>
      </aside>

      <main class="admin-main">
        <header class="admin-topbar">
          <div>
            <h1>{{ currentSectionTitle }}</h1>
            <p>{{ currentTenant?.name || '请选择租户' }}<span v-if="currentTenant?.code"> / {{ currentTenant.code }}</span></p>
          </div>
          <div class="admin-actions">
            <el-select v-model="session.tenantId" class="tenant-select" placeholder="选择租户" @change="onTenantChange">
              <el-option v-for="tenant in tenants" :key="tenant.id" :label="tenant.name" :value="tenant.id" />
            </el-select>
            <el-button @click="view = 'chat'">返回对话</el-button>
            <el-button :icon="SwitchButton" @click="logout">退出</el-button>
          </div>
        </header>

        <section v-show="activeSection === 'dashboard'" class="admin-grid">
          <article class="metric-card">
            <span>当前租户</span>
            <strong>{{ currentTenant?.name || '-' }}</strong>
            <small>{{ roleLabel(currentTenantRole) }} / {{ currentTenant?.code || '-' }}</small>
          </article>
          <article class="metric-card">
            <span>入库任务</span>
            <strong>{{ tasks.length }}</strong>
            <small>{{ runningTasks.length }} 个处理中</small>
          </article>
          <article class="metric-card">
            <span>当前模型</span>
            <strong>{{ activeModel?.id || '-' }}</strong>
            <small>{{ canManageModels ? activeModel?.provider || 'Ollama 本地' : '由平台管理员维护' }}</small>
          </article>

          <section class="panel wide">
            <div class="panel-title">
              <div>
                <h2>任务状态</h2>
                <p>展示文档解析、切分、向量写入和回写 Java 的进度。</p>
              </div>
              <el-button :icon="Refresh" @click="loadTasks">刷新</el-button>
            </div>
            <el-table :data="tasks" empty-text="暂无任务">
              <el-table-column prop="fileName" label="文件" min-width="180" />
              <el-table-column prop="knowledgeBase" label="知识库" width="150" />
              <el-table-column label="状态" width="120">
                <template #default="{ row }">
                  <el-tag :type="taskTagType(row.status)">{{ taskStatusLabel(row.status) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="进度" min-width="180">
                <template #default="{ row }">
                  <el-progress :percentage="row.progress" :status="row.status === 'failed' ? 'exception' : undefined" />
                </template>
              </el-table-column>
              <el-table-column prop="chunks" label="切片数" width="100" />
              <el-table-column label="失败原因" min-width="240">
                <template #default="{ row }">
                  <el-tooltip
                    v-if="row.status === 'failed' && row.errorMessage"
                    :content="row.errorMessage"
                    placement="top"
                    popper-class="task-error-popper"
                  >
                    <span class="task-error-text">{{ row.errorMessage }}</span>
                  </el-tooltip>
                  <span v-else class="task-error-empty">-</span>
                </template>
              </el-table-column>
              <el-table-column prop="updatedAt" label="更新时间" width="170" />
              <el-table-column label="操作" width="110" fixed="right">
                <template #default="{ row }">
                  <el-button
                    type="danger"
                    plain
                    size="small"
                    :icon="Delete"
                    :loading="loading.deleteDocument === documentIdFromTask(row)"
                    @click="deleteDocument(row)"
                  >
                    删除
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </section>
        </section>

        <section v-show="activeSection === 'upload' && canUploadDocuments" class="panel">
          <div class="panel-title">
            <div>
              <h2>文档入库</h2>
              <p>按租户和知识库提交文件，后端通过 MQ 异步解析和索引。</p>
            </div>
          </div>
          <el-form :model="uploadForm" label-position="top" class="upload-form">
            <el-form-item label="知识库">
              <el-select v-model="uploadForm.knowledgeBase" placeholder="选择或输入知识库" filterable allow-create>
                <el-option label="制度与流程" value="制度与流程" />
                <el-option label="合同档案" value="合同档案" />
                <el-option label="项目经验库" value="项目经验库" />
              </el-select>
            </el-form-item>
            <el-form-item label="标签">
              <el-input v-model="uploadForm.tags" placeholder="合规, 采购, 2026" />
            </el-form-item>
            <el-upload
              drag
              action="#"
              accept=".pdf,.doc,.docx,.txt,.md,.markdown,.csv,.xls,.xlsx"
              :auto-upload="false"
              :disabled="loading.upload"
              multiple
              v-model:file-list="uploadFiles"
              :on-change="onFileChange"
              :on-remove="onFileRemove"
            >
              <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
              <div class="el-upload__text">拖拽文件到此处，或点击选择</div>
              <template #tip>
                <div class="el-upload__tip">支持 PDF、DOC、DOCX、TXT、Markdown、CSV、Excel。</div>
              </template>
            </el-upload>
            <el-button type="primary" :loading="loading.upload" :disabled="loading.upload || uploadFiles.length === 0" @click="submitUpload">
              提交入库任务
            </el-button>
          </el-form>
        </section>

        <section v-show="activeSection === 'models' && canManageModels" class="panel">
          <div class="panel-title">
            <div>
              <h2>模型配置</h2>
              <p>管理员可维护本地 Ollama、NVIDIA NIM、DeepSeek、通义千问或 OpenAI-Compatible 模型。</p>
            </div>
            <el-button :icon="Refresh" @click="loadModels">刷新</el-button>
          </div>

          <el-form :model="modelForm" label-position="top" class="model-form">
            <div class="model-form-grid">
              <el-form-item label="供应商">
                <el-select v-model="modelForm.provider" @change="applyProviderDefaults">
                  <el-option label="Ollama 本地" value="Ollama" />
                  <el-option label="DeepSeek" value="DeepSeek" />
                  <el-option label="通义千问 / DashScope" value="DashScope" />
                  <el-option label="NVIDIA NIM" value="NVIDIA" />
                  <el-option label="OpenAI Compatible" value="OpenAI-Compatible" />
                </el-select>
              </el-form-item>
              <el-form-item label="模型名称">
                <el-input v-model="modelForm.modelName" placeholder="qwen2.5:7b" />
              </el-form-item>
              <el-form-item label="Base URL">
                <el-input v-model="modelForm.baseUrl" placeholder="http://host.docker.internal:11434" />
              </el-form-item>
              <el-form-item label="API Key">
                <el-input v-model="modelForm.apiKey" placeholder="留空则保留已保存密钥" show-password />
              </el-form-item>
              <el-form-item label="Embedding">
                <el-input v-model="modelForm.embeddingModel" placeholder="bge-m3" />
              </el-form-item>
              <el-form-item label="Embedding 供应商">
                <el-select v-model="modelForm.embeddingProvider" @change="applyEmbeddingDefaults">
                  <el-option label="Ollama 本地" value="Ollama" />
                  <el-option label="NVIDIA NIM" value="NVIDIA" />
                  <el-option label="SentenceTransformers" value="sentence_transformers" />
                </el-select>
              </el-form-item>
              <el-form-item label="Embedding Base URL">
                <el-input v-model="modelForm.embeddingBaseUrl" placeholder="https://integrate.api.nvidia.com/v1" />
              </el-form-item>
              <el-form-item label="Embedding API Key">
                <el-input v-model="modelForm.embeddingApiKey" placeholder="NVIDIA API Key，留空则保留已保存密钥" show-password />
              </el-form-item>
              <el-form-item label="Embedding input_type">
                <el-select v-model="modelForm.embeddingInputType" clearable>
                  <el-option label="passage（入库索引）" value="passage" />
                  <el-option label="query（查询）" value="query" />
                </el-select>
              </el-form-item>
              <el-form-item label="Embedding truncate">
                <el-select v-model="modelForm.embeddingTruncate">
                  <el-option label="NONE" value="NONE" />
                  <el-option label="START" value="START" />
                  <el-option label="END" value="END" />
                </el-select>
              </el-form-item>
              <el-form-item label="Rerank">
                <el-input v-model="modelForm.rerankModel" placeholder="none" />
              </el-form-item>
              <el-form-item label="Temperature">
                <el-input-number v-model="modelForm.temperature" :min="0" :max="2" :step="0.1" />
              </el-form-item>
              <el-form-item label="Top P">
                <el-input-number v-model="modelForm.topP" :min="0" :max="1" :step="0.05" />
              </el-form-item>
              <el-form-item label="Max Tokens">
                <el-input-number v-model="modelForm.maxTokens" :min="1" :max="200000" />
              </el-form-item>
              <el-form-item label="Context Window Tokens">
                <el-input-number v-model="modelForm.contextWindowTokens" :min="1024" :max="1048576" :step="1024" />
              </el-form-item>
              <el-form-item label="启用策略">
                <el-checkbox v-model="modelForm.enabled">保存后设为当前模型</el-checkbox>
              </el-form-item>
            </div>
            <div class="model-form-actions">
              <el-button @click="fillModelForm(activeModel || models[0])">填入当前模型</el-button>
              <el-button type="primary" :loading="loading.saveModel" @click="saveModel">
                {{ editingModelId ? '保存模型修改' : '保存模型配置' }}
              </el-button>
            </div>
          </el-form>

          <div class="model-grid">
            <article v-for="model in models" :key="model.id" class="model-card" :class="{ active: model.enabled }">
              <div class="model-head">
                <div>
                  <strong>{{ model.id }}</strong>
                  <span>{{ model.provider }}</span>
                </div>
                <el-tag :type="model.enabled ? 'success' : 'info'">{{ model.enabled ? '当前启用' : '可切换' }}</el-tag>
              </div>
              <dl>
                <div>
                  <dt>Base URL</dt>
                  <dd>{{ model.baseUrl || '-' }}</dd>
                </div>
                <div>
                  <dt>API Key</dt>
                  <dd>{{ model.apiKeyConfigured ? '已配置' : '未配置' }}</dd>
                </div>
                <div>
                  <dt>Temperature</dt>
                  <dd>{{ model.temperature }}</dd>
                </div>
                <div>
                  <dt>Top P</dt>
                  <dd>{{ model.topP }}</dd>
                </div>
                <div>
                  <dt>Max Tokens</dt>
                  <dd>{{ model.maxTokens }}</dd>
                </div>
                <div>
                  <dt>Context Window</dt>
                  <dd>{{ model.contextWindowTokens || 262144 }}</dd>
                </div>
                <div>
                  <dt>Embedding</dt>
                  <dd>{{ model.embeddingProvider || '-' }} / {{ model.embeddingModel || '-' }}</dd>
                </div>
                <div>
                  <dt>Embedding URL</dt>
                  <dd>{{ model.embeddingBaseUrl || '-' }}</dd>
                </div>
                <div>
                  <dt>Embedding Key</dt>
                  <dd>{{ model.embeddingApiKeyConfigured ? '已配置' : '未配置' }}</dd>
                </div>
                <div>
                  <dt>Input Type</dt>
                  <dd>{{ model.embeddingInputType || '-' }}</dd>
                </div>
              </dl>
              <div class="model-card-actions">
                <el-button @click="editModel(model)">编辑</el-button>
                <el-button :disabled="model.enabled" :loading="loading.model === model.id" @click="activateModel(model.id)">
                  切换到此模型
                </el-button>
                <el-button type="danger" plain :loading="loading.deleteModel === model.id" @click="deleteModel(model.id)">
                  删除
                </el-button>
              </div>
            </article>
          </div>
        </section>

        <section v-show="activeSection === 'employees' && canManageEmployees" class="panel">
          <div class="panel-title">
            <div>
              <h2>员工列表</h2>
              <p>创建企业的管理员可查看员工，并将普通员工升级为一般管理员。</p>
            </div>
            <el-button :icon="Refresh" @click="loadEmployees">刷新</el-button>
          </div>
          <el-table :data="employees" empty-text="暂无员工">
            <el-table-column prop="displayName" label="姓名" min-width="140" />
            <el-table-column prop="username" label="账号" min-width="200" />
            <el-table-column label="角色" width="150">
              <template #default="{ row }">
                <el-tag>{{ roleLabel(row.role) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="joinedAt" label="加入时间" width="190" />
            <el-table-column label="操作" width="210">
              <template #default="{ row }">
                <el-button
                  v-if="row.role === 'employee'"
                  size="small"
                  :loading="loading.employeeRole === row.userId"
                  @click="updateEmployeeRole(row.userId, 'tenant_admin')"
                >
                  设为一般管理员
                </el-button>
                <el-button
                  v-else-if="row.role === 'tenant_admin'"
                  size="small"
                  :loading="loading.employeeRole === row.userId"
                  @click="updateEmployeeRole(row.userId, 'employee')"
                >
                  设为普通员工
                </el-button>
                <span v-else class="table-muted">创建者</span>
              </template>
            </el-table-column>
          </el-table>
        </section>

        <section v-show="activeSection === 'companies' && isPlatformAdmin" class="panel">
          <div class="panel-title">
            <div>
              <h2>企业列表</h2>
              <p>最高管理员仅查看企业概要，不进入企业知识库或员工明细。</p>
            </div>
            <el-button :icon="Refresh" @click="loadCompanies">刷新</el-button>
          </div>
          <el-table :data="companies" empty-text="暂无企业">
            <el-table-column prop="name" label="企业名称" min-width="180" />
            <el-table-column prop="code" label="识别码" width="170" />
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <el-tag :type="row.status === 1 ? 'success' : 'info'">{{ row.status === 1 ? '启用' : '停用' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="createdAt" label="创建时间" width="190" />
          </el-table>
        </section>
      </main>
    </div>
  </el-config-provider>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  ArrowUp,
  Cpu,
  DataBoard,
  Delete,
  MoreFilled,
  OfficeBuilding,
  Refresh,
  Setting,
  SwitchButton,
  UploadFilled,
  UserFilled,
  VideoPause
} from '@element-plus/icons-vue'
import { ragClient, setAuthContext } from './api'
import { modelDefaults, embeddingDefaults } from './modelDefaults'
import { renderMarkdown } from './utils/markdown'

const view = ref('chat')
const activeSection = ref('dashboard')
const loading = reactive({
  login: false,
  register: false,
  upload: false,
  ask: false,
  history: false,
  messages: false,
  model: '',
  deleteModel: '',
  deleteChatSession: '',
  deleteDocument: '',
  saveModel: false,
  employeeRole: ''
})

const TASK_REFRESH_INTERVAL_MS = 2500

const session = reactive({
  token: window.localStorage.getItem('rag_token') || '',
  tenantId: window.localStorage.getItem('rag_tenant') || '',
  user: readStoredUser()
})

const loginForm = reactive({
  username: '',
  password: ''
})

const registerForm = reactive({
  username: '',
  password: '',
  displayName: '',
  mode: 'createCompany',
  companyName: '',
  companyCode: ''
})

const uploadForm = reactive({
  knowledgeBase: '制度与流程',
  tags: ''
})

const chatForm = reactive({
  question: '',
  knowledgeBase: 'all',
  sessionId: '',
  topK: 5,
  temperature: 0.2,
  scoreThreshold: 0.45,
  deepThinking: false
})

const modelForm = reactive({
  provider: 'Ollama',
  modelName: modelDefaults.Ollama.modelName,
  baseUrl: modelDefaults.Ollama.baseUrl,
  apiKey: '',
  embeddingProvider: modelDefaults.Ollama.embeddingProvider,
  embeddingModel: modelDefaults.Ollama.embeddingModel,
  embeddingBaseUrl: modelDefaults.Ollama.embeddingBaseUrl,
  embeddingApiKey: '',
  embeddingInputType: modelDefaults.Ollama.embeddingInputType,
  embeddingTruncate: modelDefaults.Ollama.embeddingTruncate,
  rerankModel: modelDefaults.Ollama.rerankModel,
  temperature: modelDefaults.Ollama.temperature,
  topP: modelDefaults.Ollama.topP,
  maxTokens: modelDefaults.Ollama.maxTokens,
  contextWindowTokens: modelDefaults.Ollama.contextWindowTokens,
  enabled: true
})

const tenants = ref([])
const tasks = ref([])
const models = ref([])
const chatHistory = ref([])
const historyMenuSessionId = ref('')
const employees = ref([])
const companies = ref([])
const uploadFiles = ref([])
const conversationMessages = reactive({})
const streamingConversations = reactive({})
const activeConversationKey = ref(newConversationKey())
const editingModelId = ref('')
const userMenuOpen = ref(false)
const chatMainRef = ref(null)
const reasoningContentRefs = new Map()
const streamControllers = new Map()
const notifiedFailedTaskIds = new Set()
let taskRefreshTimer = null
let streamGeneration = 0

const currentTenant = computed(() => tenants.value.find((tenant) => String(tenant.id) === String(session.tenantId)))
const currentTenantRole = computed(() => normalizeRole(currentTenant.value?.role))
const isPlatformAdmin = computed(() => session.user?.role === 'admin')
const canUploadDocuments = computed(() => ['tenant_owner', 'tenant_admin'].includes(currentTenantRole.value))
const canManageEmployees = computed(() => currentTenantRole.value === 'tenant_owner')
const canManageModels = computed(() => isPlatformAdmin.value && Boolean(session.tenantId))
const hasAdminAccess = computed(
  () => canUploadDocuments.value || canManageEmployees.value || canManageModels.value || isPlatformAdmin.value
)
const userDisplayName = computed(() => session.user?.displayName || session.user?.name || session.user?.username || '当前用户')
const userInitial = computed(() => String(userDisplayName.value || 'R').trim().slice(0, 1).toUpperCase())
const permissionSummary = computed(() => {
  if (isPlatformAdmin.value) {
    return '最高管理员'
  }
  return roleLabel(currentTenantRole.value)
})
const runningTasks = computed(() => tasks.value.filter((task) => ['queued', 'running'].includes(task.status)))
const activeModel = computed(() => models.value.find((model) => model.enabled))
const messages = computed(() => conversationMessages[activeConversationKey.value] || [])
const isActiveConversationStreaming = computed(() => Boolean(streamingConversations[activeConversationKey.value]))
const navItems = computed(() => [
  { key: 'dashboard', label: '概览', icon: DataBoard },
  ...(canUploadDocuments.value ? [{ key: 'upload', label: '文档', icon: UploadFilled }] : []),
  ...(canManageEmployees.value ? [{ key: 'employees', label: '员工', icon: UserFilled }] : []),
  ...(canManageModels.value ? [{ key: 'models', label: '模型', icon: Setting }] : []),
  ...(isPlatformAdmin.value ? [{ key: 'companies', label: '企业', icon: OfficeBuilding }] : [])
])
const currentSectionTitle = computed(() => navItems.value.find((item) => item.key === activeSection.value)?.label || '管理后台')

setAuthContext(session)

onMounted(async () => {
  if (session.token) {
    try {
      await bootstrapAfterLogin()
      view.value = 'chat'
    } catch (error) {
      handleAuthFailure(error)
    }
  }
  startTaskAutoRefresh()
})

onBeforeUnmount(() => {
  stopTaskAutoRefresh()
})

watch(activeSection, () => {
  startTaskAutoRefresh()
})

watch(
  () => view.value,
  (nextView) => {
    if (nextView !== 'chat') {
      userMenuOpen.value = false
    }
    startTaskAutoRefresh()
  }
)

function openLogin() {
  userMenuOpen.value = false
  if (session.token) {
    return
  }
  view.value = 'login'
}

function enterAdmin() {
  if (!hasAdminAccess.value) {
    ElMessage.warning('当前账号没有后台权限')
    return
  }
  userMenuOpen.value = false
  keepSectionVisible()
  view.value = 'admin'
  startTaskAutoRefresh()
}

async function login() {
  loading.login = true
  try {
    const data = await ragClient.login(loginForm)
    await applyAuthPayload(data)
    view.value = 'chat'
    resetConversation()
    ElMessage.success('登录成功')
  } catch (error) {
    ElMessage.error(`登录失败：${friendlyError(error)}`)
  } finally {
    loading.login = false
  }
}

async function register() {
  if (!registerForm.username.trim() || !registerForm.password.trim() || !registerForm.displayName.trim()) {
    ElMessage.warning('请填写账号、姓名和密码')
    return
  }
  if (registerForm.mode === 'createCompany' && !registerForm.companyName.trim()) {
    ElMessage.warning('请填写公司名称')
    return
  }
  if (registerForm.mode === 'joinCompany' && !registerForm.companyCode.trim()) {
    ElMessage.warning('请填写企业识别码')
    return
  }
  loading.register = true
  try {
    const data = await ragClient.register({
      ...registerForm,
      companyCode: registerForm.companyCode.trim()
    })
    await applyAuthPayload(data)
    view.value = 'chat'
    resetConversation()
    ElMessage.success('注册成功')
  } catch (error) {
    ElMessage.error(`注册失败：${friendlyError(error)}`)
  } finally {
    loading.register = false
  }
}

async function applyAuthPayload(data) {
  session.token = data.token
  session.user = data.user
  tenants.value = data.tenants || []
  session.tenantId = String(tenants.value[0]?.id || '')
  persistSession()
  setAuthContext(session)
  await bootstrapAfterLogin()
  keepSectionVisible()
  userMenuOpen.value = false
}

function logout() {
  cancelActiveStreams()
  clearConversationState()
  session.token = ''
  session.tenantId = ''
  session.user = null
  tenants.value = []
  tasks.value = []
  notifiedFailedTaskIds.clear()
  models.value = []
  employees.value = []
  companies.value = []
  chatHistory.value = []
  userMenuOpen.value = false
  resetConversation()
  stopTaskAutoRefresh()
  window.localStorage.removeItem('rag_token')
  window.localStorage.removeItem('rag_tenant')
  window.localStorage.removeItem('rag_user')
  setAuthContext(session)
  view.value = 'chat'
}

function persistSession() {
  window.localStorage.setItem('rag_token', session.token)
  window.localStorage.setItem('rag_tenant', session.tenantId)
  window.localStorage.setItem('rag_user', JSON.stringify(session.user || null))
}

async function bootstrapAfterLogin() {
  if (!session.token) {
    return
  }
  if (!tenants.value.length) {
    try {
      const tenantData = await ragClient.listTenants()
      tenants.value = tenantData.items || []
      if (!tenants.value.some((tenant) => String(tenant.id) === String(session.tenantId))) {
        session.tenantId = String(tenants.value[0]?.id || '')
      }
    } catch (error) {
      if (!isPlatformAdmin.value) {
        throw error
      }
      tenants.value = []
      session.tenantId = ''
    }
  }
  setAuthContext(session)
  persistSession()
  keepSectionVisible()
  await Promise.all([loadTasks(), loadModels(), loadChatHistory(), loadEmployees(), loadCompanies()])
  fillModelForm(activeModel.value || models.value[0])
}

async function onTenantChange() {
  cancelActiveStreams()
  clearConversationState()
  notifiedFailedTaskIds.clear()
  persistSession()
  setAuthContext(session)
  resetConversation()
  keepSectionVisible()
  await Promise.all([loadTasks(), loadModels(), loadChatHistory(), loadEmployees()])
  fillModelForm(activeModel.value || models.value[0])
}

async function loadTasks(options = {}) {
  const { notifyFailures = false, silent = false } = options
  if (!session.token || !session.tenantId || !hasAdminAccess.value) {
    tasks.value = []
    return
  }
  const previousTasks = tasks.value
  try {
    const data = await ragClient.listTasks(session.tenantId)
    const nextTasks = data.items || []
    if (notifyFailures) {
      notifyNewFailedTasks(previousTasks, nextTasks)
    }
    tasks.value = nextTasks
  } catch (error) {
    if (isUnauthorized(error)) {
      tasks.value = []
      throw error
    }
    if (!silent) {
      tasks.value = []
      ElMessage.warning(`文档任务加载失败：${friendlyError(error)}`)
    }
  }
}

function notifyNewFailedTasks(previousTasks, nextTasks) {
  const previousStatusMap = new Map(
    previousTasks.map((task) => [taskNotificationKey(task), task?.status]).filter(([key]) => key)
  )
  nextTasks
    .filter((task) => task?.status === 'failed')
    .forEach((task) => {
      const key = taskNotificationKey(task)
      const previousStatus = previousStatusMap.get(key)
      if (!key || notifiedFailedTaskIds.has(key) || !['queued', 'running'].includes(previousStatus)) {
        return
      }
      notifiedFailedTaskIds.add(key)
      const reason = task.errorMessage || '未返回具体失败原因'
      ElMessage.error({
        message: `文档入库失败：${task.fileName || '未命名文件'}。${reason}`,
        duration: 8000,
        showClose: true
      })
    })
}

function taskNotificationKey(task) {
  return String(documentIdFromTask(task) || task?.id || '')
}

function documentIdFromTask(task) {
  return String(task?.documentId || task?.docId || String(task?.id || '').replace(/^job-/, ''))
}

async function deleteDocument(task) {
  if (!canUploadDocuments.value) {
    ElMessage.warning('当前角色无权删除文档')
    return
  }
  const documentId = documentIdFromTask(task)
  if (!documentId || loading.deleteDocument) {
    return
  }
  loading.deleteDocument = documentId
  try {
    await ragClient.deleteDocument(documentId)
    tasks.value = tasks.value.filter((item) => documentIdFromTask(item) !== documentId)
    ElMessage.success('文档已删除')
  } catch (error) {
    ElMessage.error(`文档删除失败：${friendlyError(error)}`)
  } finally {
    loading.deleteDocument = ''
  }
}

async function loadModels() {
  if (!session.token || !canManageModels.value) {
    models.value = []
    return
  }
  try {
    const data = await ragClient.listModels()
    models.value = data.items || []
  } catch (error) {
    models.value = []
    ElMessage.warning(`模型配置加载失败：${friendlyError(error)}`)
  }
}

async function loadEmployees() {
  if (!session.token || !canManageEmployees.value) {
    employees.value = []
    return
  }
  try {
    const data = await ragClient.listEmployees()
    employees.value = data.items || []
  } catch (error) {
    employees.value = []
    ElMessage.warning(`员工列表加载失败：${friendlyError(error)}`)
  }
}

async function updateEmployeeRole(userId, role) {
  loading.employeeRole = userId
  try {
    await ragClient.updateEmployeeRole(userId, role)
    await loadEmployees()
    ElMessage.success('员工角色已更新')
  } catch (error) {
    ElMessage.error(`角色更新失败：${friendlyError(error)}`)
  } finally {
    loading.employeeRole = ''
  }
}

async function loadCompanies() {
  if (!session.token || !isPlatformAdmin.value) {
    companies.value = []
    return
  }
  try {
    const data = await ragClient.listCompanies()
    companies.value = data.items || []
  } catch (error) {
    companies.value = []
    ElMessage.warning(`企业列表加载失败：${friendlyError(error)}`)
  }
}

async function loadChatHistory() {
  if (!session.token) {
    chatHistory.value = []
    return
  }
  loading.history = true
  try {
    const data = await ragClient.listChatHistory({ page: 1, size: 50 })
    chatHistory.value = data.items || []
  } catch (error) {
    if (isUnauthorized(error)) {
      handleAuthFailure(error)
    } else {
      ElMessage.warning(`历史对话加载失败：${friendlyError(error)}`)
    }
  } finally {
    loading.history = false
  }
}

async function loadConversation(sessionId) {
  if (!sessionId || loading.messages) {
    return
  }
  historyMenuSessionId.value = ''
  const key = conversationKey(sessionId)
  activeConversationKey.value = key
  chatForm.sessionId = String(sessionId)
  if (conversationMessages[key]?.length) {
    await nextTick()
    scrollChatToBottom()
    return
  }
  loading.messages = true
  try {
    const data = await ragClient.listChatMessages({ sessionId, page: 1, size: 200 })
    setConversationMessages(key, [...(data.items || [])]
      .sort((left, right) => new Date(left.createdAt || 0) - new Date(right.createdAt || 0))
      .map(toDisplayMessage))
    await nextTick()
    scrollChatToBottom()
  } catch (error) {
    if (isMissingSession(error)) {
      clearMissingSession(sessionId)
      ElMessage.warning('该历史会话不存在，已为你开启新对话')
      return
    }
    if (isUnauthorized(error)) {
      handleAuthFailure(error)
      return
    }
    ElMessage.error(`历史消息加载失败：${friendlyError(error)}`)
  } finally {
    loading.messages = false
  }
}

function toggleHistoryMenu(sessionId) {
  historyMenuSessionId.value = String(historyMenuSessionId.value) === String(sessionId) ? '' : String(sessionId)
}

async function deleteChatSession(sessionId) {
  if (!sessionId || loading.deleteChatSession) {
    return
  }
  const sessionIdText = String(sessionId)
  loading.deleteChatSession = sessionIdText
  try {
    await ragClient.deleteChatSession(sessionIdText)
    historyMenuSessionId.value = ''
    clearMissingSession(sessionIdText)
    ElMessage.success('对话已删除')
  } catch (error) {
    if (isMissingSession(error)) {
      historyMenuSessionId.value = ''
      clearMissingSession(sessionIdText)
      ElMessage.success('对话已删除')
      return
    }
    if (isUnauthorized(error)) {
      handleAuthFailure(error)
      return
    }
    ElMessage.error(`对话删除失败：${friendlyError(error)}`)
  } finally {
    loading.deleteChatSession = ''
  }
}

function applyProviderDefaults() {
  const defaults = modelDefaults[modelForm.provider]
  if (!defaults) {
    return
  }
  Object.assign(modelForm, {
    modelName: defaults.modelName,
    baseUrl: defaults.baseUrl,
    embeddingProvider: defaults.embeddingProvider,
    embeddingModel: defaults.embeddingModel,
    embeddingBaseUrl: defaults.embeddingBaseUrl,
    embeddingInputType: defaults.embeddingInputType,
    embeddingTruncate: defaults.embeddingTruncate,
    rerankModel: defaults.rerankModel,
    temperature: defaults.temperature,
    topP: defaults.topP,
    maxTokens: defaults.maxTokens,
    contextWindowTokens: defaults.contextWindowTokens
  })
}

function applyEmbeddingDefaults() {
  const defaults = embeddingDefaults[modelForm.embeddingProvider]
  if (defaults) {
    Object.assign(modelForm, defaults)
  }
}

async function saveModel() {
  if (!canManageModels.value) {
    ElMessage.warning('模型配置仅最高管理员可维护')
    return
  }
  if (!modelForm.modelName.trim()) {
    ElMessage.warning('请输入模型名称')
    return
  }
  loading.saveModel = true
  try {
    cancelActiveStreams()
    await ragClient.saveModel({ ...modelForm, originalModelName: editingModelId.value || undefined })
    modelForm.apiKey = ''
    modelForm.embeddingApiKey = ''
    await loadModels()
    const refreshedModel = models.value.find((model) => model.id === modelForm.modelName)
    fillModelForm(refreshedModel || activeModel.value || models.value[0])
    resetConversation()
    ElMessage.success('模型配置已保存')
  } catch (error) {
    ElMessage.error(`模型保存失败：${friendlyError(error)}`)
  } finally {
    loading.saveModel = false
  }
}

function onFileChange(file, fileList) {
  uploadFiles.value = fileList
}

function onFileRemove(file, fileList) {
  uploadFiles.value = fileList
}

async function submitUpload() {
  const filesToUpload = uploadFiles.value.filter((file) => file.raw)
  if (filesToUpload.length === 0) {
    return
  }
  if (!canUploadDocuments.value) {
    ElMessage.warning('当前角色无权上传文档')
    return
  }
  loading.upload = true
  const uploadedTasks = []
  const failedFiles = []
  try {
    for (const uploadFile of filesToUpload) {
      try {
        const task = await ragClient.uploadDocument({
          file: uploadFile.raw,
          tenantId: session.tenantId,
          knowledgeBase: uploadForm.knowledgeBase,
          tags: uploadForm.tags
        })
        uploadedTasks.push(task)
        uploadFiles.value = uploadFiles.value.filter((file) => file.uid !== uploadFile.uid)
      } catch (error) {
        failedFiles.push({ name: uploadFile.name, error })
      }
    }

    if (uploadedTasks.length > 0) {
      tasks.value = [...uploadedTasks.reverse(), ...tasks.value]
      startTaskAutoRefresh()
    }

    if (failedFiles.length === 0) {
      activeSection.value = 'dashboard'
      ElMessage.success(uploadedTasks.length === 1 ? '入库任务已提交' : `${uploadedTasks.length} 个入库任务已提交`)
    } else if (uploadedTasks.length > 0) {
      ElMessage.warning(`${uploadedTasks.length} 个文件已提交，${failedFiles.length} 个文件上传失败，失败文件已保留在列表中`)
    } else {
      ElMessage.error(`上传失败：${friendlyError(failedFiles[0].error)}`)
    }
  } finally {
    loading.upload = false
  }
}

async function askQuestion() {
  const question = chatForm.question.trim()
  const initialKey = chatForm.sessionId ? conversationKey(chatForm.sessionId) : activeConversationKey.value
  if (!question || streamingConversations[initialKey]) {
    return
  }
  if (!session.token) {
    appendConversationMessage(activeConversationKey.value, {
      id: `a-${Date.now()}`,
      role: 'assistant',
      content: '请先登录账号，然后再开始对话。'
    })
    view.value = 'login'
    return
  }
  const requestSessionId = chatForm.sessionId || ''
  const requestTenantId = session.tenantId || ''
  const requestDeepThinking = chatForm.deepThinking
  const requestGeneration = streamGeneration
  const requestKey = chatForm.sessionId ? conversationKey(chatForm.sessionId) : activeConversationKey.value
  let streamKey = requestKey
  const abortController = new AbortController()
  const isCurrentStream = () => streamGeneration === requestGeneration && !abortController.signal.aborted
  activeConversationKey.value = requestKey
  const userMessage = { id: `u-${Date.now()}`, role: 'user', content: question }
  appendConversationMessage(requestKey, userMessage)
  const assistantMessageId = `a-${Date.now()}`
  appendConversationMessage(requestKey, {
    id: assistantMessageId,
    role: 'assistant',
    content: '',
    citations: [],
    streaming: true,
    deepThinking: requestDeepThinking,
    reasoning: '',
    reasoningOpen: requestDeepThinking,
    reasoningStreaming: requestDeepThinking,
    statusText: '模型思考中，正在准备检索知识库...'
  })
  chatForm.question = ''
  resizeComposer()
  streamingConversations[streamKey] = true
  streamControllers.set(streamKey, abortController)
  try {
    await ragClient.askStream({
      tenantId: requestTenantId || undefined,
      sessionId: requestSessionId || undefined,
      question,
      knowledgeBase: chatForm.knowledgeBase,
      topK: chatForm.topK,
      temperature: chatForm.temperature,
      scoreThreshold: chatForm.scoreThreshold,
      deepThinking: requestDeepThinking
    }, {
      signal: abortController.signal,
      onSession: (sessionId) => {
        if (!isCurrentStream()) {
          return
        }
        if (!sessionId) {
          return
        }
        const sessionKey = conversationKey(sessionId)
        const stillViewingRequest = activeConversationKey.value === requestKey
        if (sessionKey !== requestKey) {
          moveConversationMessages(requestKey, sessionKey)
          streamingConversations[sessionKey] = true
          delete streamingConversations[requestKey]
          streamControllers.delete(requestKey)
          streamControllers.set(sessionKey, abortController)
          streamKey = sessionKey
        }
        if (stillViewingRequest) {
          activeConversationKey.value = sessionKey
          chatForm.sessionId = String(sessionId)
        }
        upsertChatHistory({
          sessionId,
          title: question.slice(0, 40),
          updatedAt: new Date().toISOString()
        })
      },
      onDelta: (delta, event) => {
        if (!isCurrentStream()) {
          return
        }
        const key = event?.sessionId ? conversationKey(event.sessionId) : activeConversationKey.value
        patchConversationMessage(key, assistantMessageId, (message) => {
          message.content += delta
          message.streaming = true
          message.statusText = ''
        })
        if (activeConversationKey.value === key) {
          scrollReasoningToBottom(assistantMessageId)
          scrollChatToBottom({ immediate: true })
        }
      },
      onStatus: (statusText, event) => {
        if (!isCurrentStream()) {
          return
        }
        const key = event?.sessionId ? conversationKey(event.sessionId) : activeConversationKey.value
        patchConversationMessage(key, assistantMessageId, (message) => {
          message.statusText = statusText || '模型思考中...'
          message.streaming = true
        })
        if (activeConversationKey.value === key) {
          scrollChatToBottom({ immediate: true })
        }
      },
      onReasoning: (reasoning, event) => {
        if (!isCurrentStream()) {
          return
        }
        if (!requestDeepThinking) {
          return
        }
        const key = event?.sessionId ? conversationKey(event.sessionId) : activeConversationKey.value
        patchConversationMessage(key, assistantMessageId, (message) => {
          message.deepThinking = true
          message.reasoning = `${message.reasoning || ''}${reasoning}`
          message.reasoningOpen = true
          message.reasoningStreaming = true
        })
        if (activeConversationKey.value === key) {
          scrollReasoningToBottom(assistantMessageId)
          scrollChatToBottom({ immediate: true })
        }
      },
      onDone: async (event) => {
        if (!isCurrentStream()) {
          return
        }
        const key = event?.sessionId ? conversationKey(event.sessionId) : activeConversationKey.value
        patchConversationMessage(key, assistantMessageId, (message) => {
          message.content = event.answer || message.content
          message.citations = event.citations || []
          message.streaming = false
          message.reasoningStreaming = false
          message.statusText = ''
        })
        await loadChatHistory()
      }
    })
  } catch (error) {
    if (error?.name === 'AbortError' || !isCurrentStream()) {
      patchConversationMessage(streamKey, assistantMessageId, (message) => {
        message.streaming = false
        message.reasoningStreaming = false
        message.statusText = ''
      })
      return
    }
    if (isUnauthorized(error)) {
      patchConversationMessage(streamKey, assistantMessageId, (message) => {
        message.content = '当前问答接口需要登录后使用。请点击右上角“登录”，登录后可继续对话。'
        message.streaming = false
        message.reasoningStreaming = false
        message.statusText = ''
      })
      view.value = 'login'
    } else if (isMissingSession(error)) {
      clearMissingSession(requestSessionId, { reset: false })
      patchConversationMessage(streamKey, assistantMessageId, (message) => {
        message.content = '旧会话已失效，请在新对话中重新发送。'
        message.streaming = false
        message.reasoningStreaming = false
        message.statusText = ''
      })
      await loadChatHistory()
    } else {
      patchConversationMessage(streamKey, assistantMessageId, (message) => {
        message.content = `请求失败：${friendlyError(error)}`
        message.streaming = false
        message.reasoningStreaming = false
        message.statusText = ''
      })
    }
  } finally {
    streamControllers.delete(streamKey)
    delete streamingConversations[streamKey]
    await nextTick()
    if (activeConversationKey.value === streamKey || activeConversationKey.value === requestKey) {
      scrollChatToBottom()
    }
  }
}

async function activateModel(modelId) {
  if (!canManageModels.value) {
    ElMessage.warning('模型配置仅最高管理员可维护')
    return
  }
  loading.model = modelId
  try {
    cancelActiveStreams()
    await ragClient.switchModel(modelId)
    models.value = models.value.map((model) => ({ ...model, enabled: model.id === modelId }))
    fillModelForm(models.value.find((model) => model.id === modelId))
    resetConversation()
    ElMessage.success('模型已切换')
  } catch (error) {
    ElMessage.error(`模型切换失败：${friendlyError(error)}`)
  } finally {
    loading.model = ''
  }
}

async function deleteModel(modelId) {
  if (!canManageModels.value) {
    ElMessage.warning('模型配置仅最高管理员可维护')
    return
  }
  loading.deleteModel = modelId
  try {
    cancelActiveStreams()
    await ragClient.deleteModel(modelId)
    models.value = models.value.filter((model) => model.id !== modelId)
    if (editingModelId.value === modelId) {
      fillModelForm(activeModel.value || models.value[0])
    }
    resetConversation()
    ElMessage.success('模型配置已删除')
  } catch (error) {
    ElMessage.error(`模型删除失败：${friendlyError(error)}`)
  } finally {
    loading.deleteModel = ''
  }
}

function resetConversation() {
  chatForm.sessionId = ''
  activeConversationKey.value = newConversationKey()
  ensureConversation(activeConversationKey.value)
}

function cancelActiveStreams() {
  streamGeneration += 1
  for (const controller of streamControllers.values()) {
    controller.abort()
  }
  streamControllers.clear()
  Object.keys(streamingConversations).forEach((key) => {
    delete streamingConversations[key]
  })
}

function stopActiveConversationStream() {
  const key = activeConversationKey.value
  const controller = streamControllers.get(key)
  if (!controller) {
    delete streamingConversations[key]
    return
  }
  controller.abort()
  streamControllers.delete(key)
  delete streamingConversations[key]
}

function clearConversationState() {
  Object.keys(conversationMessages).forEach((key) => {
    delete conversationMessages[key]
  })
  resetConversation()
}

function newConversationKey() {
  return `draft-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function conversationKey(sessionId) {
  return sessionId ? `session-${sessionId}` : activeConversationKey.value
}

function ensureConversation(key) {
  if (!conversationMessages[key]) {
    conversationMessages[key] = []
  }
  return conversationMessages[key]
}

function setConversationMessages(key, nextMessages) {
  conversationMessages[key] = nextMessages
}

function appendConversationMessage(key, message) {
  ensureConversation(key).push(message)
}

function patchConversationMessage(key, messageId, updater) {
  const list = ensureConversation(key)
  const message = list.find((item) => item.id === messageId)
  if (!message) {
    return
  }
  updater(message)
}

function moveConversationMessages(fromKey, toKey) {
  if (fromKey === toKey) {
    return
  }
  const draftMessages = ensureConversation(fromKey)
  const existingMessages = conversationMessages[toKey] || []
  conversationMessages[toKey] = existingMessages.length ? existingMessages : draftMessages
  delete conversationMessages[fromKey]
}

function upsertChatHistory(item) {
  const normalizedId = String(item.sessionId)
  const existing = chatHistory.value.filter((entry) => String(entry.sessionId) !== normalizedId)
  chatHistory.value = [{ ...item, sessionId: item.sessionId }, ...existing]
}

function setReasoningContentRef(messageId, element) {
  if (element) {
    reasoningContentRefs.set(messageId, element)
  } else {
    reasoningContentRefs.delete(messageId)
  }
}

function scrollReasoningToBottom(messageId) {
  nextTick(() => {
    const content = reasoningContentRefs.get(messageId)?.parentElement
    if (content) {
      content.scrollTop = content.scrollHeight
    }
  })
}

function scrollChatToBottom(options = {}) {
  const immediate = Boolean(options.immediate)
  nextTick(() => {
    const target = chatMainRef.value
    if (target) {
      if (immediate) {
        target.scrollTop = target.scrollHeight
      } else {
        target.scrollTo({ top: target.scrollHeight, behavior: 'smooth' })
      }
      return
    }
    if (immediate) {
      window.scrollTo(0, document.body.scrollHeight)
      return
    }
    window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' })
  })
}

function keepSectionVisible() {
  const visibleKeys = navItems.value.map((item) => item.key)
  if (!visibleKeys.includes(activeSection.value)) {
    activeSection.value = visibleKeys[0] || 'dashboard'
  }
}

function normalizeRole(role) {
  const value = String(role || '').toLowerCase()
  if (value === 'admin') {
    return 'tenant_owner'
  }
  if (value === 'user') {
    return 'employee'
  }
  return value || 'employee'
}

function roleLabel(role) {
  return {
    tenant_owner: '企业创建者',
    tenant_admin: '一般管理员',
    employee: '普通员工',
    admin: '最高管理员',
    user: '普通员工'
  }[role] || role || '-'
}

function readStoredUser() {
  const value = window.localStorage.getItem('rag_user')
  if (!value) {
    return null
  }
  try {
    return JSON.parse(value)
  } catch {
    window.localStorage.removeItem('rag_user')
    return null
  }
}

function editModel(model) {
  fillModelForm(model)
}

function fillModelForm(model) {
  if (!model) {
    editingModelId.value = ''
    Object.assign(modelForm, {
      provider: 'Ollama',
      modelName: modelDefaults.Ollama.modelName,
      baseUrl: modelDefaults.Ollama.baseUrl,
      apiKey: '',
      embeddingProvider: modelDefaults.Ollama.embeddingProvider,
      embeddingModel: modelDefaults.Ollama.embeddingModel,
      embeddingBaseUrl: modelDefaults.Ollama.embeddingBaseUrl,
      embeddingApiKey: '',
      embeddingInputType: modelDefaults.Ollama.embeddingInputType,
      embeddingTruncate: modelDefaults.Ollama.embeddingTruncate,
      rerankModel: modelDefaults.Ollama.rerankModel,
      temperature: modelDefaults.Ollama.temperature,
      topP: modelDefaults.Ollama.topP,
      maxTokens: modelDefaults.Ollama.maxTokens,
      contextWindowTokens: modelDefaults.Ollama.contextWindowTokens,
      enabled: true
    })
    return
  }
  editingModelId.value = model.id
  Object.assign(modelForm, {
    provider: model.provider || 'Ollama',
    modelName: model.id || model.modelName || '',
    baseUrl: model.baseUrl || '',
    apiKey: '',
    embeddingProvider: model.embeddingProvider || modelDefaults[model.provider]?.embeddingProvider || modelDefaults.Ollama.embeddingProvider,
    embeddingModel: model.embeddingModel || modelDefaults[model.provider]?.embeddingModel || modelDefaults.Ollama.embeddingModel,
    embeddingBaseUrl: model.embeddingBaseUrl || '',
    embeddingApiKey: '',
    embeddingInputType: model.embeddingInputType || '',
    embeddingTruncate: model.embeddingTruncate || 'NONE',
    rerankModel: model.rerankModel || 'none',
    temperature: Number(model.temperature ?? modelDefaults.Ollama.temperature),
    topP: Number(model.topP ?? modelDefaults.Ollama.topP),
    maxTokens: Number(model.maxTokens ?? modelDefaults.Ollama.maxTokens),
    contextWindowTokens: Number(model.contextWindowTokens ?? modelDefaults.Ollama.contextWindowTokens),
    enabled: Boolean(model.enabled)
  })
}

function toDisplayMessage(message) {
  return {
    id: message.id || `${message.role}-${message.createdAt || Date.now()}`,
    role: message.role,
    content: message.content,
    citations: parseCitations(message.citationsJson),
    deepThinking: false,
    reasoning: '',
    reasoningOpen: false,
    reasoningStreaming: false,
    statusText: '',
    createdAt: message.createdAt
  }
}

function estimateReasoningLength(value) {
  const length = String(value || '').trim().length
  if (!length) {
    return ''
  }
  return `${length} 字`
}

function reasoningPlaceholder(message) {
  return message.reasoningStreaming ? '等待模型返回思考过程...' : '当前模型未返回独立思考过程'
}

function parseCitations(value) {
  if (!value) {
    return []
  }
  if (Array.isArray(value)) {
    return value
  }
  try {
    const parsed = JSON.parse(value)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function clearMissingSession(sessionId, options = {}) {
  const shouldReset = options.reset !== false
  const key = conversationKey(sessionId)
  streamControllers.get(key)?.abort()
  streamControllers.delete(key)
  delete streamingConversations[key]
  delete conversationMessages[key]
  if (shouldReset && String(chatForm.sessionId) === String(sessionId)) {
    resetConversation()
  } else if (String(chatForm.sessionId) === String(sessionId)) {
    chatForm.sessionId = ''
  }
  chatHistory.value = chatHistory.value.filter((item) => String(item.sessionId) !== String(sessionId))
}

function startTaskAutoRefresh() {
  stopTaskAutoRefresh()
  if (!session.token || view.value !== 'admin') {
    return
  }
  taskRefreshTimer = window.setInterval(async () => {
    if (!session.token || view.value !== 'admin') {
      stopTaskAutoRefresh()
      return
    }
    try {
      await loadTasks({ notifyFailures: true, silent: true })
    } catch (error) {
      if (isUnauthorized(error)) {
        handleAuthFailure(error)
      }
    }
  }, TASK_REFRESH_INTERVAL_MS)
}

function stopTaskAutoRefresh() {
  if (taskRefreshTimer) {
    window.clearInterval(taskRefreshTimer)
    taskRefreshTimer = null
  }
}

function resizeComposer(event) {
  const target = event?.target || document.querySelector('.composer textarea')
  if (!target) {
    return
  }
  target.style.height = 'auto'
  target.style.height = `${Math.min(target.scrollHeight, 180)}px`
}

function handleAuthFailure(error) {
  if (isUnauthorized(error)) {
    logout()
    return
  }
  ElMessage.error(friendlyError(error))
}

function isUnauthorized(error) {
  return error?.response?.status === 401
}

function isMissingSession(error) {
  const message = friendlyError(error)
  return message.includes('Chat session not found')
}

function friendlyError(error) {
  return (
    error?.response?.data?.message ||
    error?.response?.data?.msg ||
    error?.response?.data?.error ||
    error?.response?.statusText ||
    error?.message ||
    '未知错误'
  )
}

function taskStatusLabel(status) {
  return {
    queued: '排队中',
    running: '处理中',
    success: '已完成',
    failed: '失败'
  }[status] || status
}

function formatChatTime(value) {
  if (!value) {
    return ''
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return String(value).slice(0, 16).replace('T', ' ')
  }
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false
  })
}

function taskTagType(status) {
  return {
    queued: 'info',
    running: 'warning',
    success: 'success',
    failed: 'danger'
  }[status] || 'info'
}
</script>
