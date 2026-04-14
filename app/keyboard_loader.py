import json
from telegram import ReplyKeyboardMarkup, KeyboardButton
import logging

logger = logging.getLogger(__name__)

def load_keyboard_from_file(path="keyboard.json"):
    """
    Завантажує меню для ReplyKeyboardMarkup з JSON-файлу.
    Формат: масив масивів текстів кнопок.
    """
    try:
        with open(path, encoding="utf-8") as f:
            keyboard_data = json.load(f)
        keyboard = [
            [KeyboardButton(text) for text in row]
            for row in keyboard_data
        ]
        return ReplyKeyboardMarkup(
            keyboard=keyboard,
            resize_keyboard=True,
            one_time_keyboard=False,
            is_persistent=True,
        )
    except Exception as e:
        logger.warning(f"Не вдалося завантажити меню з {path}: {e}")
        return None
