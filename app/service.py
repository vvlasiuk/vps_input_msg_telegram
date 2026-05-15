from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import logging
import time

from app.config import Settings
from app.rabbitmq_client import RabbitPublisher
from app.telegram_gateway import TelegramGateway

logger = logging.getLogger(__name__)


class TelegramToRabbitService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._telegram = TelegramGateway(settings)
        self._publisher = RabbitPublisher(settings)
        self._offset_file = settings.telegram_offset_file
        self._offset_file.parent.mkdir(parents=True, exist_ok=True)

    def run_forever(self) -> None:
        logger.info("Service started")
        self._publisher.connect()
        offset = self._read_offset()

        while True:
            try:
                updates = self._telegram.get_updates(offset)
                for update in updates:
                    update_id = int(update.get("update_id", 0))
                    if update_id <= 0:
                        continue

                    processed = self._handle_update(update)
                    if not processed:
                        logger.warning(
                            "Update was not processed successfully, keeping offset unchanged for retry",
                            extra={"update_id": update_id},
                        )
                        break

                    offset = update_id + 1
                    self._write_offset(offset)

                if not updates:
                    time.sleep(self._settings.telegram_poll_interval_seconds)
            except KeyboardInterrupt:
                logger.info("Service stopped by user")
                break
            except Exception:
                logger.exception("Processing cycle failed")
                time.sleep(2)

        self._publisher.close()

    def _handle_update(self, update: dict[str, Any]) -> bool:
        event_data = self._telegram.extract_update_data(update)
        if not event_data:
            return True

        event_type = event_data.get("event_type", "")

        # Завантажуємо вкладення лише для message-подій
        files = []
        if event_type == "message":
            try:
                files = self._telegram.download_attachments(event_data)
            except Exception:
                logger.exception("Failed to download Telegram attachment")
                files = []

        payload = self._build_payload(event_data, files)

        try:
            self._publisher.publish(payload)
            logger.info(f"Published {event_type} to RabbitMQ", extra={"event_type": event_type})
        except Exception:
            logger.exception(f"Failed to publish {event_type} to RabbitMQ")
            return False

        # Обробка post-publish дій в залежності від типу события
        if event_type == "callback_query":
            # Для callback_query підтверджуємо callback
            callback_id = event_data.get("callback_query_id", "")
            if callback_id:
                answered = self._telegram.answer_callback_query(callback_id)
                if not answered:
                    logger.error(f"Failed to answer callback query {callback_id}")
        elif event_type == "message":
            # Для message ставимо реакцію 👀
            try:
                reacted = self._telegram.set_message_reaction_eyes(
                    chat_id=event_data["chat_id"],
                    message_id=event_data["message_id_int"],
                )
                if not reacted:
                    logger.error("Telegram returned not-ok for setMessageReaction")
            except Exception:
                logger.exception("Failed to set reaction")

        return True

    def _build_payload(self, event_data: dict[str, Any], files: list[Any]) -> dict[str, Any]:
        event_type = event_data.get("event_type", "message")
        command_name = event_data.get("command_name", "")
        command_params = event_data.get("command_params", {})

        payload: dict[str, Any] = {
            "source": {
                "system": "telegram",
                "source_id": self._settings.telegram_source_id,
                "chat_id": event_data["chat_id"],
                "user_id": event_data["user_id"],
                "username": event_data["username"],
                "message_id": event_data["message_id"],
                "timestamp": event_data["timestamp_iso"],
            },
            "command_name": command_name,
            "command_params": command_params,
            "content": {
                "text": event_data["text"],
                "language": self._settings.default_language,
                "files": [
                    {
                        "file_id": item.file_id,
                        "file_url": item.file_url,
                        "mime_type": item.mime_type,
                    }
                    for item in files
                ],
            },
        }

        # Додаємо callback-метадані для callback_query
        if event_type == "callback_query":
            payload["content"]["callback"] = {
                "id": event_data.get("callback_query_id", ""),
                "data": event_data.get("callback_data", ""),
                "chat_instance": event_data.get("callback_chat_instance", ""),
                "inline_message_id": event_data.get("callback_inline_message_id"),
            }

        return payload

    def _read_offset(self) -> int | None:
        if not self._offset_file.exists():
            return None

        raw = self._offset_file.read_text(encoding="utf-8").strip()
        if not raw:
            return None

        try:
            return int(raw)
        except ValueError:
            logger.error("Invalid offset file content, resetting")
            return None

    def _write_offset(self, offset: int) -> None:
        self._offset_file.write_text(str(offset), encoding="utf-8")

    def dump_payload_for_debug(self, payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False)
