.PHONY: install test lint typecheck audit check build docker

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
	build_portable.bat
	build_installer.bat

docker:
	docker compose --env-file .env.docker.example up --build
