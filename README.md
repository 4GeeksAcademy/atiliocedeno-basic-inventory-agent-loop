# Basic Inventory Agent Loop

Spanish setup, deployment, and isolated manual-test instructions are in [`README.es.md`](README.es.md).

## Quick start

Requirements: Python 3.14+, [`uv`](https://docs.astral.sh/uv/), and an authorized 4Geeks gateway API key for model `online/openrouter/openai/gpt-6-luna`.

```bash
git clone <REPOSITORY_URL>
cd atiliocedeno-basic-inventory-agent-loop
uv sync
cp .env.example .env
```

Set `LLM_API_KEY` in `.env` to your own credential. Keep the authorized gateway and model configured as:

```dotenv
LLM_BASE_URL=https://llm.4geeks.ai
LLM_MODEL=online/openrouter/openai/gpt-6-luna
LLM_API_KEY=replace_with_your_api_key
```

Run these commands in separate terminals from the repository root.

Terminal 1 — inventory API:

```bash
uv run uvicorn api.app:app --host 127.0.0.1 --port 8000
```

Terminal 2 — interactive agent:

```bash
uv run python agent.py
```

Enter requests at `Tú:`. Type `salir` or press `Ctrl+C` to stop the agent. The default inventory is `products.csv` at the repository root; conversation events append to `conversation_log.csv` beside `agent.py`. See [`README.es.md`](README.es.md) for all environment-variable names, deployment notes, and the manual test against a temporary CSV that leaves the original inventory unchanged.