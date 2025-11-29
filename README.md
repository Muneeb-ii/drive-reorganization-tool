# HDD Folder Restructure Tool

A command-line tool that uses **Google Gemini 2.5 Pro** to analyze your directory structure and propose a cleaner, more organized folder hierarchy.

Now features **Event-Based Organization** to automatically group photos and videos into meaningful events (e.g., "2023 - Christmas", "2024 - Hawaii Trip").

## Features

- **Event-Based Organization**: Automatically detects clusters of files by name or date and groups them into event folders.
- **Rule-Based Planning**: Scalable mode for large directories where the LLM designs rules instead of moving every file individually.
- **Smart Analysis**: Uses AI to understand file types, dates, and naming patterns.
- **Safe by Default**: 
  - **Dry-run** mode lets you preview all changes.
  - **Collision Detection** automatically renames duplicates (e.g., `file_1.txt`) to prevent data loss.
  - **Drive Safety** checks ensure external drives are connected before operations.
- **Full Transparency**: Generates JSON reports for metadata, plan, and execution.
- **Resumable**: Can skip the LLM call and reuse an existing plan.

## Installation

```bash
# Clone or download this repository
cd folder-restructure

# Install dependencies
pip install -r requirements.txt

# Set your Gemini API key (copy .env.example to .env)
cp .env.example .env
# Then edit .env and add your key:
# GEMINI_API_KEY=your-api-key-here
```

### Getting a Gemini API Key

1. Go to [Google AI Studio](https://aistudio.google.com/)
2. Sign in with your Google account
3. Click "Get API Key" → "Create API Key"
4. Copy the key and set it as an environment variable

## Usage

### 1. Event-Based Organization (Recommended)

Use the `rules` mode for the best results with large photo/video collections. This mode detects events and creates rules to organize them.

```bash
python -m reorganize_hdd run /path/to/your/directory --mode rules --dry-run
```

This will:
1. Scan the directory (with a progress bar).
2. Detect file clusters (events).
3. Ask Gemini to design organization rules based on these events.
4. Generate a plan to move files into `Year - Event Name/Type/` folders.
5. Simulate the moves and save a report.

### 2. Apply Changes

Once you are happy with the plan, run without `--dry-run`:

```bash
python -m reorganize_hdd run /path/to/your/directory --mode rules
```

**⚠️ Warning**: This will actually move files! Always run with `--dry-run` first.

### 3. Direct Mode (Small Directories)

For smaller directories (< 500 files), you can use the direct mode where the LLM decides the move for every single file:

```bash
python -m reorganize_hdd run /path/to/your/directory --mode direct --dry-run
```

### Custom Output Paths

```bash
python -m reorganize_hdd run /path/to/directory \
    --dry-run \
    --metadata-out ./output/metadata.json \
    --plan-out ./output/plan.json \
    --report-out ./output/report.json
```

## CLI Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `root` | Root directory to reorganize (required) | - |
| `--mode` | Planning mode: `rules` (recommended) or `direct` | `direct` |
| `--dry-run` | Simulate changes without modifying files | `False` |
| `--auto` | Automatic mode (skip confirmation prompts) | `False` |
| `--delay` | Delay between API calls (seconds) | `0` |
| `--allow-cross-device` | Allow moves across different drives | `False` |

## How It Works (Rules Mode)

```
┌─────────────────────────────────────────────────────────────────┐
│                      reorganize_hdd                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 1: Scan & Cluster                                         │
│  - Walk directory tree (Progress Bar)                           │
│  - Detect clusters by name (e.g. "Trip_001.jpg")                │
│  - Detect clusters by time (e.g. 50 files in 2 hours)           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 2: Generate Rules (LLM)                                   │
│  - Send summary & clusters to Gemini                            │
│  - Gemini returns rules (e.g. "Match *.jpg in Cluster 1")       │
│  - Output: plan.json (with rules)                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 3: Apply Rules                                            │
│  - Match files against rules locally                            │
│  - Resolve collisions (file.txt -> file_1.txt)                  │
│  - Generate move list                                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 4: Execute                                                │
│  - Validate moves (check drive connection)                      │
│  - Move files safely                                            │
└─────────────────────────────────────────────────────────────────┘
```

## Safety Features

1.  **Drive Connectivity Check**: Prevents crashes if the external drive disconnects.
2.  **Collision Handling**: Automatically renames files if multiple files map to the same destination.
3.  **Cross-Device Protection**: Prevents accidental moves between drives (unless `--allow-cross-device` is used).
4.  **Interactive Safety**: Detects non-interactive environments to prevent hanging.
5.  **JSON Recovery**: Robustly handles truncated responses from the LLM.

## Troubleshooting

### "Root directory not found. Is the drive connected?"
Ensure your external drive is mounted and accessible. The tool checks this to prevent errors.

### "Plan has destination collisions"
This should no longer happen! The tool now automatically resolves collisions by appending a counter (e.g., `_1`, `_2`) to the filename.

### "LLM returned invalid JSON"
The tool includes robust recovery logic for truncated JSON. If it still fails, try running again or reducing the batch size.

## License

MIT License - Use freely, modify as needed.
