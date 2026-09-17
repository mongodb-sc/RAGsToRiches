# Ally Financial access to 54.147.137.184

Source: nginx `access.log` on the Atlas National Bank EC2 demo host  
Ally ARIN ranges: `198.74.80.0/20` (ALLY-FINANCIAL) and `74.114.112.0/22` (ALLY-INVEST)  
Log window scanned: 7–17 Sep 2026 (refreshed 17 Sep 2026)

## Summary

| Metric | Value |
|---|---|
| Requests from Ally space | **603** |
| Source IPs | **1** — `198.74.88.193` |
| Sessions (30-min gap) | **16** |
| Active days | **9–11 Sep and 16 Sep 2026** |
| ALLY-INVEST (`74.114.112.0/22`) hits | **0** |

Every Ally hit came from corporate NAT **`198.74.88.193`**. User-agents show **Mac Chrome 152** and **Windows Edge 151/152** — at least two people or two machines behind the same Ally firewall.

New activity since the prior report: a substantial **Windows Edge 152** return on **16 Sep** (181 requests), including a fresh open of `/`.

## Requests by day

| Day | Requests |
|---|---|
| 9 Sep | 305 |
| 10 Sep | 24 |
| 11 Sep | 93 |
| 16 Sep | 181 |

## Sessions (Eastern Time)

| When (ET) | Reqs | Client | What happened |
|---|---|---|---|
| 9 Sep 12:00–12:52 PM | 253 | Mac Chrome 152 | Opened `/` and loaded the Streamlit UI |
| 9 Sep 1:32–1:50 PM | 3 | Windows Edge 151 | health / host-config / stream |
| 9 Sep 2:37–2:58 PM | 41 | Windows Edge 151 | Widget JS + stream reconnect |
| 9 Sep 3:41–3:46 PM | 8 | Windows Edge 151 | stream + health |
| 10 Sep 9:48 AM | 2 | Mac Chrome 152 | health + host-config only |
| 10 Sep 2:41–3:15 PM | 18 | Mac Chrome 152 | 6 stream reconnects |
| 10 Sep 5:35–5:36 PM | 4 | Mac Chrome 152 | short reconnect |
| 11 Sep 11:21–11:56 AM | 22 | Windows Edge 152 | ImageList / widget JS; downloaded `/sources.zip` |
| 11 Sep 12:33–12:53 PM | 64 | Windows Edge 152 | Autocomplete / TextInput / JSON view |
| 11 Sep 1:25–1:59 PM | 7 | Windows Edge 152 | stream reconnects |
| **16 Sep 9:25–9:53 AM** | **157** | **Windows Edge 152** | **Returned; opened `/` and reloaded full UI** |
| 16 Sep 10:46 AM | 1 | Windows Edge 152 | stream reconnect |
| 16 Sep 1:06–1:10 PM | 16 | Windows Edge 152 | health/host-config; **10× 502** when Streamlit briefly unavailable |
| 16 Sep 1:46 PM | 3 | Windows Edge 152 | short reconnect |
| 16 Sep 2:27 PM | 3 | Windows Edge 152 | short reconnect |
| 16 Sep 3:43 PM | 1 | Windows Edge 152 | last Ally hit (stream) |

## Browsers

| User-agent | Requests |
|---|---|
| Windows Edge 152 | 274 |
| Windows Edge 151 | 167 |
| Mac Chrome 152 | 162 |

## App paths vs Streamlit chrome

| Path | Hits | Meaning |
|---|---|---|
| `/_stcore/host-config` | 34 | UI bootstrap |
| `/_stcore/health` | 34 | UI heartbeat |
| `/_stcore/stream` | 29 | Live Streamlit websocket (mostly status 101) |
| `/` | 3 | Opened the banking demo homepage (9 Sep ×2, 16 Sep ×1) |
| `/sources.zip` | 1 | Downloaded the source zip (11 Sep) |
| All other `/static` and `/lib` | ~499 | Streamlit JS/CSS/fonts after load |

## What they did not do

No `/docs`, `/health`, `/api/agent/run`, or exploit paths from Ally space. All Ally requests were GET. Outcomes: **564 × 200**, **29 × 101**, **10 × 502** (16 Sep 1:10 PM ET health/host-config only — backend blip, not a client error). First hit 9 Sep 12:00 PM ET; last hit 16 Sep 3:43 PM ET. No Ally traffic on 12–15 Sep or on 17 Sep through the scan time.

## Cursor canvas

The interactive version of this report lives at `docs/canvases/ally-financial-access.canvas.tsx`.
