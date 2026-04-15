# Darwin Research Agent

Darwin is an autonomous research agent that connects a local LLM to arXiv, a PDF parser, and Obsidian through MCP (Model Context Protocol). You give it a topic, it searches, downloads, reads, and saves structured notes — all locally.

The agent is built around a tool-calling loop where the LLM reasons over a growing message history and dispatches tools as needed — no fixed pipeline, no hardcoded steps. Each tool is an independent MCP server communicating over stdio, so the architecture is modular and the LLM is the only orchestrator. Inference runs entirely through Ollama, meaning no queries, paper content, or API keys leave the machine.

---

## How it works

The agent runs a reasoning loop: the LLM decides at each step whether to call a tool or return a final answer. Tool results are injected back into the message history so the model has full context across every step.

```
User prompt
    └─> LLM (llama3.1 via Ollama)
            ├─ tool call ─> MCP Client Router
            │                   ├─> ArXiv Server   (search, download, read)
            │                   ├─> PDF Parser     (section extraction)
            │                   └─> Obsidian Server (create/search notes)
            └─ final answer ─> Streamlit UI
```

All tool communication happens over stdio using the MCP protocol. The LLM never calls external APIs directly.

---

## Dependencies

**System**
- Python 3.10+
- [Ollama](https://ollama.com) with `llama3.1` pulled

**Python packages**

```bash
poetry install
```

Key packages: `fastmcp`, `ollama`, `arxiv`, `pymupdf`, `httpx`, `streamlit`, `loguru`

**Optional providers** — if you want to run with a cloud LLM instead of Ollama, set `DARWIN_CONFIG` to point at one of the alternate config files:

| Config | Provider |
|---|---|
| `config/agent_config.json` | Ollama (default) |
| `config/agent_config_groq.json` | Groq |
| `config/agent_config_openai.json` | OpenAI |

---

## Setup

**1. Clone and install**

```bash
git clone <repo>
cd Darwin
poetry install
```

**2. Start Ollama**

```bash
ollama serve
ollama pull llama3.1
```

**3. Configure Obsidian vault path**

Edit `config/claude_desktop_config.json` and set `OBSIDIAN_VAULT_PATH` to your vault directory:

```json
"OBSIDIAN_VAULT_PATH": "/path/to/your/vault"
```

Downloaded PDFs go to `./papers/` by default. Change `PAPER_STORAGE` in the same config to override.

---

## Running

**Streamlit UI**

```bash
streamlit run ui_app.py
```

Click **Start Agent** in the sidebar. The agent starts MCP servers as subprocesses and signals `AGENT_READY` when all three are connected.

**With an alternate provider**

```bash
DARWIN_CONFIG=config/agent_config_groq.json streamlit run ui_app.py
```

**CLI**

```bash
python agent_wrapper.py
```

---

## MCP Servers

Each server is a standalone Python process that exposes tools over stdio.

| Server | Path | Tools |
|---|---|---|
| ArXiv | `src/arxiv_server/server.py` | `search_papers`, `download_paper`, `read_paper`, `confirm_download`, `list_papers` |
| PDF Parser | `src/pdf_parser/server.py` | `extract_pdf_sections`, `extract_figures` |
| Obsidian | `src/obsidian_server/server.py` | `obsidian_create_note`, `obsidian_create_paper_note`, `obsidian_global_search` |

Server config is in `config/claude_desktop_config.json`. The MCP client reads this at startup and connects to each server.

---

## Search engine

`search_papers` rewrites plain-English queries into structured arXiv Lucene queries scoped to title and abstract (`ti:`, `abs:`). It runs two passes — relevance-sorted and date-sorted — and merges results. If both return nothing it falls back to a broadened OR query. Raw keyword search is used as the baseline for evaluation.

---

## Evaluation

```bash
# Full system evaluation
python evaluate_system.py

# Search engine comparison only (structured vs baseline)
python evaluate_search.py

# Single section
python evaluate_system.py --section pdf
```

Outputs a timestamped CSV and JSON to the working directory. Run `plot_eval_results.py` against the JSON to generate charts.

---

## Project structure

```
Darwin/
├── src/
│   ├── agent/
│   │   ├── mcp_client.py       # MCP session manager + tool router
│   │   ├── ollama_client.py    # Ollama chat wrapper
│   │   └── openai_client.py    # OpenAI-compatible wrapper (Groq, OpenAI)
│   ├── arxiv_server/server.py
│   ├── pdf_parser/server.py
│   └── obsidian_server/server.py
├── config/
│   ├── agent_config.json
│   └── claude_desktop_config.json
├── agent_wrapper.py            # Subprocess entry point used by the UI
├── ui_app.py                   # Streamlit frontend
├── evaluate_system.py          # End-to-end evaluation
└── evaluate_search.py          # Search engine comparison
```
