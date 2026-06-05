.PHONY: help build up down logs clean test shell

help:
	@echo "Available commands:"
	@echo "  make build    - Build Docker images"
	@echo "  make up       - Start all services"
	@echo "  make down     - Stop all services"
	@echo "  make logs     - View logs"
	@echo "  make clean    - Clean temporary files"
	@echo "  make test     - Run tests"
	@echo "  make shell    - Enter container shell"

build:
	docker-compose build --no-cache

up:
	docker-compose up -d
	@echo "Services started. API available at http://localhost:8000"

down:
	docker-compose down

logs:
	docker-compose logs -f

clean:
	docker-compose down -v
	docker system prune -f
	rm -rf logs/*.log
	rm -rf temp/*

test:
	docker-compose run --rm api pytest tests/ -v

shell:
	docker-compose exec api /bin/bash

restart:
	docker-compose restart api

status:
	docker-compose ps

# Production commands
prod-build:
	docker-compose -f docker-compose.prod.yml build

prod-up:
	docker-compose -f docker-compose.prod.yml up -d

prod-down:
	docker-compose -f docker-compose.prod.yml down