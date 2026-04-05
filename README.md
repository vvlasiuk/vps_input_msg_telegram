# Мікросервіс Telegram -> RabbitMQ

Цей сервіс отримує повідомлення з Telegram, зберігає вкладені файли на диск, формує стандартизований JSON, публікує його в RabbitMQ, а потім ставить реакцію `👀` на повідомлення в Telegram.

## Основна поведінка

- Вхід: оновлення Telegram Bot API (`getUpdates`) з групи/чату.
- Транспортний вихід: публікація в RabbitMQ exchange.
- Топологія RabbitMQ НЕ створюється сервісом. Вона має існувати заздалегідь:
  - exchange: `input_messages_exchange` (налаштовується)
  - routing key: `input.messages` (налаштовується)
  - queue та binding налаштовуються на стороні RabbitMQ.
- Файли зберігаються в:
  - `FILES_BASE_DIR/system/source_id/chat_id`
  - приклад фактичного шляху реалізації:
    - `storage/telegram/my_telegram_bot/-1001234567890/20260327 084000_111222333.jpg`
- Формат імені файлу:
  - `YYYY.MM.DD HH.MM.SS_message_id[optional_index].ext`
- Реакція `👀` ставиться лише після успішної публікації в RabbitMQ.
- Якщо завантаження файлу або публікація не вдалися, реакція не ставиться.
- Текстові повідомлення без файлів також публікуються.

## Формат JSON

```json
{
  "source": {
    "system": "telegram",
    "source_id": "my_telegram_bot",
    "chat_id": "123456789",
    "user_id": "987654321",
    "username": "volodymyr",
    "message_id": "111222333",
    "timestamp": "2026-03-27T08:40:00Z"
  },
  "content": {
    "text": "optional text",
    "language": "uk",
    "files": [
      {
        "file_id": "abc123xyz",
        "file_url": "<local disk path>",
        "mime_type": "image/jpeg"
      }
    ]
  }
}
```

## Налаштування

1. Встановіть залежності:
   - `pip install -r requirements.txt`
2. Створіть env-файл (за потреби поза проєктом) на основі `.env.example`.
3. Переконайтесь, що RabbitMQ доступний, exchange існує, і налаштований binding для потрібного routing key.
  Сервіс лише публікує повідомлення в exchange.
4. Запустіть сервіс:
   - env-файл за замовчуванням з кореня проєкту:
     - `python main.py`
   - власний шлях до env-файлу:
     - `python main.py --env-file D:\configs\telegram_input.env`

## Логування

- Файлове логування використовує циклічну ротацію (`RotatingFileHandler`).
- Максимальний розмір лог-файлу за замовчуванням: 10 МБ.
- `LOG_LEVEL=ERROR` — лише технічні помилки.
- `LOG_LEVEL=DEBUG` — детальне логування.
- Налаштувати місце логів можна або через:
  - `LOG_FILE_PATH` (повний шлях, найвищий пріоритет), або
  - `LOG_DIR` + `LOG_FILE_NAME`.
- Для кількох екземплярів сервісу використовуйте різні лог-файли.

## Примітки

- Бот повинен мати дозвіл на читання повідомлень у цільовій групі.
- Бот повинен мати дозвіл на встановлення реакцій у групі.
- Використовується long polling, webhook не потрібен.
