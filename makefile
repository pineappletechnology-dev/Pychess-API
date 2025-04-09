APP=main
HOST=127.0.0.1
PORT=8000

# Rodar o servidor
run:
	uvicorn $(APP):app --host $(HOST) --port $(PORT) --reload