from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import argparse
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_source_id: str
    telegram_allowed_chat_id: Optional[str]
    telegram_poll_timeout_seconds: int
    telegram_poll_interval_seconds: float
    telegram_offset_file: Path
    telegram_timezone_offset_hours: float

    rabbitmq_host: str
    rabbitmq_port: int
    rabbitmq_user: str
    rabbitmq_password: str
    rabbitmq_vhost: str
    rabbitmq_exchange: str
    rabbitmq_exchange_type: str
    rabbitmq_queue: str
    rabbitmq_routing_key: str
    rabbitmq_heartbeat_seconds: int
    rabbitmq_blocked_connection_timeout_seconds: int

    files_base_dir: Path
    default_language: str

    log_level: str
    log_file_path: Path
    log_max_bytes: int
    log_backup_count: int


def _to_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: str, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Telegram to RabbitMQ transport microservice")
    parser.add_argument(
        "--env-file",
        dest="env_file",
        default=None,
        help="Path to .env file. If omitted, .env in project root is used.",
    )
    return parser.parse_args()


def load_settings(args: argparse.Namespace) -> Settings:
    project_root = Path(__file__).resolve().parents[1]
    env_file_path = Path(args.env_file) if args.env_file else project_root / ".env"

    if env_file_path.exists():
        load_dotenv(env_file_path)

    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")

    telegram_source_id = os.getenv("TELEGRAM_SOURCE_ID", "my_telegram_bot").strip() or "my_telegram_bot"
    telegram_allowed_chat_id = os.getenv("TELEGRAM_ALLOWED_CHAT_ID", "").strip() or None

    files_base_dir = Path(os.getenv("FILES_BASE_DIR", str(project_root / "storage"))).expanduser().resolve()
    offset_file = Path(os.getenv("TELEGRAM_OFFSET_FILE", str(project_root / "var" / "offset.txt"))).expanduser().resolve()
    telegram_timezone_offset_hours = _to_float(os.getenv("TELEGRAM_TIMEZONE_OFFSET_HOURS", "2"), 2.0)

    log_dir = Path(os.getenv("LOG_DIR", str(project_root / "logs"))).expanduser().resolve()
    log_file_name = os.getenv("LOG_FILE_NAME", "service.log").strip() or "service.log"
    log_file_path_env = os.getenv("LOG_FILE_PATH", "").strip()
    if log_file_path_env:
        log_file_path = Path(log_file_path_env).expanduser().resolve()
    else:
        log_file_path = (log_dir / log_file_name).resolve()

    return Settings(
        telegram_bot_token=telegram_bot_token,
        telegram_source_id=telegram_source_id,
        telegram_allowed_chat_id=telegram_allowed_chat_id,
        telegram_poll_timeout_seconds=_to_int(os.getenv("TELEGRAM_POLL_TIMEOUT_SECONDS", "30"), 30),
        telegram_poll_interval_seconds=_to_float(os.getenv("TELEGRAM_POLL_INTERVAL_SECONDS", "1.0"), 1.0),
        telegram_offset_file=offset_file,
        telegram_timezone_offset_hours=telegram_timezone_offset_hours,
        rabbitmq_host=os.getenv("RABBITMQ_HOST", "localhost"),
        rabbitmq_port=_to_int(os.getenv("RABBITMQ_PORT", "5672"), 5672),
        rabbitmq_user=os.getenv("RABBITMQ_USER", "guest"),
        rabbitmq_password=os.getenv("RABBITMQ_PASSWORD", "guest"),
        rabbitmq_vhost=os.getenv("RABBITMQ_VHOST", "input_message"),
        rabbitmq_exchange=os.getenv("RABBITMQ_EXCHANGE", "input_messages_exchange"),
        rabbitmq_exchange_type=os.getenv("RABBITMQ_EXCHANGE_TYPE", "direct"),
        rabbitmq_queue=os.getenv("RABBITMQ_QUEUE", "input.messages.queue"),
        rabbitmq_routing_key=os.getenv("RABBITMQ_ROUTING_KEY", "input.messages"),
        rabbitmq_heartbeat_seconds=_to_int(os.getenv("RABBITMQ_HEARTBEAT_SECONDS", "60"), 60),
        rabbitmq_blocked_connection_timeout_seconds=_to_int(
            os.getenv("RABBITMQ_BLOCKED_CONNECTION_TIMEOUT_SECONDS", "300"), 300
        ),
        files_base_dir=files_base_dir,
        default_language=os.getenv("DEFAULT_LANGUAGE", "uk"),
        log_level=os.getenv("LOG_LEVEL", "ERROR").upper(),
        log_file_path=log_file_path,
        log_max_bytes=_to_int(os.getenv("LOG_MAX_BYTES", str(10 * 1024 * 1024)), 10 * 1024 * 1024),
        log_backup_count=_to_int(os.getenv("LOG_BACKUP_COUNT", "3"), 3),
    )
