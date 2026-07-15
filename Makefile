SERVICE ?=

.PHONY: up down logs ps sh

up:
	docker compose up -d --build $(SERVICE)

down:
	docker compose down $(SERVICE)

logs:
	docker compose logs -f $(SERVICE)

ps:
	docker compose ps

sh:
	docker compose exec $(if $(SERVICE),$(SERVICE),backend) sh
