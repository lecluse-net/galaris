start:
	docker compose up -d --build --wait --wait-timeout 120
.PHONY: start

stop:
	docker compose down
.PHONY: stop

restart:
	docker compose down
	docker compose up -d --build --wait --wait-timeout 120
.PHONY: restart

update:
	docker compose build --pull
	docker compose up -d --force-recreate --wait --wait-timeout 120
.PHONY: update
