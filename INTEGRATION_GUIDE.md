# Darwin Integration Guide - Next Steps Implementation

This guide explains how to use the newly integrated features.

## 1. Obsidian Integration

Your research agent can now automatically save structured notes to Obsidian!

### Prerequisites
- Obsidian installed on your computer
- "Local REST API" plugin enabled in Obsidian
- API key from Obsidian settings

### Setup
1. Open Obsidian → Settings → Community Plugins
2. Search for and install "Local REST API"
3. Enable the plugin
4. Go to Local REST API settings and get your API key
5. Update the Obsidian configuration in `config/claude_desktop_config.json`:
   ```json
   "env": {
       "OBSIDIAN_API_KEY": "your-api-key-here",
       "OBSIDIAN_PORT": "27123"
   }
   ```

### Usage Examples
After setup, your agent will automatically:
- **Create paper notes**: Each paper gets a structured note with metadata
- **Add metadata**: Tags by domain, methodology, publication year
- **Link papers**: Establishes connections between related research
- **Generate digests**: Creates weekly summaries of research findings

Try this:
```
Search papers on machine learning 2025 and save them to Obsidian
```

The agent will now:
1. Search for papers
2. Show you the results for approval
3. Download papers you approve
4. Create structured notes in Obsidian
5. Link them to related research
6. Create a weekly digest summarizing key findings

## 2. Human-in-the-Loop Approval System

Before downloading papers, the agent now asks for your explicit approval!

### How It Works
When the agent finds relevant papers, it will display:
```
================================================================================
PAPER DOWNLOAD CONFIRMATION
================================================================================

Title: Machine Learning Advances in 2025
Paper ID: 2501.12345
Published: 2025-01-15

Abstract Preview:
This paper presents novel approaches to...
[preview of abstract...]

--------------------------------------------------------------------------------

Download this paper? (yes/no/skip):
```

### Responses
- **yes/y**: Download the paper and save to local storage
- **no/n**: Skip this paper, move to next
- **skip/s**: Skip without deciding, continue to next

This ensures:
- ✅ You only download papers you actually need
- ✅ Better control over storage usage
- ✅ Improved filtering based on your preferences
- ✅ Reproducible research (validated paper set)

## 3. Enhanced Agent System Prompt

Your agent now operates with a comprehensive "Darwin Research Assistant" persona.

### Key Capabilities

**Smart Filtering**: The agent now:
- Analyzes abstracts to rank relevance
- Filters 100 results down to 5-7 most relevant papers
- Explains filtering criteria

**Structured Note Creation**: Each paper gets:
```
Title, Authors, Abstract
↓
Methods & Contribution
↓
Key Findings & Limitations
↓
Related Work Links
↓
Tags & Metadata
```

**Weekly Digest Generation**: Automatic summaries that include:
- Research objectives
- Papers reviewed with key contributions
- Methodology comparisons
- Emerging research directions
- Actionable follow-up questions

**Metadata Organization**:
- Domain tags: `machine-learning`, `nlp`, `computer-vision`, etc.
- Methodology tags: `neural-networks`, `reinforcement-learning`, etc.
- Relevance rating: 1-5 scale
- Publication year for temporal organization

### Example Workflow

**Request:**
```
I need a comprehensive literature review on transformer models published in 2024-2025
```

**Agent Workflow:**
1. Searches arXiv for transformer papers from 2024-2025
2. Filters to 7 most relevant papers (explaining why)
3. Shows filtered list for approval
4. For each approved paper:
   - Displays download confirmation
   - You approve/reject individually
   - Creates structured Obsidian note
   - Extracts key findings
   - Links to related papers
5. Creates a weekly digest summarizing:
   - Core methodological approaches
   - Key innovations and results
   - Limitations identified
   - Suggested follow-up research

## Advanced Usage

### Create a Specific Research Workflow
```
Perform a systematic literature review on federated learning with privacy-preserving techniques. 
Search for papers from 2023-2025, download the top 5 most relevant, create Obsidian notes, 
and generate a digest with comparison of privacy techniques used.
```

### Compare Methodologies Across Papers
```
After reading these papers, what are the 3 main methodological differences in how they approach 
multi-agent learning? Create a comparison table in Obsidian.
```

### Track Research Gaps
```
Based on the papers you've reviewed, what are the identified research gaps and open questions?
Create a note with recommended follow-up research directions.
```

## Configuration Reference

### agent_config.json
- `model_name`: LLM to use (default: llama3.1)
- `api_base`: Ollama API endpoint (default: localhost:11434)
- `temperature`: Response creativity (0-1, default: 0.7)
- `system_prompt`: Core agent behavior and instructions

### claude_desktop_config.json - MCP Servers

**ArXiv Server**
```json
"arxiv": {
    "command": "python",
    "args": ["path/to/arxiv_server/server.py"],
    "env": {
        "PAPER_STORAGE": "path/to/papers"
    }
}
```

**PDF Tools Server**
```json
"pdf_tools": {
    "command": "python",
    "args": ["path/to/pdf_parser/server.py"]
}
```

**Obsidian Server** (NEW)
```json
"obsidian": {
    "command": "python",
    "args": ["path/to/obsidian_server/server.py"],
    "env": {
        "OBSIDIAN_API_KEY": "your-api-key",
        "OBSIDIAN_PORT": "27123",
        "DEFAULT_FOLDER": "Research/Incoming"
    }
}
```

## Troubleshooting

### Obsidian Connection Failed
- Verify Obsidian is open
- Check "Local REST API" plugin is enabled
- Confirm OBSIDIAN_API_KEY is correct
- Check port 27123 is not blocked

### Human-in-the-Loop Not Triggering
- Ensure agent prompt is loaded (restart agent)
- Check agent is using `confirm_download` tool
- Verify tool receives all required parameters

### Notes Not Appearing in Obsidian
- Check DEFAULT_FOLDER exists in vault
- Verify OBSIDIAN_API_KEY has write permissions
- Look for errors in agent terminal output

## Next Advanced Features to Consider

1. **Semantic Search**: Vector embeddings for better paper similarity
2. **Multi-Agent Specialization**: Separate agents for search, analysis, writing
3. **Docker Deployment**: Container for easy sharing and reproducibility
4. **Custom Templates**: User-defined note formats by research domain
5. **Citation Analysis**: Automatic tracking of paper citations and influence
6. **Real-time Collaboration**: Send research findings to team members

---

Ready to test? Restart your agent and try:
```
search papers on machine learning and show me the top results
```
