# HDD Folder Restructure Tool

A command-line tool that uses **Google Gemini 2.5 Pro** to analyze your directory structure and propose a cleaner, more organized folder hierarchy.

Now features **Event-Based Organization** to automatically group photos and videos into meaningful events (e.g., "2023 - Christmas", "2024 - Hawaii Trip").

## Features

## Key Features

- **AI-Powered Organization**: Uses LLMs (via Gemini) to understand your file structure and create personalized organization rules.
- **Enterprise-Grade Streaming**: Optimized for huge datasets (e.g., 2TB+, 1M+ files). Uses JSONL streaming to ensure constant, low memory usage (O(1)).
- **100% Coverage Guarantee**: Automatically generates "Catch-All" rules to ensure NO file is left behind.
- **Deterministic & Reproducible**: Uses deterministic sampling to ensure that running the tool twice on the same data yields the same result.
- **Safety First**:
    - **Dry Run**: Always previews changes before applying them.
    - **Undo Capability**: Automatically generates a streaming undo plan for every operation.
    - **Collision Handling**: Smartly handles duplicate filenames with O(1) resolution.
    - **Cross-Device Protection**: Prevents accidental moves across different drives.
- **Smart Metadata**: Extracts EXIF dates from photos to organize by "Date Taken".
- **Robust Execution**: Parallel processing for fast execution, with automatic path normalization for cross-platform compatibility.

## Installation

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/yourusername/drive-reorganization-tool.git
    cd drive-reorganization-tool
    ```

2.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

3.  **Set up API Key**:
    Export your Gemini API key:
    ```bash
    export GEMINI_API_KEY="your_api_key_here"
    ```

## Usage

### 1. Scan Your Drive
Scan the drive to build a metadata index. This is fast and memory-efficient.

```bash
python -m reorganize_hdd scan /path/to/your/drive -o metadata.jsonl
```

### 2. Plan Organization
Generate a reorganization plan based on the scan.

**Automatic Mode (AI)**:
Let the AI analyze your files and suggest a plan.
```bash
python -m reorganize_hdd plan metadata.jsonl --goal "Organize photos by year and documents by type" -o plan.jsonl
```

**Rules Mode (Manual)**:
Apply predefined rules for specific file types.
```bash
python -m reorganize_hdd plan metadata.jsonl --mode rules -o plan.jsonl
```

### 3. Apply Changes
Execute the plan. This will move files and clean up empty directories.

```bash
python -m reorganize_hdd apply plan.jsonl --root /path/to/your/drive
```

**Undo**:
If you made a mistake, simply apply the generated undo plan:
```bash
python -m reorganize_hdd apply undo_plan_YYYYMMDD_HHMMSS.jsonl --root /path/to/your/drive
```
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

### "Cleanup seems stuck"
On large external drives, the cleanup phase (removing empty directories) can take a few minutes due to I/O latency. This is normal. The tool is recursively checking every folder.

### "LLM returned invalid JSON"
The tool includes robust recovery logic for truncated JSON. If it still fails, try running again or reducing the batch size.

## License

MIT License - Use freely, modify as needed.
