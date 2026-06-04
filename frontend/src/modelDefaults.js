export const modelDefaults = {
  Ollama: {
    modelName: 'qwen2.5:7b',
    baseUrl: 'http://host.docker.internal:11434',
    embeddingProvider: 'sentence_transformers',
    embeddingModel: 'BAAI/bge-small-zh-v1.5',
    embeddingBaseUrl: '',
    embeddingInputType: '',
    embeddingTruncate: 'NONE',
    rerankModel: 'none',
    temperature: 0.2,
    topP: 0.8,
    maxTokens: 2048,
    contextWindowTokens: 262144
  },
  DeepSeek: {
    modelName: 'deepseek-v4-pro',
    baseUrl: 'https://api.deepseek.com',
    embeddingProvider: 'sentence_transformers',
    embeddingModel: 'BAAI/bge-small-zh-v1.5',
    embeddingBaseUrl: '',
    embeddingInputType: '',
    embeddingTruncate: 'NONE',
    rerankModel: 'deepseek-v4-flash',
    temperature: 0.3,
    topP: 0.9,
    maxTokens: 8192,
    contextWindowTokens: 262144
  },
  DashScope: {
    modelName: 'qwen-plus',
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    embeddingProvider: 'sentence_transformers',
    embeddingModel: 'BAAI/bge-small-zh-v1.5',
    embeddingBaseUrl: '',
    embeddingInputType: '',
    embeddingTruncate: 'NONE',
    rerankModel: 'none',
    temperature: 0.3,
    topP: 0.9,
    maxTokens: 8192,
    contextWindowTokens: 262144
  },
  'OpenAI-Compatible': {
    modelName: 'gpt-4o-mini',
    baseUrl: 'https://api.openai.com/v1',
    embeddingProvider: 'sentence_transformers',
    embeddingModel: 'BAAI/bge-small-zh-v1.5',
    embeddingBaseUrl: '',
    embeddingInputType: '',
    embeddingTruncate: 'NONE',
    rerankModel: 'none',
    temperature: 0.2,
    topP: 0.8,
    maxTokens: 4096,
    contextWindowTokens: 262144
  },
  NVIDIA: {
    modelName: 'meta/llama-3.1-8b-instruct',
    baseUrl: 'https://integrate.api.nvidia.com/v1',
    embeddingProvider: 'NVIDIA',
    embeddingModel: 'nvidia/nv-embedqa-e5-v5',
    embeddingBaseUrl: 'https://integrate.api.nvidia.com/v1',
    embeddingInputType: 'passage',
    embeddingTruncate: 'NONE',
    rerankModel: 'none',
    temperature: 0.2,
    topP: 0.8,
    maxTokens: 4096,
    contextWindowTokens: 262144
  }
}

export const embeddingDefaults = {
  Ollama: {
    embeddingModel: 'bge-m3',
    embeddingBaseUrl: 'http://host.docker.internal:11434',
    embeddingInputType: '',
    embeddingTruncate: 'NONE'
  },
  NVIDIA: {
    embeddingModel: 'nvidia/nv-embedqa-e5-v5',
    embeddingBaseUrl: 'https://integrate.api.nvidia.com/v1',
    embeddingInputType: 'passage',
    embeddingTruncate: 'NONE'
  },
  sentence_transformers: {
    embeddingModel: 'BAAI/bge-small-zh-v1.5',
    embeddingBaseUrl: '',
    embeddingInputType: '',
    embeddingTruncate: 'NONE'
  }
}
