from __future__ import annotations

import json
import logging
from typing import Any

import pika
from pika.adapters.blocking_connection import BlockingChannel

from app.config import Settings

logger = logging.getLogger(__name__)


class RabbitPublisher:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._connection: pika.BlockingConnection | None = None
        self._channel: BlockingChannel | None = None

    def connect(self) -> None:
        credentials = pika.PlainCredentials(self._settings.rabbitmq_user, self._settings.rabbitmq_password)
        parameters = pika.ConnectionParameters(
            host=self._settings.rabbitmq_host,
            port=self._settings.rabbitmq_port,
            virtual_host=self._settings.rabbitmq_vhost,
            credentials=credentials,
            heartbeat=self._settings.rabbitmq_heartbeat_seconds,
            blocked_connection_timeout=self._settings.rabbitmq_blocked_connection_timeout_seconds,
        )

        self._connection = pika.BlockingConnection(parameters)
        self._channel = self._connection.channel()
        self._channel.exchange_declare(
            exchange=self._settings.rabbitmq_exchange,
            exchange_type=self._settings.rabbitmq_exchange_type,
            durable=True,
        )
        self._channel.queue_declare(queue=self._settings.rabbitmq_queue, durable=True)
        self._channel.queue_bind(
            queue=self._settings.rabbitmq_queue,
            exchange=self._settings.rabbitmq_exchange,
            routing_key=self._settings.rabbitmq_routing_key,
        )

    def ensure_connection(self) -> None:
        if self._connection is None or self._channel is None:
            self.connect()
            return

        if self._connection.is_closed or self._channel.is_closed:
            self.connect()

    def publish(self, payload: dict[str, Any]) -> None:
        self.ensure_connection()
        if self._channel is None:
            raise RuntimeError("RabbitMQ channel is unavailable")

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._channel.basic_publish(
            exchange=self._settings.rabbitmq_exchange,
            routing_key=self._settings.rabbitmq_routing_key,
            body=body,
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=2,
            ),
            mandatory=False,
        )

    def close(self) -> None:
        try:
            if self._connection and self._connection.is_open:
                self._connection.close()
        except Exception:
            logger.exception("Failed to close RabbitMQ connection")
