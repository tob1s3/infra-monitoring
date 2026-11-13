"""Готовит секреты и конфиг Alertmanager для локального запуска из .env.

    python scripts/render_config.py

На сервере то же самое делает Ansible-роль monitoring по тому же шаблону.
"""

import os
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parent.parent


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("'\"")
    return {**values, **os.environ}


def main() -> None:
    env = read_env(ROOT / ".env")
    token, chat_id = env.get("TELEGRAM_BOT_TOKEN", ""), env.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id.lstrip("-").isdigit():
        sys.exit("Заполните TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID (число) в .env")

    # Автоэкранирование HTML здесь не нужно: это YAML, а chat_id выше проверен как число
    jinja = Environment(  # noqa: S701  # nosec B701
        loader=FileSystemLoader(ROOT / "alertmanager"),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    config = jinja.get_template("alertmanager.yml.j2").render(telegram_chat_id=chat_id)
    (ROOT / "alertmanager" / "alertmanager.yml").write_text(config, encoding="utf-8")

    secrets = ROOT / "secrets"
    secrets.mkdir(exist_ok=True)
    token_file = secrets / "telegram_bot_token"
    token_file.write_text(token, encoding="utf-8")
    token_file.chmod(0o644)  # контейнер Alertmanager читает файл от своего пользователя

    print("Готово: alertmanager/alertmanager.yml и secrets/telegram_bot_token")


if __name__ == "__main__":
    main()
