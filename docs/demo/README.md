# Demo walkthrough media

Captured from the live Streamlit UI at [https://54.147.137.184.sslip.io/](https://54.147.137.184.sslip.io/).

## Video

- [walkthrough.mp4](walkthrough.mp4) — ~25s slideshow of the UI tour
- [walkthrough.webm](walkthrough.webm) — same tour, WebM

## Screenshots

| # | Screen | File |
|---|---|---|
| 1 | Help / overview | [01-help-overview.png](screenshots/01-help-overview.png) |
| 2 | Banking RAG Assistant | [02-rag-assistant.png](screenshots/02-rag-assistant.png) |
| 3 | RAG answer with citations | [03-rag-answer.png](screenshots/03-rag-answer.png) |
| 4 | Knowledge Graph | [04-knowledge-graph.png](screenshots/04-knowledge-graph.png) |
| 5 | Governance & Security | [05-governance.png](screenshots/05-governance.png) |
| 6 | Agent Memory & State | [06-agent-memory.png](screenshots/06-agent-memory.png) |
| 7 | Checkpoint Inspector | [07-checkpoints.png](screenshots/07-checkpoints.png) |
| 8 | Audit & Lineage | [08-audit-lineage.png](screenshots/08-audit-lineage.png) |
| 9 | Audit tree expanded | [09-audit-tree-expanded.png](screenshots/09-audit-tree-expanded.png) |

## Re-record

```bash
cd docs/demo
npm install
npx playwright install chromium   # if needed
DEMO_URL=https://54.147.137.184.sslip.io/ node record-walkthrough.js
# then rebuild video from screenshots with ffmpeg (see record-walkthrough.js notes)
```
