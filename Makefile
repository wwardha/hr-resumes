DC ?= docker compose

.PHONY: build build-nc rebuild down up logs

# Build images and start containers in the background
build:
	$(DC) build
	$(DC) up -d

# Build images with no cache and start containers
build-nc:
	$(DC) build --no-cache
	$(DC) up -d

# Stop containers, rebuild with no cache, then start
rebuild:
	$(DC) down
	$(DC) build --no-cache
	$(DC) up -d

# Stop and remove containers, networks, images, and volumes
down:
	$(DC) down

# Start containers in the background
up:
	$(DC) up -d

# Follow logs from all services
logs:
	$(DC) logs -f --tail=100
