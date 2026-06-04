package com.example.rag.ratelimit;

import com.example.rag.common.exception.BizException;
import java.time.Duration;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

@Component
public class RedisRateLimiter {

    private final StringRedisTemplate redisTemplate;

    public RedisRateLimiter(StringRedisTemplate redisTemplate) {
        this.redisTemplate = redisTemplate;
    }

    public void check(String bucket, long limit, Duration window) {
        Long count = redisTemplate.opsForValue().increment(bucket);
        if (count != null && count == 1L) {
            redisTemplate.expire(bucket, window);
        }
        if (count != null && count > limit) {
            throw new BizException(429, "Too many requests, please retry later.");
        }
    }
}
