"""MongoDB-branded Streamlit dashboard for the retail-banking RAG demo.

Cursor session prompts that produced this app (full text is in the docs canvas):
1. Create a complete Python FastAPI + Streamlit application that demonstrates
   MongoDB Atlas as a RAG and Data Platform for retail banking.
2. add screenpipe mcp server so you can do screen recordings
3. document source code with mongodb doc links, use cases, requirements,
   and walk through of each use case. Use screenpipe to record performing
   each use case in the broswer app.
4. add the cursor prompts to the documentation.
"""

from __future__ import annotations

import json
import sys
from html import escape as html_escape
from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.agent_memory import fetch_session_turns, retrieve_long_term_memory
from app.services.agent_workflow import (
    list_checkpoint_history,
    rewind_to_checkpoint,
    run_agent,
)
from app.services.audit_lineage import get_lineage, list_audit_logs, list_recent_executions
from app.services.database import ping_atlas
from app.services.graph_service import (
    get_customer_graph,
    list_customers,
    render_pyvis_html,
)
from app.services.security import (
    ROLE_LABELS,
    filter_context_by_role,
    role_policy_summary,
)
from app.services.vector_search import rag_chat

ASSETS = Path(__file__).resolve().parent / "assets"
LOGO_WHITE = ASSETS / "mongodb-logo-white.svg"
LOGO_COLOR = ASSETS / "mongodb-logo.svg"
LEAF = ASSETS / "mongodb-leaf.svg"

APP_TABS: tuple[tuple[str, str], ...] = (
    ("help", "Use cases & Help"),
    ("rag", "Banking RAG Assistant"),
    ("graph", "Knowledge Graph"),
    ("gov", "Governance & Security"),
    ("memory", "Agent Memory & State"),
    ("ckpt", "Checkpoint Inspector"),
    ("audit", "Audit & Lineage"),
)
APP_TAB_LABELS = dict(APP_TABS)
FEATURED_RAG_QUESTION = (
    "What are the overdraft fees and daily transfer limits for checking accounts?"
)

DEMO_PATHS: dict[str, tuple[str, list[str]]] = {
    "help": (
        "Overview",
        [
            "Click a use-case card to open that demo.",
            "Do RAG, Graph, then Governance in order.",
            "Run the agent, then open Checkpoints and Audit.",
        ],
    ),
    "rag": (
        "1. Banking RAG",
        [
            "Stay on **Tier 1 Agent**.",
            "Keep product **all** and search mode **hybrid**.",
            "Click **What is the outgoing domestic wire fee?** — expect **$25**.",
            "Switch to **Compliance Manager**.",
            "Click **What CIP data is required to open an account?**",
        ],
    ),
    "graph": (
        "2. Knowledge Graph",
        [
            "Keep **CUST-0001** and depth **3**.",
            "Click **Run $graphLookup**.",
            "Hover nodes, then expand JSON and the pipeline.",
            "Toggle persona: Tier 1 redacts SSN and balances.",
        ],
    ),
    "gov": (
        "3. Governance",
        [
            "Use **Compare roles** on this page.",
            "Tier 1: 1 of 4 chunks; fees stay, PII is gone.",
            "Compliance: 4 of 4, including SSN and balance.",
            "Read **Live filtered context** after each toggle.",
        ],
    ),
    "memory": (
        "4. Agent Memory",
        [
            "Keep **CUST-0001** and the default thread id.",
            "As Tier 1, click **Does this customer prefer email or SMS alerts?**",
            "Confirm the public email-alert memory on the right.",
            "Switch to Compliance and ask about lending.",
            "The August 2026 auto-loan memory should appear.",
        ],
    ),
    "ckpt": (
        "5. Checkpoints",
        [
            "Run an agent question on **Agent Memory** first.",
            "Confirm four steps in the table.",
            "Select an earlier checkpoint.",
            "Click a **checkpoint_id** to rewind to that snapshot.",
        ],
    ),
    "audit": (
        "6. Audit & Lineage",
        [
            "Run the agent at least once.",
            "Pick an execution in recent runs.",
            "Expand Audit trail for each LangGraph node.",
            "Expand Vector provenance for chunk id, source, and score.",
        ],
    ),
}

SAMPLE_CHUNKS = [
    {
        "doc_id": "POL-008",
        "title": "Personal Checking Fee Schedule",
        "source": "knowledge_base",
        "clearance_level": "public",
        "product_type": "checking",
        "document_type": "fee_schedule",
        "score": 0.91,
        "content": (
            "Outgoing domestic wires are $25. Incoming domestic wires are $15. "
            "Monthly maintenance is $12 and is waived with a $1,500 average collected balance."
        ),
        "metadata": {"product_type": "checking"},
    },
    {
        "doc_id": "POL-016",
        "title": "Customer Identification Program and BSA/AML Procedures",
        "source": "knowledge_base",
        "clearance_level": "restricted",
        "product_type": "checking",
        "document_type": "wire_rules",
        "score": 0.84,
        "content": (
            "CIP requires name, date of birth, street address, and SSN. "
            "Structured cash deposits designed to avoid a Currency Transaction Report "
            "must be escalated for Suspicious Activity Report consideration."
        ),
        "metadata": {"clearance_level": "restricted"},
    },
    {
        "doc_id": "TR-001",
        "title": "Service transcript for Avery Chen",
        "source": "transcript",
        "clearance_level": "restricted",
        "product_type": "checking",
        "document_type": "customer_transcript",
        "score": 0.79,
        "content": (
            "Agent verified SSN 219-09-9999 for customer CUST-0001. "
            "Caller requested a balance on ACCT-0001. Posted balance is $18,440.22. "
            "Date of birth on file is 1984-03-12."
        ),
        "metadata": {
            "ssn": "219-09-9999",
            "balance": 18440.22,
            "account_number": "441229183",
            "date_of_birth": "1984-03-12",
            "customer_id": "CUST-0001",
        },
    },
    {
        "doc_id": "ACCT-META-0001",
        "title": "Private account metadata",
        "source": "account_metadata",
        "clearance_level": "restricted",
        "product_type": "checking",
        "document_type": "account_metadata",
        "score": 0.73,
        "content": (
            "Joint checking ACCT-0001 for household HH-01. Exact available balance "
            "$18,440.22. Routing 021000021. Account number 441229183."
        ),
        "metadata": {
            "balance": 18440.22,
            "account_number": "441229183",
            "routing_number": "021000021",
        },
    },
]


def _inject_brand() -> None:
    """Apply a single high-contrast MongoDB dark theme to every Streamlit surface.

    The official dark theme in ``.streamlit/config.toml`` sets widget colors.
    These rules keep markdown, chat, JSON, code, and custom HTML on the same
    navy / mist / leaf palette so body copy never renders black-on-black.
    """

    st.markdown(
        """
        <style>
          @import url('https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;600;700&display=swap');

          :root {
            --mdb-green: #00ED64;
            --mdb-forest: #00684A;
            --mdb-navy: #001E2B;
            --mdb-slate: #21313C;
            --mdb-panel: #1A2B35;
            --mdb-mist: #F9FBFA;
            --mdb-muted: #C1C7C6;
            --mdb-line: #5C6C75;
          }

          html, body, [class*="css"], .stApp, .stMarkdown, p, span, li, label {
            font-family: "Source Sans 3", "Helvetica Neue", Helvetica, Arial, sans-serif;
          }

          html, body, .stApp {
            height: 100%;
            overflow: hidden;
          }

          .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"],
          section.main, [data-testid="stMainBlockContainer"] {
            background-color: #001E2B !important;
            color: #F9FBFA !important;
          }

          header[data-testid="stHeader"],
          [data-testid="stToolbar"],
          [data-testid="stDecoration"] {
            display: none !important;
            height: 0 !important;
            min-height: 0 !important;
          }
          [data-testid="stAppViewContainer"] {
            padding-top: 0 !important;
            height: 100vh !important;
            overflow: hidden !important;
          }
          [data-testid="stMain"],
          section.main {
            overflow-y: auto !important;
            overflow-x: hidden !important;
            height: 100% !important;
            padding-top: 0.5rem !important;
          }
          [data-testid="stBottom"] {
            position: sticky;
            bottom: 0;
            background: #001E2B !important;
            z-index: 20;
          }
          [data-testid="stSidebar"] {
            background: #001E2B !important;
            border-right: 1px solid #5C6C75;
          }
          [data-testid="stSidebar"] [data-testid="stMarkdownContainer"],
          [data-testid="stSidebar"] [data-testid="stWidgetLabel"],
          [data-testid="stSidebar"] p,
          [data-testid="stSidebar"] label,
          [data-testid="stSidebar"] span {
            color: #F9FBFA !important;
          }
          [data-testid="stSidebar"] a {
            color: #00ED64 !important;
          }

          .block-container {
            padding-top: 2.75rem !important;
            padding-bottom: 10rem !important;
            color: #F9FBFA !important;
          }

          h1, h2, h3, h4, h5, h6,
          [data-testid="stHeading"] *,
          [data-testid="stMarkdownContainer"],
          [data-testid="stMarkdownContainer"] p,
          [data-testid="stMarkdownContainer"] li,
          [data-testid="stMarkdownContainer"] span,
          [data-testid="stCaption"],
          [data-testid="stWidgetLabel"],
          [data-testid="stWidgetLabel"] p,
          label, .stCaption, .stMarkdown {
            color: #F9FBFA !important;
          }

          [data-testid="stCaption"] {
            color: #C1C7C6 !important;
            font-size: 1.1rem !important;
            line-height: 1.5 !important;
          }

          [data-testid="stMain"] [data-testid="stMarkdownContainer"] p,
          [data-testid="stMain"] [data-testid="stMarkdownContainer"] li {
            font-size: 1.28rem !important;
            line-height: 1.55 !important;
          }
          [data-testid="stMain"] [data-testid="stHeading"] h2 {
            font-size: 1.85rem !important;
          }
          [data-testid="stMain"] [data-testid="stHeading"] h3 {
            font-size: 1.5rem !important;
          }

          .hero {
            display: flex;
            align-items: center;
            gap: 18px;
            padding: 18px 22px;
            border: 1px solid #5C6C75;
            border-radius: 12px;
            background: #21313C;
            margin-bottom: 16px;
          }
          .hero h1 {
            margin: 0;
            color: #F9FBFA !important;
            font-size: 1.7rem;
            letter-spacing: -0.02em;
          }
          .hero p { margin: 4px 0 0 0; color: #C1C7C6 !important; }

          .pill {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 999px;
            background: #00684A;
            color: #F9FBFA !important;
            font-size: 0.75rem;
            font-weight: 700;
            letter-spacing: 0.04em;
            text-transform: uppercase;
          }

          .citation {
            border-left: 4px solid #00ED64;
            background: #21313C;
            color: #F9FBFA !important;
            padding: 14px 16px;
            border-radius: 0 10px 10px 0;
            margin-bottom: 8px;
            font-size: 1.22rem !important;
            line-height: 1.5 !important;
          }
          .citation strong { color: #F9FBFA !important; font-size: 1.28rem !important; }

          .stTabs [data-baseweb="tab-list"] { gap: 8px; background: transparent; }
          .stTabs [data-baseweb="tab"] {
            background: #21313C;
            color: #F9FBFA !important;
            border-radius: 10px 10px 0 0;
            padding: 10px 16px;
          }
          .stTabs [aria-selected="true"] {
            background: #00684A !important;
            color: #F9FBFA !important;
          }

          [data-testid="stSegmentedControl"] button,
          div[data-testid="stButtonGroup"] button {
            background: #21313C !important;
            color: #F9FBFA !important;
            border: 1px solid #5C6C75 !important;
          }
          [data-testid="stSegmentedControl"] button[aria-checked="true"],
          div[data-testid="stButtonGroup"] button[aria-checked="true"] {
            background: #00684A !important;
            color: #F9FBFA !important;
            border-color: #00ED64 !important;
          }

          .stButton > button[kind="primary"] {
            background: #00ED64 !important;
            color: #001E2B !important;
            border: 0 !important;
            font-weight: 700 !important;
          }
          .stButton > button[kind="primary"]:hover {
            background: #B1FFC6 !important;
            color: #001E2B !important;
          }
          .stButton > button[kind="primary"] p,
          .stButton > button[kind="primary"] span {
            color: #001E2B !important;
          }
          .stButton > button[kind="secondary"] {
            background: #21313C !important;
            color: #F9FBFA !important;
            border: 1px solid #5C6C75 !important;
            font-weight: 600 !important;
          }
          .stButton > button[kind="secondary"]:hover {
            background: #00684A !important;
            color: #F9FBFA !important;
            border-color: #00ED64 !important;
          }
          .stButton > button[kind="secondary"] p,
          .stButton > button[kind="secondary"] span {
            color: #F9FBFA !important;
          }

          [data-testid="stChatMessage"] {
            background: #21313C !important;
            color: #F9FBFA !important;
            border: 1px solid #5C6C75;
            border-radius: 12px;
          }
          [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"],
          [data-testid="stChatMessage"] p,
          [data-testid="stChatMessage"] li,
          [data-testid="stChatMessage"] span {
            color: #F9FBFA !important;
            font-size: 1.32rem !important;
            line-height: 1.55 !important;
          }
          .featured-question {
            font-weight: 700 !important;
            font-size: 1.5rem !important;
            line-height: 1.4 !important;
            color: #F9FBFA !important;
            margin: 0 !important;
          }
          .st-key-example-overdraft-fees button {
            font-weight: 700 !important;
            font-size: 1.35rem !important;
            line-height: 1.4 !important;
            white-space: normal !important;
            min-height: 3.4rem;
            padding: 0.7rem 1rem !important;
          }
          .st-key-example-overdraft-fees button p,
          .st-key-example-overdraft-fees button span {
            font-weight: 700 !important;
            font-size: 1.35rem !important;
            white-space: normal !important;
            line-height: 1.4 !important;
          }

          [data-testid="stChatInput"] textarea,
          [data-testid="stChatInput"] input {
            color: #F9FBFA !important;
            background: #21313C !important;
          }

          input, textarea, select,
          [data-baseweb="select"] > div,
          [data-baseweb="input"] {
            color: #F9FBFA !important;
            background-color: #21313C !important;
            caret-color: #F9FBFA;
          }
          div[data-baseweb="popover"],
          ul[role="listbox"],
          li[role="option"] {
            background-color: #21313C !important;
            color: #F9FBFA !important;
          }

          [data-testid="stExpander"] {
            background: #21313C !important;
            border: 1px solid #5C6C75 !important;
          }
          [data-testid="stExpander"] summary,
          [data-testid="stExpander"] p,
          [data-testid="stExpander"] span {
            color: #F9FBFA !important;
            font-size: 1.18rem !important;
            line-height: 1.5 !important;
          }

          [data-testid="stCode"], pre, code,
          [data-testid="stCode"] * {
            background-color: #011627 !important;
            color: #F9FBFA !important;
            font-size: 1.12rem !important;
            line-height: 1.5 !important;
          }

          [data-testid="stJson"], [data-testid="stJson"] * {
            color: #F9FBFA !important;
            background-color: #011627 !important;
            font-size: 1.15rem !important;
            line-height: 1.5 !important;
          }

          [data-testid="stMetricValue"] {
            color: #00ED64 !important;
            font-size: 2.5rem !important;
          }
          [data-testid="stMetricLabel"], [data-testid="stMetricLabel"] * {
            color: #C1C7C6 !important;
            font-size: 1.15rem !important;
          }

          [data-testid="stAlert"] {
            background-color: #21313C !important;
            border: 1px solid #5C6C75 !important;
          }
          [data-testid="stAlert"] p, [data-testid="stAlert"] span {
            color: #F9FBFA !important;
            font-size: 1.22rem !important;
            line-height: 1.5 !important;
          }

          .response-table-wrap {
            overflow-x: auto;
            margin: 0.4rem 0 1.2rem;
          }
          table.response-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 1.18rem;
            line-height: 1.45;
          }
          table.response-table th,
          table.response-table td {
            border: 1px solid #5C6C75;
            padding: 10px 12px;
            text-align: left;
            vertical-align: top;
            color: #F9FBFA !important;
            word-break: break-word;
          }
          table.response-table th {
            background: #21313C;
            font-weight: 700;
            font-size: 1.12rem;
          }
          table.response-table td { background: #001E2B; }
          table.response-table tr:nth-child(even) td { background: #1A2B35; }

          [class*="st-key-ckpt-sel-"] button,
          [class*="st-key-exec-sel-"] button {
            font-size: 1.05rem !important;
            font-weight: 700 !important;
            white-space: normal !important;
            line-height: 1.3 !important;
            min-height: 2.6rem;
            word-break: break-all;
          }

          .guide {
            background: #21313C;
            border: 1px solid #5C6C75;
            border-left: 4px solid #00ED64;
            border-radius: 10px;
            padding: 16px 20px;
            margin: 0 0 18px 0;
            color: #F9FBFA;
          }
          .guide-kicker {
            color: #00ED64;
            font-size: 0.75rem;
            font-weight: 700;
            letter-spacing: 0.06em;
            text-transform: uppercase;
            margin-bottom: 6px;
          }
          .guide h3 {
            margin: 0 0 8px 0;
            color: #F9FBFA !important;
            font-size: 1.4rem;
          }
          .guide p, .guide li {
            color: #F9FBFA !important;
            font-size: 1.18rem;
            line-height: 1.5;
          }
          .guide ol { margin: 8px 0 10px 1.2rem; padding: 0; }
          .guide li { margin: 4px 0; }
          .guide .expect {
            margin-top: 10px;
            padding: 10px 12px;
            background: #001E2B;
            border-radius: 8px;
            color: #C1C7C6 !important;
          }
          .guide a { color: #00ED64 !important; }
          a.usecase-card,
          .usecase-card {
            display: block;
            background: #21313C;
            border: 1px solid #5C6C75;
            border-radius: 10px;
            padding: 16px 18px;
            height: 100%;
            color: #F9FBFA !important;
            text-decoration: none !important;
            cursor: pointer;
            box-sizing: border-box;
            transition: border-color 0.15s ease, background 0.15s ease;
          }
          a.usecase-card:hover {
            background: #00684A;
            border-color: #00ED64;
          }
          .usecase-card h3 { color: #F9FBFA !important; margin-top: 0; }
          .usecase-card p, .usecase-card li { color: #F9FBFA !important; }

          button[kind="tertiary"] {
            white-space: pre-wrap !important;
            text-align: left !important;
            height: auto !important;
            min-height: 14.5rem;
            padding: 22px 24px !important;
            background: #21313C !important;
            color: #F9FBFA !important;
            border: 1px solid #5C6C75 !important;
            border-radius: 10px !important;
            font-weight: 400 !important;
            font-size: 1.28rem !important;
            line-height: 1.5 !important;
            width: 100%;
            align-items: flex-start !important;
          }
          button[kind="tertiary"] p,
          button[kind="tertiary"] span {
            color: #F9FBFA !important;
            font-weight: 400 !important;
            font-size: 1.28rem !important;
            line-height: 1.5 !important;
            white-space: pre-wrap !important;
          }
          button[kind="tertiary"] p::first-line,
          button[kind="tertiary"] span::first-line {
            font-size: 1.7rem;
            font-weight: 700;
          }
          button[kind="tertiary"]:hover {
            background: #00684A !important;
            border-color: #00ED64 !important;
            color: #F9FBFA !important;
          }

          a.sources-zip {
            position: fixed;
            top: 1rem;
            right: 1.25rem;
            z-index: 1000;
            width: 44px;
            height: 44px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: #21313C;
            border: 1px solid #5C6C75;
            border-radius: 10px;
            box-shadow: 0 6px 18px rgba(0, 0, 0, 0.35);
          }
          a.sources-zip:hover {
            background: #00684A;
            border-color: #00ED64;
          }
          a.sources-zip svg { display: block; }
        </style>
        <a class="sources-zip" href="/sources.zip" download="sources.zip"
           title="Download sources.zip" aria-label="Download sources.zip">
          <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22"
               viewBox="0 0 24 24" fill="none" stroke="#00ED64"
               stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
               aria-hidden="true">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="7 10 12 15 17 10"/>
            <line x1="12" y1="15" x2="12" y2="3"/>
          </svg>
        </a>
        """,
        unsafe_allow_html=True,
    )


def _header() -> None:
    logo_col, copy_col = st.columns([1, 4], vertical_alignment="center")
    with logo_col:
        if LOGO_WHITE.exists():
            st.image(str(LOGO_WHITE), width=220)
        elif LEAF.exists():
            st.image(str(LEAF), width=72)
    with copy_col:
        st.markdown(
            """
            <div class="hero">
              <div>
                <div class="pill">Atlas · RAG · Vector Search · $graphLookup</div>
                <h1>Retail Banking Data Platform</h1>
                <p>MongoDB Atlas as the retrieval, graph, and governance layer for Atlas National Bank.</p>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _set_nav_tab(tab_key: str) -> None:
    """Remember the selected use case before the next rerun renders the sidebar."""

    st.session_state.nav_tab = tab_key


def _sidebar() -> str:
    sidebar_logo = LOGO_WHITE if LOGO_WHITE.exists() else LOGO_COLOR
    if sidebar_logo.exists():
        st.sidebar.image(str(sidebar_logo), width="stretch")
    elif LEAF.exists():
        st.sidebar.image(str(LEAF), width=72)

    st.sidebar.markdown("### Atlas controls")
    role_label = st.sidebar.radio(
        "Active persona",
        options=list(ROLE_LABELS.values()),
        index=0,
        help="Tier 1 sees public knowledge only. Compliance sees transcripts and private metadata.",
    )
    role = next(key for key, label in ROLE_LABELS.items() if label == role_label)
    policy = role_policy_summary(role)
    st.sidebar.markdown(
        f"**Clearance:** {', '.join(policy['allowed_clearance'])}<br>"
        f"**Sources:** {', '.join(policy['allowed_sources'])}<br>"
        f"**PII redaction:** {'on' if policy['redacts_pii'] else 'off'}",
        unsafe_allow_html=True,
    )

    health = ping_atlas()
    if health.get("ok"):
        st.sidebar.success(f"Connected to `{health['database']}`")
    else:
        st.sidebar.error(f"Atlas unreachable: {health.get('error')}")

    use_case = st.session_state.get("nav_tab") or "help"
    path_title, path_steps = DEMO_PATHS.get(use_case, DEMO_PATHS["help"])
    st.sidebar.markdown(f"### Demo path · {path_title}")
    st.sidebar.markdown(
        "<br>".join(f"{index}. {step}" for index, step in enumerate(path_steps, start=1)),
        unsafe_allow_html=True,
    )
    st.sidebar.markdown(
        "[Atlas Architecture Center](https://www.mongodb.com/docs/atlas/architecture/current/) "
        "— Well-Architected Framework guidance for governance, security, "
        "reliability, performance, and cost."
    )
    return role


def _guide(kicker: str, title: str, steps: list[str], expect: str, docs_html: str) -> None:
    """Render an always-visible walkthrough panel above a use-case tab."""

    items = "".join(f"<li>{step}</li>" for step in steps)
    st.markdown(
        f"""
        <div class="guide">
          <div class="guide-kicker">{kicker}</div>
          <h3>{title}</h3>
          <ol>{items}</ol>
          <div class="expect"><strong>You should see:</strong> {expect}</div>
          <p style="margin:10px 0 0 0;">{docs_html}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _section_with_help(title: str, help_text: str) -> None:
    """Render a section title with the same ? tooltip used on sliders and selectboxes."""

    st.subheader(title, help=help_text)


def _response_table(rows: list[dict]) -> None:
    """Render result rows as HTML so table text can be enlarged with CSS."""

    if not rows:
        return
    keys: list[str] = []
    for row in rows:
        for key in row:
            label = str(key)
            if label not in keys:
                keys.append(label)
    head = "".join(f"<th>{html_escape(key)}</th>" for key in keys)
    body_rows = []
    for row in rows:
        cells = []
        for key in keys:
            value = row.get(key)
            cells.append(f"<td>{html_escape('' if value is None else str(value))}</td>")
        body_rows.append(f"<tr>{''.join(cells)}</tr>")
    st.markdown(
        '<div class="response-table-wrap"><table class="response-table">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody>"
        "</table></div>",
        unsafe_allow_html=True,
    )


def _help_tab() -> None:
    st.subheader("Use cases & Help")
    st.caption(
        "Six Atlas National Bank demos. Do the first three in order, then run the "
        "stateful agent. The sidebar persona changes what RAG, the graph, and "
        "long-term memory are allowed to show."
    )
    st.markdown(
        "[Download sources.zip](/sources.zip) — FastAPI, Streamlit, seed script, "
        "and the use-case docs canvas. Secrets (`.env`) are omitted."
    )
    st.caption("Click a card to open that use case.")
    summaries = [
        (
            "rag",
            "1. Banking RAG",
            "Ask a policy question. Atlas Vector Search (and hybrid $rankFusion) "
            "retrieves passages; the model answers with citations and vector scores.",
        ),
        (
            "graph",
            "2. Knowledge Graph",
            "Pick a customer and run $graphLookup. Household members, joint "
            "accounts, and recent joint transactions expand in one aggregation.",
        ),
        (
            "gov",
            "3. Governance",
            "Same retrieved chunks, two roles. Tier 1 keeps public KB and redacts "
            "PII. Compliance sees restricted transcripts and balances.",
        ),
        (
            "memory",
            "4. Agent Memory",
            "A LangGraph run recalls short-term thread turns and long-term "
            "user_memory facts via Atlas Vector Search before answering.",
        ),
        (
            "ckpt",
            "5. Checkpoints",
            "Every graph node is persisted in checkpoints. Inspect step "
            "latency and rewind to an earlier workflow snapshot.",
        ),
        (
            "audit",
            "6. Audit & Lineage",
            "ai_audit_logs records each tool call. Provenance maps the "
            "final answer back to chunk id, source doc, and vector score.",
        ),
    ]
    for row_start in range(0, len(summaries), 3):
        cards = st.columns(3)
        for column, (tab_key, title, body) in zip(
            cards, summaries[row_start : row_start + 3], strict=True
        ):
            with column:
                st.button(
                    f"{title}\n\n{body}",
                    key=f"usecase-card-{tab_key}",
                    type="tertiary",
                    use_container_width=True,
                    on_click=_set_nav_tab,
                    args=(tab_key,),
                )

    st.markdown("### Recommended path")
    st.markdown(
        """
1. Stay on **Tier 1 Agent** in the sidebar.
2. Open **Banking RAG Assistant** and click **What is the outgoing domestic wire fee?**
3. Confirm the answer is **$25** and citation **[1] Personal Checking Fee Schedule**.
4. Switch the sidebar to **Compliance Manager** and click **What CIP data is required to open an account?**
5. Restricted CIP policy and customer transcripts should now appear.
6. Open **Knowledge Graph**, keep **CUST-0001**, depth **3**, click **Run $graphLookup**.
7. Hover nodes: Compliance shows SSN/balances; switch back to Tier 1 to see redaction.
8. Open **Governance & Security** and toggle the on-page role radio to compare the same four chunks live.
9. Open **Agent Memory & State**, keep **CUST-0001**, click **Does this customer prefer email or SMS alerts?**
10. Open **Checkpoint Inspector** and rewind to an earlier node snapshot.
11. Open **Audit & Lineage** and expand the execution tree: audit trail, then chunk scores.
        """
    )

    st.markdown("### What each control means")
    st.markdown(
        """
- **Active persona (sidebar)** — applied to RAG retrieval filters and graph metadata.
- **Product pre-filter** — Atlas `$vectorSearch.filter` on `product_type`.
- **Search mode** — `hybrid` uses `$rankFusion` (vector + lexical); `vector` is `$vectorSearch` only.
- **Top K** — number of passages sent to the LLM.
- **Traversal depth** — `$graphLookup.maxDepth` from the customer node.
        """
    )

    st.markdown("### MongoDB docs")
    st.markdown(
        """
- [$vectorSearch](https://www.mongodb.com/docs/atlas/atlas-vector-search/vector-search-stage/)
- [Pre-filters](https://www.mongodb.com/docs/atlas/atlas-vector-search/vector-search-stage/#std-label-avs-filter)
- [$rankFusion](https://www.mongodb.com/docs/manual/reference/operator/aggregation/rankFusion/)
- [$graphLookup](https://www.mongodb.com/docs/manual/reference/operator/aggregation/graphLookup/)
- [Queryable Encryption](https://www.mongodb.com/docs/manual/core/queryable-encryption/) (production PII)
        """
    )


def _rag_tab(user_role: str) -> None:
    st.subheader("Banking RAG Assistant")
    _guide(
        "Use case 1 · walkthrough",
        "Ask Atlas for a grounded fee or policy answer",
        [
            "Leave the sidebar on <strong>Tier 1 Agent</strong> for the first question.",
            "Keep product filter on <strong>all</strong> and search mode on <strong>hybrid</strong>.",
            "Click <strong>What is the outgoing domestic wire fee?</strong>",
            "Read the cited answer, then switch the sidebar to <strong>Compliance Manager</strong>.",
            "Click <strong>What CIP data is required to open an account?</strong> to pull restricted documents.",
        ],
        "Tier 1 should answer <strong>$25</strong> from the public fee schedule. "
        "Compliance should also retrieve the restricted CIP policy and transcripts.",
        'Docs: <a href="https://www.mongodb.com/docs/atlas/atlas-vector-search/vector-search-stage/" target="_blank">$vectorSearch</a> · '
        '<a href="https://www.mongodb.com/docs/manual/reference/operator/aggregation/rankFusion/" target="_blank">$rankFusion</a>',
    )
    st.caption(
        "Questions are embedded with OpenAI `text-embedding-3-small`, retrieved from "
        "Atlas Vector Search (and hybrid lexical search), then grounded in a cited answer."
    )

    col_a, col_b, col_c = st.columns([2, 1, 1])
    with col_a:
        product_type = st.selectbox(
            "Product pre-filter",
            options=["all", "checking", "savings", "money_market", "cd", "brokerage"],
        )
    with col_b:
        search_mode = st.selectbox(
            "Search mode",
            options=["hybrid", "vector"],
            help=(
                "Vector search finds passages that mean the same thing as the "
                "question. Hybrid does that and matches the actual words, then "
                "merges the two ranked lists.\n\n"
                "Vector uses Atlas $vectorSearch only. The question is embedded "
                "with text-embedding-3-small and compared to knowledge_base.embedding "
                "on kb_vector_index (cosine). Role and product filters run inside "
                "the ANN candidate set. Best for paraphrase and intent "
                "(e.g. “What do we charge to send a domestic wire?” still hits "
                "the fee schedule). Weaker on exact tokens: fee amounts, form "
                "names, or wording that must appear verbatim.\n\n"
                "Hybrid runs $vectorSearch plus Atlas Search ($search) on "
                "kb_text_index over title and content, then fuses the rankings "
                "with $rankFusion (RRF). This demo weights vector 0.65 and text "
                "0.35. If $rankFusion is unavailable, the app fuses the lists in "
                "Python. A passage that is only somewhat similar in meaning but "
                "contains “outgoing domestic wire” and “$25” can still rank near "
                "the top.\n\n"
                "Use hybrid (default) for the wire-fee walkthrough so the $25 "
                "sentence is more likely in the top K. Use vector to show a pure "
                "ANN retrieve with no lexical assist."
            ),
        )
    with col_c:
        limit = st.slider(
            "Top K",
            min_value=3,
            max_value=10,
            value=5,
            help=(
                "How many knowledge-base passages Atlas returns and the LLM "
                "reads before answering. Each cited chunk in the response comes "
                "from this set.\n\n"
                "Vector mode sets $vectorSearch.limit to this value. Hybrid "
                "mode retrieves a slightly larger candidate pool from each "
                "pipeline, then keeps only the top K after $rankFusion.\n\n"
                "A higher K can surface a fee or policy sentence that ranked "
                "just outside the first few hits, but it also sends more tokens "
                "to the model and can dilute a tight answer. Default 5 is "
                "enough for the wire-fee walkthrough. Raise it if citations "
                "look thin; lower it to show a more conservative retrieve."
            ),
        )

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    for turn in st.session_state.chat_history:
        with st.chat_message(turn["role"]):
            _render_chat_text(turn["content"])
            if turn.get("citations"):
                _render_citations(turn["citations"])

    if st.button(
        FEATURED_RAG_QUESTION,
        key="example-overdraft-fees",
        use_container_width=True,
    ):
        chosen_example = FEATURED_RAG_QUESTION
    else:
        chosen_example = None
    examples = [
        "What is the outgoing domestic wire fee?",
        "When are check deposits available under Regulation CC?",
        "Can either joint owner close a checking account?",
        "What CIP data is required to open an account?",
    ]
    example_cols = st.columns(len(examples))
    for column, example in zip(example_cols, examples, strict=True):
        if column.button(example, key=f"example-{example}"):
            chosen_example = example
    prompt = st.chat_input("Ask a policy, fee, or wire question")
    question = prompt or chosen_example

    if question:
        with st.chat_message("user"):
            _render_chat_text(question)
        st.session_state.chat_history.append({"role": "user", "content": question})

        with st.chat_message("assistant"):
            with st.spinner("Retrieving from Atlas Vector Search..."):
                result = rag_chat(
                    question,
                    user_role=user_role,
                    product_type=None if product_type == "all" else product_type,
                    search_mode=search_mode,
                    limit=limit,
                )
            st.markdown(result["answer"])
            _render_citations(result["citations"])
            with st.expander("Grounded prompt sent to the LLM"):
                st.code(result["prompt"], language="markdown")
        st.session_state.chat_history.append(
            {
                "role": "assistant",
                "content": result["answer"],
                "citations": result["citations"],
            }
        )


def _render_chat_text(content: str) -> None:
    """Show a chat turn, enlarging the featured overdraft/transfer question."""

    if content == FEATURED_RAG_QUESTION:
        st.markdown(
            f'<p class="featured-question">{content}</p>',
            unsafe_allow_html=True,
        )
        return
    st.markdown(content)


def _render_citations(citations: list[dict]) -> None:
    if not citations:
        st.info("No authorized citations were returned for this persona.")
        return
    st.markdown("**Citations and vector scores**")
    for citation in citations:
        score = citation.get("score") or citation.get("vector_score")
        score_text = f"{float(score):.4f}" if isinstance(score, (int, float)) else "n/a"
        redacted = " · redacted" if citation.get("redacted") else ""
        st.markdown(
            f"""
            <div class="citation">
              <strong>[{citation.get('index')}] {citation.get('title')}</strong><br/>
              score {score_text} · {citation.get('clearance_level')} ·
              {citation.get('product_type')} · {citation.get('source')}{redacted}
            </div>
            """,
            unsafe_allow_html=True,
        )


def _graph_tab(user_role: str) -> None:
    st.subheader("Knowledge Graph")
    _guide(
        "Use case 2 · walkthrough",
        "Expand one customer into a household and account network",
        [
            "Keep the first customer in the list (<strong>CUST-0001</strong> if present).",
            "Set traversal depth to <strong>3</strong>.",
            "Click <strong>Run $graphLookup</strong>.",
            "Read the node/edge metrics, then drag the PyVis canvas and hover a customer or account.",
            "Expand <strong>Structured JSON</strong> and <strong>Aggregation pipeline</strong>.",
            "Toggle the sidebar persona: Tier 1 redacts SSN and exact balances on hover text.",
        ],
        "A household node, several accounts, related customers, and joint transactions. "
        "Compliance hover text can include SSN and balances; Tier 1 shows <code>[REDACTED]</code>.",
        'Docs: <a href="https://www.mongodb.com/docs/manual/reference/operator/aggregation/graphLookup/" target="_blank">$graphLookup</a>',
    )
    st.caption(
        "Enter a customer ID to expand household members, joint accounts, and recent "
        "joint transactions with a MongoDB `$graphLookup` aggregation."
    )

    customers = list_customers()
    if not customers:
        st.warning("No customers found. Run `python -m app.scripts.seed_data` first.")
        return

    labels = {
        f"{item['customer_id']} · {item['first_name']} {item['last_name']} · {item['household_id']}": item[
            "customer_id"
        ]
        for item in customers
    }
    selected_label = st.selectbox("Customer", options=list(labels.keys()))
    depth = st.slider(
        "Traversal depth",
        min_value=1,
        max_value=4,
        value=3,
        help=(
            "How many hops $graphLookup walks from the selected customer. "
            "It is passed as $graphLookup.maxDepth.\n\n"
            "The walk starts at the customer’s connections array in "
            "graph_nodes, then follows each neighbor’s connections to the "
            "next node_id. Depth 1 is usually the household and owned "
            "accounts. Depth 2–3 pulls in other household members, their "
            "accounts, and related customers. Depth 4 expands the same "
            "pattern one hop further.\n\n"
            "Joint transactions are attached afterward with $lookup (up to "
            "8 recent joint txns) and are not limited by this slider. "
            "Default 3 is the walkthrough setting for CUST-0001."
        ),
    )
    customer_id = labels[selected_label]

    if st.button("Run $graphLookup", type="primary"):
        payload = get_customer_graph(customer_id, max_depth=depth, user_role=user_role)
        stats = payload.get("stats") or {}
        metric_cols = st.columns(4)
        metric_cols[0].metric(
            "Nodes",
            stats.get("node_count", 0),
            help=(
                "Unique vertices drawn on the canvas after $graphLookup. "
                "A node is a customer, household, account, or joint "
                "transaction from graph_nodes (plus recent joint txns "
                "joined from the transactions collection).\n\n"
                "The selected customer is depth 0. Each $graphLookup hop "
                "adds neighbors. Hover a node to see type, hop depth, and "
                "role-governed metadata (Tier 1 redacts SSN and balances)."
            ),
        )
        metric_cols[1].metric(
            "Edges",
            stats.get("edge_count", 0),
            help=(
                "Relationships drawn between those nodes. Edges come from "
                "each document’s connections array, plus links from joint "
                "transactions to their accounts and parties.\n\n"
                "Typical labels: household_member (customer ↔ household), "
                "owns (customer ↔ account), household_account, related "
                "(customer ↔ customer), joint_transaction, and party. "
                "Undirected duplicates are collapsed so A→B and B→A count "
                "once."
            ),
        )
        metric_cols[2].metric(
            "Accounts",
            stats.get("accounts", 0),
            help=(
                "Nodes whose type is account — checking, savings, and other "
                "products reached from the customer or household within the "
                "traversal depth.\n\n"
                "Joint accounts appear because both owners are connected "
                "through the household graph. Hover an account for product "
                "type and (if your persona allows) balance. This count is a "
                "subset of Nodes, not a separate query."
            ),
        )
        metric_cols[3].metric(
            "Joint txns",
            stats.get("transactions", 0),
            help=(
                "Recent joint transactions attached after the graph walk. "
                "A $lookup on the transactions collection keeps documents "
                "where is_joint is true and the account or a party is in "
                "the expanded network, then sorts by timestamp and limits "
                "to 8.\n\n"
                "Each txn is rendered as a diamond node and linked to its "
                "account(s) and customer parties. This count is not "
                "controlled by Traversal depth."
            ),
        )

        html = render_pyvis_html(payload)
        components.html(html, height=660, scrolling=False)

        with st.expander("Structured JSON for PyVis"):
            display = {
                "root": payload.get("root"),
                "stats": stats,
                "nodes": payload.get("nodes"),
                "edges": payload.get("edges"),
            }
            st.json(display)
        with st.expander("Aggregation pipeline"):
            st.code(json.dumps(payload.get("pipeline"), indent=2, default=str), language="json")


def _governance_tab(user_role: str) -> None:
    st.subheader("Governance & Security")
    _guide(
        "Use case 3 · walkthrough",
        "Compare Tier 1 redaction with Compliance full access",
        [
            "Use the <strong>Compare roles</strong> radio on this page (it is independent of the live filter below).",
            "Select <strong>Tier 1 Agent</strong>. Only the public fee schedule should remain. SSN and customer balances are stripped.",
            "Select <strong>Compliance Manager</strong>. Restricted CIP policy, the service transcript, and private account metadata return.",
            "Read <strong>Live filtered context</strong> — that is <code>filter_context_by_role</code> applied to the same four chunks.",
        ],
        "Tier 1: 1 of 4 chunks, fee amounts like $25 stay visible, transcript PII is gone. "
        "Compliance: 4 of 4 chunks, including SSN <code>219-09-9999</code> and balance <code>$18,440.22</code>.",
        'Docs: <a href="https://www.mongodb.com/docs/atlas/atlas-vector-search/vector-search-stage/#std-label-avs-filter" target="_blank">Vector Search pre-filters</a>',
    )
    st.caption(
        "Toggle roles to watch retrieval filters and PII redaction change in real time. "
        "Tier 1 keeps public knowledge only. Compliance keeps restricted transcripts and private account metadata."
    )

    persona = st.radio(
        "Compare roles",
        options=list(ROLE_LABELS.keys()),
        format_func=lambda key: ROLE_LABELS[key],
        index=0 if user_role == "tier1_support" else 1,
        horizontal=True,
    )
    policy = role_policy_summary(persona)
    filtered = filter_context_by_role(persona, SAMPLE_CHUNKS)

    st.markdown("**Live filtered context**")
    if not filtered:
        st.warning("This persona receives zero chunks from the current retrieval set.")
    for chunk in filtered:
        badge = "REDACTED" if chunk.get("redacted") else "FULL ACCESS"
        st.markdown(f"**{chunk.get('title')}** · `{chunk.get('clearance_level')}` · {badge}")
        st.write(chunk.get("content"))
        if chunk.get("metadata"):
            st.caption(json.dumps(chunk["metadata"]))

    dropped = len(SAMPLE_CHUNKS) - len(filtered)
    st.info(
        f"{len(filtered)} of {len(SAMPLE_CHUNKS)} chunks remain visible. "
        f"{dropped} were removed by source or clearance rules."
    )

    left, right = st.columns(2)
    with left:
        st.markdown("**Policy**")
        st.json(policy)
    with right:
        st.markdown("**Raw retrieved chunks**")
        st.json(SAMPLE_CHUNKS)


def _customer_options() -> dict[str, str]:
    """Build a label -> customer_id map for agent tabs."""

    customers = list_customers()
    if not customers:
        return {"CUST-0001 · seed customer": "CUST-0001"}
    return {
        f"{item['customer_id']} · {item['first_name']} {item['last_name']}": item["customer_id"]
        for item in customers
    }


def _select_checkpoint(checkpoint_id: str) -> None:
    """Select a checkpoint_id and load that MongoDBSaver snapshot immediately."""

    st.session_state.selected_checkpoint_id = checkpoint_id
    thread_id = st.session_state.get("agent_thread_id")
    if thread_id:
        st.session_state.rewind_snapshot = rewind_to_checkpoint(thread_id, checkpoint_id)


def _select_execution(execution_id: str) -> None:
    """Remember the Recent executions row that drives the audit trail."""

    st.session_state.selected_execution_id = execution_id


def _ensure_agent_session() -> None:
    """Initialize Streamlit keys shared by the three agent tabs."""

    if "agent_thread_id" not in st.session_state:
        st.session_state.agent_thread_id = "THR-DEMO-0001"
    if "last_agent_result" not in st.session_state:
        st.session_state.last_agent_result = None
    if "rewind_snapshot" not in st.session_state:
        st.session_state.rewind_snapshot = None


def _agent_memory_tab(user_role: str) -> None:
    st.subheader("Agent Memory & State")
    _guide(
        "Use case 4 · walkthrough",
        "Run a stateful agent that recalls thread history and long-term facts",
        [
            "Keep <strong>CUST-0001</strong> and the default thread id.",
            "Leave the sidebar on <strong>Tier 1 Agent</strong> first.",
            "Click <strong>Does this customer prefer email or SMS alerts?</strong>",
            "Short-term turns appear on the left. Public email-alert memory should appear on the right.",
            "Switch the sidebar to <strong>Compliance Manager</strong> and run <strong>What lending did this customer apply for?</strong>",
            "The restricted August 2026 auto-loan memory should now be visible.",
        ],
        "Tier 1 recalls public preferences only. Compliance also sees the auto-loan fact. "
        "Both panes refresh from MongoDB <code>session_turns</code> and <code>user_memory</code>.",
        'Docs: <a href="https://www.mongodb.com/docs/atlas/atlas-vector-search/vector-search-stage/" target="_blank">$vectorSearch</a>',
    )
    _ensure_agent_session()
    labels = _customer_options()
    col_a, col_b = st.columns([2, 1])
    with col_a:
        selected = st.selectbox(
            "Customer",
            options=list(labels.keys()),
            key="agent-customer",
            help=(
                "Which customer the LangGraph agent grounds on. Long-term "
                "memories in user_memory are filtered to this customer_id. "
                "The graph_traversal node also starts $graphLookup from this "
                "customer. Keep CUST-0001 for the seeded email-alert and "
                "auto-loan facts."
            ),
        )
    with col_b:
        st.session_state.agent_thread_id = st.text_input(
            "Thread id",
            value=st.session_state.agent_thread_id,
            key="agent-thread",
            help=(
                "LangGraph conversation key. Short-term turns are stored in "
                "session_turns under this thread_id. MongoDBSaver writes "
                "checkpoints for the same id so Checkpoint Inspector and "
                "Audit can rewind or trace this run.\n\n"
                "Reuse THR-DEMO-0001 to accumulate history across questions. "
                "Change it to start a clean buffer without wiping older threads."
            ),
        )
    customer_id = labels[selected]

    examples = [
        "Does this customer prefer email or SMS alerts?",
        "What lending did this customer apply for?",
        "What household account pays the mortgage?",
    ]
    example_cols = st.columns(len(examples))
    chosen = None
    for column, example in zip(example_cols, examples, strict=True):
        if column.button(example, key=f"agent-ex-{example}"):
            chosen = example
    typed = st.text_input(
        "Or type an agent question",
        key="agent-question",
        help=(
            "Free-text question for the four-node graph: recall_memory → "
            "vector_search → graph_traversal → final_answer. The sample "
            "buttons above fill this for the walkthrough. The question is "
            "appended to session_turns and also embeds for long-term memory "
            "recall and knowledge-base search."
        ),
    )
    question = chosen or (typed.strip() or None)

    if st.button("Run LangGraph agent", type="primary") or chosen:
        if not question:
            st.warning("Enter a question or click one of the sample prompts.")
        else:
            with st.spinner("Running recall → vector search → graph → answer..."):
                result = run_agent(
                    question,
                    thread_id=st.session_state.agent_thread_id,
                    customer_id=customer_id,
                    user_role=user_role,
                )
            st.session_state.last_agent_result = result
            st.success(
                f"execution `{result['execution_id']}` · checkpoint `{result.get('checkpoint_id')}`"
            )
            st.markdown(result.get("answer") or "")
            if result.get("citations"):
                _render_citations(result["citations"])

    result = st.session_state.last_agent_result
    left, right = st.columns(2)
    with left:
        _section_with_help(
            "Short-term memory",
            (
                "Per-thread conversation buffer in the session_turns collection. "
                "Each Run LangGraph agent appends the user question and the "
                "model answer, keyed by thread_id and timestamp.\n\n"
                "The recall_memory node reads the latest turns so the agent "
                "can refer to earlier questions in this thread. This is "
                "ephemeral working memory — it is not embedded and is not "
                "shared across thread ids. The sidebar persona can redact PII "
                "in the displayed rows."
            ),
        )
        turns = fetch_session_turns(st.session_state.agent_thread_id, user_role=user_role)
        if turns:
            _response_table(turns)
        else:
            st.info("No session turns yet for this thread.")
    with right:
        _section_with_help(
            "Long-term memory",
            (
                "Durable customer facts in user_memory, recalled by embedding "
                "the current question and ranking stored fact embeddings "
                "(Atlas $vectorSearch when the index exists, otherwise local "
                "cosine).\n\n"
                "Facts are scoped to the selected customer and filtered by "
                "persona: Tier 1 sees public preferences (email vs SMS). "
                "Compliance also sees restricted items such as the August "
                "2026 auto-loan application. Unlike short-term turns, these "
                "rows survive a new thread id."
            ),
        )
        query = (result or {}).get("question") or "customer preferences and recent applications"
        memories = retrieve_long_term_memory(customer_id, query, user_role=user_role)
        if memories:
            _response_table(
                [
                    {
                        "memory_id": item.get("memory_id"),
                        "fact": item.get("fact") or item.get("content"),
                        "score": item.get("score"),
                        "clearance_level": item.get("clearance_level"),
                    }
                    for item in memories
                ]
            )
        else:
            st.info("No authorized long-term memories for this persona.")


def _checkpoint_tab() -> None:
    st.subheader("Checkpoint Inspector")
    _guide(
        "Use case 5 · walkthrough",
        "Inspect LangGraph node snapshots and rewind the thread",
        [
            "Run an agent question on <strong>Agent Memory & State</strong> first.",
            "Confirm four steps: recall_memory, vector_search, graph_traversal, final_answer.",
            "Select an earlier checkpoint in the table.",
            "Click a <strong>checkpoint_id</strong> to rewind to that snapshot.",
        ],
        "Each row is a MongoDB <code>checkpoints</code> document written by <code>MongoDBSaver</code>. "
        "Rewind shows the channel state at that node without losing later history.",
        'Docs: <a href="https://www.mongodb.com/docs/atlas/atlas-vector-search/ai-integrations/langchain/" target="_blank">LangChain + Atlas</a>',
    )
    _ensure_agent_session()
    thread_id = st.session_state.agent_thread_id
    history = list_checkpoint_history(thread_id)
    if not history:
        st.info("No checkpoints yet. Run the agent on the previous tab.")
        return

    rows = []
    for item in history:
        steps = item.get("step_log") or []
        latencies = ", ".join(
            f"{step.get('step_name')} {step.get('execution_latency_ms')}ms" for step in steps
        )
        rows.append(
            {
                "checkpoint_id": item.get("checkpoint_id"),
                "created_at": item.get("created_at"),
                "question": item.get("question"),
                "steps": latencies,
                "parent": item.get("parent_checkpoint_id"),
            }
        )
    ids = [item["checkpoint_id"] for item in rows if item.get("checkpoint_id")]
    if not ids:
        st.info("Checkpoint rows are missing ids.")
        return
    if st.session_state.get("selected_checkpoint_id") not in ids:
        st.session_state.selected_checkpoint_id = ids[0]
        st.session_state.rewind_snapshot = rewind_to_checkpoint(
            thread_id, st.session_state.selected_checkpoint_id
        )

    snapshot = st.session_state.rewind_snapshot
    if not snapshot or snapshot.get("checkpoint_id") != st.session_state.selected_checkpoint_id:
        snapshot = rewind_to_checkpoint(thread_id, st.session_state.selected_checkpoint_id)
        st.session_state.rewind_snapshot = snapshot

    weights = [2.3, 1.7, 2.2, 2.5, 1.5]
    header = st.columns(weights)
    for column, label in zip(
        header,
        ("checkpoint_id", "created_at", "question", "steps", "parent"),
        strict=True,
    ):
        column.markdown(f"**{label}**")
    for row in rows:
        cid = row["checkpoint_id"]
        cols = st.columns(weights)
        is_selected = st.session_state.selected_checkpoint_id == cid
        cols[0].button(
            str(cid),
            key=f"ckpt-sel-{cid}",
            type="primary" if is_selected else "secondary",
            use_container_width=True,
            on_click=_select_checkpoint,
            args=(cid,),
            help=(
                "Click to rewind to this MongoDBSaver snapshot. "
                "LangGraph writes one row after each node: recall_memory, "
                "vector_search, graph_traversal, and final_answer."
            ),
        )
        cols[1].markdown(str(row["created_at"] or ""))
        cols[2].markdown(str(row["question"] or ""))
        cols[3].markdown(str(row["steps"] or ""))
        cols[4].markdown(str(row["parent"] or ""))

    st.caption(f"Rewound to `{st.session_state.selected_checkpoint_id}` — click another checkpoint_id to jump.")

    snapshot = st.session_state.rewind_snapshot
    if snapshot:
        st.markdown(f"**Rewound to** `{snapshot.get('checkpoint_id')}`")
        state = snapshot.get("state") or {}
        st.json(
            {
                "question": state.get("question"),
                "execution_id": state.get("execution_id"),
                "step_log": state.get("step_log"),
                "answer": state.get("answer"),
                "graph": state.get("graph"),
            }
        )


def _pretty_value(value: Any) -> str:
    """Format tool payloads and scores for tree leaf bodies."""

    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4f}"
    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2, default=str)
    return str(value)


def _tree_leaf(label: str, value: Any, *, kind: str = "detail") -> dict[str, Any]:
    """Build a leaf node that shows a titled payload when expanded."""

    text = _pretty_value(value)
    return {
        "id": f"{kind}-{label}",
        "kind": kind,
        "label": label,
        "meta": "",
        "open": False,
        "body": text,
        "children": [],
    }


def _chunk_tree_node(chunk: dict[str, Any]) -> dict[str, Any]:
    """Build one provenance node: citation, scores, then field-level leaves."""

    index = chunk.get("citation_index") or "?"
    chunk_id = chunk.get("chunk_id") or "unknown-chunk"
    score = chunk.get("vector_score")
    score_label = f"score {_pretty_value(score)}" if score is not None else "no score"
    redacted = " · redacted" if chunk.get("redacted") else ""
    return {
        "id": f"chunk-{chunk_id}-{index}",
        "kind": "chunk",
        "label": f"[{index}] {chunk_id}",
        "meta": f"{chunk.get('source_doc') or 'untitled'} · {score_label}{redacted}",
        "open": False,
        "body": "",
        "children": [
            _tree_leaf("source_doc", chunk.get("source_doc")),
            _tree_leaf("source collection", chunk.get("source")),
            _tree_leaf("doc_version", chunk.get("doc_version")),
            _tree_leaf("vector_score", chunk.get("vector_score")),
            _tree_leaf("clearance_level", chunk.get("clearance_level")),
            _tree_leaf("product_type", chunk.get("product_type")),
            _tree_leaf("redacted", chunk.get("redacted")),
            _tree_leaf("content_excerpt", chunk.get("content_excerpt")),
        ],
    }


def _step_tree_node(row: dict[str, Any]) -> dict[str, Any]:
    """Build one audit-trail node for a LangGraph step and its tool I/O."""

    name = str(row.get("step_name") or "unnamed-step")
    latency = row.get("execution_latency_ms")
    latency_label = f"{latency} ms" if latency is not None else ""
    tool = row.get("tool_called") or ""
    meta_parts = [part for part in (tool, latency_label, row.get("user_role")) if part]
    children = [
        _tree_leaf("reasoning_thought", row.get("reasoning_thought")),
        _tree_leaf("tool_input", row.get("tool_input")),
        _tree_leaf("tool_output", row.get("tool_output")),
        _tree_leaf("timestamp", row.get("timestamp")),
    ]
    return {
        "id": f"step-{row.get('log_id') or name}",
        "kind": "step",
        "label": name,
        "meta": " · ".join(str(part) for part in meta_parts),
        "open": False,
        "body": "",
        "children": children,
    }


def _execution_tree_model(
    summary: dict[str, Any],
    logs: list[dict[str, Any]],
    lineage: list[dict[str, Any]],
) -> dict[str, Any]:
    """Nest execution → audit trail → chunk provenance for the tree control."""

    execution_id = summary.get("execution_id") or "unknown-execution"
    steps = len(logs)
    latency = summary.get("total_latency_ms")
    meta = " · ".join(
        part
        for part in (
            summary.get("thread_id"),
            summary.get("customer_id"),
            summary.get("user_role"),
            f"{steps} steps",
            f"{latency} ms" if latency is not None else "",
        )
        if part
    )
    children: list[dict[str, Any]] = [
        {
            "id": f"meta-{execution_id}",
            "kind": "folder",
            "label": "Execution metadata",
            "meta": "",
            "open": False,
            "body": "",
            "children": [
                _tree_leaf("thread_id", summary.get("thread_id")),
                _tree_leaf("customer_id", summary.get("customer_id")),
                _tree_leaf("user_role", summary.get("user_role")),
                _tree_leaf("started_at", summary.get("started_at")),
                _tree_leaf("ended_at", summary.get("ended_at")),
                _tree_leaf("steps", summary.get("steps")),
                _tree_leaf("total_latency_ms", summary.get("total_latency_ms")),
            ],
        },
        {
            "id": f"audit-{execution_id}",
            "kind": "folder",
            "label": "Audit trail",
            "meta": f"{steps} LangGraph nodes",
            "open": True,
            "body": "",
            "children": [_step_tree_node(row) for row in logs],
        },
        {
            "id": f"prov-{execution_id}",
            "kind": "folder",
            "label": "Chunk-level vector provenance",
            "meta": f"{len(lineage)} grounded chunks",
            "open": True,
            "body": "",
            "children": [_chunk_tree_node(chunk) for chunk in lineage],
        },
    ]
    if lineage and lineage[0].get("answer"):
        children.insert(
            1,
            {
                "id": f"answer-{execution_id}",
                "kind": "answer",
                "label": "Grounded answer",
                "meta": "",
                "open": False,
                "body": str(lineage[0]["answer"]),
                "children": [
                    _tree_leaf("question", lineage[0].get("question")),
                ],
            },
        )
    return {
        "id": f"exec-{execution_id}",
        "kind": "execution",
        "label": str(execution_id),
        "meta": meta,
        "open": True,
        "body": "",
        "children": children,
    }


def _tree_node_html(node: dict[str, Any]) -> str:
    """Render one tree node and its descendants as accessible HTML."""

    children = node.get("children") or []
    has_kids = bool(children) or bool(node.get("body"))
    opened = " open" if node.get("open") and has_kids else ""
    kind = html_escape(str(node.get("kind") or "detail"))
    label = html_escape(str(node.get("label") or ""))
    meta = html_escape(str(node.get("meta") or ""))
    meta_html = f'<span class="tree-meta">{meta}</span>' if meta else ""
    body = node.get("body") or ""
    body_html = (
        f'<pre class="tree-body">{html_escape(body)}</pre>' if body else ""
    )
    kids_html = "".join(_tree_node_html(child) for child in children)
    kids_block = f'<ul class="tree-kids">{kids_html}</ul>' if kids_html else ""
    if not has_kids:
        return (
            f'<li class="tree-node kind-{kind} leaf">'
            f'<div class="tree-row"><span class="tree-kind">{kind}</span>'
            f'<span class="tree-label">{label}</span>{meta_html}</div></li>'
        )
    return (
        f'<li class="tree-node kind-{kind}">'
        f"<details{opened}>"
        f'<summary class="tree-row"><span class="tree-kind">{kind}</span>'
        f'<span class="tree-label">{label}</span>{meta_html}</summary>'
        f"{kids_block}{body_html}"
        f"</details></li>"
    )


def _render_audit_tree(model: dict[str, Any]) -> None:
    """Paint the hierarchical execution / audit / provenance tree."""

    tree_html = _tree_node_html(model)
    components.html(
        f"""
        <!DOCTYPE html>
        <html>
        <head>
          <style>
            :root {{
              --navy: #001E2B;
              --slate: #21313C;
              --panel: #1A2B35;
              --mist: #F9FBFA;
              --muted: #C1C7C6;
              --line: #5C6C75;
              --leaf: #00ED64;
              --forest: #00684A;
            }}
            html, body {{
              margin: 0;
              background: var(--navy);
              color: var(--mist);
              font-family: "Source Sans 3", "Helvetica Neue", Helvetica, Arial, sans-serif;
            }}
            .tree-shell {{
              border: 1px solid var(--line);
              border-radius: 12px;
              background: var(--slate);
              padding: 12px 14px 16px;
            }}
            .tree-toolbar {{
              display: flex;
              gap: 8px;
              margin-bottom: 10px;
            }}
            .tree-toolbar button {{
              background: var(--panel);
              color: var(--mist);
              border: 1px solid var(--line);
              border-radius: 8px;
              padding: 6px 10px;
              font-weight: 600;
              cursor: pointer;
            }}
            .tree-toolbar button:hover {{
              border-color: var(--leaf);
              background: var(--forest);
            }}
            .tree-root, .tree-kids {{
              list-style: none;
              margin: 0;
              padding-left: 0;
            }}
            .tree-kids {{
              margin-left: 14px;
              padding-left: 14px;
              border-left: 1px solid var(--line);
            }}
            .tree-node {{ margin: 4px 0; }}
            details > summary {{
              list-style: none;
              cursor: pointer;
            }}
            details > summary::-webkit-details-marker {{ display: none; }}
            .tree-row {{
              display: flex;
              flex-wrap: wrap;
              align-items: baseline;
              gap: 8px;
              padding: 7px 10px;
              border-radius: 8px;
              background: var(--panel);
            }}
            details[open] > summary.tree-row {{
              border: 1px solid var(--forest);
            }}
            .tree-kind {{
              font-size: 0.68rem;
              font-weight: 700;
              letter-spacing: 0.05em;
              text-transform: uppercase;
              color: var(--navy);
              background: var(--leaf);
              border-radius: 999px;
              padding: 2px 7px;
            }}
            .kind-step > details > .tree-row .tree-kind,
            .kind-step.leaf .tree-kind {{ background: #0498EC; color: var(--navy); }}
            .kind-chunk > details > .tree-row .tree-kind,
            .kind-chunk.leaf .tree-kind {{ background: #B1FFC6; color: var(--navy); }}
            .kind-folder > details > .tree-row .tree-kind {{ background: #7167E9; color: #fff; }}
            .kind-answer > details > .tree-row .tree-kind {{ background: #FFC01E; color: var(--navy); }}
            .kind-detail .tree-kind {{ background: var(--line); color: var(--mist); }}
            .tree-label {{
              font-weight: 700;
              font-size: 0.98rem;
              color: var(--mist);
            }}
            .tree-meta {{
              color: var(--muted);
              font-size: 0.85rem;
            }}
            .tree-body {{
              margin: 8px 0 8px 28px;
              padding: 10px 12px;
              background: var(--navy);
              border: 1px solid var(--line);
              border-radius: 8px;
              color: var(--mist);
              white-space: pre-wrap;
              word-break: break-word;
              font-size: 0.82rem;
              line-height: 1.45;
              max-height: 260px;
              overflow: auto;
            }}
          </style>
        </head>
        <body>
          <div class="tree-shell">
            <div class="tree-toolbar">
              <button type="button" id="expand-all">Expand all</button>
              <button type="button" id="collapse-all">Collapse all</button>
            </div>
            <ul class="tree-root">{tree_html}</ul>
          </div>
          <script>
            const root = document.querySelector(".tree-root");
            document.getElementById("expand-all").onclick = () => {{
              root.querySelectorAll("details").forEach((node) => {{ node.open = true; }});
            }};
            document.getElementById("collapse-all").onclick = () => {{
              root.querySelectorAll("details").forEach((node) => {{ node.open = false; }});
            }};
          </script>
        </body>
        </html>
        """,
        height=720,
        scrolling=True,
    )


def _audit_tab() -> None:
    st.subheader("Audit & Lineage")
    _guide(
        "Use case 6 · walkthrough",
        "Trace every tool call and the chunks that grounded the answer",
        [
            "Run the agent at least once so <code>ai_audit_logs</code> has rows.",
            "Pick an execution in the recent-runs table.",
            "Expand <strong>Audit trail</strong> to open each LangGraph node and its tool I/O.",
            "Expand <strong>Chunk-level vector provenance</strong> for chunk id, source, version, and vector score.",
        ],
        "One execution root. Audit trail has four nodes. Provenance count matches the "
        "authorized chunks that reached <code>final_answer</code>.",
        'Docs: <a href="https://www.mongodb.com/docs/manual/core/data-modeling-introduction/" target="_blank">MongoDB data modeling</a>',
    )
    recent = list_recent_executions()
    if not recent:
        st.info("No audit executions yet. Run the agent first.")
        return
    _section_with_help(
        "Recent executions",
        (
            "One summary row per agent run, grouped from ai_audit_logs by "
            "execution_id. A run is minted when you click Run LangGraph "
            "agent (EX-…).\n\n"
            "Each row shows thread, customer, persona, start/end, step "
            "count, and summed latency. Four steps is a complete graph: "
            "recall_memory, vector_search, graph_traversal, final_answer. "
            "Click an execution_id to open the execution tree: "
            "audit trail nodes and chunk-level provenance."
        ),
    )
    execution_ids = [item["execution_id"] for item in recent if item.get("execution_id")]
    if not execution_ids:
        st.info("Recent rows are missing execution ids.")
        return
    last = st.session_state.get("last_agent_result") or {}
    last_id = last.get("execution_id")
    current = st.session_state.get("selected_execution_id")
    if current not in execution_ids:
        st.session_state.selected_execution_id = (
            last_id if last_id in execution_ids else execution_ids[0]
        )

    weights = [2.2, 1.6, 1.3, 1.4, 1.6, 1.6, 0.8, 1.2]
    labels = (
        "execution_id",
        "thread_id",
        "customer_id",
        "user_role",
        "started_at",
        "ended_at",
        "steps",
        "total_latency_ms",
    )
    header = st.columns(weights)
    for column, label in zip(header, labels, strict=True):
        column.markdown(f"**{label}**")
    for item in recent:
        eid = item.get("execution_id")
        if not eid:
            continue
        cols = st.columns(weights)
        is_selected = st.session_state.selected_execution_id == eid
        cols[0].button(
            str(eid),
            key=f"exec-sel-{eid}",
            type="primary" if is_selected else "secondary",
            use_container_width=True,
            on_click=_select_execution,
            args=(eid,),
            help=(
                "Click to load this run’s Execution audit trail and "
                "chunk-level provenance. Defaults to the last Agent "
                "Memory run when that EX-… id is still in the list."
            ),
        )
        cols[1].markdown(str(item.get("thread_id") or ""))
        cols[2].markdown(str(item.get("customer_id") or ""))
        cols[3].markdown(str(item.get("user_role") or ""))
        cols[4].markdown(str(item.get("started_at") or ""))
        cols[5].markdown(str(item.get("ended_at") or ""))
        cols[6].markdown(str(item.get("steps") or ""))
        cols[7].markdown(str(item.get("total_latency_ms") or ""))

    selected = st.session_state.selected_execution_id
    st.caption(
        f"Selected execution `{selected}` — click an execution_id to load the tree."
    )
    logs = list_audit_logs(execution_id=selected)
    lineage = get_lineage(selected)
    summary = next(
        (item for item in recent if item.get("execution_id") == selected),
        {"execution_id": selected},
    )
    _section_with_help(
        "Execution tree",
        (
            "The same three layers the collections already model: one "
            "execution root, an audit-trail branch (one ai_audit_logs "
            "document per LangGraph node), and a chunk-level provenance "
            "branch (answer_lineage rows).\n\n"
            "Expand a step for reasoning plus tool input/output. Expand a "
            "chunk for source_doc, doc_version, vector_score, clearance, "
            "and the excerpt that grounded the answer."
        ),
    )
    _render_audit_tree(_execution_tree_model(summary, logs, lineage))
    if not logs and not lineage:
        st.info("No audit or lineage rows for this execution.")


def main() -> None:
    st.set_page_config(
        page_title="MongoDB Atlas | Retail Banking RAG",
        page_icon=str(LEAF) if LEAF.exists() else "🍃",
        layout="wide",
    )
    _inject_brand()
    _header()
    if st.session_state.get("nav_tab") not in {key for key, _label in APP_TABS}:
        st.session_state.nav_tab = "help"
    user_role = _sidebar()

    nav_cols = st.columns(len(APP_TABS), gap="small")
    for column, (key, label) in zip(nav_cols, APP_TABS, strict=True):
        with column:
            selected = st.session_state.nav_tab == key
            st.button(
                label,
                key=f"navbtn-{key}",
                type="primary" if selected else "secondary",
                use_container_width=True,
                on_click=_set_nav_tab,
                args=(key,),
            )

    active = st.session_state.nav_tab
    if active == "help":
        _help_tab()
    elif active == "rag":
        _rag_tab(user_role)
    elif active == "graph":
        _graph_tab(user_role)
    elif active == "gov":
        _governance_tab(user_role)
    elif active == "memory":
        _agent_memory_tab(user_role)
    elif active == "ckpt":
        _checkpoint_tab()
    else:
        _audit_tab()


if __name__ == "__main__":
    main()
