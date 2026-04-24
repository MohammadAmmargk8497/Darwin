# Darwin Research Agent

A **privacy-focused AI research assistant** that searches, downloads, and organizes academic papers from arXiv — powered by a local LLM via Ollama and connected through the **Model Context Protocol (MCP)**. No data leaves your machine.

---

## Features

- **Intelligent Paper Search** — Natural language queries are rewritten into structured arXiv Lucene queries with dual-pass retrieval (relevance + recency) and automatic fallback
- **PDF Download & Extraction** — Download papers by arXiv ID, extract structured sections (abstract, methods, results, conclusion) using regex-based academic header detection
- **Obsidian Note Generation** — Auto-creates rich research notes with real paper content, arXiv metadata, and YAML frontmatter — directly in your Obsidian vault
- **Human-in-the-Loop Safety** — Approval gates before downloads; auto-approve mode available for batch workflows
- **Multi-Provider LLM Support** — Works with Ollama (local/private), OpenAI, or any OpenAI-compatible API (Groq, Together AI, OpenRouter)
- **Streamlit Web UI** — Interactive chat interface with clickable paper cards, Abstract/PDF links, and sidebar controls
- **Evaluation Framework** — Built-in search quality metrics, pipeline tests, and CSV result export

---

## Architecture

```
 User
  |
  v
Streamlit UI  /  CLI
  |
  v
Agent Wrapper (subprocess bridge)
  |
  v
Local LLM (Ollama / OpenAI-compatible)
  |
  v
MCP Client
  |
  +---> ArXiv Server      — search, download, read papers
  +---> PDF Parser         — extract sections & figures from PDFs
  +---> Obsidian Server    — create structured notes in vault
```

All three MCP servers run locally as stdio processes. The agent orchestrates tool calls based on user intent, and the LLM decides which tools to invoke.

---

## Quick Start

Two install paths. Pick one.

### Option A — Docker (recommended, zero host changes)

Tested on Ubuntu 24.04. Requires only Docker.

```bash
# One-time Docker setup
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-v2
sudo usermod -aG docker "$USER"   # log out and back in so group membership applies

# Clone and start
git clone https://github.com/MohammadAmmargk8497/Darwin.git
cd Darwin
./scripts/docker-run.sh
```

The script builds the image and starts Ollama + the Darwin UI. It:

- **Auto-detects an NVIDIA GPU** (`nvidia-smi`) and `nvidia-container-toolkit`,
  and wires GPU passthrough to the Ollama container if both are present.
- **Picks an Ollama model sized for your VRAM**:
  - no GPU / small GPU → `llama3.2:3b` (~2 GB)
  - 8–22 GB VRAM → `llama3.1:8b` (~5 GB)
  - 22+ GB VRAM → `qwen2.5:14b` (~9 GB)
  Override anytime with `MODEL_NAME=... ./scripts/docker-run.sh`.
- **Streams logs in the foreground** and auto-shuts-down both containers when
  you Ctrl-C or close the terminal. Pass `--detach` to keep it running after
  the shell returns.

Open http://localhost:8501. The first run pulls the model into a Docker
volume — subsequent starts take seconds.

```bash
./scripts/docker-run.sh              # foreground, auto-shutdown on exit
./scripts/docker-run.sh --detach     # keep running; stop with `docker compose down`
docker compose down -v               # drop the pulled-model volume too
```

Your downloaded papers (`papers/`), Obsidian vault (`Darwin Research/`), and
logs (`logs/`) live on the host, bind-mounted into the container — edit them
with any tool and the agent sees the changes.

### Option B — Native Ubuntu install

Two commands. No Docker required.

```bash
git clone https://github.com/MohammadAmmargk8497/Darwin.git
cd Darwin
./scripts/install.sh    # installs Python deps, Ollama, pulls the model, seeds dirs
./scripts/run.sh        # starts Ollama (if needed) and the Streamlit UI
```

Open http://localhost:8501.

If something looks off:

```bash
./scripts/doctor.sh     # diagnoses what's missing
./scripts/stop.sh       # stops Streamlit (leaves the systemd ollama alone)
```

### Option C — Manual pip install

For non-Debian systems or when you want full control:

```bash
git clone https://github.com/MohammadAmmargk8497/Darwin.git
cd Darwin
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# You also need Ollama:
#   Linux/macOS: curl -fsSL https://ollama.com/install.sh | sh
#   other:       https://ollama.com/download
ollama pull llama3.2:3b
ollama serve &

streamlit run ui_app.py       # UI
# or: python -m src.agent.main   # CLI
```

### Configuration

All settings live in `.env` (gitignored) or `config/agent_config.json`.
Environment variables always win over JSON.

Common overrides:

```bash
# .env
MODEL_NAME=llama3.2:3b
PROVIDER=ollama
API_BASE=http://localhost:11434
OPENAI_API_KEY=...                          # only if PROVIDER=openai
OBSIDIAN_VAULT_PATH=/path/to/my/vault       # if you want a vault outside the repo
```

See `.env.example` for the full list.

---

## Usage — 3-Prompt Demo Pipeline

### 1. Search Papers

```
search papers on diffusion models for image generation
```

The agent rewrites this into a structured arXiv query, runs dual-pass search (relevance + recency), and returns paper cards with clickable Abstract/PDF links.

### 2. Download & Read

```
download and read paper 2310.08337v3 without approval
```

Downloads the PDF from arXiv, extracts full text via PyMuPDF, and returns a summary. The `without approval` flag skips the confirmation gate.

### 3. Save to Obsidian

```
create a research note for paper 2310.08337v3 for Obsidian
```

The system automatically:
- Fetches metadata from arXiv (title, authors, abstract, published date)
- Extracts structured sections from the downloaded PDF (methods, results, conclusion)
- Writes a rich Obsidian note with YAML frontmatter to `Darwin Research/Research/Incoming/`

---

## Project Structure

```
Darwin/
├── config/
│   ├── agent_config.json              LLM provider, model, system prompt
│   └── claude_desktop_config.json     MCP server definitions
│
├── src/
│   ├── common/                        Shared: settings, exceptions, vault I/O,
│   │                                  PDF sections, rate limiter, logging
│   ├── agent/                         LLM clients + MCP client + CLI entry
│   ├── arxiv_server/                  arXiv search / download / read
│   ├── pdf_parser/                    PDF section & figure extraction
│   └── obsidian_server/               Note creation, vault search
│
├── tests/                             pytest unit tests (run: make test)
│
├── scripts/
│   ├── install.sh                     Native Ubuntu installer
│   ├── run.sh                         Start UI + Ollama
│   ├── stop.sh                        Stop UI + foreground Ollama
│   ├── doctor.sh                      Environment diagnostics
│   └── docker-run.sh                  One-command Docker startup
│
├── docker/
│   └── entrypoint.sh                  Wait-for-Ollama + model pull
│
├── Dockerfile                         Multi-stage image (Python 3.12 slim)
├── docker-compose.yml                 Ollama + Darwin services
│
├── ui_app.py                          Streamlit web interface
├── agent_wrapper.py                   Subprocess bridge for UI
├── evaluate_system.py                 End-to-end evaluation suite
├── evaluate_search.py                 Search quality benchmarks
│
├── papers/                            Downloaded PDFs (host-bind-mounted)
├── Darwin Research/                   Obsidian vault (host-bind-mounted)
│   └── Research/Incoming/             Default note folder
├── logs/                              Runtime logs (host-bind-mounted)
│
├── .env.example                       Config template — copy to .env
├── Makefile                           install / test / lint / typecheck
├── pyproject.toml                     Project deps (Poetry)
├── requirements.txt                   Pip-compatible deps (used by Docker)
└── README.md
```

---

## MCP Tools Reference

### ArXiv Server

| Tool | Description |
|------|-------------|
| `search_papers(query, max_results, categories)` | Smart arXiv search with query rewriting, dual-pass retrieval, and fallback |
| `download_paper(paper_id)` | Download PDF by arXiv ID with local dedup |
| `read_paper(paper_id, max_chars)` | Extract text from a downloaded PDF |
| `list_papers()` | List all locally cached papers |
| `confirm_download(paper_title, paper_id, ...)` | Human-in-the-loop approval gate |
| `log_research_action(action, paper_id, result)` | Log actions to SQLite for evaluation |

### PDF Parser

| Tool | Description |
|------|-------------|
| `extract_pdf_sections(pdf_path, max_chars)` | Extract structured sections (abstract, methods, results, conclusion, etc.) using regex-based header detection |
| `extract_figures(pdf_path)` | Extract figure metadata (page, dimensions) |

### Obsidian Server

| Tool | Description |
|------|-------------|
| `obsidian_create_paper_note(paper_id, ...)` | Create a structured paper note with auto-fetched arXiv metadata and auto-extracted PDF sections |
| `obsidian_create_note(title, content, tags)` | Create a general research note |
| `obsidian_update_note(note_path, append_content)` | Append content to existing notes |
| `obsidian_create_weekly_digest(papers)` | Generate a weekly research digest |
| `obsidian_manage_frontmatter(note_path, tags)` | Update note metadata |
| `obsidian_global_search(query)` | Search across vault |

---

## How It Works

### Search Query Rewriting

Plain English queries are automatically converted to structured arXiv Lucene syntax:

```
"diffusion models for image generation"
  --> (ti:diffusion OR abs:diffusion) AND (ti:models OR abs:models)
      AND (ti:image OR abs:image) AND (ti:generation OR abs:generation)
```

Short queries (1-3 key terms) use exact phrase matching; longer queries use AND-of-terms for flexibility.

### PDF Section Detection

The parser uses regex patterns to identify academic paper headers:

- Numbered sections: `1. Introduction`, `2 Methods`, `II. RESULTS`
- Plain headers: `Abstract`, `Methodology`, `Conclusion`
- Canonical mapping: `methodology` -> `methods`, `conclusions` -> `conclusion`
- Per-section limit of 3,000 characters to avoid token explosion

### Auto-Enrichment Pipeline

When creating an Obsidian note, the system:

1. Queries arXiv API by paper ID to fetch title, authors, abstract, published date
2. Locates the downloaded PDF in `papers/`
3. Runs regex-based section extraction on the full PDF text
4. Merges all data into a structured Obsidian note with YAML frontmatter

---

## Evaluation

Run the built-in evaluation suite:

```bash
python evaluate_system.py
```

This tests:
- Search quality (structured vs baseline queries)
- Download pipeline (success, dedup, file integrity)
- PDF extraction accuracy (section detection)
- Obsidian note creation (content validation)
- Error handling and edge cases

Results are exported to `eval_results_<timestamp>.csv`.

---

## Configuration Options

### Switching LLM Provider

**Ollama (local, default):**
```json
{
    "provider": "ollama",
    "model_name": "llama3.2:3b",
    "api_base": "http://localhost:11434"
}
```

**OpenAI:**
```json
{
    "provider": "openai",
    "model_name": "gpt-4",
    "api_key": "sk-...",
    "api_base": "https://api.openai.com/v1"
}
```

**Groq / OpenRouter / Together AI:**
```json
{
    "provider": "openai",
    "model_name": "llama-3.1-70b-versatile",
    "api_key": "gsk_...",
    "api_base": "https://api.groq.com/openai/v1"
}
```

### Obsidian Vault Path

Set via environment variable or auto-detected:
```bash
export OBSIDIAN_VAULT_PATH="/path/to/your/vault"
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| LLM Runtime | Ollama (local) / OpenAI API |
| Tool Protocol | Model Context Protocol (MCP) via FastMCP |
| Paper Source | arXiv API |
| PDF Parsing | PyMuPDF (fitz) |
| Note Storage | Obsidian (markdown vault) |
| Web UI | Streamlit |
| Language | Python 3.10+ |

---

## Repository

GitHub: [https://github.com/MohammadAmmargk8497/Darwin](https://github.com/MohammadAmmargk8497/Darwin)

---

## License

This project is for academic and research purposes.
