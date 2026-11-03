# Agente de inventario con IA

Asistente conversacional para una tienda familiar de suministros para cafeterías. Carla, la dueña, le habla en lenguaje natural ("acaban de llegar 30 litros de leche de avena", "vendimos 12 bolsas de arábica hoy", "¿qué productos están por agotarse?") y el sistema consulta y actualiza el stock por ella.

El proyecto tiene dos piezas que funcionan juntas:

1. **API REST** ([api/app.py](api/app.py)), construida con FastAPI. Gestiona el inventario y lo guarda en `products.csv`.
2. **Agente de IA** ([agent.py](agent.py)). Usa un LLM de Groq y los endpoints de la API como herramientas (tools). El bucle está escrito a mano en Python, sin frameworks de agentes. Cada evento se añade a `conversation_log.csv`.

## Requisitos

- Python 3.12 o superior
- [uv](https://docs.astral.sh/uv/)
- Una clave de API de [Groq](https://console.groq.com/keys)

## Instalación

```bash
# 1. Crea el entorno virtual e instala uv dentro (omite este paso si ya tienes uv instalado de forma global)
python -m venv .venv
.venv/Scripts/python -m pip install uv     # macOS/Linux: .venv/bin/python -m pip install uv

# 2. Activa el entorno
.venv\Scripts\Activate.ps1                 # Windows (PowerShell)
source .venv/Scripts/activate              # Windows (Git Bash)
source .venv/bin/activate                  # macOS/Linux

# 3. Instala las dependencias
uv sync
```

Copia `.env.example` a `.env` y pon tu clave:

```
GROQ_API_KEY=tu_clave_aqui
```

Variables opcionales:

- `API_URL`: dirección de la API. Por defecto, `http://127.0.0.1:8000`.
- `GROQ_MODEL`: modelo que usa el agente. Por defecto, `openai/gpt-oss-120b`.

> ⚠️ **No subas nunca tu `.env` al repositorio.** Ya está incluido en `.gitignore`.

## Arrancar el sistema

> 📌 **Importante: la API debe estar en marcha antes de iniciar el agente.** Necesitas dos terminales abiertos a la vez, con el entorno virtual activado en ambos y situados en la raíz del proyecto.

```bash
# Terminal 1: arrancar la API
uvicorn api.app:app --reload

# Terminal 2: arrancar el agente (cuando la API ya esté en marcha)
python agent.py
```

Si el agente no encuentra la API, muestra un aviso y se cierra.

Con la API en marcha, la documentación interactiva está en http://127.0.0.1:8000/docs.

### Detener y relanzar

- **Detener:** pulsa `Ctrl + C` en cada terminal. Detén primero el agente y después la API. También puedes salir del agente escribiendo `salir`.
- **Relanzar el agente:** ejecuta `python agent.py` de nuevo en el Terminal 2. No hace falta reiniciar la API. El agente empieza una sesión nueva y añade filas a `conversation_log.csv` sin borrar las anteriores.

## Ejemplo de conversación

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

| Método | Ruta | Descripción | Códigos |
|---|---|---|---|
| `GET` | `/inventory` | Lista completa de productos | 200 |
| `POST` | `/inventory` | Añade un producto (`name`, `quantity`, `unit`) | 201, 409 (nombre duplicado), 422 (datos no válidos) |
| `PATCH` | `/inventory/{product_id}` | Suma `delta` al stock: positivo para entradas, negativo para salidas | 200, 400 (stock insuficiente), 404 (no existe), 422 (`delta` = 0) |
| `GET` | `/inventory/alerts?threshold=10` | Productos con cantidad por debajo del umbral (por defecto, 10) | 200, 422 |

## Herramientas del agente

| Tool | Endpoint |
|---|---|
| `list_products` | `GET /inventory` |
| `add_product(name, quantity, unit)` | `POST /inventory` |
| `update_stock(product_id, delta)` | `PATCH /inventory/{product_id}` |
| `get_low_stock_alerts(threshold?)` | `GET /inventory/alerts` |

## Ficheros de datos

**`products.csv`**: el inventario. Persiste entre sesiones.

```
id,name,quantity,unit
1,Café arábica en grano,25,bolsas
```

**`conversation_log.csv`**: registro de cada evento del bucle. Solo se le añaden filas, nunca se sobrescribe. Se crea solo la primera vez que se usa el agente.

| Campo | Descripción |
|---|---|
| `actor` | `user`, `agent` o `tool` |
| `message` | Texto del mensaje, o argumentos y resultado de la tool |
| `tool_call` | Nombre de la tool llamada (vacío si no aplica) |
| `timestamp` | Fecha y hora en formato ISO 8601 |

## Estructura

```
api/
  __init__.py
  app.py               # API REST (FastAPI)
agent.py               # Agente de IA y CLI
products.csv           # Inventario
conversation_log.csv   # Registro de conversaciones (se genera solo)
.env.example           # Plantilla de variables de entorno
pyproject.toml / uv.lock
```

### Contribuidores

Esta plantilla fue creada como parte de los [Recursos de Python de 4Geeks](https://4geeks.com/es/technology/python) para el aprendizaje en [4Geeks.com](https://4geeks.com) por [Alejandro Sanchez](https://twitter.com/alesanchezr) y [muchos otros contribuyentes](https://github.com/4GeeksAcademy/python-hello/graphs/contributors).
