"""Agente de IA para el inventario de la tienda de Carla.

Bucle implementado a mano (sin frameworks de agentes):
    Observar -> Pensar -> Actuar -> Actualizar -> Repetir

Requiere la API en marcha (uvicorn api.app:app --reload) y GROQ_API_KEY en .env.
Cada evento se añade a conversation_log.csv (solo adición).
"""

import csv
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv
from openai import OpenAI, OpenAIError

load_dotenv()

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
LOG_FILE = Path(__file__).resolve().parent / "conversation_log.csv"
LOG_FIELDS = ["actor", "message", "tool_call", "timestamp"]
MAX_STEPS = 10  # tope de iteraciones Pensar/Actuar por cada mensaje del usuario

http = httpx.Client(base_url=API_URL, timeout=10)

SYSTEM_PROMPT = """Eres el asistente de inventario de una tienda familiar de suministros \
para cafeterías con dos locales. Hablas con Carla, la dueña, en español, de forma breve, \
clara y cercana.

Estilo:
- Escribe en español de España y tutea a Carla: "tú tienes", "¿quieres...?", "puedes", \
"dime", "avísame".
- Puedes usar algún emoji con moderación: como mucho uno por respuesta y solo si aporta.

Reglas:
- Usa SIEMPRE las herramientas para consultar o cambiar el stock; nunca inventes cantidades.
- Para actualizar un producto por su nombre, llama primero a list_products para obtener su \
product_id. Identifica el producto aunque Carla use un nombre abreviado ("arábica", "avena").
- Entregas, llegadas o compras -> delta positivo. Ventas, consumos, mermas o roturas -> \
delta negativo.
- Si el producto no existe, pregunta a Carla si quiere darlo de alta (y en qué unidad) \
antes de llamar a add_product.
- Si un mensaje es ambiguo (varios productos posibles, cantidad poco clara), pregunta antes \
de modificar nada.
- Si una herramienta devuelve un error, explícaselo a Carla en lenguaje sencillo.
- El stock nunca puede quedar negativo: si una salida supera lo disponible, no ofrezcas \
registrarla igualmente; propón ajustar la cantidad o registrar antes una entrega.
- Tras modificar el stock, confirma la cantidad resultante con su unidad. Si queda por \
debajo de 10, avísalo."""

# ---------------------------------------------------------------------------
# Definición de tools (formato function calling)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_products",
            "description": (
                "Devuelve todos los productos del inventario con su id, nombre, cantidad "
                "y unidad. Úsala para consultar el stock o para encontrar el product_id "
                "de un producto a partir de su nombre."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_product",
            "description": "Da de alta un producto nuevo en el inventario.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nombre del producto"},
                    "quantity": {
                        "type": "number",
                        "description": "Cantidad inicial en stock (0 o más)",
                    },
                    "unit": {
                        "type": "string",
                        "description": "Unidad de medida: unidades, kg, litros, bolsas, botellas...",
                    },
                },
                "required": ["name", "quantity", "unit"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_stock",
            "description": (
                "Suma o resta stock a un producto existente. delta positivo para entradas "
                "(entregas, llegadas); delta negativo para salidas (ventas, consumos)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "integer",
                        "description": "Id del producto (obtenlo con list_products)",
                    },
                    "delta": {
                        "type": "number",
                        "description": "Cantidad a sumar (positiva) o restar (negativa); distinta de 0",
                    },
                },
                "required": ["product_id", "delta"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_low_stock_alerts",
            "description": (
                "Devuelve los productos cuya cantidad está por debajo de un umbral "
                "(por defecto 10). Úsala para saber qué está por agotarse."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "threshold": {
                        "type": "number",
                        "description": "Umbral de stock bajo; opcional, por defecto 10",
                    },
                },
                "required": [],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Ejecución de tools: cada una llama al endpoint correspondiente de la API
# ---------------------------------------------------------------------------

def _call_api(method: str, path: str, **kwargs) -> str:
    """Llama a la API y devuelve el resultado como texto JSON (también los errores)."""
    try:
        response = http.request(method, path, **kwargs)
    except httpx.HTTPError as exc:
        return json.dumps({"error": f"No se pudo conectar con la API: {exc}"}, ensure_ascii=False)
    try:
        body = response.json()
    except ValueError:
        body = response.text
    if response.is_error:
        detail = body.get("detail", body) if isinstance(body, dict) else body
        return json.dumps({"error": response.status_code, "detail": detail}, ensure_ascii=False)
    return json.dumps(body, ensure_ascii=False)


def list_products() -> str:
    return _call_api("GET", "/inventory")


def add_product(name: str, quantity: float, unit: str) -> str:
    return _call_api("POST", "/inventory", json={"name": name, "quantity": quantity, "unit": unit})


def update_stock(product_id: int, delta: float) -> str:
    return _call_api("PATCH", f"/inventory/{product_id}", json={"delta": delta})


def get_low_stock_alerts(threshold: float | None = None) -> str:
    params = {"threshold": threshold} if threshold is not None else None
    return _call_api("GET", "/inventory/alerts", params=params)


TOOL_HANDLERS = {
    "list_products": list_products,
    "add_product": add_product,
    "update_stock": update_stock,
    "get_low_stock_alerts": get_low_stock_alerts,
}


def execute_tool(name: str, raw_arguments: str | None) -> str:
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return json.dumps({"error": f"Tool desconocida: {name}"}, ensure_ascii=False)
    try:
        arguments = json.loads(raw_arguments or "{}") or {}
        return handler(**arguments)
    except (json.JSONDecodeError, TypeError) as exc:
        return json.dumps({"error": f"Argumentos no válidos para {name}: {exc}"}, ensure_ascii=False)

# ---------------------------------------------------------------------------
# Registro de conversación (append-only)
# ---------------------------------------------------------------------------

def log_event(actor: str, message: str, tool_call: str = "") -> None:
    """Añade una fila a conversation_log.csv. Se abre y cierra en cada evento
    para que nada se pierda si se interrumpe la sesión."""
    write_header = not LOG_FILE.exists() or LOG_FILE.stat().st_size == 0
    with LOG_FILE.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(LOG_FIELDS)
        writer.writerow([
            actor,
            message,
            tool_call,
            datetime.now().astimezone().isoformat(timespec="seconds"),
        ])

# ---------------------------------------------------------------------------
# Limpieza de Markdown (la respuesta se muestra en una terminal)
# ---------------------------------------------------------------------------

_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def _table_row_to_text(line: str) -> str:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|") if cell.strip()]
    if len(cells) <= 1:
        return " ".join(cells)
    return f"- {cells[0]}: {' '.join(cells[1:])}"


def strip_markdown(text: str) -> str:
    """Convierte la respuesta del LLM a texto plano legible en la terminal."""
    lines = text.splitlines()
    output = []
    for i, line in enumerate(lines):
        # Tablas: se descartan cabecera y separador; cada fila pasa a "- celda1: resto"
        if _TABLE_SEPARATOR.match(line):
            continue
        if line.lstrip().startswith("|"):
            is_header = i + 1 < len(lines) and _TABLE_SEPARATOR.match(lines[i + 1])
            if not is_header:
                output.append(_table_row_to_text(line))
            continue
        line = re.sub(r"^\s{0,3}#{1,6}\s+", "", line)          # encabezados
        line = re.sub(r"^\s{0,3}>\s?", "", line)               # citas
        line = re.sub(r"^(\s*)[*+]\s+", r"\1- ", line)         # viñetas * / + -> -
        line = re.sub(r"(\*\*|__)(.+?)\1", r"\2", line)        # **negrita** / __negrita__
        line = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", line)  # *cursiva*
        line = re.sub(r"`([^`]*)`", r"\1", line)               # `código`
        line = line.replace("**", "")                          # restos sueltos
        output.append(line.rstrip())
    # Colapsar líneas en blanco repetidas
    return re.sub(r"\n{3,}", "\n\n", "\n".join(output)).strip()


_REPEATED_ANSWER = re.compile(r"(.{20,}?)(?:\s{0,4}\1)+", re.DOTALL)


def remove_repetition(text: str) -> str:
    """Elimina repeticiones que a veces genera el modelo:
    - la respuesta entera duplicada, incluso pegada sin separación ("...¿Algo más?Tienes...")
    - párrafos idénticos consecutivos."""
    text = text.strip()
    # Respuesta entera repetida 2+ veces (bloques de 20+ caracteres, para no tocar "jaja")
    repeated = _REPEATED_ANSWER.fullmatch(text)
    if repeated:
        text = repeated.group(1).strip()
    # Párrafos idénticos consecutivos
    paragraphs = re.split(r"\n\s*\n", text)
    kept = [p for i, p in enumerate(paragraphs) if i == 0 or p.strip() != paragraphs[i - 1].strip()]
    return "\n\n".join(kept)


def clean_answer(text: str) -> str:
    """Limpieza final de la respuesta antes de mostrarla, guardarla en el historial y en el log."""
    return remove_repetition(strip_markdown(text))

# ---------------------------------------------------------------------------
# Bucle del agente
# ---------------------------------------------------------------------------

def run_turn(client: OpenAI, messages: list[dict], user_input: str) -> str:
    """Procesa un mensaje del usuario y devuelve la respuesta final del agente.
    `messages` es el historial de la sesión y se actualiza en el sitio."""
    # Observar
    messages.append({"role": "user", "content": user_input})
    log_event("user", user_input)

    for _ in range(MAX_STEPS):
        # Pensar
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )
        reply = response.choices[0].message

        # Respuesta final: no hay tools pendientes -> fin del turno
        if not reply.tool_calls:
            answer = clean_answer(reply.content or "")
            messages.append({"role": "assistant", "content": answer})
            log_event("agent", answer)
            return answer

        messages.append({
            "role": "assistant",
            "content": reply.content or "",
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.function.name, "arguments": call.function.arguments},
                }
                for call in reply.tool_calls
            ],
        })

        for call in reply.tool_calls:
            name = call.function.name
            log_event("agent", call.function.arguments or "{}", name)
            # Actuar
            result = execute_tool(name, call.function.arguments)
            log_event("tool", result, name)
            # Actualizar: el resultado vuelve al contexto del LLM
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
        # Repetir

    answer = "No he podido completar la petición en un número razonable de pasos. ¿Puedes reformularla?"
    messages.append({"role": "assistant", "content": answer})
    log_event("agent", answer)
    return answer


def check_api() -> bool:
    try:
        http.get("/inventory").raise_for_status()
        return True
    except httpx.HTTPError:
        return False


def main() -> None:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or api_key == "tu_clave_aqui":
        sys.exit("Falta GROQ_API_KEY en el fichero .env.")
    if not check_api():
        sys.exit(
            f"La API no responde en {API_URL}. Arráncala primero en otra terminal:\n"
            "    uvicorn api.app:app --reload"
        )

    client = OpenAI(api_key=api_key, base_url=GROQ_BASE_URL)
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    print("Asistente de inventario listo. Escribe 'salir' para terminar.\n")
    while True:
        try:
            user_input = input("Tú: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n¡Hasta luego!")
            break
        if not user_input:
            continue
        if user_input.lower() in {"salir", "exit", "quit"}:
            print("¡Hasta luego!")
            break

        turn_start = len(messages)
        try:
            answer = run_turn(client, messages, user_input)
        except OpenAIError as exc:
            # Deshacer el turno para no dejar llamadas a tools sin respuesta en el historial
            del messages[turn_start:]
            answer = f"Ha fallado la conexión con el modelo ({exc.__class__.__name__}). Inténtalo de nuevo."
            log_event("agent", f"{answer} Detalle: {exc}")
        except KeyboardInterrupt:
            del messages[turn_start:]
            print("\n(Petición cancelada)")
            continue
        print(f"Agente: {answer}\n")


if __name__ == "__main__":
    main()
