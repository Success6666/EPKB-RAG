package com.example.rag.model;

import com.example.rag.model.dto.ActivateModelResponse;
import com.example.rag.model.dto.ModelListResponse;
import com.example.rag.model.dto.UpsertModelRequest;
import cn.dev33.satoken.annotation.SaCheckPermission;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/models")
public class ModelController {

    private final ModelService modelService;

    public ModelController(ModelService modelService) {
        this.modelService = modelService;
    }

    @GetMapping
    @SaCheckPermission("model:switch")
    public ModelListResponse list() {
        return modelService.list();
    }

    @PostMapping
    @SaCheckPermission("model:switch")
    public ModelListResponse.ModelItem upsert(@Valid @RequestBody UpsertModelRequest request) {
        return modelService.upsert(request);
    }

    @PutMapping("/{modelId}/activate")
    @SaCheckPermission("model:switch")
    public ActivateModelResponse activate(@PathVariable String modelId) {
        return modelService.activate(modelId);
    }

    @DeleteMapping("/{modelId}")
    @SaCheckPermission("model:switch")
    public void delete(@PathVariable String modelId) {
        modelService.delete(modelId);
    }
}
