package com.example.rag.document;

import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.example.rag.config.RagProperties;
import com.example.rag.document.dto.KnowledgeBaseListResponse;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class DocumentControllerTest {

    private final DocumentService documentService = org.mockito.Mockito.mock(DocumentService.class);
    private final MockMvc mockMvc = MockMvcBuilders
        .standaloneSetup(new DocumentController(documentService, new RagProperties()))
        .build();

    @Test
    void knowledgeBasesReturnsServiceItems() throws Exception {
        when(documentService.listKnowledgeBases()).thenReturn(new KnowledgeBaseListResponse(List.of(
            new KnowledgeBaseListResponse.Item("1", "制度与流程", "企业制度"),
            new KnowledgeBaseListResponse.Item("2", "合同档案", "")
        )));

        mockMvc.perform(get("/api/documents/knowledge-bases"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.items[0].id").value("1"))
            .andExpect(jsonPath("$.items[0].name").value("制度与流程"))
            .andExpect(jsonPath("$.items[0].description").value("企业制度"))
            .andExpect(jsonPath("$.items[1].id").value("2"))
            .andExpect(jsonPath("$.items[1].name").value("合同档案"));

        verify(documentService).listKnowledgeBases();
    }
}
