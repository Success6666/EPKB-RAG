package com.example.rag.model;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.example.rag.common.exception.BizException;
import com.example.rag.model.dto.ActivateModelResponse;
import com.example.rag.model.dto.ModelListResponse;
import com.example.rag.model.dto.UpsertModelRequest;
import com.example.rag.model.mapper.ModelConfigMapper;
import com.example.rag.tenant.TenantContext;
import java.math.BigDecimal;
import java.util.List;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

@Service
public class ModelService {

    private final ModelConfigMapper modelConfigMapper;

    public ModelService(ModelConfigMapper modelConfigMapper) {
        this.modelConfigMapper = modelConfigMapper;
    }

    public ModelListResponse list() {
        Long tenantId = TenantContext.tenantId();
        List<ModelConfig> configs = modelConfigMapper.selectList(new LambdaQueryWrapper<ModelConfig>()
            .eq(ModelConfig::getTenantId, tenantId)
            .eq(ModelConfig::getDeleted, 0)
            .orderByDesc(ModelConfig::getEnabled)
            .orderByAsc(ModelConfig::getProvider));
        List<ModelListResponse.ModelItem> items = configs.stream()
            .map(config -> new ModelListResponse.ModelItem(
                config.getModelName(),
                config.getProvider(),
                Integer.valueOf(1).equals(config.getEnabled()),
                config.getBaseUrl(),
                StringUtils.hasText(config.getApiKey()),
                config.getTemperature(),
                config.getTopP(),
                config.getMaxTokens(),
                config.getContextWindowTokens(),
                firstText(config.getEmbeddingProvider(), defaultEmbeddingProvider(config.getProvider())),
                firstText(config.getEmbeddingModel(), defaultEmbeddingModel(config.getEmbeddingProvider())),
                config.getEmbeddingBaseUrl(),
                StringUtils.hasText(config.getEmbeddingApiKey()),
                firstText(config.getEmbeddingInputType(), defaultEmbeddingInputType(config.getEmbeddingProvider())),
                firstText(config.getEmbeddingTruncate(), "NONE"),
                config.getRerankModel()
            ))
            .toList();
        return new ModelListResponse(items);
    }

    @Transactional
    public ModelListResponse.ModelItem upsert(UpsertModelRequest request) {
        Long tenantId = TenantContext.tenantId();
        String modelName = request.modelName().trim();
        String originalModelName = trimToNull(request.originalModelName());
        String lookupModelName = originalModelName == null ? modelName : originalModelName;
        ModelConfig config = modelConfigMapper.selectOne(new LambdaQueryWrapper<ModelConfig>()
            .eq(ModelConfig::getTenantId, tenantId)
            .eq(ModelConfig::getModelName, lookupModelName)
            .eq(ModelConfig::getDeleted, 0)
            .last("limit 1"));
        if (config == null && originalModelName != null) {
            throw new BizException(404, "Model config not found: " + originalModelName);
        }
        if (config != null && !lookupModelName.equals(modelName)) {
            ModelConfig duplicate = modelConfigMapper.selectOne(new LambdaQueryWrapper<ModelConfig>()
                .eq(ModelConfig::getTenantId, tenantId)
                .eq(ModelConfig::getModelName, modelName)
                .eq(ModelConfig::getDeleted, 0)
                .last("limit 1"));
            if (duplicate != null && !duplicate.getId().equals(config.getId())) {
                throw new BizException(409, "Model config already exists: " + modelName);
            }
        }
        if (config == null) {
            config = new ModelConfig();
            config.setTenantId(tenantId);
            config.setDeleted(0);
            config.setEnabled(0);
        }

        config.setProvider(request.provider().trim());
        config.setModelName(modelName);
        config.setBaseUrl(trimToNull(request.baseUrl()));
        if (StringUtils.hasText(request.apiKey())) {
            config.setApiKey(request.apiKey().trim());
        }
        config.setEmbeddingProvider(firstText(request.embeddingProvider(), defaultEmbeddingProvider(request.provider())));
        config.setEmbeddingModel(firstText(request.embeddingModel(), defaultEmbeddingModel(config.getEmbeddingProvider())));
        config.setEmbeddingBaseUrl(trimToNull(request.embeddingBaseUrl()));
        if (StringUtils.hasText(request.embeddingApiKey())) {
            config.setEmbeddingApiKey(request.embeddingApiKey().trim());
        }
        config.setEmbeddingInputType(firstText(request.embeddingInputType(), defaultEmbeddingInputType(config.getEmbeddingProvider())));
        config.setEmbeddingTruncate(firstText(request.embeddingTruncate(), "NONE").toUpperCase());
        config.setRerankModel(firstText(request.rerankModel(), "none"));
        config.setTemperature(firstDecimal(request.temperature(), BigDecimal.valueOf(0.2)));
        config.setTopP(firstDecimal(request.topP(), BigDecimal.valueOf(0.8)));
        config.setMaxTokens(request.maxTokens() == null ? 4096 : request.maxTokens());
        config.setContextWindowTokens(request.contextWindowTokens() == null ? 262144 : request.contextWindowTokens());

        if (Boolean.TRUE.equals(request.enabled())) {
            disableTenantModels(tenantId);
            config.setEnabled(1);
        } else {
            config.setEnabled(0);
        }

        if (config.getId() == null) {
            modelConfigMapper.insert(config);
        } else {
            modelConfigMapper.updateById(config);
        }
        return toItem(config);
    }

    @Transactional
    public ActivateModelResponse activate(String modelId) {
        Long tenantId = TenantContext.tenantId();
        List<ModelConfig> configs = modelConfigMapper.selectList(new LambdaQueryWrapper<ModelConfig>()
            .eq(ModelConfig::getTenantId, tenantId)
            .eq(ModelConfig::getDeleted, 0));
        boolean found = configs.stream().anyMatch(config -> modelId.equals(config.getModelName()));
        if (!found) {
            throw new BizException(404, "Model config not found: " + modelId);
        }
        for (ModelConfig config : configs) {
            config.setEnabled(modelId.equals(config.getModelName()) ? 1 : 0);
            modelConfigMapper.updateById(config);
        }
        return new ActivateModelResponse(modelId);
    }

    @Transactional
    public void delete(String modelId) {
        Long tenantId = TenantContext.tenantId();
        ModelConfig config = modelConfigMapper.selectOne(new LambdaQueryWrapper<ModelConfig>()
            .eq(ModelConfig::getTenantId, tenantId)
            .eq(ModelConfig::getModelName, modelId)
            .eq(ModelConfig::getDeleted, 0)
            .last("limit 1"));
        if (config == null) {
            throw new BizException(404, "Model config not found: " + modelId);
        }
        modelConfigMapper.update(null, new LambdaUpdateWrapper<ModelConfig>()
            .eq(ModelConfig::getTenantId, tenantId)
            .eq(ModelConfig::getModelName, modelId)
            .eq(ModelConfig::getDeleted, 0)
            .set(ModelConfig::getEnabled, 0)
            .set(ModelConfig::getDeleted, 1));
    }

    private void disableTenantModels(Long tenantId) {
        List<ModelConfig> configs = modelConfigMapper.selectList(new LambdaQueryWrapper<ModelConfig>()
            .eq(ModelConfig::getTenantId, tenantId)
            .eq(ModelConfig::getDeleted, 0));
        for (ModelConfig existing : configs) {
            existing.setEnabled(0);
            modelConfigMapper.updateById(existing);
        }
    }

    private ModelListResponse.ModelItem toItem(ModelConfig config) {
        return new ModelListResponse.ModelItem(
            config.getModelName(),
            config.getProvider(),
            Integer.valueOf(1).equals(config.getEnabled()),
            config.getBaseUrl(),
            StringUtils.hasText(config.getApiKey()),
            config.getTemperature(),
            config.getTopP(),
            config.getMaxTokens(),
            config.getContextWindowTokens(),
            firstText(config.getEmbeddingProvider(), defaultEmbeddingProvider(config.getProvider())),
            firstText(config.getEmbeddingModel(), defaultEmbeddingModel(config.getEmbeddingProvider())),
            config.getEmbeddingBaseUrl(),
            StringUtils.hasText(config.getEmbeddingApiKey()),
            firstText(config.getEmbeddingInputType(), defaultEmbeddingInputType(config.getEmbeddingProvider())),
            firstText(config.getEmbeddingTruncate(), "NONE"),
            config.getRerankModel()
        );
    }

    private String trimToNull(String value) {
        return StringUtils.hasText(value) ? value.trim() : null;
    }

    private String firstText(String value, String fallback) {
        return StringUtils.hasText(value) ? value.trim() : fallback;
    }

    private BigDecimal firstDecimal(BigDecimal value, BigDecimal fallback) {
        return value == null ? fallback : value;
    }

    private String defaultEmbeddingProvider(String provider) {
        return "NVIDIA";
    }

    private String defaultEmbeddingModel(String embeddingProvider) {
        String normalized = embeddingProvider == null ? "" : embeddingProvider.trim().toLowerCase();
        if ("nvidia".equals(normalized)) {
            return "nvidia/nv-embedqa-e5-v5";
        }
        if ("ollama".equals(normalized) || "local".equals(normalized)) {
            return "bge-m3";
        }
        return "nvidia/nv-embedqa-e5-v5";
    }

    private String defaultEmbeddingInputType(String embeddingProvider) {
        String normalized = embeddingProvider == null ? "" : embeddingProvider.trim().toLowerCase();
        return "nvidia".equals(normalized) || !StringUtils.hasText(embeddingProvider) ? "passage" : null;
    }
}
