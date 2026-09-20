.PHONY: start stop restart update logs

start:
	docker compose up -d --build --wait --wait-timeout 90

stop:
	docker compose down

restart:
	docker compose down
	docker compose up -d --build --wait --wait-timeout 90

update:
	docker compose build --pull --no-cache
	docker compose up -d --force-recreate --wait --wait-timeout 90

logs:
	docker compose logs -f
