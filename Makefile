.PHONY: install test lint typecheck audit security check build portable installer docker

install:
	python -m pip install -r requirements-local.txt

test:
	python -m pytest

lint:
	python -m ruff check shorts_generator web launcher.py main.py tests

typecheck:
	python -m mypy

audit:
	python -m pip_audit -r requirements-dev.txt --progress-spinner off

check: lint typecheck test

build:
	python scripts/build.py all

portable:
	python scripts/build.py portable

installer:
	python scripts/build.py installer

security:
	python -m bandit -r shorts_generator web launcher.py main.py -ll -x tests

docker:
	docker compose --env-file .env.docker.example up --build
