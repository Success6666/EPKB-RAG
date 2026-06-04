package com.example.rag;

import com.example.rag.config.RagProperties;
import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;

@MapperScan("com.example.rag.**.mapper")
@SpringBootApplication
@EnableConfigurationProperties(RagProperties.class)
public class RagPlatformApplication {

    public static void main(String[] args) {
        SpringApplication.run(RagPlatformApplication.class, args);
    }
}
