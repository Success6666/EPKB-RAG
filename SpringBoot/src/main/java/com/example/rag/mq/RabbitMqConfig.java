package com.example.rag.mq;

import com.example.rag.config.RagProperties;
import org.springframework.amqp.core.Binding;
import org.springframework.amqp.core.BindingBuilder;
import org.springframework.amqp.core.DirectExchange;
import org.springframework.amqp.core.Queue;
import org.springframework.amqp.core.QueueBuilder;
import org.springframework.amqp.support.converter.Jackson2JsonMessageConverter;
import org.springframework.amqp.support.converter.MessageConverter;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class RabbitMqConfig {

    @Bean
    public DirectExchange documentExchange(RagProperties properties) {
        return new DirectExchange(properties.getRabbitmq().getDocumentExchange(), true, false);
    }

    @Bean
    public DirectExchange documentDeadLetterExchange(RagProperties properties) {
        return new DirectExchange(properties.getRabbitmq().getDocumentDeadLetterExchange(), true, false);
    }

    @Bean
    public Queue documentIndexQueue(RagProperties properties) {
        return QueueBuilder.durable(properties.getRabbitmq().getDocumentIndexQueue())
                .deadLetterExchange(properties.getRabbitmq().getDocumentDeadLetterExchange())
                .deadLetterRoutingKey(properties.getRabbitmq().getDocumentDeadLetterRoutingKey())
                .build();
    }

    @Bean
    public Binding documentIndexBinding(
            @Qualifier("documentIndexQueue") Queue documentIndexQueue,
            @Qualifier("documentExchange") DirectExchange documentExchange,
            RagProperties properties
    ) {
        return BindingBuilder.bind(documentIndexQueue).to(documentExchange).with(properties.getRabbitmq().getDocumentRoutingKey());
    }

    @Bean
    public Queue documentDeadLetterQueue(RagProperties properties) {
        return QueueBuilder.durable(properties.getRabbitmq().getDocumentDeadLetterQueue()).build();
    }

    @Bean
    public Binding documentDeadLetterBinding(
            @Qualifier("documentDeadLetterQueue") Queue documentDeadLetterQueue,
            @Qualifier("documentDeadLetterExchange") DirectExchange documentDeadLetterExchange,
            RagProperties properties
    ) {
        return BindingBuilder.bind(documentDeadLetterQueue)
                .to(documentDeadLetterExchange)
                .with(properties.getRabbitmq().getDocumentDeadLetterRoutingKey());
    }

    @Bean
    public MessageConverter jsonMessageConverter() {
        return new Jackson2JsonMessageConverter();
    }
}
