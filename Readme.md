## Что надо сделать:

### Механизм для отправки запросов на добавление изменений

-   команда для добавления запросов на изменение
-   возможность добавлять описание, менять заголовок
-   возможность сохранять чат и сообщение и отвечать на него
-   уведомление о добавлении изменения

### Возможность добавлять задачи которые будут запускаться по времени

-   отправка стикера каждый день
-   отправка копии базы каждый день
-   возможность добавления крон задач

### Поменять ведение правил

Сделать так что бы ты вводишь паттерн, настройки и потом запускается сессия по добавлению ответов на паттерн. Ответы могут быть разных типов. Пересылка сообщений, и просто текст. После надо каждому расписать вероятность. Добавить так же возможность отвечать на сообщения с контекстом, получать в сообщении от кого сообщение, автор сообщения. Возможность реагировать на пересылку сообщений бота. Отправка стикеров. Добавить теги для просмотра правил

### топ языков

Показывает топ языков, свифт должен быть на последнем месте

## Добавление нового правила

П: /add_rule
Б: От кого? (можно несколько id через пробел)
П: 0
Б: Паттерн сообщения
П: .\*да.\*
Б: Ответы на сообщение (пишите отдельными сообщениями, можно пересылать, можно отправлять стикеры, картинки, видео и аудио) [Ответы закончились]
П: да
П: нет
П: [Ответы закончились]
Б: Напишите вероятности ответов ({сколько})(через пробел)
П: 0 0
Б: Теги(через пробел)
П: да нет
Б: Игнорировать регистр(1 - да, 0 - нет)
П: 1
Б: Правило с id {id} успешно добавлено [Удалить правило]

## sidecars

- [Telegram API](https://github.com/tdlib/telegram-bot-api)
- [cloudflare bypasser](https://github.com/KmXK/cloudflare-bypass)
  just clone repo and run docker ([docker here](https://docs.docker.com/engine/install/ubuntu/))
