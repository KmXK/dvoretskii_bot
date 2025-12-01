.PHONY: dev prod down logs logs-dev url

# Dev режим - web + bore туннель
dev:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build

# Прод режим - всё включено (bot, caddy, fluentbit)
prod:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# Остановить все контейнеры
down:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.dev.yml down

# Логи
logs:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f

logs-dev:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml logs -f

