.PHONY: setup dev api stt mobile test build doctor reset

setup:
	npm run setup

dev:
	npm run dev

api:
	npm run api

stt:
	npm run stt

mobile:
	npm run mobile

test:
	npm test

build:
	npm run build:web

doctor:
	npm run doctor

reset:
	curl -X POST http://localhost:8001/v1/demo/reset
