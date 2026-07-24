# pm-chain — Graph Engine

DAG Pipeline + Gate engine for PM workflow orchestration.

9-stage product management pipeline with conflict detection & quality gates. Converts implicit PM experience into executable AI pipelines.

## Architecture

Market Research → Competitive Analysis → Brainstorming → PRD → GTM → Brand Strategy → Risk Assessment → Architecture → Prototype

Each stage: defined input/output + quality gate. Cross-stage conflict detection auto-flags when prior assumptions contradict later outputs.

## Key Features

- **10 quality gates** — tab count, file size, content depth at each stage
- **7 category templates** — consumer electronics, SaaS, AI-native, physical goods, marketplace, service, content
- **Pipeline conflict detection** — assumption vs output mismatch auto-flagged
- **30+ feedback rules** — continuous improvement loop

## Stack

Python · DAG · Claude Code Skill Framework

## Usage

```bash
# Generate graph JSONs for all categories
python main.py generate

# Run a single pipeline
python main.py run graphs/pm-chain-quick.json
```
