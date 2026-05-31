# Dvoretskii Watch (Wear OS)

Нативное приложение для Galaxy Watch (Wear OS 4) — ведёт счёт настольного
тенниса/сквоша прямо с часов, поверх REST API бота.

## Как это работает

1. В вебаппе бота открой **Теннис → ⌚ Привязать часы** — там покажется
   8-символьный код (живёт 5 минут).
2. На часах открой это приложение → **Ввести код** → впиши код → **Привязать**.
   Часы обменивают код на долгоживущий bearer-токен (`POST /api/watch/pair/claim`)
   и сохраняют его локально (`SharedPreferences`).
3. Дальше часы дёргают теннисные ручки с заголовком `Authorization: Bearer <token>`:
   - `GET /api/tennis/active` — текущая активная сессия (поллинг раз в 2.5 c);
   - `POST /api/tennis/sessions/{id}/point {side}` — тап = очко;
   - `POST /api/tennis/sessions/{id}/undo_point` — отмена очка.
   Эти мутации идут через тот же room_manager, что и вебаппа, поэтому веб-табло
   (WebSocket) обновляется тем же бродкастом.

Часы у Galaxy Watch 5 Pro без камеры, поэтому QR не используется — только
ручной ввод кода.

## Сборка

Открой папку `watch/` в Android Studio (Hedgehog+). Студия сама подтянет
Gradle wrapper и зависимости. Либо из CLI:

```bash
cd watch
gradle wrapper            # один раз, если нет gradle/wrapper/gradle-wrapper.jar
./gradlew :app:assembleDebug
```

### Базовый URL бота

По умолчанию `https://tg.kmxk.ru`. Переопредели, не трогая код, — добавь в
`watch/local.properties`:

```
BOT_BASE_URL=https://your-domain
```

(пробрасывается в `BuildConfig.BOT_BASE_URL`).

## Установка на часы

- Включи на часах режим разработчика и ADB-отладку (по Wi-Fi или через телефон).
- `./gradlew :app:installDebug` либо запусти конфигурацию `app` из Android Studio,
  выбрав часы как target.

## Структура

```
app/src/main/java/com/dvoretskii/watch/
  MainActivity.kt          — хост, переключает Pair ↔ Scoreboard
  data/Prefs.kt            — токен/имя юзера в SharedPreferences
  data/ApiClient.kt        — OkHttp + org.json, все REST-вызовы
  data/Models.kt           — ActiveState, PairResult
  ui/PairScreen.kt         — ввод кода (системный RemoteInput) и привязка
  ui/ScoreboardScreen.kt   — табло: тап = очко, отмена, индикатор подачи
```

При ответе `401` (токен отозвали из вебаппы) приложение чистит токен и
возвращается к экрану привязки.
