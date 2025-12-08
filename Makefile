.PHONY: dev dev-metrics prod down logs logs-dev

dev:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml watch

dev-metrics:
	METRICS_ENABLED=true docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile metrics watch

prod:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile metrics up -d --build

down:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.dev.yml --profile metrics down

logs:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile metrics logs -f

logs-dev:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile metrics logs -f

