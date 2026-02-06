# ArXiv MCP Server

🔍 Enable AI assistants to search and access arXiv papers through a simple MCP interface.
The ArXiv MCP Server provides a bridge between AI assistants and arXiv's research repository through the Model Context Protocol (MCP). It allows AI models to search for papers and access their content in a programmatic way.

🤝 Contribute • 📝 Report Bug

Pulse MCP Badge

✨ Core Features

🔎 Paper Search: Query arXiv papers with filters for date ranges and categories
📄 Paper Access: Download and read paper content
📋 Paper Listing: View all downloaded papers
🗃️ Local Storage: Papers are saved locally for faster access
📝 Prompts: A Set of Research Prompts
🚀 Quick Start

## Installing via Smithery

To install ArXiv Server for Claude Desktop automatically via Smithery:

npx -y @smithery/cli install arxiv-mcp-server --client claude

## Installing Manually

Install using uv:

uv tool install arxiv-mcp-server
For development:

# Clone and set up development environment
git clone https://github.com/blazickjp/arxiv-mcp-server.git
cd arxiv-mcp-server

# Create and activate virtual environment
uv venv
source .venv/bin/activate

# Install with test dependencies
uv pip install -e ".[test]"
🔌 MCP Integration

Add this configuration to your MCP client config file:

{
    "mcpServers": {
        "arxiv-mcp-server": {
            "command": "uv",
            "args": [
                "tool",
                "run",
                "arxiv-mcp-server",
                "--storage-path", "/path/to/paper/storage"
            ]
        }
    }
}
For Development:

{
    "mcpServers": {
        "arxiv-mcp-server": {
            "command": "uv",
            "args": [
                "--directory",
                "path/to/cloned/arxiv-mcp-server",
                "run",
                "arxiv-mcp-server",
                "--storage-path", "/path/to/paper/storage"
            ]
        }
    }
}
💡 Available Tools

The server provides four main tools:

1. Paper Search

Search for papers with optional filters:

result = await call_tool("search_papers", {
    "query": "transformer architecture",
    "max_results": 10,
    "date_from": "2023-01-01",
    "categories": ["cs.AI", "cs.LG"]
})
2. Paper Download

Download a paper by its arXiv ID:

result = await call_tool("download_paper", {
    "paper_id": "2401.12345"
})
3. List Papers

View all downloaded papers:

result = await call_tool("list_papers", {})
4. Read Paper

Access the content of a downloaded paper:

result = await call_tool("read_paper", {
    "paper_id": "2401.12345"
})
📝 Research Prompts

The server offers specialized prompts to help analyze academic papers:

Paper Analysis Prompt

A comprehensive workflow for analyzing academic papers that only requires a paper ID:

result = await call_prompt("deep-paper-analysis", {
    "paper_id": "2401.12345"
})
This prompt includes:

Detailed instructions for using available tools (list_papers, download_paper, read_paper, search_papers)
A systematic workflow for paper analysis
Comprehensive analysis structure covering:
Executive summary
Research context
Methodology analysis
Results evaluation
Practical and theoretical implications
Future research directions
Broader impacts
⚙️ Configuration

Configure through environment variables:

Variable	Purpose	Default
ARXIV_STORAGE_PATH	Paper storage location	~/.arxiv-mcp-server/papers
🧪 Testing

Run the test suite:

python -m pytest
📄 License

Released under the MIT License. See the LICENSE file for details.

