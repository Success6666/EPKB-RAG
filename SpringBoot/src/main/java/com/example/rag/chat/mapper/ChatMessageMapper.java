package com.example.rag.chat.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.example.rag.chat.ChatMessage;
import java.util.List;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface ChatMessageMapper extends BaseMapper<ChatMessage> {

    @Select("""
        <script>
        SELECT COUNT(1)
        FROM rag_chat_message
        WHERE tenant_id = #{tenantId}
          AND user_id = #{userId}
          AND deleted = 0
          <if test="sessionId != null">AND session_id = #{sessionId}</if>
        </script>
        """)
    long countByTenantUserAndSession(
        @Param("tenantId") Long tenantId,
        @Param("userId") Long userId,
        @Param("sessionId") Long sessionId
    );

    @Select("""
        <script>
        SELECT id, tenant_id, session_id, user_id, role, content, citations_json, prompt_tokens, completion_tokens, created_at, deleted
        FROM rag_chat_message
        WHERE tenant_id = #{tenantId}
          AND user_id = #{userId}
          AND deleted = 0
          <if test="sessionId != null">AND session_id = #{sessionId}</if>
        ORDER BY created_at DESC
        LIMIT #{size} OFFSET #{offset}
        </script>
        """)
    List<ChatMessage> pageByTenantUserAndSession(
        @Param("tenantId") Long tenantId,
        @Param("userId") Long userId,
        @Param("sessionId") Long sessionId,
        @Param("size") int size,
        @Param("offset") int offset
    );

    @Select("""
        SELECT id, tenant_id, session_id, user_id, role, content, citations_json, prompt_tokens, completion_tokens, created_at, deleted
        FROM rag_chat_message
        WHERE tenant_id = #{tenantId}
          AND user_id = #{userId}
          AND session_id = #{sessionId}
          AND deleted = 0
        ORDER BY created_at ASC
        """)
    List<ChatMessage> listByTenantUserAndSession(
        @Param("tenantId") Long tenantId,
        @Param("userId") Long userId,
        @Param("sessionId") Long sessionId
    );
}
