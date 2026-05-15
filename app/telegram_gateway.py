from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import logging
import mimetypes
import re
import time

import requests

import json

from app.config import Settings
from app.keyboard_loader import load_keyboard_from_file

logger = logging.getLogger(__name__)


@dataclass
class DownloadedFile:
    file_id: str
    file_url: str
    mime_type: str


class TelegramGateway:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._token = settings.telegram_bot_token
        self._api_base = f"https://api.telegram.org/bot{self._token}"
        self._file_base = f"https://api.telegram.org/file/bot{self._token}"
        self._message_timezone = timezone(timedelta(hours=self._settings.telegram_timezone_offset_hours))

    def set_bot_commands_from_file(self, commands_path: str = "commands.json") -> None:
        """
        Встановлює команди для Telegram-бота з файлу, якщо файл існує.
        """
        import os
        if not os.path.exists(commands_path):
            logger.info(f"Файл команд {commands_path} не знайдено, команди не встановлюються.")
            return
        try:
            with open(commands_path, encoding="utf-8") as f:
                commands = json.load(f)
            payload = {"commands": commands}
            response = requests.post(f"{self._api_base}/setMyCommands", json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            if not data.get("ok"):
                logger.warning(f"Не вдалося встановити команди: {data}")
            else:
                logger.info("Команди Telegram-бота успішно встановлено.")
        except Exception as exc:
            logger.exception(f"Помилка при встановленні команд Telegram-бота: {exc}")

    def get_updates(self, offset: int | None) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": self._settings.telegram_poll_timeout_seconds,
            "allowed_updates": ["message", "web_app_data", "callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset

        response = requests.post(f"{self._api_base}/getUpdates", json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API getUpdates failed: {data}")
        # print(f"Received updates: {json.dumps(data, ensure_ascii=False)}")
        return data.get("result", [])

    def set_message_reaction_eyes(self, chat_id: str, message_id: int) -> bool:
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "reaction": [{"type": "emoji", "emoji": "👀"}], 
            "is_big": False,
        }
        response = requests.post(f"{self._api_base}/setMessageReaction", json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        return bool(data.get("ok"))

    def extract_update_data(self, update: dict[str, Any]) -> dict[str, Any] | None:
        """
        Екстрагує дані з update.message або update.callback_query.
        Повертає уніфіковану структуру з тип події та метаданими.
        """
        # Спробуємо message
        message = update.get("message")
        if message:
            return self._extract_from_message(message, update.get("update_id", 0))

        # Спробуємо callback_query
        callback_query = update.get("callback_query")
        if callback_query:
            return self._extract_from_callback_query(callback_query, update.get("update_id", 0))

        return None

    def _extract_from_message(self, message: dict[str, Any], update_id: int) -> dict[str, Any] | None:
        """Екстрагує дані з message-подій."""
        chat = message.get("chat", {})
        chat_id = str(chat.get("id", ""))
        if not chat_id:
            return None

        if self._settings.telegram_allowed_chat_id and chat_id != self._settings.telegram_allowed_chat_id:
            return None

        sender = message.get("from", {})
        timestamp = datetime.fromtimestamp(message.get("date", int(time.time())), tz=self._message_timezone)
        command_name, command_params = self._extract_command_from_web_app_data(
            message.get("web_app_data"),
        )
        return {
            "event_type": "message",
            "update_id": update_id,
            "chat_id": chat_id,
            "user_id": str(sender.get("id", "")),
            "username": sender.get("username") or "",
            "message_id": str(message.get("message_id", "")),
            "message_id_int": int(message.get("message_id", 0)),
            "timestamp_iso": timestamp.isoformat(),
            "timestamp_file": timestamp.strftime("%Y-%m-%d_%H-%M-%S"),
            "text": message.get("text") or message.get("caption") or "",
            "command_name": command_name,
            "command_params": command_params,
            "raw_message": message,
            "callback_query_id": None,
            "callback_data": None,
        }

    def _extract_from_callback_query(self, callback_query: dict[str, Any], update_id: int) -> dict[str, Any] | None:
        """Екстрагує дані з callback_query-подій."""
        callback_query_id = callback_query.get("id", "")
        if not callback_query_id:
            return None

        message = callback_query.get("message")
        if not message:
            return None

        chat = message.get("chat", {})
        chat_id = str(chat.get("id", ""))
        if not chat_id:
            return None

        if self._settings.telegram_allowed_chat_id and chat_id != self._settings.telegram_allowed_chat_id:
            return None

        from_user = callback_query.get("from", {})
        message_timestamp = datetime.fromtimestamp(message.get("date", int(time.time())), tz=self._message_timezone)

        return {
            "event_type": "callback_query",
            "update_id": update_id,
            "chat_id": chat_id,
            "user_id": str(from_user.get("id", "")),
            "username": from_user.get("username") or "",
            "message_id": str(message.get("message_id", "")),
            "message_id_int": int(message.get("message_id", 0)),
            "timestamp_iso": message_timestamp.isoformat(),
            "timestamp_file": message_timestamp.strftime("%Y-%m-%d_%H-%M-%S"),
            "text": "",
            "command_name": callback_query.get("data", ""),
            "command_params": {},
            "raw_message": message,
            # "callback_query_id": callback_query_id,
            # "callback_data": callback_query.get("data", ""),
            # "callback_chat_instance": callback_query.get("chat_instance", ""),
            # "callback_inline_message_id": callback_query.get("inline_message_id"),
        }

    # Зберегти старий extract_message_data для сумісності (опціонально)
    def extract_message_data(self, update: dict[str, Any]) -> dict[str, Any] | None:
        """Застарілий метод. Використовуйте extract_update_data."""
        message = update.get("message")
        if not message:
            return None

        chat = message.get("chat", {})
        chat_id = str(chat.get("id", ""))
        if not chat_id:
            return None

        if self._settings.telegram_allowed_chat_id and chat_id != self._settings.telegram_allowed_chat_id:
            return None

        sender = message.get("from", {})
        timestamp = datetime.fromtimestamp(message.get("date", int(time.time())), tz=self._message_timezone)
        command_name, command_params = self._extract_command_from_web_app_data(
            message.get("web_app_data"),
        )
        return {
            "chat_id": chat_id,
            "user_id": str(sender.get("id", "")),
            "username": sender.get("username") or "",
            "message_id": str(message.get("message_id", "")),
            "message_id_int": int(message.get("message_id", 0)),
            "timestamp_iso": timestamp.isoformat(),
            "timestamp_file": timestamp.strftime("%Y-%m-%d_%H-%M-%S"),
            "text": message.get("text") or message.get("caption") or "",
            "command_name": command_name,
            "command_params": command_params,
            "raw_message": message,
        }

    def download_attachments(self, message_meta: dict[str, Any]) -> list[DownloadedFile]:
        raw_message = message_meta["raw_message"]
        files: list[DownloadedFile] = []

        candidates: list[tuple[str, str | None]] = []

        if "photo" in raw_message and raw_message["photo"]:
            largest_photo = raw_message["photo"][-1]
            candidates.append((largest_photo.get("file_id", ""), "image/jpeg"))

        if "document" in raw_message:
            doc = raw_message["document"]
            candidates.append((doc.get("file_id", ""), doc.get("mime_type")))

        if "video" in raw_message:
            video = raw_message["video"]
            candidates.append((video.get("file_id", ""), video.get("mime_type") or "video/mp4"))

        if "audio" in raw_message:
            audio = raw_message["audio"]
            candidates.append((audio.get("file_id", ""), audio.get("mime_type") or "audio/mpeg"))

        if "voice" in raw_message:
            voice = raw_message["voice"]
            candidates.append((voice.get("file_id", ""), voice.get("mime_type") or "audio/ogg"))

        if "animation" in raw_message:
            animation = raw_message["animation"]
            candidates.append((animation.get("file_id", ""), animation.get("mime_type") or "video/mp4"))

        for index, (file_id, mime_type) in enumerate(candidates):
            if not file_id:
                continue
            files.append(self._download_single_file(message_meta, file_id, mime_type, index))

        return files

    def _download_single_file(
        self,
        message_meta: dict[str, Any],
        file_id: str,
        mime_type: str | None,
        index: int,
    ) -> DownloadedFile:
        file_info = self._get_file(file_id)
        remote_path = file_info.get("file_path", "")
        if not remote_path:
            raise RuntimeError(f"Missing file_path for file_id={file_id}")

        resolved_mime_type = mime_type or self._guess_mime_type(remote_path)
        extension = self._pick_extension(resolved_mime_type, remote_path)

        target_dir = (
            self._settings.files_base_dir
            / "telegram"
            / self._settings.telegram_source_id
            / str(message_meta["chat_id"])
        )
        target_dir.mkdir(parents=True, exist_ok=True)

        safe_message_id = re.sub(r"[^0-9]", "", str(message_meta["message_id"])) or str(message_meta["message_id"])
        suffix = f"_{index}" if index > 0 else ""
        file_name = f"{message_meta['timestamp_file']}_{safe_message_id}{suffix}{extension}"
        local_path = target_dir / file_name

        response = requests.get(f"{self._file_base}/{remote_path}", timeout=120)
        response.raise_for_status()
        local_path.write_bytes(response.content)

        return DownloadedFile(
            file_id=file_id,
            file_url=str(local_path),
            mime_type=resolved_mime_type,
        )

    def _get_file(self, file_id: str) -> dict[str, Any]:
        payload = {"file_id": file_id}
        response = requests.post(f"{self._api_base}/getFile", json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API getFile failed for file_id={file_id}")
        return data.get("result", {})

    @staticmethod
    def _guess_mime_type(remote_path: str) -> str:
        guessed, _ = mimetypes.guess_type(remote_path)
        return guessed or "application/octet-stream"

    @staticmethod
    def _pick_extension(mime_type: str, remote_path: str) -> str:
        extension = Path(remote_path).suffix
        if extension:
            return extension
        guessed = mimetypes.guess_extension(mime_type)
        return guessed or ".bin"

    def load_keyboard_markup(self, keyboard_path: str = "keyboard.json"):
        """
        Завантажує меню для ReplyKeyboardMarkup з JSON-файлу, якщо файл існує.
        Повертає ReplyKeyboardMarkup або None.
        """
        import os
        try:
            if not os.path.exists(keyboard_path):
                logger.info(f"Файл меню {keyboard_path} не знайдено, меню не використовується.")
                return None
            markup = load_keyboard_from_file(keyboard_path)
            if markup:
                logger.info(f"Меню Telegram-бота успішно завантажено з {keyboard_path}.")
            return markup
        except Exception as exc:
            logger.exception(f"Помилка при завантаженні меню Telegram-бота: {exc}")
            return None

    @staticmethod
    def _extract_command_from_web_app_data(web_app_data: Any) -> tuple[str | None, dict[str, Any]]:
        if not isinstance(web_app_data, dict):
            return None, {}

        raw_data = web_app_data.get("data")
        if not raw_data:
            return None, {}

        if not isinstance(raw_data, str):
            return None, {}

        try:
            parsed = json.loads(raw_data)
        except (TypeError, ValueError):
            return None, {}

        if not isinstance(parsed, dict):
            return None, {}

        command_name_raw = (
            parsed.get("command_name")
            or parsed.get("name")
            or parsed.get("command")
        )
        command_name = str(command_name_raw).strip() if command_name_raw else None

        params_value = parsed.get("command_params", parsed.get("params", {}))

        if isinstance(params_value, dict):
            command_params = params_value
        elif params_value is None or params_value == "":
            command_params = {}
        elif isinstance(params_value, str):
            try:
                decoded = json.loads(params_value)
                command_params = decoded if isinstance(decoded, dict) else {"value": decoded}
            except (TypeError, ValueError):
                command_params = {"value": params_value}

        return command_name, command_params

    def answer_callback_query(self, callback_query_id: str, text: str | None = None, show_alert: bool = False) -> bool:
        """
        Відповідає на callback_query, щоб клієнт знав що запит оброблено.
        """
        payload: dict[str, Any] = {
            "callback_query_id": callback_query_id,
        }
        if text:
            payload["text"] = text
        if show_alert:
            payload["show_alert"] = True

        try:
            response = requests.post(f"{self._api_base}/answerCallbackQuery", json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            return bool(data.get("ok"))
        except Exception as exc:
            logger.exception(f"Failed to answer callback query {callback_query_id}: {exc}")
            return False