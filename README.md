# Research Agent

A privacy-focused research agent leverages the Model Context Protocol (MCP) to connect a local LLM with external research tools like ArXiv, PDF parsers, and Obsidian.

## Setup

1.  **Install Dependencies using Poetry**:
    ```bash
    poetry install
    ```

2.  **Configuration**:
    *   Check `config/` for server configurations.
    *   Ensure Ollama is running (`ollama serve`).

## Components

*   **ArXiv MCP Server**: Searches and downloads papers.
*   **PDF Parser**: Extracts text/figures from PDFs.
*   **Obsidian Server**: Manages knowledge graph.
*   **Research Agent**: Orchestrates the workflow.

## Usage

(Coming soon)
