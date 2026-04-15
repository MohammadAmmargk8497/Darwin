# Darwin Research Agent

A privacy-focused research agent that connects a local LLM (via Ollama) to external research tools using the **Model Context Protocol (MCP)** — no data leaves your machine.

---

## Architecture

```
Local LLM (Ollama)
       ↓
  MCP Client
       ↓
  ┌────────────────────────────────────────────┐
  │  ArXiv Server    — search & download papers │
  │  PDF Parser      — extract text & figures   │
  │  Obsidian Server — manage notes & knowledge │
  └────────────────────────────────────────────┘
```

---

## Quick Start

### 1. Install dependencies

```bash
poetry install
```

### 2. Start Ollama

```bash
ollama serve
ollama pull llama3.1
```

### 3. Configure

Edit the files in `config/`:

| File | Purpose |
|---|---|
| `agent_config.json` | Model, temperature, agent behaviour |
| `obsidian_config.json` | Vault path and API key |
| `claude_desktop_config.json` | MCP host config for Claude Desktop |

> Obsidian requires the **Local REST API** plugin. Get your key from Obsidian → Settings → Local REST API.

### 4. Run

```bash
# Streamlit UI
streamlit run ui_app.py

# CLI
python agent_wrapper.py
```

---

## Components

| Component | Path | Role |
|---|---|---|
| Research Agent | `src/agent/` | Orchestrates the full pipeline |
| ArXiv Server | `src/arxiv_server/` | Search and fetch papers |
| PDF Parser | `src/pdf_parser/` | Extract text and figures from PDFs |
| Obsidian Server | `src/obsidian_server/` | Read and write vault notes |
| UI | `ui_app.py` | Streamlit interface |
| Agent Wrapper | `agent_wrapper.py` | CLI entry point |

---

## ArXiv Tools

| Tool | Description |
|---|---|
| `search_papers` | Query arXiv with keyword, date, and category filters |
| `download_paper` | Download a paper by arXiv ID |
| `list_papers` | Browse locally stored papers |
| `read_paper` | Read the content of a downloaded paper |

---

## MCP Config

```json
{
    "mcpServers": {
        "arxiv-mcp-server": {
            "command": "uv",
            "args": ["tool", "run", "arxiv-mcp-server", "--storage-path", "./papers"]
        },
        "obsidian": {
            "command": "obsidian-mcp-server",
            "env": {
                "OBSIDIAN_API_KEY": "your-key",
                "OBSIDIAN_PORT": "27123",
                "DEFAULT_FOLDER": "Research/Incoming"
            }
        }
    }
}
```

---

## Agent Workflow

When given a research topic, the agent will:

1. Search arXiv and surface the most relevant papers
2. Download and parse selected PDFs
3. Create structured notes in your Obsidian vault
4. Link new notes to existing research in your vault
5. Generate a digest summarising all findings

Downloaded papers are cached locally in `papers/`.
