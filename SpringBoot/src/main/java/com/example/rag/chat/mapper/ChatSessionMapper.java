package com.example.rag.chat.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.example.rag.chat.ChatSession;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface ChatSessionMapper extends BaseMapper<ChatSession> {
}
