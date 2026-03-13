# Granola Bridge

A Python background daemon that monitors [Granola](https://granola.so) meeting transcripts, extracts action items via local LLM, and syncs approved items to Trello.

## Features

- **Automatic monitoring**: Watches Granola's cache file for new meetings (auto-detects latest version)
- **Local LLM extraction**: Uses OpenAI-compatible APIs (LMStudio, Ollama) to extract action items
- **Action item review**: Approve or reject extracted action items before they become Trello cards
- **Trello integration**: Creates cards with context from the meeting after review
- **Semantic search**: Search across all meeting transcripts using Ollama embeddings (optional)
- **Backlog handling**: Meetings captured while the app was offline can be reviewed and processed on demand
- **Web dashboard**: View meetings, action items, and manage retries at localhost:8080
- **Manual uploads**: Process voice memo transcripts or other meeting notes
- **Retry queue**: Failed operations automatically retry with exponential backoff
- **Notifications**: Daily summaries and failure alerts via Slack/Discord webhooks
- **Auto-start on login**: launchd service or double-click `.command` file to start automatically
- **LLM failure recovery**: Meetings are saved even if LLM is down; process them later with one click

## Requirements

- Python 3.11+
- [LMStudio](https://lmstudio.ai/) (or any OpenAI-compatible API) running locally
- Trello account with API access
- macOS (for launchd service management)
- [Ollama](https://ollama.ai/) (optional, for semantic search and improved extraction)

## Quick Start

### 1. Clone and install

```bash
git clone <repo-url>
cd granola-to-trello

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install the package
pip install -e .
```

### 2. Configure Trello

1. Get your API key: https://trello.com/app-key
2. Generate a token: Click "Token" link on the API key page
3. Get your list ID:
   - Open your Trello board
   - Add `.json` to the URL (e.g., `https://trello.com/b/XXXXX.json`)
   - Find your target list's `id` field

### 3. Create configuration

```bash
# Copy example files
cp .env.example .env
cp config.yaml.example ~/.granola-bridge/config.yaml

# Edit .env with your Trello credentials
nano .env
```

**.env**:
```
TRELLO_API_KEY=your_api_key
TRELLO_API_TOKEN=your_token
TRELLO_LIST_ID=your_list_id
```

### 4. Start LMStudio

1. Open LMStudio and load a model (e.g., Llama 3, Mistral, etc.)
2. Start the local server (default: http://localhost:1234)

### 5. (Optional) Set up Ollama for semantic search

1. Install Ollama: https://ollama.ai/
2. Pull the embedding model: `ollama pull nomic-embed-text`
3. Ollama runs automatically on port 11434. LM Studio (port 1234) and Ollama don't conflict.

### 6. Initialize and run

```bash
# Initialize database
granola-bridge init

# Run daemon (foreground for testing)
granola-bridge run

# Or run just the web dashboard
granola-bridge web
```

### 7. Install as service (optional)

```bash
./scripts/install.sh
```

## Usage

### CLI Commands

```bash
# Run the daemon (watches Granola + web dashboard)
granola-bridge run

# Run web dashboard only
granola-bridge web

# Process a single transcript file
granola-bridge process --file transcript.txt

# Dry run (extract action items without creating cards)
granola-bridge process --file transcript.txt --dry-run

# Initialize database
granola-bridge init
```

### Web Dashboard

Access at http://localhost:8080 (default):

- **Dashboard**: Overview of meetings and action items; button to process any meetings the LLM missed
- **Meetings**: List and detail views of all meetings
- **Action Item Review**: On each meeting's detail page, approve (👍) or reject (👎) extracted action items — only approved items are sent to Trello
- **Backlog**: Meetings captured while the app was offline appear as backlog; process or dismiss them from the meeting detail page
- **Upload**: Manually upload transcripts for processing
- **Search**: Semantic search across all meeting transcripts (requires Ollama)
- **Retry Queue**: Monitor and manage failed operations

### Starting the App

Three ways to run Granola Bridge:

**Double-click launcher** (simplest):
```
scripts/start-granola-bridge.command
```
Double-click this file in Finder to open a terminal and start the server.

**macOS app bundle**:
```
scripts/GranolaBridge.app
```
Double-click to launch from Finder or add to your Dock.

**launchd service** (runs automatically at login):
```bash
./scripts/install.sh
```

### Service Management (launchd)

```bash
# Start service
launchctl load ~/Library/LaunchAgents/com.granola-bridge.daemon.plist

# Stop service
launchctl unload ~/Library/LaunchAgents/com.granola-bridge.daemon.plist

# Check status
launchctl list | grep granola

# View logs
tail -f ~/.granola-bridge/logs/daemon.log
```

## Configuration

### config.yaml

```yaml
granola:
  cache_path: "~/Library/Application Support/Granola/cache-v6.json"
  watch_debounce_ms: 500

llm:
  base_url: "http://localhost:1234/v1"
  model: "local-model"
  timeout_seconds: 120

trello:
  api_base_url: "https://api.trello.com/1"

retry:
  max_attempts: 5
  base_delay_seconds: 30

web:
  host: "127.0.0.1"
  port: 8080

notifications:
  daily_summary:
    enabled: true
    time: "09:00"

database:
  path: "~/.granola-bridge/bridge.db"

embedding:
  ollama_url: "http://localhost:11434"
  model: "nomic-embed-text"
  chroma_path: "~/.granola-bridge/chroma"
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TRELLO_API_KEY` | Yes | Trello API key |
| `TRELLO_API_TOKEN` | Yes | Trello API token |
| `TRELLO_LIST_ID` | Yes | Target list ID for cards |
| `SLACK_WEBHOOK_URL` | No | Slack webhook for notifications |
| `DISCORD_WEBHOOK_URL` | No | Discord webhook for notifications |

## How It Works

1. **File Watch**: The daemon monitors Granola's cache file (auto-detects the latest `cache-vN.json` if the configured path doesn't exist)
2. **Deduplication**: New meetings are identified by their Granola ID and stored in SQLite
3. **Embedding**: Transcript segments are stored and embedded via Ollama for RAG-based retrieval (if Ollama is available)
4. **LLM Extraction**: Relevant transcript chunks are retrieved via RAG and sent to your local LLM to extract action items (falls back to chunk-based extraction if Ollama is unavailable)
5. **Review**: Extracted action items enter a review state — approve or reject each one in the web UI
6. **Trello Cards**: Each approved action item becomes a card with:
   - Title from the action item
   - Description with context from the meeting
   - Assignee if mentioned
   - Link back to the meeting
7. **Retry Queue**: Failed operations are queued with exponential backoff

## Development

```bash
# Create and activate virtual environment (if not already done)
python3 -m venv venv
source venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run with verbose logging
granola-bridge -v run

# Run without activating venv (use full path)
./venv/bin/granola-bridge run
```

## Project Structure

```
granola-to-trello/
├── src/granola_bridge/
│   ├── main.py              # CLI entry point
│   ├── config.py            # Configuration loading
│   ├── core/
│   │   ├── daemon.py        # Background daemon orchestration
│   │   ├── watcher.py       # File system monitoring
│   │   ├── scheduler.py     # Retry queue processor
│   │   └── notifier.py      # Webhook notifications
│   ├── services/
│   │   ├── granola_parser.py    # Parse Granola cache file (auto-detects latest version)
│   │   ├── llm_client.py        # OpenAI-compatible API client
│   │   ├── trello_client.py     # Trello API wrapper
│   │   ├── action_extractor.py  # LLM prompt + response parsing
│   │   └── embedding_service.py # Ollama embedding + ChromaDB
│   ├── models/
│   │   ├── database.py          # SQLAlchemy setup
│   │   ├── meeting.py           # Meeting model
│   │   ├── action_item.py       # ActionItem model
│   │   ├── transcript_segment.py # Transcript segment model
│   │   └── retry_queue.py       # RetryQueue model
│   └── web/
│       ├── app.py           # FastAPI app
│       ├── routes/
│       │   ├── dashboard.py # Dashboard routes
│       │   ├── meetings.py  # Meeting + action item review routes
│       │   ├── search.py    # Semantic search routes
│       │   ├── upload.py    # Manual transcript upload
│       │   └── retry_queue.py # Retry queue routes
│       └── templates/       # Jinja2 + HTMX templates
├── scripts/
│   ├── GranolaBridge.app        # macOS app bundle
│   ├── start-granola-bridge.command  # Double-click launcher
│   ├── install.sh               # launchd service installation
│   └── uninstall.sh             # launchd service removal
├── launchd/                 # macOS service config
└── tests/
```

## Troubleshooting

### "granola-bridge: command not found"
- Activate the virtual environment first: `source venv/bin/activate`
- Or run directly: `./venv/bin/granola-bridge run`
- Don't use `python -m granola_bridge` - use the installed `granola-bridge` script

### "Cannot connect to LLM server"
- Ensure LMStudio is running and has a model loaded
- Check the server is listening on the configured port (default: 1234)
- Verify `llm.base_url` in config.yaml

### "Invalid Trello API credentials"
- Double-check your API key and token in `.env`
- Ensure the token hasn't expired
- Verify the list ID exists on your board

### "Granola cache not found"
- Ensure Granola is installed and has been run at least once
- Check the `granola.cache_path` in config.yaml matches your system

### No action items extracted
- Check the LLM is responding (test with `curl http://localhost:1234/v1/models`)
- Try a different/larger model for better extraction
- View the daemon logs for LLM response details

### Semantic search not working
- Ensure Ollama is running: `curl http://localhost:11434/api/tags`
- Verify the embedding model is pulled: `ollama pull nomic-embed-text`
- Check the `embedding` section in your config.yaml

### "Falling back to chunk-based extraction"
- This is expected behavior when Ollama is unavailable
- Action items will still be extracted using the standard chunk-based method
- Install and start Ollama to enable RAG-enhanced extraction

## License

MIT
