SERVICE ?=

.PHONY: up down logs ps sh

up:
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "→ .env creado desde .env.example (valores locales por defecto, edítalo si quieres otros)"; \
	fi
	docker compose up -d --build $(SERVICE)

down:
	docker compose down $(SERVICE)

logs:
	docker compose logs -f $(SERVICE)

ps:
	docker compose ps

sh:
	docker compose exec $(if $(SERVICE),$(SERVICE),backend) sh
