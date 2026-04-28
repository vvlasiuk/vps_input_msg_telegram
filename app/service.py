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
        message_meta = self._telegram.extract_message_data(update)
        if not message_meta:
            return True

        files = []
        try:
            files = self._telegram.download_attachments(message_meta)
        except Exception:
            logger.exception("Failed to download Telegram attachment")
            files = []

        payload = self._build_payload(message_meta, files)

        try:
            self._publisher.publish(payload)
        except Exception:
            logger.exception("Failed to publish message to RabbitMQ")
            return False

        try:
            reacted = self._telegram.set_message_reaction_eyes(
                chat_id=message_meta["chat_id"],
                message_id=message_meta["message_id_int"],
            )
            if not reacted:
                logger.error("Telegram returned not-ok for setMessageReaction")
        except Exception:
            logger.exception("Failed to set reaction")

        return True

    def _build_payload(self, message_meta: dict[str, Any], files: list[Any]) -> dict[str, Any]:
        web_app_data = message_meta.get("web_app_data")
        command = None
        if web_app_data:
            if isinstance(web_app_data, dict):
                command = web_app_data

        return {
            "source": {
                "system": "telegram",
                "source_id": self._settings.telegram_source_id,
                "chat_id": message_meta["chat_id"],
                "user_id": message_meta["user_id"],
                "username": message_meta["username"],
                "message_id": message_meta["message_id"],
                "timestamp": message_meta["timestamp_iso"],
            },
            "command": command,
            "content": {
                "text": message_meta["text"],
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
