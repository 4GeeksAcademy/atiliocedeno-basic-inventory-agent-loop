# Agente de inventario

Proyecto de 4Geeks: un agente conversacional en español consulta y actualiza un inventario CSV mediante una API FastAPI. El agente llama al modelo autorizado a través del gateway compatible con OpenAI y ejecuta las herramientas de inventario por HTTP.

## Requisitos e instalación desde un clon

- Python 3.14 o superior.
- [`uv`](https://docs.astral.sh/uv/).
- Una clave de API del gateway 4Geeks autorizada para el modelo indicado abajo.

```bash
git clone <URL_DEL_REPOSITORIO>
cd atiliocedeno-basic-inventory-agent-loop
uv sync
cp .env.example .env
```

Edita `.env` localmente: reemplaza el valor de ejemplo de `LLM_API_KEY` por tu clave. No pongas credenciales reales en README, en `.env.example` ni en Git. El gateway y modelo autorizados para esta entrega son:

```dotenv
LLM_BASE_URL=https://llm.4geeks.ai
LLM_MODEL=online/openrouter/openai/gpt-6-luna
LLM_API_KEY=replace_with_your_api_key
```

### Variables que lee `agent.py`

- Clave, en este orden de preferencia: `LLM_API_KEY`, `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `GROQ_API_KEY`.
- URL base, en este orden: `LLM_BASE_URL`, `OPENROUTER_BASE_URL`, `OPENAI_BASE_URL`, `GROQ_BASE_URL`; si ninguna está definida se usa `https://api.groq.com/openai/v1`.
- Modelo, en este orden: `LLM_MODEL`, `OPENROUTER_MODEL`, `OPENAI_MODEL`, `GROQ_MODEL`; si ninguno está definido se usa `llama-3.3-70b-versatile`.
- `INVENTORY_API_URL` define la URL de la API de inventario; su valor por defecto es `http://127.0.0.1:8000`.

`agent.py` carga `.env` al iniciarse. Mantén `LLM_BASE_URL` y `LLM_MODEL` configurados para usar el gateway/modelo autorizados, en lugar de los valores por defecto.

## Arranque local

Abre dos terminales en la raíz del clon.

**Terminal 1 — API** (lee y escribe `products.csv`):

```bash
uv run uvicorn api.app:app --host 127.0.0.1 --port 8000
```

**Terminal 2 — agente interactivo:**

```bash
uv run python agent.py
```

Escribe las solicitudes después del prompt `Tú:`. Para salir, escribe `salir` o pulsa `Ctrl+C`. La API documenta sus endpoints en `http://127.0.0.1:8000/docs`.

## Prueba manual aislada (modelo real, CSV temporal)

Esta prueba conserva intacto el inventario original: inicia una instancia de la API en el puerto `8001` apuntando a un archivo temporal con 8 litros de leche de avena. Requiere que `.env` tenga la clave, gateway y modelo autorizados. No ejecutes la prueba contra el puerto habitual `8000`.

**Terminal 1 — crear el CSV temporal e iniciar la API:**

```bash
set -e
cd atiliocedeno-basic-inventory-agent-loop
mkdir /tmp/4geeks-inventory-manual
printf 'id,name,quantity,unit\n1,Leche de avena,8,litros\n' > /tmp/4geeks-inventory-manual/products.csv
INVENTORY_CSV_PATH=/tmp/4geeks-inventory-manual/products.csv uv run uvicorn api.app:app --host 127.0.0.1 --port 8001
```

Déjala ejecutándose. **Terminal 2 — conectar el agente a esa API temporal:**

```bash
cd atiliocedeno-basic-inventory-agent-loop
INVENTORY_API_URL=http://127.0.0.1:8001 uv run python agent.py
```

En el agente (no en la terminal del shell), escribe exactamente estas frases, una por turno:

```text
Tú: Llegaron 3 litros de leche de avena
Tú: ¿Cuántos litros quedan ahora?
```

La primera solicitud debe producir un único `PATCH` exitoso; la segunda debe consultar el inventario. **Terminal 3 — verificar el saldo directamente por GET:**

```bash
curl --fail http://127.0.0.1:8001/inventory
```

Criterio de aceptación: el CSV temporal muestra `quantity` igual a `11` para la leche de avena, el log de la primera operación contiene un único resultado exitoso de `adjust_inventory`, y el archivo original `products.csv` no cambia. Comprueba su estado desde la raíz del proyecto con:

```bash
git diff -- products.csv
```

Al terminar, escribe `salir` en `Tú:`, detén la API con `Ctrl+C` y elimina el CSV temporal:

```bash
rm -rf /tmp/4geeks-inventory-manual
```

## Datos guardados y endpoints

- `products.csv`, en la raíz del clon, es el inventario predeterminado. En la prueba aislada se usa el archivo temporal definido por `INVENTORY_CSV_PATH` para la API.
- `conversation_log.csv`, en la raíz junto a `agent.py`, recibe eventos del agente en modo append. Conserva los registros anteriores; no se trunca al iniciar otra conversación.
- La API proporciona `GET /inventory`, `POST /inventory`, `PATCH /inventory/{product_id}` y `GET /inventory/alerts?threshold=10`.
- El agente permite como máximo cinco llamadas al modelo por mensaje del usuario.
- Las conversaciones se envían al proveedor LLM configurado; no incluyas datos sensibles en las solicitudes.

## Despliegue

Ejecuta API y agente como procesos separados. En despliegue, configura `INVENTORY_API_URL` con una dirección alcanzable desde el agente y monta almacenamiento persistente para el CSV de inventario. La API puede escuchar en todas las interfaces del contenedor con:

```bash
uv run uvicorn api.app:app --host 0.0.0.0 --port 8000
```

No expongas públicamente los endpoints de escritura sin autenticación y controles de red. Protege también `conversation_log.csv`, que contiene mensajes y actividad operativa. `.env` está ignorado por Git; usa `.env.example` solo como plantilla no secreta.
