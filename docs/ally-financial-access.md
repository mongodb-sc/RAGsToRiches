# Ally Financial access to 54.147.137.184

Source: nginx `access.log` on the Atlas National Bank EC2 demo host  
Ally ARIN ranges: `198.74.80.0/20` (ALLY-FINANCIAL) and `74.114.112.0/22` (ALLY-INVEST)  
Log window scanned: 5–15 Sep 2026

## Summary

| Metric | Value |
|---|---|
| Requests from Ally space | **422** |
| Source IPs | **1** — `198.74.88.193` |
| Sessions (30-min gap) | **10** |
| Active days | **9–11 Sep 2026** |
| ALLY-INVEST (`74.114.112.0/22`) hits | **0** |

Every Ally hit came from corporate NAT **`198.74.88.193`**. User-agents show **Mac Chrome 152** and **Windows Edge 151/152** — at least two people or two machines behind the same Ally firewall.

## Requests by day

| Day | Requests |
|---|---|
| 9 Sep | 305 |
| 10 Sep | 24 |
| 11 Sep | 93 |

## Sessions (Eastern Time)

| When (ET) | Reqs | Client | What happened |
|---|---|---|---|
| 9 Sep 12:00–12:52 PM | 253 | Mac Chrome 152 | Opened `/` and loaded the Streamlit UI |
| 9 Sep 1:32–1:50 PM | 3 | Streamlit keepalive | health / host-config / stream |
| 9 Sep 2:37–2:58 PM | 41 | UI assets | Widget JS + stream reconnect |
| 9 Sep 3:41–3:46 PM | 8 | Streamlit keepalive | stream + health |
| 10 Sep 9:48 AM | 2 | Streamlit keepalive | health + host-config only |
| 10 Sep 2:41–3:15 PM | 18 | Streamlit keepalive | 6 stream reconnects |
| 10 Sep 5:35–5:36 PM | 4 | Streamlit keepalive | short reconnect |
| 11 Sep 11:21–11:56 AM | 22 | UI assets | ImageList / widget JS |
| 11 Sep 12:33–12:53 PM | 64 | Windows Edge 152 | Autocomplete / TextInput / JSON view |
| 11 Sep 1:25–1:59 PM | 7 | Windows Edge 152 | stream reconnects; last hit 1:59 PM ET |

## Browsers

| User-agent | Requests |
|---|---|
| Windows Edge 151 | 167 |
| Mac Chrome 152 | 162 |
| Windows Edge 152 | 93 |

## App paths vs Streamlit chrome

| Path | Hits | Meaning |
|---|---|---|
| `/_stcore/stream` | 22 | Live Streamlit websocket (status 101) |
| `/_stcore/health` | 22 | UI heartbeat |
| `/_stcore/host-config` | 22 | UI bootstrap |
| `/` | 2 | Opened the banking demo homepage |
| `/sources.zip` | 1 | Downloaded the source zip |
| All other `/static` and `/lib` | 353 | Streamlit JS/CSS/fonts after load |

## What they did not do

No `/docs`, `/health`, `/api/agent/run`, or exploit paths from Ally space. Every request was GET and succeeded (**400 × 200**, **22 × 101**). First hit 9 Sep 12:00 PM ET; last hit 11 Sep 1:59 PM ET.

## Cursor canvas

The interactive version of this report lives at `docs/canvases/ally-financial-access.canvas.tsx`.
