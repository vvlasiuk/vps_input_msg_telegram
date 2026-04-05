from __future__ import annotations

import json
import logging
from typing import Any

import pika
from pika import exceptions as pika_exceptions
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
        # Enable publisher confirms so basic_publish reflects broker acknowledgement.
        self._channel.confirm_delivery()

    def ensure_connection(self) -> None:
        if self._connection is None or self._channel is None:
            self.connect()
            return

        if self._connection.is_closed or self._channel.is_closed:
            self.connect()
            return

        if self._connection.is_open and self._channel.is_open:
            return

        try:
            try:
                if self._connection and self._connection.is_open:
                    self._connection.close()
            except Exception:
                logger.exception("Failed to close stale RabbitMQ connection")
            finally:
                self._connection = None
                self._channel = None
        finally:
            self.connect()

    def publish(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        _connection_errors = (
            pika_exceptions.AMQPConnectionError,
            pika_exceptions.AMQPChannelError,
            OSError,
        )

        for attempt in range(2):
            try:
                self.ensure_connection()
                if self._channel is None:
                    raise RuntimeError("RabbitMQ channel is unavailable")

                confirmed = self._channel.basic_publish(
                    exchange=self._settings.rabbitmq_exchange,
                    routing_key=self._settings.rabbitmq_routing_key,
                    body=body,
                    properties=pika.BasicProperties(
                        content_type="application/json",
                        delivery_mode=2,
                    ),
                    mandatory=True,
                )
                if confirmed is False:
                    raise RuntimeError("RabbitMQ broker nacked the published message")
                return
            except _connection_errors as exc:
                if attempt == 0:
                    logger.warning(
                        "RabbitMQ connection error on publish (%s), reconnecting and retrying once", exc
                    )
                    self._connection = None
                    self._channel = None
                else:
                    raise

    def close(self) -> None:
        try:
            if self._connection and self._connection.is_open:
                self._connection.close()
        except Exception:
            logger.exception("Failed to close RabbitMQ connection")
