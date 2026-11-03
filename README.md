# AI Inventory Agent

A conversational assistant for a family-run coffee-shop supply store. Carla, the owner, talks to it in plain language ("acaban de llegar 30 litros de leche de avena", "vendimos 12 bolsas de arábica hoy", "¿qué productos están por agotarse?") and the system checks and updates the stock for her. The agent speaks Spanish.

The project has two parts that work together:

1. **REST API** ([api/app.py](api/app.py)), built with FastAPI. It manages the inventory and stores it in `products.csv`.
2. **AI agent** ([agent.py](agent.py)). It uses a Groq LLM with the API endpoints as tools. The loop is hand-written in plain Python, with no agent frameworks. Every event is appended to `conversation_log.csv`.

## Requirements

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)
- A [Groq](https://console.groq.com/keys) API key

## Installation

```bash
# 1. Create the virtual environment and install uv inside it (skip this step if uv is installed globally)
python -m venv .venv
.venv/Scripts/python -m pip install uv     # macOS/Linux: .venv/bin/python -m pip install uv

# 2. Activate the environment
.venv\Scripts\Activate.ps1                 # Windows (PowerShell)
source .venv/Scripts/activate              # Windows (Git Bash)
source .venv/bin/activate                  # macOS/Linux

# 3. Install the dependencies
uv sync
```

Copy `.env.example` to `.env` and add your key:

```
GROQ_API_KEY=your_key_here
```

Optional variables:

- `API_URL`: address of the API. Defaults to `http://127.0.0.1:8000`.
- `GROQ_MODEL`: model the agent uses. Defaults to `openai/gpt-oss-120b`.

> ⚠️ **Never commit your `.env` file.** It is already listed in `.gitignore`.

## Running the system

> 📌 **Important: the API must be running before you start the agent.** You need two terminals open at the same time, both with the virtual environment activated and both in the project root.

```bash
# Terminal 1: start the API
uvicorn api.app:app --reload

# Terminal 2: start the agent (once the API is running)
python agent.py
```

If the agent cannot reach the API, it shows a warning and exits.

While the API is running, the interactive docs are at http://127.0.0.1:8000/docs.

### Stopping and restarting

- **Stop:** press `Ctrl + C` in each terminal. Stop the agent first, then the API. You can also leave the agent by typing `salir`.
- **Restart the agent:** run `python agent.py` again in Terminal 2. You don't need to restart the API. The agent starts a new session and appends rows to `conversation_log.csv` without deleting the earlier ones.

## Example conversation

```
Tú: Acaban de llegar 30 litros de leche de avena
Agente: Listo. La leche de avena tiene ahora 38 litros en stock.

Tú: Vendimos 12 bolsas de arábica hoy
Agente: Venta registrada: quedan 13 bolsas de café arábica en grano.

Tú: ¿Qué productos están por agotarse?
Agente: Estos productos están por debajo de 10:
- Tapas para vasos 12oz: 6 unidades
- Sirope de vainilla: 4 botellas
```

## API

| Method | Path | Description | Status codes |
|---|---|---|---|
| `GET` | `/inventory` | Full product list | 200 |
| `POST` | `/inventory` | Adds a product (`name`, `quantity`, `unit`) | 201, 409 (duplicate name), 422 (invalid data) |
| `PATCH` | `/inventory/{product_id}` | Adds `delta` to the stock: positive for incoming stock, negative for outgoing | 200, 400 (not enough stock), 404 (not found), 422 (`delta` = 0) |
| `GET` | `/inventory/alerts?threshold=10` | Products with quantity below the threshold (default 10) | 200, 422 |

## Agent tools

| Tool | Endpoint |
|---|---|
| `list_products` | `GET /inventory` |
| `add_product(name, quantity, unit)` | `POST /inventory` |
| `update_stock(product_id, delta)` | `PATCH /inventory/{product_id}` |
| `get_low_stock_alerts(threshold?)` | `GET /inventory/alerts` |

## Data files

**`products.csv`**: the inventory. It persists between sessions.

```
id,name,quantity,unit
1,Café arábica en grano,25,bolsas
```

**`conversation_log.csv`**: a record of every event in the loop. Rows are only ever appended, never overwritten. It is created the first time the agent runs.

| Field | Description |
|---|---|
| `actor` | `user`, `agent` or `tool` |
| `message` | Message text, or the tool's arguments and result |
| `tool_call` | Name of the tool called (empty when not applicable) |
| `timestamp` | Date and time in ISO 8601 format |

## Structure

```
api/
  __init__.py
  app.py               # REST API (FastAPI)
agent.py               # AI agent and CLI
products.csv           # Inventory
conversation_log.csv   # Conversation log (created automatically)
.env.example           # Environment variable template
pyproject.toml / uv.lock
```

### Contributors

This template was built as part of the [4Geeks Python Resources](https://4geeks.com/technology/python) for learning at [4Geeks.com](https://4geeks.com) by [Alejandro Sanchez](https://twitter.com/alesanchezr) and [many other contributors](https://github.com/4GeeksAcademy/python-hello/graphs/contributors).
