import json
from telegram import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
import logging

logger = logging.getLogger(__name__)

def load_keyboard_from_file(path="keyboard.json"):
    try:
        with open(path, encoding="utf-8") as f:
            keyboard_data = json.load(f)

        keyboard = []
        for row in keyboard_data:
            built_row = []
            for item in row:
                if isinstance(item, str):
                    built_row.append(KeyboardButton(text=item))
                elif isinstance(item, dict):
                    text = str(item.get("text", "")).strip()
                    web_app_url = item.get("web_app")
                    if text and web_app_url:
                        built_row.append(KeyboardButton(text=text, web_app=WebAppInfo(url=str(web_app_url))))
                    elif text:
                        built_row.append(KeyboardButton(text=text))
                # інші типи просто ігноруємо
            if built_row:
                keyboard.append(built_row)

        if not keyboard:
            return None

        return ReplyKeyboardMarkup(
            keyboard=keyboard,
            resize_keyboard=True,
            one_time_keyboard=False,
            is_persistent=True,
        )
    except Exception as e:
        logger.warning(f"Не вдалося завантажити меню з {path}: {e}")
        return None
