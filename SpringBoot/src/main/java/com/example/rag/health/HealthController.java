package com.example.rag.health;

import java.util.Map;
import com.example.rag.tenant.TenantContext;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/health")
public class HealthController {

    private final JdbcTemplate jdbcTemplate;
    private final StringRedisTemplate redisTemplate;
    private final RabbitTemplate rabbitTemplate;

    public HealthController(JdbcTemplate jdbcTemplate, StringRedisTemplate redisTemplate, RabbitTemplate rabbitTemplate) {
        this.jdbcTemplate = jdbcTemplate;
        this.redisTemplate = redisTemplate;
        this.rabbitTemplate = rabbitTemplate;
    }

    @GetMapping
    public Map<String, Object> health() {
        Long tenantId = TenantContext.tenantIdOrNull();
        return Map.of(
            "status", "ok",
            "tenantId", tenantId == null ? "" : tenantId,
            "components", Map.of(
                "mysql", mysqlHealth(),
                "redis", redisHealth(),
                "rabbitmq", rabbitHealth(),
                "vectorStore", "external",
                "ollama", "external"
            )
        );
    }

    private String mysqlHealth() {
        try {
            jdbcTemplate.queryForObject("select 1", Integer.class);
            return "ok";
        } catch (Exception ex) {
            return "down";
        }
    }

    private String redisHealth() {
        try {
            return "PONG".equals(redisTemplate.getConnectionFactory().getConnection().ping()) ? "ok" : "down";
        } catch (Exception ex) {
            return "down";
        }
    }

    private String rabbitHealth() {
        try {
            rabbitTemplate.execute(channel -> channel.isOpen());
            return "ok";
        } catch (Exception ex) {
            return "down";
        }
    }
}
