import csv
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import dotenv_values, load_dotenv
from openai import OpenAI


ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / ".env")
DOTENV_CONFIG = dotenv_values(ROOT_DIR / ".env")

CONVERSATION_LOG = ROOT_DIR / "conversation_log.csv"
API_BASE_URL = os.getenv("INVENTORY_API_URL", "http://127.0.0.1:8000").rstrip("/")
LLM_BASE_URL = (
	DOTENV_CONFIG.get("LLM_BASE_URL")
	or DOTENV_CONFIG.get("OPENROUTER_BASE_URL")
	or DOTENV_CONFIG.get("OPENAI_BASE_URL")
	or DOTENV_CONFIG.get("GROQ_BASE_URL")
	or os.getenv("LLM_BASE_URL")
	or os.getenv("OPENROUTER_BASE_URL")
	or os.getenv("OPENAI_BASE_URL")
	or os.getenv("GROQ_BASE_URL")
	or "https://api.groq.com/openai/v1"
).rstrip("/")
MODEL = (
	DOTENV_CONFIG.get("LLM_MODEL")
	or DOTENV_CONFIG.get("OPENROUTER_MODEL")
	or DOTENV_CONFIG.get("OPENAI_MODEL")
	or DOTENV_CONFIG.get("GROQ_MODEL")
	or os.getenv("LLM_MODEL")
	or os.getenv("OPENROUTER_MODEL")
	or os.getenv("OPENAI_MODEL")
	or os.getenv("GROQ_MODEL")
	or "llama-3.3-70b-versatile"
)
MAX_MODEL_CALLS_PER_TURN = 5

SYSTEM_PROMPT = """Eres el asistente de inventario de una tienda de suministros para cafeterías.
Conversas siempre en español, con respuestas breves y claras. Usa las herramientas para
consultas sobre el inventario. Crea productos solo cuando el usuario pida incorporarlos
al catálogo. Ajusta stock solo ante una entrega o venta real y explícita; una pregunta
hipotética sobre cuánto quedaría no debe modificar el inventario. Si falta información
para una operación real, pregunta antes de actuar. Nunca inventes resultados: basa la
respuesta en los datos devueltos por la API."""

TOOLS = [
	{
		"type": "function",
		"function": {
			"name": "list_inventory",
			"description": "Lista todos los productos y sus cantidades actuales.",
			"parameters": {"type": "object", "properties": {}, "required": []},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "create_product",
			"description": "Incorpora un producto nuevo al catálogo de inventario.",
			"parameters": {
				"type": "object",
				"properties": {
					"name": {"type": "string", "description": "Nombre del producto."},
					"quantity": {
						"type": "number",
						"description": "Cantidad inicial, mayor o igual a cero.",
					},
					"unit": {"type": "string", "description": "Unidad del producto."},
				},
				"required": ["name", "quantity", "unit"],
				"additionalProperties": False,
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "adjust_inventory",
			"description": (
				"Ajusta el stock de un producto existente por un delta. Usa delta positivo "
				"para una entrega y negativo para una venta real ya confirmada."
			),
			"parameters": {
				"type": "object",
				"properties": {
					"product_id": {"type": "integer", "description": "ID del producto."},
					"delta": {
						"type": "number",
						"description": "Cambio de stock: positivo suma y negativo resta.",
					},
				},
				"required": ["product_id", "delta"],
				"additionalProperties": False,
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "get_inventory_alerts",
			"description": "Lista productos por debajo de un umbral de cantidad.",
			"parameters": {
				"type": "object",
				"properties": {
					"threshold": {
						"type": "number",
						"description": "Umbral no negativo; por defecto es 10.",
					}
				},
				"required": [],
				"additionalProperties": False,
			},
		},
	},
]


def log_event(actor: str, message: str, tool_call: str | None = None) -> None:
	fields = ["actor", "message", "tool_call", "timestamp"]
	needs_header = not CONVERSATION_LOG.exists() or CONVERSATION_LOG.stat().st_size == 0
	with CONVERSATION_LOG.open("a", newline="", encoding="utf-8") as log_file:
		writer = csv.DictWriter(log_file, fieldnames=fields)
		if needs_header:
			writer.writeheader()
		writer.writerow(
			{
				"actor": actor,
				"message": message,
				"tool_call": tool_call or "",
				"timestamp": datetime.now(timezone.utc).isoformat(),
			}
		)


def request_inventory_api(method: str, path: str, payload: dict | None = None) -> dict | list:
	url = f"{API_BASE_URL}{path}"
	body = None if payload is None else json.dumps(payload).encode("utf-8")
	request = Request(
		url,
		data=body,
		method=method,
		headers={"Content-Type": "application/json"},
	)
	try:
		with urlopen(request, timeout=15) as response:
			return json.loads(response.read().decode("utf-8"))
	except HTTPError as error:
		error_body = error.read().decode("utf-8")
		try:
			details = json.loads(error_body)
		except json.JSONDecodeError:
			details = error_body
		return {"http_status": error.code, "error": details}
	except URLError as error:
		return {"error": f"No se pudo conectar con la API: {error.reason}"}


def execute_tool(name: str, arguments: dict) -> dict | list:
	if name == "list_inventory":
		return request_inventory_api("GET", "/inventory")
	if name == "create_product":
		return request_inventory_api("POST", "/inventory", arguments)
	if name == "adjust_inventory":
		product_id = arguments["product_id"]
		delta = float(arguments["delta"])
		if not math.isfinite(delta):
			return {"error": "El delta debe ser un número finito."}
		return request_inventory_api(
			"PATCH", f"/inventory/{product_id}", {"delta": delta}
		)
	if name == "get_inventory_alerts":
		threshold = arguments.get("threshold")
		query = "" if threshold is None else f"?{urlencode({'threshold': threshold})}"
		return request_inventory_api("GET", f"/inventory/alerts{query}")
	return {"error": f"Herramienta desconocida: {name}"}


def run_agent() -> None:
	api_key = (
		os.getenv("LLM_API_KEY")
		or os.getenv("OPENROUTER_API_KEY")
		or os.getenv("OPENAI_API_KEY")
		or os.getenv("GROQ_API_KEY")
	)
	if not api_key:
		print(
			"Falta una clave de API. Define LLM_API_KEY, OPENROUTER_API_KEY "
			"o OPENAI_API_KEY en .env."
		)
		raise SystemExit(1)

	# OpenAI's client speaks the OpenAI-compatible protocol; base_url and model select
	# the actual provider/gateway, independently of the environment variable used for the key.
	client = OpenAI(api_key=api_key, base_url=LLM_BASE_URL)
	history = [{"role": "system", "content": SYSTEM_PROMPT}]
	print("Agente de inventario listo. Escribe 'salir' para terminar.")

	while True:
		try:
			user_message = input("Tú: ").strip()
		except (EOFError, KeyboardInterrupt):
			print()
			break
		if not user_message:
			continue
		if user_message.lower() in {"salir", "exit", "quit"}:
			break

		history.append({"role": "user", "content": user_message})
		log_event("user", user_message)
		confirmed_movements = []

		for model_call_number in range(1, MAX_MODEL_CALLS_PER_TURN + 1):
			try:
				completion = client.chat.completions.create(
					model=MODEL,
					messages=history,
					tools=TOOLS,
					tool_choice="auto",
				)
			except Exception as error:
				print(f"No se pudo completar la solicitud al modelo: {error}")
				break

			assistant_message = completion.choices[0].message
			if not assistant_message.tool_calls:
				history.append(assistant_message.model_dump(exclude_none=True))
				answer = assistant_message.content or "No recibí una respuesta del modelo."
				log_event("agent", answer)
				print(f"Agente: {answer}")
				break

			if model_call_number == MAX_MODEL_CALLS_PER_TURN:
				for tool_call in assistant_message.tool_calls:
					try:
						arguments = json.loads(tool_call.function.arguments or "{}")
						if not isinstance(arguments, dict):
							arguments = {}
					except (json.JSONDecodeError, TypeError, ValueError):
						arguments = {}
					call_details = (
						f"Solicitud no ejecutada por límite de llamadas (id={tool_call.id}; "
						f"argumentos={json.dumps(arguments, ensure_ascii=False)})"
					)
					log_event(
						"agent",
						f"{tool_call.function.name}: {call_details}",
						tool_call.function.name,
					)

				stop_reason = (
					f"Se alcanzó el límite de {MAX_MODEL_CALLS_PER_TURN} llamadas al modelo "
					"para este mensaje. No ejecuté las herramientas solicitadas en la quinta llamada."
				)
				if confirmed_movements:
					movement_summary = "; ".join(confirmed_movements)
				else:
					movement_summary = "Ningún movimiento de inventario fue confirmado por la API."
				notice = f"{stop_reason} Movimientos ya confirmados por la API: {movement_summary}"
				history.append({"role": "assistant", "content": notice})
				log_event("agent", notice)
				print(f"Agente: {notice}")
				# Deliberately do not append the fifth assistant tool_calls message:
				# that would leave unresolved tool calls in the conversation history.
				break

			history.append(assistant_message.model_dump(exclude_none=True))

			for tool_call in assistant_message.tool_calls:
				arguments = {}
				try:
					arguments = json.loads(tool_call.function.arguments or "{}")
					if not isinstance(arguments, dict):
						raise ValueError("Los argumentos deben ser un objeto JSON.")
				except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
					arguments_error = str(error)
				else:
					arguments_error = None

				call_data = {
					"id": tool_call.id,
					"arguments": arguments,
				}
				log_event(
					"agent",
					f"Solicitud de herramienta (id={tool_call.id}; "
					f"argumentos={json.dumps(call_data['arguments'], ensure_ascii=False)})",
					tool_call.function.name,
				)

				if arguments_error is not None:
					result = {"error": f"No se pudo ejecutar la herramienta: {arguments_error}"}
				else:
					try:
						result = execute_tool(tool_call.function.name, arguments)
					except (KeyError, TypeError, ValueError) as error:
						result = {"error": f"No se pudo ejecutar la herramienta: {error}"}

				result_content = json.dumps(result, ensure_ascii=False)
				log_event(
					"tool",
					result_content,
					tool_call.function.name,
				)
				if (
					tool_call.function.name in {"create_product", "adjust_inventory"}
					and isinstance(result, dict)
					and "http_status" not in result
					and "error" not in result
					and "id" in result
					and "quantity" in result
				):
					confirmed_movements.append(
						f"{result.get('name', 'Producto')} (id={result['id']}): "
						f"{result['quantity']} {result.get('unit', '')}".strip()
					)
				history.append(
					{
						"role": "tool",
						"tool_call_id": tool_call.id,
						"content": result_content,
					}
				)


def main() -> None:
	try:
		run_agent()
	except OSError as error:
		print(f"No se pudo acceder al registro de conversación: {error}", file=sys.stderr)
		raise SystemExit(1) from error


if __name__ == "__main__":
	main()
