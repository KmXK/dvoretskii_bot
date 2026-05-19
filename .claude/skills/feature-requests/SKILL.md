---
name: feature-requests
description: View and manage bot feature requests via the production API at http://tg.kmxk.ru. Use when the user asks to list, filter, update status, change priority, or add notes to feature requests.
metadata:
  type: project
---

# Feature Requests Admin Skill

Use `scripts/api_admin.py` to interact with the production feature request system.

## Prerequisites

Before running any command, read `.env` and check that these variables are present and non-empty:

| Variable | How to get |
|----------|-----------|
| `PROD_API_URL` | URL прод-сервера, например `https://tg.kmxk.ru` |
| `PROD_BOT_TOKEN` | Токен продакшн бота из @BotFather |
| `ADMIN_USER_ID` | Твой Telegram user ID — узнать через @userinfobot |

If any are missing, **do not run the script**. Instead tell the user exactly which variables to add, for example:

> Добавь в `.env`:
> ```
> PROD_BOT_TOKEN=<токен из @BotFather>
> ADMIN_USER_ID=<твой Telegram ID из @userinfobot>
> ```

## Commands

```bash
# List all feature requests (sorted by priority)
python scripts/api_admin.py list

# Filter by status
python scripts/api_admin.py list --status open
python scripts/api_admin.py list --status in_progress

# Update status
python scripts/api_admin.py update <id> --status done

# Update priority (1 = highest)
python scripts/api_admin.py update <id> --priority 2

# Add a note
python scripts/api_admin.py update <id> --note "текст заметки"

# Combine options
python scripts/api_admin.py update <id> --status in_progress --priority 1 --note "берём в работу"
```

## Statuses

| Key | Emoji | Meaning |
|-----|-------|---------|
| `open` | 🔵 | Новая заявка |
| `in_progress` | 🟡 | В работе |
| `testing` | 🟠 | На тестировании |
| `done` | ✅ | Выполнено |
| `denied` | ❌ | Отклонено |

## Output format

```
# id  status  priority  votes  text
#  5 🟡 p=2 👍3  Добавить тёмную тему
```

## Workflow

1. Run the Bash tool to execute the script from the project root.
2. Parse the output to answer the user's question.
3. For updates, confirm the action with the user before running if it's destructive (e.g. denying a popular feature).
