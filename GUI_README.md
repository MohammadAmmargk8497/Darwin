# Darwin Research Agent - GUI

🎨 Beautiful web-based interface for the Darwin Research Agent

## Features

✨ **Search Papers** - Query ArXiv with real-time results
📥 **Download** - Get papers with one click
📖 **Read** - View full paper content in the browser
📝 **Create Notes** - Generate Obsidian notes directly
⚙️ **Flexible Approval** - Choose between auto-approval or manual confirmation

## Installation

### Prerequisites
- Python 3.10+
- Ollama running locally (`ollama serve`)
- Darwin agent configured

### Setup

1. **Install Streamlit** (if not already installed):
```bash
pip install streamlit
```

2. **Start Ollama** (in one terminal):
```bash
ollama serve
```

3. **Run the GUI** (in another terminal):
```bash
streamlit run ui_app.py
```

## Usage

The GUI opens in your browser at `http://localhost:8501`

### Search & Download Workflow

1. **Search Tab**: Enter a query (e.g., "machine learning")
   - Results show title, ID, date, summary
   - Click paper ID to copy

2. **Download Tab**: 
   - Enter paper ID (from search results)
   - Choose approval mode in settings:
     - **Ask for confirmation**: You approve each download
     - **Auto-approve**: Downloads proceed automatically
   - Click "Download"

3. **Read Tab**:
   - Enter paper ID
   - Click "Read Paper"
   - View full text in expanded section

4. **Create Note Tab**:
   - **Generic Note**: Create research thoughts
   - **Paper-Specific Note**: Add analysis for a paper
   - Automatically saves to Obsidian vault

## Settings

**Sidebar Settings**:
- 🔌 **Connect to Services**: Initialize agent connection
- 📋 **Downloaded Papers**: See all your papers
- 🔧 **Approval Settings**: Toggle auto-approval mode

## Features

### ✨ Modern UI
- Clean, professional design
- Dark-mode friendly
- Responsive layout
- Color-coded messages (success/error/info)

### 🚀 Real-time Operations
- Live search results
- Instant downloads
- Paper content extraction
- Note creation confirmation

### 🔒 Smart Approval Gate
- Manual approval for important downloads
- Auto-approval for quick workflows
- Per-session tracking

### 📱 Fully Responsive
- Works on desktop
- Touch-friendly
- Mobile compatible

## Troubleshooting

**"Failed to initialize" error**:
- Ensure Ollama is running: `ollama serve`
- Check agent configuration in `config/agent_config.json`
- Verify MCP servers are configured

**Search returns no results**:
- Check internet connection
- ArXiv has rate limits - wait a moment
- Try more specific queries

**Download fails**:
- Verify paper ID is correct (e.g., `2306.04338v1`)
- Check `papers/` folder exists
- Ensure sufficient disk space

## Deployment

### Run Locally
```bash
streamlit run ui_app.py
```

### Deploy to Streamlit Cloud
```bash
streamlit deploy
```

### Run in Docker
```bash
docker run -p 8501:8501 -v $(pwd):/app streamlit run ui_app.py
```

## Architecture

```
┌─────────────────────────────────────┐
│   Streamlit GUI (ui_app.py)        │
│   - Search interface                │
│   - Download manager                │
│   - Paper reader                    │
│   - Note creator                    │
└──────────────┬──────────────────────┘
               │
       ┌───────▼───────┐
       │   MCP Client  │
       └───────┬───────┘
               │
    ┌──────────┼──────────┐
    │          │          │
┌───▼───┐ ┌───▼────┐ ┌──▼────┐
│ ArXiv │ │ Obsidian│ │ PDF   │
│Server │ │ Server  │ │Parser │
└───────┘ └────────┘ └───────┘
```

## Future Enhancements

- 📊 Analytics dashboard
- 🔖 Paper bookmarks
- 🏷️ Smart tagging
- 🔍 Full-text search
- 💬 Chat interface
- 📈 Research trends

## License

MIT - See LICENSE file

---

**Questions?** Check the main [README.md](README.md) or [INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md)
