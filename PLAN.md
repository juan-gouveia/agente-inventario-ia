# Plan: Agente de inventario con IA (FastAPI + bucle de agente manual)

## Contexto
Carla (tienda de suministros para cafeterías, 2 locales) necesita saber y actualizar su stock hablando en lenguaje natural ("acaban de llegar 30 unidades de leche de avena", "vendimos 12 bolsas de arábica", "¿qué está por agotarse?"). El repo actual es el boilerplate "Python Hello" de 4Geeks (`main.py`, `server.py`, `README.md`, `README.es.md`, `learn.json`), sin `pyproject.toml`. Hay que construir:
1. Una API REST FastAPI con persistencia en `products.csv`.
2. Un agente CLI (`agent.py`) que usa un LLM de Groq (SDK `openai`) con los endpoints como tools, bucle implementado a mano (sin LangChain/LlamaIndex/AutoGen), y registro append-only en `conversation_log.csv`.

No se tocan `main.py`, `server.py` ni `learn.json` (son parte de la plantilla).

---

## Fase 0 — Entorno y estructura ✅ (completada)
> `uv` no estaba instalado globalmente: se creó `.venv` con `python -m venv`, se instaló `uv` dentro (`.venv/Scripts/uv`) y se fijó como dependencia de desarrollo (`uv add --dev uv`) para que los `uv sync` no lo eliminen. `uv init --bare` (solo `pyproject.toml`, sin tocar `main.py`/README).

- `uv init` (si no existe `pyproject.toml`) y `uv add fastapi uvicorn openai python-dotenv httpx`
  - `httpx` para que el agente llame a la API (ya viene como dependencia de `openai`, pero se declara explícitamente).
- Crear `.gitignore` con: `.env`, `.venv/`, `__pycache__/`, `*.pyc`.
- Crear `.env.example` con `GROQ_API_KEY=tu_clave_aqui` (y opcionales `API_URL=http://127.0.0.1:8000`, `GROQ_MODEL=openai/gpt-oss-120b`).
- Estructura final:
  ```
  api/__init__.py
  api/app.py
  agent.py
  products.csv          # catálogo semilla
  conversation_log.csv  # se crea automáticamente
  .env / .env.example / .gitignore
  README.md / README.es.md
  ```

## Fase 1 — API (`api/app.py`) ✅ (completada)
> Verificada con `TestClient` sobre una copia temporal del CSV: 200/201/400/404/409/422 según lo esperado. `delta = 0` se rechaza con 422.

**Datos (`products.csv`)**: columnas `id,name,quantity,unit`. Semilla de ~8 productos de cafetería (café arábica en grano – bolsas, leche de avena – litros, leche entera – litros, vasos 12oz – unidades, tapas – unidades, azúcar – kg, sirope de vainilla – botellas, filtros – unidades), algunos por debajo de 10 para probar alertas.

**Helpers internos**:
- `read_products() -> list[dict]` (crea el CSV con cabecera si no existe; castea `id` a int y `quantity` a float).
- `write_products(products)` — reescribe el CSV completo (escritura a fichero temporal + `os.replace` para no corromperlo).
- Ruta del CSV resuelta respecto a la raíz del proyecto (`Path(__file__).resolve().parent.parent / "products.csv"`), para que funcione con `uvicorn api.app:app` desde la raíz.

**Modelos Pydantic**:
- `ProductCreate { name: str (min_length=1), quantity: float (>=0), unit: str (min_length=1) }`
- `StockUpdate { delta: float }` (distinto de 0)
- `Product { id: int, name, quantity, unit }`

**Endpoints**:
| Método | Ruta | Comportamiento | Errores |
|---|---|---|---|
| GET | `/inventory` | Lista completa | — |
| POST | `/inventory` | Crea producto, id = max+1 → **201** | **409** si ya existe un nombre igual (case-insensitive); **422** validación |
| PATCH | `/inventory/{product_id}` | `quantity += delta`, devuelve producto actualizado | **404** si no existe; **400** si el resultado sería negativo (mensaje: "Stock insuficiente: hay X unidad, se intentó restar Y") |
| GET | `/inventory/alerts?threshold=10` | Productos con `quantity < threshold` (por defecto 10, `ge=0`) | — |

- Declarar `/inventory/alerts` **antes** de `/inventory/{product_id}` no es estrictamente necesario (métodos distintos), pero mantener orden claro.
- Todos los errores vía `HTTPException(status_code, detail="mensaje descriptivo")`.

## Fase 2 — Agente (`agent.py`) ✅ (completada)
> Modelo por defecto cambiado a `openai/gpt-oss-120b` (`llama-3.3-70b-versatile` ya no está disponible en la cuenta de Groq). Probado de punta a punta contra Groq con la API en proceso (`TestClient`) y CSV temporales. Si falla el LLM a mitad de turno, el historial se revierte a su estado anterior. Respuestas en texto plano (sin Markdown).
**Configuración**: `load_dotenv()`; cliente `OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")`; modelo desde `GROQ_MODEL` (por defecto `openai/gpt-oss-120b`); `API_URL` por defecto `http://127.0.0.1:8000`. Si falta la clave → mensaje claro y salida.

**Comprobación inicial**: `GET /inventory` al arrancar; si falla, imprimir "La API no está en marcha, ejecuta `uvicorn api.app:app --reload`" y salir.

**Tools (formato function-calling de OpenAI)**, cada una con `name`, `description` y `parameters` JSON Schema tipado:
- `list_products()` → GET `/inventory`
- `add_product(name: string, quantity: number, unit: string)` → POST `/inventory`
- `update_stock(product_id: integer, delta: number)` → PATCH `/inventory/{id}` (descripción: positivo = entrada/entrega, negativo = venta/salida)
- `get_low_stock_alerts(threshold?: number)` → GET `/inventory/alerts`

Despacho mediante diccionario `TOOL_HANDLERS = {name: función}`. Cada handler devuelve un string JSON con el cuerpo de la respuesta; ante error HTTP devuelve `{"error": status, "detail": ...}` para que el LLM lo explique (sin lanzar excepción).

**System prompt** (español): asistente de inventario de la tienda de Carla; para actualizar stock por nombre debe llamar primero a `list_products` para obtener el `product_id`; ventas → delta negativo, entregas → positivo; si el producto no existe, preguntar antes de crearlo; respuestas breves y directas.

**Bucle** (`run_turn(messages, user_input)`):
1. **Observar**: añadir `{"role":"user"}` al historial → log `user`.
2. **Pensar**: `client.chat.completions.create(model, messages, tools, tool_choice="auto")`.
3. Si la respuesta trae `tool_calls`: añadir el mensaje del assistant (con sus tool_calls) al historial; para cada call → log `agent` (tool_call=nombre, message=argumentos) → **Actuar**: ejecutar handler → log `tool` (message=resultado, tool_call=nombre) → **Actualizar**: añadir `{"role":"tool","tool_call_id", "content"}` → **Repetir** paso 2.
4. Si no hay `tool_calls`: respuesta final → añadir al historial, log `agent` (tool_call vacío), devolver texto. Fin limpio.
5. Tope de seguridad `MAX_STEPS = 10` iteraciones por turno.
- Manejo de `json.JSONDecodeError` en argumentos y de errores de la API del LLM (mensaje al usuario, el bucle CLI continúa).

**Historial**: lista `messages` en memoria iniciada con el system prompt, vive toda la sesión.

**CLI** (`main()`): banner, `input("Tú: ")`, salir con `salir`/`exit` o Ctrl+C/EOF (capturar `KeyboardInterrupt`/`EOFError`), imprimir `Agente: ...`.

## Fase 3 — Registro (`conversation_log.csv`) ✅ (implementada junto con la Fase 2)
> `log_event` ya está en `agent.py` y verificado en la prueba e2e. Falta la comprobación con sesiones reales (relanzar y ver que se añaden filas), incluida en la Fase 5.
- Función `log_event(actor, message, tool_call="")` en `agent.py`:
  - Abre en modo `"a"` con `newline=""` y `encoding="utf-8"`; si el fichero no existe o está vacío, escribe cabecera `actor,message,tool_call,timestamp`.
  - `timestamp = datetime.now().astimezone().isoformat(timespec="seconds")` (ISO 8601 con zona).
  - Usa `csv.writer` (escapa comas/saltos de línea de los mensajes); se cierra tras cada fila → nada se pierde con Ctrl+C.
- Eventos registrados: mensaje del usuario, llamada a tool (actor `agent`), resultado de tool (actor `tool`), respuesta final (actor `agent`).

## Fase 4 — README (`README.md` y `README.es.md`)
Reemplazar el contenido de la plantilla en ambos (inglés y español, mismo contenido):
- Descripción del proyecto y de las dos piezas.
- Requisitos: Python 3.11+, `uv`, clave de Groq.
- Instalación: `uv sync` (o `uv add ...`), copiar `.env.example` → `.env`.
- **Nota destacada: la API debe estar en marcha antes del agente.** Sección "Arrancar el sistema" con dos terminales:
  ```bash
  # Terminal 1 — API
  uv run uvicorn api.app:app --reload
  # Terminal 2 — Agente
  uv run python agent.py
  ```
- Detener (Ctrl+C: primero agente, luego API) y relanzar el agente sin reiniciar la API.
- Tabla de endpoints y ejemplo de conversación ("acaban de llegar 30 litros de leche de avena", "vendimos 12 bolsas de arábica", "¿qué está por agotarse?").
- Formato de `products.csv` y `conversation_log.csv`.
- Aviso: nunca subir `.env`.
- Conservar la sección de contribuidores de 4Geeks al final.

## Fase 5 — Verificación
1. `uv run uvicorn api.app:app --reload` y probar en `http://127.0.0.1:8000/docs`:
   - GET `/inventory` → 200 con la semilla.
   - POST duplicado → 409; POST válido → 201 y aparece en `products.csv`.
   - PATCH id inexistente → 404; delta que deja stock negativo → 400; delta válido → 200.
   - GET `/inventory/alerts` y `?threshold=50`.
2. `uv run python agent.py` (con API arriba) y probar:
   - "Acaban de llegar 30 litros de leche de avena" → list_products + update_stock(+30).
   - "Vendimos 12 bolsas de arábica hoy" → update_stock(-12).
   - "¿Qué productos están por agotarse?" → get_low_stock_alerts.
   - Pregunta de seguimiento ("¿y cuánto queda ahora de avena?") para comprobar el historial.
3. Revisar `conversation_log.csv`: 4 columnas, timestamps ISO, actores correctos; relanzar el agente y comprobar que se añaden filas sin borrar las anteriores.
4. Arrancar el agente con la API apagada → mensaje claro, sin traceback.
5. `git status` confirma que `.env` no aparece.
