from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import logging
import mimetypes
import re
import time

import requests

from app.config import Settings

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

    def get_updates(self, offset: int | None) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": self._settings.telegram_poll_timeout_seconds,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            payload["offset"] = offset

        response = requests.post(f"{self._api_base}/getUpdates", json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API getUpdates failed: {data}")
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

    def extract_message_data(self, update: dict[str, Any]) -> dict[str, Any] | None:
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
        timestamp = datetime.fromtimestamp(message.get("date", int(time.time())), tz=timezone.utc)

        return {
            "chat_id": chat_id,
            "user_id": str(sender.get("id", "")),
            "username": sender.get("username") or "",
            "message_id": str(message.get("message_id", "")),
            "message_id_int": int(message.get("message_id", 0)),
            "timestamp_iso": timestamp.isoformat().replace("+00:00", "Z"),
            "timestamp_file": timestamp.strftime("%Y.%m.%d %H.%M.%S"),
            "text": message.get("text") or message.get("caption") or "",
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
