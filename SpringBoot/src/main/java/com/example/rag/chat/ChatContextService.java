package com.example.rag.chat;

import com.example.rag.chat.dto.ChatAskRequest;
import com.example.rag.chat.mapper.ChatMessageMapper;
import com.example.rag.config.RagProperties;
import com.example.rag.langchain.LangChain4jChatService;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

@Service
public class ChatContextService {

    private static final int TOKEN_SAFETY_MARGIN = 2048;

    private final ChatMessageMapper chatMessageMapper;
    private final StringRedisTemplate redisTemplate;
    private final RagProperties ragProperties;
    private final LangChain4jChatService langChain4jChatService;

    public ChatContextService(
        ChatMessageMapper chatMessageMapper,
        StringRedisTemplate redisTemplate,
        RagProperties ragProperties,
        LangChain4jChatService langChain4jChatService
    ) {
        this.chatMessageMapper = chatMessageMapper;
        this.redisTemplate = redisTemplate;
        this.ragProperties = ragProperties;
        this.langChain4jChatService = langChain4jChatService;
    }

    public ContextPackage buildContextPackage(
        ChatAskRequest request,
        Long tenantId,
        Long userId,
        Long sessionId,
        String question,
        int tokenBudget,
        int contextWindowTokens
    ) {
        List<ChatAskRequest.HistoryMessage> allHistory = loadHistory(tenantId, userId, sessionId);
        int allHistoryTokens = estimateMessagesTokens(allHistory);
        boolean compressed = allHistoryTokens >= compressionTriggerTokens(contextWindowTokens);
        int summaryReserve = compressed ? summaryReserveTokens(tokenBudget) : 0;
        int availableForRawHistory = Math.max(0, tokenBudget - summaryReserve - estimateTokens(question) - TOKEN_SAFETY_MARGIN);
        if (compressed) {
            availableForRawHistory = Math.min(
                availableForRawHistory,
                Math.max(1024, compressionTriggerTokens(contextWindowTokens) - summaryReserve)
            );
        }
        List<ChatAskRequest.HistoryMessage> selectedHistory = selectHistoryWithinBudget(allHistory, availableForRawHistory);
        String summary = compressed ? contextSummary(request, tenantId, sessionId, allHistory, selectedHistory, summaryReserve) : null;
        return new ContextPackage(
            selectedHistory,
            summary,
            compressed,
            tokenBudget,
            contextWindowTokens,
            allHistoryTokens,
            estimateMessagesTokens(selectedHistory)
        );
    }

    public int historyTokenBudget(int contextWindowTokens) {
        int retrievalReserve = Math.max(0, ragProperties.getChat().getRetrievalReserveTokens());
        return Math.max(1024, contextWindowTokens - retrievalReserve);
    }

    public Map<String, Object> runtimeContext(Long tenantId, Long userId, Long sessionId, ContextPackage contextPackage) {
        Map<String, Object> context = new LinkedHashMap<>();
        context.put("tenantId", tenantId);
        context.put("userId", userId);
        context.put("sessionId", sessionId);
        context.put("contextWindowTokens", contextPackage.contextWindowTokens());
        context.put("tokenBudget", contextPackage.tokenBudget());
        context.put("contextCompressed", contextPackage.compressed());
        context.put("historyTokens", contextPackage.historyTokens());
        context.put("selectedHistoryTokens", contextPackage.selectedHistoryTokens());
        if (StringUtils.hasText(contextPackage.summary())) {
            context.put("contextSummary", contextPackage.summary());
        }
        return context;
    }

    private List<ChatAskRequest.HistoryMessage> loadHistory(Long tenantId, Long userId, Long sessionId) {
        return chatMessageMapper.listByTenantUserAndSession(tenantId, userId, sessionId).stream()
            .map(message -> new ChatAskRequest.HistoryMessage(message.getRole(), message.getContent()))
            .toList();
    }

    private List<ChatAskRequest.HistoryMessage> selectHistoryWithinBudget(List<ChatAskRequest.HistoryMessage> history, int tokenBudget) {
        if (history.isEmpty() || tokenBudget <= 0) {
            return List.of();
        }
        List<ChatAskRequest.HistoryMessage> selected = new ArrayList<>();
        int used = 0;
        for (int index = history.size() - 1; index >= 0; index--) {
            ChatAskRequest.HistoryMessage message = history.get(index);
            int tokens = estimateTokens(message.role()) + estimateTokens(message.content()) + 8;
            if (!selected.isEmpty() && used + tokens > tokenBudget) {
                break;
            }
            if (selected.isEmpty() && tokens > tokenBudget) {
                selected.add(new ChatAskRequest.HistoryMessage(message.role(), truncateByTokens(message.content(), tokenBudget)));
                break;
            }
            selected.add(0, message);
            used += tokens;
        }
        return selected;
    }

    private String contextSummary(
        ChatAskRequest request,
        Long tenantId,
        Long sessionId,
        List<ChatAskRequest.HistoryMessage> allHistory,
        List<ChatAskRequest.HistoryMessage> selectedHistory,
        int summaryReserve
    ) {
        int omitted = Math.max(0, allHistory.size() - selectedHistory.size());
        if (omitted == 0) {
            return null;
        }
        String cached = redisTemplate.opsForValue().get(summaryKey(tenantId, sessionId, omitted));
        if (StringUtils.hasText(cached)) {
            return truncateByTokens(cached, summaryReserve);
        }
        List<ChatAskRequest.HistoryMessage> omittedHistory = allHistory.subList(0, omitted);
        String modelSummary = langChain4jChatService.compressHistory(request, omittedHistory, summaryReserve).orElse(null);
        if (StringUtils.hasText(modelSummary)) {
            String value = truncateByTokens(modelSummary, summaryReserve);
            redisTemplate.opsForValue().set(summaryKey(tenantId, sessionId, omitted), value, Duration.ofDays(30));
            return value;
        }
        StringBuilder summary = new StringBuilder();
        summary.append("Earlier conversation summary: compressed ")
            .append(omittedHistory.size())
            .append(" historical messages.\n");
        summary.append("Retained facts, user goals, constraints, decisions, and pending tasks in chronological order:\n");
        int used = estimateTokens(summary.toString());
        for (ChatAskRequest.HistoryMessage message : omittedHistory) {
            String line = message.role() + ": " + singleLine(message.content()) + "\n";
            int tokens = estimateTokens(line);
            if (used + tokens > summaryReserve) {
                break;
            }
            summary.append(line);
            used += tokens;
        }
        String value = summary.toString().trim();
        redisTemplate.opsForValue().set(summaryKey(tenantId, sessionId, omitted), value, Duration.ofDays(30));
        return value;
    }

    private int compressionTriggerTokens(int contextWindowTokens) {
        int configured = ragProperties.getChat().getCompressionTriggerTokens();
        if (configured <= 0) {
            return Math.max(1024, (int) (contextWindowTokens * 0.8));
        }
        return Math.min(configured, contextWindowTokens);
    }

    private int summaryReserveTokens(int tokenBudget) {
        int configured = Math.max(1024, ragProperties.getChat().getSummaryReserveTokens());
        return Math.min(configured, Math.max(1024, tokenBudget / 5));
    }

    private int estimateMessagesTokens(List<ChatAskRequest.HistoryMessage> messages) {
        int total = 0;
        for (ChatAskRequest.HistoryMessage message : messages) {
            total += estimateTokens(message.role()) + estimateTokens(message.content()) + 8;
        }
        return total;
    }

    private int estimateTokens(String value) {
        if (!StringUtils.hasText(value)) {
            return 0;
        }
        int tokens = 0;
        int asciiRun = 0;
        for (int index = 0; index < value.length(); index++) {
            char ch = value.charAt(index);
            if (ch <= 0x007f) {
                if (Character.isLetterOrDigit(ch)) {
                    asciiRun++;
                    if (asciiRun == 4) {
                        tokens++;
                        asciiRun = 0;
                    }
                } else {
                    if (asciiRun > 0) {
                        tokens++;
                        asciiRun = 0;
                    }
                    if (!Character.isWhitespace(ch)) {
                        tokens++;
                    }
                }
            } else {
                if (asciiRun > 0) {
                    tokens++;
                    asciiRun = 0;
                }
                tokens++;
            }
        }
        if (asciiRun > 0) {
            tokens++;
        }
        return tokens;
    }

    private String truncateByTokens(String value, int tokenBudget) {
        if (!StringUtils.hasText(value) || tokenBudget <= 0) {
            return "";
        }
        int used = 0;
        StringBuilder result = new StringBuilder();
        for (int index = 0; index < value.length(); index++) {
            char ch = value.charAt(index);
            int tokenCost = ch <= 0x007f ? 1 : 1;
            if (used + tokenCost > tokenBudget) {
                break;
            }
            result.append(ch);
            used += tokenCost;
        }
        return result.toString();
    }

    private String singleLine(String value) {
        if (value == null) {
            return "";
        }
        return value.replaceAll("\\s+", " ").trim();
    }

    private String summaryKey(Long tenantId, Long sessionId, int omittedMessages) {
        return "chat:summary:" + tenantId + ":" + sessionId + ":" + omittedMessages;
    }

    public record ContextPackage(
        List<ChatAskRequest.HistoryMessage> history,
        String summary,
        boolean compressed,
        int tokenBudget,
        int contextWindowTokens,
        int historyTokens,
        int selectedHistoryTokens
    ) {
    }
}
