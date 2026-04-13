from __future__ import annotations

import logging
import sys

from app.config import load_settings, parse_args
from app.logger import configure_logging
from app.service import TelegramToRabbitService


def main() -> int:
    args = parse_args()

    try:
        settings = load_settings(args)
    except Exception as exc:
        print(f"Configuration error: {exc}")
        return 1

    configure_logging(settings)
    logger = logging.getLogger(__name__)

    logger.info("Configuration loaded successfully")

    # Встановлення команд Telegram-бота при старті, якщо файл існує
    from app.telegram_gateway import TelegramGateway
    TelegramGateway(settings).set_bot_commands_from_file()

    service = TelegramToRabbitService(settings)
    service.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
