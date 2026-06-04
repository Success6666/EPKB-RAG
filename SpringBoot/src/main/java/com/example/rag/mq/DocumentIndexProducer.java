package com.example.rag.mq;

import com.example.rag.config.RagProperties;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.stereotype.Component;

@Component
public class DocumentIndexProducer {

    private final RabbitTemplate rabbitTemplate;
    private final RagProperties properties;

    public DocumentIndexProducer(RabbitTemplate rabbitTemplate, RagProperties properties) {
        this.rabbitTemplate = rabbitTemplate;
        this.properties = properties;
    }

    public void send(DocumentIndexMessage message) {
        rabbitTemplate.convertAndSend(
            properties.getRabbitmq().getDocumentExchange(),
            properties.getRabbitmq().getDocumentRoutingKey(),
            message
        );
    }
}
