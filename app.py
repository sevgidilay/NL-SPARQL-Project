"""
NL-SPARQL Translation System — Streamlit UI
"""

import json
import os
import glob
import html
import random
import re
import time
import yaml
from datetime import datetime
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import concurrent.futures

from src import llm_client
from src import nl_to_sparql
from src import sparql_to_nl
from src import sparql_executor
from src import answer_summarizer
from src import domain_router
from src import entity_linker
from src import kg_pipeline
from src.chat import ChatMemory
from src.chat.ui import render_chat_tab
from src.chat.viz import build_pyvis_html, detect_label_uri_columns
from src.wikidata_generic import WIKIDATA_GENERIC_CONFIG


# ── Page config ───────────────────────────────────────────────
st.set_page_config(
    page_title="NL ↔ SPARQL",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Session state ─────────────────────────────────────────────
if "dark_mode" not in st.session_state:
    st.session_state.dark_mode = False
if "chat_memory" not in st.session_state:
    st.session_state.chat_memory = ChatMemory()


def _replace_widget_text(key: str, value: str) -> None:
    st.session_state[key] = value


# Apply any pending model switch before the selectbox widget is instantiated
if st.session_state.get("_pending_model"):
    st.session_state.selected_model = st.session_state._pending_model
    st.session_state._pending_model = None

# Apply pending domain + question from "Use this" example button.
# Must run before ANY widget is instantiated so the selectbox renders
# with the correct domain instead of resetting to the default.
if st.session_state.get("_pending_domain") is not None:
    st.session_state.selected_domain = st.session_state._pending_domain
    del st.session_state["_pending_domain"]
if st.session_state.get("_pending_nl_input") is not None:
    st.session_state.nl_input = st.session_state._pending_nl_input
    del st.session_state["_pending_nl_input"]

# ── Custom theme ──────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Serif:ital,wght@0,300;0,400;0,600;1,400&family=IBM+Plex+Sans:wght@300;400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');

/* ── Variables ── */
:root {
    color-scheme: light;
    --bg:              #fffafa;
    --surface:         #FFFFFF;
    --sidebar-bg:      #EDE8F5;
    --header-bg:       #E2D8F2;        
    --border:          #DDD6F3;
    --border-strong:   #C4B8E0;
    --text:            #2D2640;
    --text-muted:      #6B6080;
    --text-subtle:     #9B93AD;
    --accent:          #7C5CFC;
    --accent-light:    #EDE8FF;
    --accent-dim:      #5A3ED4;
    --code-bg:         #1E1B2E;
    --success-bg:      #ECFDF5;
    --success-border:  #A7F3D0;
    --success-text:    #065F46;
    --error-bg:        #FFF1F2;
    --error-border:    #FECDD3;
    --error-text:      #881337;
    --warn-bg:         #FFFBEB;
    --warn-border:     #FDE68A;
    --warn-text:       #78350F;
    --info-bg:         #EDE8FF;
    --info-border:     #C4B8E0;
    --info-text:       #3B2E6E;
    --font-serif:      'IBM Plex Serif', Georgia, serif;
    --font-sans:       'IBM Plex Sans', -apple-system, sans-serif;
    --font-mono:       'IBM Plex Mono', 'Courier New', monospace;
    --radius:          8px;
    --radius-lg:       12px;
    --shadow-sm:       0 1px 4px rgba(100,80,160,0.08);
}

/* ── Global ── */
html, body, .stApp {
    font-family: var(--font-sans) !important;
    background-color: var(--bg) !important;
    color: var(--text) !important;
    color-scheme: light !important;
    -webkit-font-smoothing: antialiased;
}
.main .block-container {
    padding: 2.5rem 2.75rem 5rem !important;
    max-width: 1080px !important;
}

/* ── Streamlit chrome ── */
footer { display: none !important; }
[data-testid="stHeader"] {
    background: var(--bg) !important;
    border-bottom: 1px solid var(--border-strong) !important;
}
/* Always-visible sidebar toggle — override parent wrapper opacity too */
[data-testid="collapsedControl"],
div:has(> [data-testid="collapsedControl"]) {
    display: flex !important;
    visibility: visible !important;
    opacity: 1 !important;
    transition: none !important;
}

/* ── App header ── */
.app-title {
    font-family: var(--font-serif) !important;
    font-size: 2rem;
    font-weight: 600;
    letter-spacing: -0.025em;
    color: var(--text);
    line-height: 1.15;
    margin: 0;
}
.app-pill {
    display: inline-block;
    background: var(--accent);
    color: #fff;
    font-family: var(--font-mono);
    font-size: 9.5px;
    font-weight: 500;
    padding: 3px 9px;
    border-radius: 3px;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    vertical-align: middle;
    position: relative;
    top: -3px;
    margin-left: 8px;
}
.app-sub {
    font-size: 0.9rem;
    color: var(--text-muted);
    font-weight: 300;
    margin: 6px 0 2rem;
}
.app-divider {
    border: none;
    border-top: 1px solid var(--border);
    margin: 0 0 1.75rem;
}

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background-color: var(--sidebar-bg) !important;
    border-right: 1px solid var(--border) !important;
}
[data-testid="stSidebar"] .block-container {
    padding: 1.75rem 1.25rem !important;
}
.sb-logo {
    font-family: var(--font-mono);
    font-size: 0.78rem;
    font-weight: 500;
    color: var(--accent);
    letter-spacing: 0.04em;
    margin-bottom: 1.5rem;
    display: block;
}
.sb-label {
    font-size: 0.65rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--text-subtle);
    margin: 1.25rem 0 0.5rem;
    display: block;
}
.sb-desc {
    font-size: 0.8rem;
    color: var(--text-muted);
    line-height: 1.55;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 8px 10px;
    margin-top: 6px;
}
.sb-endpoint {
    font-family: var(--font-mono);
    font-size: 0.68rem;
    color: var(--text-subtle);
    word-break: break-all;
    line-height: 1.4;
    padding-top: 4px;
    display: block;
}

.sb-status-row {
    font-size: 0.75rem;
    font-family: var(--font-mono);
    color: var(--text);
    line-height: 1.7;
    display: block;
}
.model-provider-heading {
    font-family: var(--font-mono);
    font-size: 0.62rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--text-subtle);
    margin: 10px 0 5px;
}
.model-status-card {
    display: flex;
    align-items: center;
    gap: 8px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 7px 10px;
    overflow: visible;
}
.model-name {
    font-family: var(--font-mono);
    font-size: 0.71rem;
    color: var(--text);
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    position: relative;
    cursor: default;
}
.model-name[data-tooltip]:hover::after {
    content: attr(data-tooltip);
    position: absolute;
    bottom: calc(100% + 6px);
    left: 0;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 0.68rem;
    white-space: nowrap;
    z-index: 9999;
    pointer-events: none;
    box-shadow: 0 2px 6px rgba(0,0,0,0.15);
    color: var(--text);
}
.model-provider-tag,
.model-state-tag {
    font-size: 0.57rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    padding: 2px 6px;
    border-radius: 2px;
    white-space: nowrap;
}
.model-provider-tag {
    background: var(--info-bg);
    color: var(--info-text);
    border: 1px solid var(--info-border);
}

/* Sidebar selectbox */
[data-testid="stSidebar"] [data-testid="stSelectbox"] > div > div {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
    font-size: 0.88rem !important;
    color: var(--text) !important;
}
[data-testid="stSidebar"] [data-testid="stSelectbox"] > div > div:focus-within {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px var(--accent-light) !important;
}
/* Sidebar checkbox label — keep readable, not uppercase */
[data-testid="stSidebar"] [data-testid="stCheckbox"] label,
[data-testid="stSidebar"] [data-testid="stCheckbox"] p {
    font-size: 0.86rem !important;
    font-weight: 400 !important;
    text-transform: none !important;
    letter-spacing: 0 !important;
    color: var(--text) !important;
}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {
    background: transparent !important;
    border-bottom: 1.5px solid var(--border) !important;
    gap: 0 !important;
}
.stTabs [data-baseweb="tab"] {
    font-family: var(--font-sans) !important;
    font-size: 0.875rem !important;
    font-weight: 500 !important;
    color: var(--text-muted) !important;
    background: transparent !important;
    border: none !important;
    border-bottom: 2px solid transparent !important;
    padding: 10px 22px !important;
    margin-bottom: -1.5px !important;
    letter-spacing: 0 !important;
    transition: color 0.15s !important;
}
.stTabs [data-baseweb="tab"]:hover { color: var(--text) !important; }
.stTabs [aria-selected="true"] {
    color: var(--accent) !important;
    font-weight: 600 !important;
    border-bottom-color: var(--accent) !important;
}
.stTabs [data-baseweb="tab-panel"] {
    padding-top: 1.75rem !important;
}

/* ── Section micro-labels ── */
.s-label {
    font-size: 0.68rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--text-subtle);
    display: block;
    margin-bottom: 8px;
}
.s-label + * { margin-top: 0 !important; }

/* ── Inputs ── */
.stTextArea label { display: none !important; }
.stTextArea [data-testid="stWidgetLabel"] { display: none !important; }
.stTextArea textarea {
    font-family: var(--font-sans) !important;
    font-size: 0.95rem !important;
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
    color: var(--text) !important;
    padding: 12px 14px !important;
    transition: border-color 0.15s, box-shadow 0.15s !important;
    resize: vertical !important;
    line-height: 1.6 !important;
}
.stTextArea textarea:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px var(--accent-light) !important;
    outline: none !important;
}
.stTextArea textarea::placeholder {
    color: var(--text-subtle) !important;
    font-style: italic !important;
}

/* ── Buttons ── */
/* Primary — cover old + new Streamlit testid formats */
.stButton > button[kind="primary"],
[data-testid="baseButton-primary"],
[data-testid="stBaseButton-primary"] {
    font-family: var(--font-sans) !important;
    font-size: 0.875rem !important;
    font-weight: 600 !important;
    background: var(--accent) !important;
    color: #fff !important;
    border: none !important;
    border-radius: var(--radius) !important;
    padding: 9px 26px !important;
    letter-spacing: 0.01em !important;
    transition: background 0.15s, box-shadow 0.15s !important;
}
.stButton > button[kind="primary"]:hover,
[data-testid="baseButton-primary"]:hover,
[data-testid="stBaseButton-primary"]:hover {
    background: var(--accent-dim) !important;
    color: #fff !important;
    box-shadow: var(--shadow-sm) !important;
}

/* Secondary / default */
.stButton > button,
.stButton > button[kind="secondary"],
[data-testid="baseButton-secondary"],
[data-testid="stBaseButton-secondary"] {
    font-family: var(--font-sans) !important;
    font-size: 0.82rem !important;
    font-weight: 400 !important;
    background: var(--surface) !important;
    color: var(--text) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
    padding: 7px 12px !important;
    text-align: left !important;
    white-space: normal !important;
    height: auto !important;
    line-height: 1.45 !important;
    transition: border-color 0.15s, background 0.15s, color 0.15s !important;
}
.stButton > button:hover,
.stButton > button[kind="secondary"]:hover,
[data-testid="baseButton-secondary"]:hover,
[data-testid="stBaseButton-secondary"]:hover {
    border-color: var(--accent) !important;
    background: var(--accent-light) !important;
    color: var(--accent) !important;
}

/* ── Code block ── */
[data-testid="stCodeBlock"],
.stCodeBlock {
    border-radius: var(--radius) !important;
    overflow: hidden !important;
    border: 1px solid #1e2a3a !important;
    margin: 0 !important;
}
[data-testid="stCodeBlock"] pre,
.stCodeBlock pre {
    font-family: var(--font-mono) !important;
    font-size: 0.82rem !important;
    line-height: 1.65 !important;
    padding: 1rem 1.25rem !important;
    background: var(--code-bg) !important;
    margin: 0 !important;
}

/* ── Alerts ── */
[data-testid="stAlert"] {
    border-radius: var(--radius) !important;
    padding: 10px 16px !important;
    font-size: 0.88rem !important;
    line-height: 1.55 !important;
}
[data-testid="stAlert"][data-type="success"],
.stSuccess {
    background: var(--success-bg) !important;
    border: 1px solid var(--success-border) !important;
    color: var(--success-text) !important;
}
[data-testid="stAlert"][data-type="error"],
.stError {
    background: var(--error-bg) !important;
    border: 1px solid var(--error-border) !important;
    color: var(--error-text) !important;
}
[data-testid="stAlert"][data-type="warning"],
.stWarning {
    background: var(--warn-bg) !important;
    border: 1px solid var(--warn-border) !important;
    color: var(--warn-text) !important;
}
[data-testid="stAlert"][data-type="info"],
.stInfo {
    background: var(--info-bg) !important;
    border: 1px solid var(--info-border) !important;
    color: var(--info-text) !important;
}

/* ── Expander ── */
[data-testid="stExpander"] {
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
    background: var(--surface) !important;
    margin-top: 0.75rem !important;
    overflow: hidden !important;
}
[data-testid="stExpander"] summary {
    font-size: 0.85rem !important;
    font-weight: 500 !important;
    color: var(--text-muted) !important;
    padding: 10px 14px !important;
    transition: color 0.15s !important;
}
[data-testid="stExpander"] summary:hover { color: var(--accent) !important; }

/* ── Dataframe ── */
[data-testid="stDataFrame"] {
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
    overflow: hidden !important;
}

/* ── Quick example cards ── */
.qx-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 12px 14px 10px;
    margin-bottom: 6px;
    min-height: 118px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    transition: border-color 0.15s, box-shadow 0.15s;
}
.qx-card:hover {
    border-color: var(--border-strong);
    box-shadow: var(--shadow-sm);
}
.qx-tags {
    display: flex;
    gap: 5px;
    flex-wrap: wrap;
}
.qx-tag {
    display: inline-block;
    padding: 2px 7px;
    border-radius: 3px;
    font-family: var(--font-mono);
    font-size: 0.6rem;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    line-height: 1.4;
    white-space: nowrap;
}
.qx-tag-domain {
    background: var(--accent-light);
    color: var(--accent);
    border: 1px solid #D6E5F2;
}
.qx-q {
    font-size: 0.875rem;
    color: var(--text);
    line-height: 1.5;
    flex: 1;
}

/* Compact load button under each card */
[data-testid="stHorizontalBlock"]:has(.qx-card) .stButton > button {
    font-size: 0.72rem !important;
    padding: 5px 10px !important;
    color: var(--text-muted) !important;
    text-align: center !important;
    justify-content: center !important;
    background: transparent !important;
    border: 1px dashed var(--border) !important;
}
[data-testid="stHorizontalBlock"]:has(.qx-card) .stButton > button:hover {
    color: var(--accent) !important;
    border-color: var(--accent) !important;
    border-style: solid !important;
    background: var(--accent-light) !important;
}

/* ── Tag badge (inline) ── */
.tag {
    display: inline-block;
    padding: 2px 7px;
    border-radius: 3px;
    font-family: var(--font-mono);
    font-size: 0.62rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 4px;
}

/* ── Divider ── */
hr { border: none !important; border-top: 1px solid var(--border) !important; margin: 1.5rem 0 !important; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 2px; }

/* ── Sidebar model switch buttons ── */
[data-testid="stSidebar"] [data-testid="column"]:last-child button {
    min-height: 32px !important;
    height: 32px !important;
    padding: 0 !important;
    font-size: 0.8rem !important;
    background: transparent !important;
    border: 1px solid var(--border) !important;
    border-radius: 6px !important;
    color: var(--text-subtle) !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    transition: all 0.15s !important;
}
[data-testid="stSidebar"] [data-testid="column"]:last-child button:hover {
    border-color: var(--accent) !important;
    color: var(--accent) !important;
    background: var(--accent-light) !important;
}
[data-testid="stSidebar"] [data-testid="column"]:last-child button:disabled {
    opacity: 0.3 !important;
    cursor: not-allowed !important;
}
/* ── Refresh button — icon only, no card ── */
[data-testid="stSidebar"] [data-testid="stHorizontalBlock"]:has(.sb-label) [data-testid="column"]:last-child button {
    border: none !important;
    box-shadow: none !important;
    height: 18px !important;
    min-height: 18px !important;
    font-size: 0.85rem !important;
    padding: 0 2px !important;
    color: var(--text-subtle) !important;
    background: transparent !important;
}
[data-testid="stSidebar"] [data-testid="stHorizontalBlock"]:has(.sb-label) [data-testid="column"]:last-child button:hover {
    border: none !important;
    background: transparent !important;
    color: var(--text) !important;
}

/* ── Model status dot animation ── */
@keyframes _dot_pulse {
    0%, 100% { box-shadow: 0 0 0 2px rgba(34,197,94,0.25); }
    50%       { box-shadow: 0 0 0 5px rgba(34,197,94,0.06); }
}
.model-dot-ok { animation: _dot_pulse 2.6s ease-in-out infinite; }
</style>
""", unsafe_allow_html=True)

if st.session_state.dark_mode:
    st.markdown("""
<style>
:root {
    color-scheme: dark;
    --bg:              #12110F;
    --surface:         #1C1B18;
    --sidebar-bg:      #171613;
    --border:          #2E2C28;
    --border-strong:   #4A4741;
    --text:            #EDEAE4;
    --text-muted:      #9E9790;
    --text-subtle:     #635D57;
    --accent:          #5BA4D4;
    --accent-light:    #1A2C3E;
    --accent-dim:      #3D7DB8;
    --code-bg:         #0D1117;
    --success-bg:      #0D2118;
    --success-border:  #1A4731;
    --success-text:    #6EE7A0;
    --error-bg:        #1F0D0D;
    --error-border:    #6B1E1E;
    --error-text:      #FCA5A5;
    --warn-bg:         #1E180A;
    --warn-border:     #6B4A0A;
    --warn-text:       #FCD34D;
    --info-bg:         #0D1A2E;
    --info-border:     #1A3055;
    --info-text:       #93C5FD;
}
html, body, .stApp { color-scheme: dark !important; }
.qx-tag-domain { border-color: #1E3055 !important; }
</style>
""", unsafe_allow_html=True)


# ── Load configs / models ─────────────────────────────────────
@st.cache_data(ttl=300)
def fetch_models() -> list:
    return llm_client.list_models()


MONITORED_MODELS = ["llama3.3:latest", "qwen3:latest", "mistral:latest"]
if hasattr(llm_client, "HF_MODELS"):
    for hf_m in llm_client.HF_MODELS:
        MONITORED_MODELS.append(f"HuggingFace: {hf_m}")


def _model_provider_and_name(model_name: str) -> tuple[str, str]:
    if model_name.startswith("HuggingFace: "):
        return "HuggingFace", model_name.removeprefix("HuggingFace: ")
    return "Hactar", model_name


def _models_by_provider(models: list[str]) -> dict[str, list[str]]:
    grouped = {"Hactar": [], "HuggingFace": []}
    for model_name in models:
        provider, _ = _model_provider_and_name(model_name)
        grouped.setdefault(provider, []).append(model_name)
    return {provider: items for provider, items in grouped.items() if items}


@st.cache_data(ttl=60, show_spinner=False)
def fetch_model_status() -> dict:
    return llm_client.check_models_status(MONITORED_MODELS)


@st.cache_data(ttl=30)
def load_configs():
    configs = {}
    for filepath in glob.glob("configs/*.yaml"):
        with open(filepath, "r") as f:
            cfg = yaml.safe_load(f)
            name = cfg.get("domain_name", os.path.basename(filepath))
            configs[name] = cfg
    return configs


configs = load_configs()

if not configs:
    st.error("No domain configs found in configs/. Add a YAML file to get started.")
    st.stop()

# ── Domain grouping ───────────────────────────────────────────
_wikidata_domains = [n for n, c in configs.items() if "wikidata.org" in c.get("endpoint", "")]
_dbpedia_domains  = [n for n, c in configs.items() if "dbpedia.org"  in c.get("endpoint", "")]
_other_domains    = [n for n, c in configs.items() if n not in _wikidata_domains and n not in _dbpedia_domains]

_AUTO = "Auto-detect"
_SEP_WD = "─── Wikidata ───"
_SEP_DB = "─── DBpedia ───"
_SEPARATORS = {_SEP_WD, _SEP_DB}

_default_domain = _wikidata_domains[0] if _wikidata_domains else list(configs.keys())[0]

_all_domain_options = (
    [_AUTO]
    + ([_SEP_WD] + _wikidata_domains if _wikidata_domains else [])
    + ([_SEP_DB] + _dbpedia_domains  if _dbpedia_domains  else [])
    + _other_domains
)

def _resolve_domain(selection: str) -> str:
    if selection in _SEPARATORS or selection not in configs:
        return _default_domain
    return selection


def _use_example(question: str) -> None:
    # Use a pending pattern (same as _pending_model) so the domain selectbox
    # is not reset by Streamlit when session state is written inside on_click.
    st.session_state["_pending_nl_input"] = question
    st.session_state["_pending_domain"] = st.session_state.get("selected_domain", _AUTO)

if "selected_domain" not in st.session_state:
    st.session_state.selected_domain = _AUTO

domain = _resolve_domain(st.session_state.get("selected_domain", _default_domain))
config = configs[domain]

# One example per domain, ordered to spread across knowledge bases
_cross_domain_sparql_examples = [
    dict(ex, domain_name=name)
    for name, cfg in configs.items()
    for ex in cfg.get("few_shot_examples", [])[:1]
]


def detect_endpoint(query: str, configs: dict, fallback_config: dict) -> tuple:
    """Detect which SPARQL endpoint to use based on prefix keywords in the query."""
    q = query.lower()
    if "wd:" in q or "wdt:" in q or "wikibase:label" in q:
        for name, cfg in configs.items():
            if "wikidata" in cfg.get("endpoint", "").lower():
                return cfg["endpoint"], name
    if "dbo:" in q or "dbr:" in q or "dbp:" in q:
        for name, cfg in configs.items():
            if "dbpedia" in cfg.get("endpoint", "").lower():
                return cfg["endpoint"], name
    return fallback_config.get("endpoint"), None


WD_URI = "http://www.wikidata.org/entity/"
WDT_URI = "http://www.wikidata.org/prop/direct/"
RDFS_URI = "http://www.w3.org/2000/01/rdf-schema#"
LAMIA_URI = "https://group-b-lamia.unige.ch/kg/"
LAMIA_ONTOLOGY_URI = "https://group-b-lamia.unige.ch/kg/ontology"

_WD_ENTITY_RE = re.compile(r'^https?://www\.wikidata\.org/entity/(Q\d+)$')
_QID_BARE_RE  = re.compile(r'^(Q\d+)$')


def _cell_html(value: str) -> str:
    """Return an HTML snippet for a single result cell.

    - Bare QIDs (Q42) and full Wikidata entity URIs are turned into
      clickable links that open the Wikidata item page.
    - Other values are HTML-escaped plain text.
    """
    v = str(value or "").strip()
    # Full Wikidata entity URI  →  QID link
    m = _WD_ENTITY_RE.match(v)
    if m:
        qid = m.group(1)
        url = f"https://www.wikidata.org/wiki/{qid}"
        return f'<a href="{url}" target="_blank" rel="noopener">{html.escape(qid)}</a>'
    # Bare QID (already shortened by executor)
    m = _QID_BARE_RE.match(v)
    if m:
        qid = m.group(1)
        url = f"https://www.wikidata.org/wiki/{qid}"
        return f'<a href="{url}" target="_blank" rel="noopener">{html.escape(qid)}</a>'
    return html.escape(v)


def _render_results_table(rows: list) -> None:
    """Render a list-of-dicts result set as an HTML table with Wikidata links."""
    if not rows:
        return
    columns = list(rows[0].keys())
    header = "".join(f"<th>{html.escape(c)}</th>" for c in columns)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{_cell_html(row.get(c, ''))}</td>" for c in columns)
        body_rows.append(f"<tr>{cells}</tr>")
    body = "\n".join(body_rows)
    table_html = f"""
<div style="overflow-x:auto;">
<table class="wd-result-table">
  <thead><tr>{header}</tr></thead>
  <tbody>{body}</tbody>
</table>
</div>
<style>
.wd-result-table {{
    width: 100%;
    border-collapse: collapse;
    font-family: var(--font-sans);
    font-size: 0.82rem;
    color: var(--text);
}}
.wd-result-table th {{
    background: var(--header-bg);
    color: var(--text-muted);
    font-size: 0.7rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    padding: 7px 12px;
    border-bottom: 1.5px solid var(--border-strong);
    text-align: left;
    white-space: nowrap;
}}
.wd-result-table td {{
    padding: 6px 12px;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
    word-break: break-word;
}}
.wd-result-table tr:last-child td {{
    border-bottom: none;
}}
.wd-result-table tr:hover td {{
    background: var(--accent-light);
}}
.wd-result-table a {{
    color: var(--accent);
    text-decoration: none;
    font-family: var(--font-mono);
    font-size: 0.78rem;
    background: var(--info-bg);
    border: 1px solid var(--info-border);
    border-radius: 3px;
    padding: 1px 5px;
}}
.wd-result-table a:hover {{
    text-decoration: underline;
    background: var(--accent-light);
}}
</style>
"""
    st.markdown(table_html, unsafe_allow_html=True)


def _slug_uri_part(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value).strip()).strip("_")
    return slug or "item"


def _humanize_var_name(value: str) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value or ""))
    text = re.sub(r"[_-]+", " ", text).strip()
    return text.title() or "Entity"


def _class_uri_for_var(value: str):
    from rdflib import URIRef

    return URIRef(f"{LAMIA_URI}class/{_slug_uri_part(value)}")


def _result_value_to_uri(value: str):
    from rdflib import URIRef

    value = str(value or "").strip()
    if value.startswith(("http://", "https://")):
        return URIRef(value)
    if re.fullmatch(r"Q\d+", value):
        return URIRef(f"{WD_URI}{value}")
    return URIRef(f"{LAMIA_URI}entity/{_slug_uri_part(value)}")


def _expand_prefixed_name(token: str, prefixes: dict):
    token = token.strip().strip("<>")
    if token.startswith(("http://", "https://")):
        return token
    if ":" not in token:
        return None
    prefix, local = token.split(":", 1)
    base = prefixes.get(prefix)
    return f"{base}{local}" if base else None


def _infer_predicate_uri(query: str, src_k: str, tgt_k: str):
    from rdflib import URIRef

    prefixes = {
        "wdt": WDT_URI,
        "rdfs": RDFS_URI,
        "lamia": LAMIA_URI,
    }
    for prefix, uri in re.findall(r"(?im)^\s*PREFIX\s+([A-Za-z][\w-]*):\s*<([^>]+)>", query):
        prefixes[prefix] = uri

    pattern = rf"\?{re.escape(src_k)}\s+([A-Za-z][\w-]*:[^\s;.]+|<[^>]+>)\s+\?{re.escape(tgt_k)}"
    match = re.search(pattern, query)
    if match:
        expanded = _expand_prefixed_name(match.group(1), prefixes)
        if expanded:
            return URIRef(expanded)

    return URIRef(f"{LAMIA_URI}relation/{_slug_uri_part(src_k)}_to_{_slug_uri_part(tgt_k)}")


def build_turtle_export(rows: list, query: str, uri_cols: list, label_map: dict) -> str:
    """Serialize visualized query results as Turtle for Protege import."""
    from rdflib import Graph, Literal, Namespace, URIRef
    from rdflib.namespace import OWL, RDF
    from rdflib.namespace import RDFS

    WD = Namespace(WD_URI)
    WDT = Namespace(WDT_URI)
    LAMIA = Namespace(LAMIA_URI)
    graph = Graph()
    graph.bind("wd", WD)
    graph.bind("wdt", WDT)
    graph.bind("rdfs", RDFS)
    graph.bind("lamia", LAMIA)
    graph.bind("owl", OWL)
    graph.bind("rdf", RDF)
    graph.add((URIRef(LAMIA_ONTOLOGY_URI), RDF.type, OWL.Ontology))

    if len(uri_cols) >= 2:
        src_k, tgt_k = uri_cols[0], uri_cols[1]
        # Only use label_map values when a true label column exists (key != value)
        src_lk = label_map.get(src_k)
        tgt_lk = label_map.get(tgt_k)
        src_class = _class_uri_for_var(src_k)
        tgt_class = _class_uri_for_var(tgt_k)
        predicate = _infer_predicate_uri(query, src_k, tgt_k)

        graph.add((src_class, RDF.type, OWL.Class))
        graph.add((src_class, RDFS.subClassOf, OWL.Thing))
        graph.add((src_class, RDFS.label, Literal(_humanize_var_name(src_k), lang="en")))
        graph.add((tgt_class, RDF.type, OWL.Class))
        graph.add((tgt_class, RDFS.subClassOf, OWL.Thing))
        graph.add((tgt_class, RDFS.label, Literal(_humanize_var_name(tgt_k), lang="en")))
        graph.add((predicate, RDF.type, OWL.ObjectProperty))
        graph.add((predicate, RDFS.domain, src_class))
        graph.add((predicate, RDFS.range, tgt_class))
        graph.add((predicate, RDFS.label, Literal(f"{_humanize_var_name(src_k)} to {_humanize_var_name(tgt_k)}", lang="en")))

        _seen_triples: set = set()
        for row in rows:
            if not row.get(src_k) or not row.get(tgt_k):
                continue
            source = _result_value_to_uri(row.get(src_k, ""))
            target = _result_value_to_uri(row.get(tgt_k, ""))
            triple_key = (str(source), str(target))
            graph.add((source, RDF.type, OWL.NamedIndividual))
            graph.add((source, RDF.type, src_class))
            graph.add((target, RDF.type, OWL.NamedIndividual))
            graph.add((target, RDF.type, tgt_class))
            if triple_key not in _seen_triples:
                graph.add((source, predicate, target))
                _seen_triples.add(triple_key)
            if src_lk and row.get(src_lk):
                graph.add((source, RDFS.label, Literal(row[src_lk], lang="en")))
            if tgt_lk and row.get(tgt_lk):
                graph.add((target, RDFS.label, Literal(row[tgt_lk], lang="en")))
    else:
        entity_k = uri_cols[0] if uri_cols else next(iter(rows[0].keys()))
        entity_lk = label_map.get(entity_k)
        center_name = _humanize_var_name(entity_k) + "s" if not entity_k.lower().endswith("s") else _humanize_var_name(entity_k)
        center = URIRef(f"{LAMIA_URI}concept/{_slug_uri_part(entity_k)}")
        predicate = URIRef(f"{LAMIA_URI}relation/has_member")
        center_class = URIRef(f"{LAMIA_URI}class/concept")
        entity_class = _class_uri_for_var(entity_k)

        graph.add((center_class, RDF.type, OWL.Class))
        graph.add((center_class, RDFS.subClassOf, OWL.Thing))
        graph.add((center_class, RDFS.label, Literal("Concept", lang="en")))
        graph.add((entity_class, RDF.type, OWL.Class))
        graph.add((entity_class, RDFS.subClassOf, OWL.Thing))
        graph.add((entity_class, RDFS.label, Literal(_humanize_var_name(entity_k), lang="en")))
        graph.add((center, RDF.type, OWL.NamedIndividual))
        graph.add((center, RDF.type, center_class))
        graph.add((predicate, RDF.type, OWL.ObjectProperty))
        graph.add((predicate, RDFS.domain, center_class))
        graph.add((predicate, RDFS.range, entity_class))
        graph.add((predicate, RDFS.label, Literal("Has Member", lang="en")))
        graph.add((center, RDFS.label, Literal(center_name, lang="en")))

        for row in rows:
            if not row.get(entity_k):
                continue
            entity = _result_value_to_uri(row.get(entity_k, ""))
            graph.add((entity, RDF.type, OWL.NamedIndividual))
            graph.add((entity, RDF.type, entity_class))
            graph.add((center, predicate, entity))
            if entity_lk and row.get(entity_lk):
                graph.add((entity, RDFS.label, Literal(row[entity_lk], lang="en")))

    return graph.serialize(format="turtle")


# ── Header ────────────────────────────────────────────────────
st.markdown("""
<h1 class="app-title">NL ↔ SPARQL<span class="app-pill">Research Prototype</span></h1>
<p class="app-sub">Bidirectional translation between natural language and SPARQL &mdash; powered by the Hactar LLM</p>
<hr class="app-divider">
""", unsafe_allow_html=True)


# ── Sidebar ───────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<span class="sb-logo">◈ NL-SPARQL</span>', unsafe_allow_html=True)

    st.markdown('<span class="sb-label">Language Model</span>', unsafe_allow_html=True)
    models = fetch_models()
    if models:
        preferred_models = ["llama3.3:latest", "llama3:latest", "llama3.2:3b", "qwen3.5:9b", "qwen3:8b"]
        if hasattr(llm_client, "HF_MODELS"):
            for hf_m in reversed(llm_client.HF_MODELS):
                preferred_models.insert(0, f"HuggingFace: {hf_m}")
        default_model = next((m for m in preferred_models if m in models), models[0])
        default_idx = models.index(default_model)
        model = st.selectbox("Model", models, index=default_idx, key="selected_model", label_visibility="collapsed")
    else:
        if "selected_model" not in st.session_state:
            st.session_state.selected_model = "llama3.3:latest"
        model = st.text_input("Model", key="selected_model", label_visibility="collapsed")
        st.warning("Could not fetch model list from Hactar.")

    _sh, _sr = st.columns([5, 1])
    with _sh:
        st.markdown('<span class="sb-label">Model Status</span>', unsafe_allow_html=True)
    with _sr:
        if st.button("↺", key="refresh_model_status", help="Refresh model status"):
            fetch_model_status.clear()
            st.rerun()
    _status = fetch_model_status()
    for _provider, _provider_models in _models_by_provider(MONITORED_MODELS).items():
        st.markdown(
            f'<div class="model-provider-heading">{html.escape(_provider)}</div>',
            unsafe_allow_html=True,
        )
        for _m in _provider_models:
            _model_provider, _display_name = _model_provider_and_name(_m)
            _ok = _status.get(_m, False)
            _dot_color = "#22c55e" if _ok else "#9ca3af"
            _state = "Running" if _ok else "Offline"
            _badge_bg = "var(--success-bg)" if _ok else "rgba(100,80,160,0.05)"
            _badge_fg = "var(--success-text)" if _ok else "var(--text-subtle)"
            _badge_bd = "var(--success-border)" if _ok else "var(--border)"
            _dot_cls = "model-dot-ok" if _ok else ""
            _c1, _c2 = st.columns([5, 1])
            with _c1:
                st.markdown(
                    f'<div class="model-status-card">'
                    f'<span class="{_dot_cls}" style="width:7px;height:7px;border-radius:50%;'
                    f'background:{_dot_color};flex-shrink:0;display:inline-block;"></span>'
                    f'<span class="model-name" data-tooltip="{html.escape(_m)}">{html.escape(_display_name)}</span>'
                    f'<span class="model-state-tag" style="background:{_badge_bg};'
                    f'color:{_badge_fg};border:1px solid {_badge_bd};">{_state}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with _c2:
                if _ok:
                    if st.button("→", key=f"sw_{_m}", help=f"Switch to {_m}"):
                        st.session_state._pending_model = _m
                        fetch_model_status.clear()
                        st.rerun()
                else:
                    st.button("→", key=f"sw_{_m}", disabled=True)

    st.markdown('<span class="sb-label">Options</span>', unsafe_allow_html=True)
    enable_summary = st.checkbox(
        "Summarize results in plain English",
        value=True,
        help="Ask the LLM to produce a concise answer from the raw query results",
    )
    wikidata_only = st.toggle(
        "Wikidata lookup only",
        key="wikidata_only",
        help="Skip domain selection. Uses Wikidata entity lookup with a generic prompt — no domain-specific examples or ontology hints.",
    )

    st.markdown("---")
    st.markdown('<span class="sb-label">Appearance</span>', unsafe_allow_html=True)
    st.toggle("Dark mode", key="dark_mode")

    st.markdown('<span class="sb-label">Endpoints</span>', unsafe_allow_html=True)
    _active_ep = WIKIDATA_GENERIC_CONFIG["endpoint"] if wikidata_only else config.get("endpoint", "")
    _seen_eps = {}
    for _cfg in configs.values():
        _ep = _cfg.get("endpoint", "")
        if _ep and _ep not in _seen_eps:
            if "wikidata.org" in _ep:
                _seen_eps[_ep] = "Wikidata"
            elif "dbpedia.org" in _ep:
                _seen_eps[_ep] = "DBpedia"
            else:
                _seen_eps[_ep] = _ep
    for _ep, _label in _seen_eps.items():
        _active_style = "font-weight:600;" if _ep == _active_ep else "opacity:0.45;"
        st.markdown(
            f'<span class="sb-endpoint" style="{_active_style}">{_label} — {_ep}</span>',
            unsafe_allow_html=True,
        )


# ── Tag palette ───────────────────────────────────────────────
if st.session_state.dark_mode:
    TAG_COLORS = {
        "Simple":    ("#0D2118", "#6EE7A0"),
        "Lookup":    ("#0D1A2E", "#93C5FD"),
        "Filter":    ("#1E180A", "#FCD34D"),
        "Join":      ("#1A1030", "#C4B5FD"),
        "Aggregate": ("#1F0D16", "#FDA4AF"),
        "Path":      ("#0D1E22", "#67E8F9"),
    }
else:
    TAG_COLORS = {
        "Simple":    ("#DCFCE7", "#15803D"),
        "Lookup":    ("#DBEAFE", "#1D4ED8"),
        "Filter":    ("#FEF3C7", "#B45309"),
        "Join":      ("#EDE9FE", "#7C3AED"),
        "Aggregate": ("#FFE4E6", "#BE123C"),
        "Path":      ("#CFFAFE", "#0E7490"),
    }


# ── Tabs ──────────────────────────────────────────────────────
chat_tab, tab1, tab3, tab2, tab4 = st.tabs(["Chat", "Natural Language → SPARQL", "SPARQL → Natural Language", "Knowledge Graph (Experimental)", "Model Arena"])

# ── Chat tab ──────────────────────────────────────────────────
with chat_tab:
    render_chat_tab(st.session_state.chat_memory, configs, model, wikidata_only=wikidata_only)


# ── Tab 1: NL → SPARQL ────────────────────────────────────────
with tab1:
    def _on_domain_change():
        val = st.session_state.selected_domain
        if val == _SEP_WD:
            st.session_state.selected_domain = _wikidata_domains[0] if _wikidata_domains else "Auto"
        elif val == _SEP_DB:
            st.session_state.selected_domain = _dbpedia_domains[0] if _dbpedia_domains else "Auto"

    domain = _resolve_domain(st.session_state.selected_domain)
    config = configs[domain]

    examples = config.get("example_questions", [])
    if examples:
        st.markdown('<span class="s-label">Quick examples</span>', unsafe_allow_html=True)
        short_domain = domain.split("(")[0].strip()
        num_cols = 3
        rows = [examples[i:i + num_cols] for i in range(0, len(examples), num_cols)]

        for row_idx, row in enumerate(rows):
            cols = st.columns(num_cols, gap="small")
            for col_idx, ex in enumerate(row):
                q = ex["question"] if isinstance(ex, dict) else ex
                tag = ex.get("tag", "") if isinstance(ex, dict) else ""
                bg, fg = TAG_COLORS.get(tag, ("#2A2925", "#9E9790") if st.session_state.dark_mode else ("#F0EFEC", "#78716C"))
                idx = row_idx * num_cols + col_idx

                type_tag_html = (
                    f'<span class="qx-tag" style="background:{bg};color:{fg};">{tag}</span>'
                    if tag else ""
                )

                with cols[col_idx]:
                    st.markdown(
                        f'<div class="qx-card">'
                        f'  <div class="qx-tags">'
                        f'    <span class="qx-tag qx-tag-domain">{short_domain}</span>'
                        f'    {type_tag_html}'
                        f'  </div>'
                        f'  <div class="qx-q">{q}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                    st.button(
                        "Use this →",
                        key=f"ex_{idx}",
                        use_container_width=True,
                        on_click=_use_example,
                        args=(q,),
                    )

    st.markdown('<span class="s-label" style="margin-top:1.5rem;display:block;">Your question</span>', unsafe_allow_html=True)
    question = st.text_area(
        "Question",
        key="nl_input",
        placeholder="e.g. What are the symptoms of diabetes?",
        height=90,
        label_visibility="collapsed",
    )

    col_btn, col_domain = st.columns([3, 2], vertical_alignment="bottom")
    with col_btn:
        run_nl = st.button("Translate & Execute", type="primary", key="nl_go", use_container_width=True)
    with col_domain:
        if wikidata_only:
            st.markdown(
                '<div style="padding:8px 12px;border:1px solid var(--border);border-radius:6px;'
                'font-size:0.82rem;color:var(--text-muted);">Wikidata (Generic)</div>',
                unsafe_allow_html=True,
            )
        else:
            st.selectbox(
                "Domain",
                _all_domain_options,
                key="selected_domain",
                on_change=_on_domain_change,
                label_visibility="collapsed",
            )

    if run_nl:
        if not question.strip():
            st.warning("Please enter a question.")
        else:
            _MSGS = {
                "generate": [
                    "Figuring out what you meant...",
                    "Turning words into something a database understands...",
                    "Writing SPARQL so you don't have to...",
                    "Making sense of your question...",
                ],
                "execute": [
                    "Bothering Wikidata...",
                    "Waiting for the internet...",
                    "Sending it off, fingers crossed...",
                    "Asking the knowledge base nicely...",
                ],
                "summarize": [
                    "Reading the raw data so you don't have to...",
                    "Making the results sound like English...",
                    "Putting it into words...",
                    "Almost there...",
                ],
            }

            _bar = st.empty()
            _step = st.empty()
            _t0 = time.time()

            def _bar_running(placeholder, msg):
                placeholder.markdown(f"""
<style>
@keyframes _kf_slide {{
    0%   {{ left: -35%; }}
    100% {{ left: 110%; }}
}}
</style>
<div style="margin:6px 0 2px;">
<div style="position:relative;width:100%;height:3px;background:var(--border);border-radius:2px;overflow:hidden;">
  <div style="position:absolute;height:100%;width:35%;background:var(--accent);border-radius:2px;
              animation:_kf_slide 1.4s ease-in-out infinite;"></div>
</div>
</div>
<div style="font-size:0.78rem;color:var(--text-muted);margin-top:4px;">{msg}</div>
""", unsafe_allow_html=True)

            def _bar_done(placeholder, pct, msg):
                placeholder.markdown(f"""
<div style="margin:6px 0 2px;">
<div style="width:100%;height:3px;background:var(--border);border-radius:2px;overflow:hidden;">
  <div style="width:{pct}%;height:100%;background:var(--accent);border-radius:2px;"></div>
</div>
</div>
<div style="font-size:0.78rem;color:var(--text-muted);margin-top:4px;">{msg}</div>
""", unsafe_allow_html=True)

            # Resolve config (auto-detect if needed)
            _bar_running(_bar, random.choice(_MSGS["generate"]))
            if wikidata_only:
                _nl_config = WIKIDATA_GENERIC_CONFIG
                st.info("Wikidata lookup only — domain selection disabled.")
            elif st.session_state.get("selected_domain") == _AUTO:
                _detected_name = domain_router.detect_domain(question, configs, model=model)
                _nl_config = configs[_detected_name]
                st.info(f"Auto-detected domain: {_detected_name}")
            else:
                _nl_config = config

            # Run shared fixed pipeline
            _pr = kg_pipeline.run_pipeline(question, _nl_config, model)
            _bar_done(_bar, 33, "SPARQL generated.")

            # LLM extraction card (Wikidata mode only)
            if _pr.llm_terms:
                _ents = _pr.llm_terms.get("entities", [])
                _rels = _pr.llm_terms.get("relations", [])
                _lbl = (
                    f"LLM extraction · "
                    f"{len(_ents)} {'entity' if len(_ents) == 1 else 'entities'}, "
                    f"{len(_rels)} {'relation' if len(_rels) == 1 else 'relations'}"
                )
                with st.expander(_lbl, expanded=False):
                    if _ents:
                        st.caption("Entities:")
                        for _e in _ents:
                            st.markdown(f"- `{_e}`")
                    if _rels:
                        st.caption("Relations:")
                        for _r in _rels:
                            st.markdown(f"- `{_r}`")
                    if not _ents and not _rels:
                        st.caption("LLM returned no entities or relations for this question.")

            # Entity lookup display
            if _pr.entity_hints or _pr.predicate_hints:
                _expander_label = f"Entity lookup · {len(_pr.entity_hints)} resolved" if _pr.entity_hints else "Entity lookup · 0 entities"
                with st.expander(_expander_label, expanded=False):
                    for _h in _pr.entity_hints:
                        st.markdown(f'**"{_h["surface"]}"** → `wd:{_h["qid"]}` — {_h["description"]}')
                    if _pr.predicate_hints:
                        st.caption("Predicate hints:")
                        for _p in _pr.predicate_hints:
                            st.markdown(f'**"{_p["surface"]}"** → `{_p["pid"]}` — {_p["label"]}')
            elif "wikidata.org" in _nl_config.get("endpoint", ""):
                with st.expander("Entity lookup · no entities found", expanded=False):
                    st.caption("No named entities were detected in this question.")

            # SPARQL display
            if _pr.sparql:
                _expander_title = "Retry SPARQL" if _pr.retried else "Generated SPARQL"
                with st.expander(_expander_title, expanded=False):
                    st.code(_pr.sparql, language="sparql")

            _bar_done(_bar, 66, "Query executed.")

            # Results display
            if _pr.found_in_kg and _pr.results:
                n = len(_pr.results)
                with st.expander(f"Raw results · {n} row{'s' if n != 1 else ''}", expanded=False):
                    _render_results_table(_pr.results)
            elif _pr.sparql:
                st.warning(
                    "No results found for your query. "
                    "This may mean the information is not available in the knowledge base, "
                    "or the question could not be translated into a matching query. "
                    "Try rephrasing or narrowing your question."
                )
                with st.expander("View generated SPARQL", expanded=False):
                    st.code(_pr.sparql, language="sparql")
            else:
                st.error("Could not generate a SPARQL query for this question.")

            # Summary display
            if _pr.found_in_kg and _pr.results and enable_summary:
                if _pr.summary:
                    _bar_done(_bar, 100, f"Done. That took {time.time() - _t0:.1f}s.")
                    st.markdown('<span class="s-label" style="margin-top:1.25rem;display:block;">Answer</span>', unsafe_allow_html=True)
                    st.info(_pr.summary)
                else:
                    _bar_done(_bar, 100, f"Done. That took {time.time() - _t0:.1f}s.")
            else:
                _bar_done(_bar, 100, f"Done. That took {time.time() - _t0:.1f}s.")


# ── Tab 2: Knowledge Graph ────────────────────────────────────
with tab2:
    st.markdown(
        '<span class="s-label">Graph query</span>'
        '<p style="font-size:0.82rem;color:var(--text-muted);margin:-2px 0 10px;">'
        'Write a SELECT query and visualize the results as an interactive network. '
        'Queries with <strong>2+ entity columns</strong> (e.g. disease → drug) produce a relationship graph. '
        'Flat lists (single entity) produce a star graph around a central concept node.</p>',
        unsafe_allow_html=True,
    )

    # Example graph queries
    _graph_examples = {
        "Philosopher influences": (
            "SELECT ?philosopher ?philosopherLabel ?influence ?influenceLabel WHERE {\n"
            "  ?philosopher wdt:P737 ?influence .\n"
            "  ?philosopher wdt:P106 wd:Q4964182 .\n"
            "  SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . }\n"
            "}\n"
            "LIMIT 40"
        ),
        "Diseases & symptoms": (
            "SELECT ?disease ?diseaseLabel ?symptom ?symptomLabel WHERE {\n"
            "  ?disease wdt:P31 wd:Q12136 .\n"
            "  ?disease wdt:P780 ?symptom .\n"
            "  SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . }\n"
            "}\n"
            "LIMIT 30"
        ),
        "Diseases & treatments": (
            "SELECT ?disease ?diseaseLabel ?drug ?drugLabel WHERE {\n"
            "  ?disease wdt:P31 wd:Q12136 .\n"
            "  ?disease wdt:P2176 ?drug .\n"
            "  SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . }\n"
            "}\n"
            "LIMIT 30"
        ),
        "Scientists & advisors": (
            "SELECT ?student ?studentLabel ?advisor ?advisorLabel WHERE {\n"
            "  ?student wdt:P184 ?advisor .\n"
            "  ?student wdt:P106 wd:Q901 .\n"
            "  SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . }\n"
            "}\n"
            "LIMIT 40"
        ),
    }

    st.markdown('<span class="s-label" style="margin-top:0.5rem;display:block;">Try an example</span>', unsafe_allow_html=True)
    _gcols = st.columns(len(_graph_examples), gap="small")
    for i, (label, sparql_text) in enumerate(_graph_examples.items()):
        with _gcols[i]:
            if st.button(label, key=f"graph_ex_{i}", use_container_width=True):
                st.session_state["graph_input"] = sparql_text
                st.rerun()

    if "graph_input" not in st.session_state:
        st.session_state["graph_input"] = list(_graph_examples.values())[0]
    graph_query = st.text_area(
        "Graph SPARQL",
        key="graph_input",
        height=160,
        placeholder="SELECT ?source ?sourceLabel ?target ?targetLabel WHERE { ... } LIMIT 50",
        label_visibility="collapsed",
    )

    # Controls: layout selector + physics toggle + visualize button
    _ctrl_col1, _ctrl_col2, _ctrl_col3 = st.columns([2, 2, 1])
    with _ctrl_col1:
        _graph_layout = st.selectbox(
            "Layout", ["Force-directed", "Hierarchical"],
            key="graph_layout",
        )
    with _ctrl_col2:
        st.markdown('<div style="height:0.35rem"></div>', unsafe_allow_html=True)
        _show_physics = st.checkbox("Physics controls", key="graph_physics", value=False)
    with _ctrl_col3:
        st.markdown('<div style="height:1.55rem"></div>', unsafe_allow_html=True)
        run_graph = st.button("Visualize", type="primary", key="graph_go", use_container_width=True)

    if run_graph:
        if not graph_query.strip():
            st.warning("Please enter a SPARQL query.")
        else:
            _graph_fallback = list(configs.values())[0]
            _graph_ep, _graph_domain = detect_endpoint(graph_query, configs, _graph_fallback)

            with st.spinner("Fetching data..."):
                graph_result = sparql_executor.execute(graph_query, _graph_ep)

            if not graph_result["success"]:
                st.error(f"Query failed: {graph_result['error']}")
            elif not graph_result["results"]:
                st.info("Query returned no results.")
            else:
                rows = graph_result["results"]
                _uri_cols, _label_map = detect_label_uri_columns(rows)

                # Store for path finder
                st.session_state["_graph_rows"]      = rows
                st.session_state["_graph_uri_cols"]  = _uri_cols
                st.session_state["_graph_label_map"] = _label_map
                st.session_state["_graph_query"]     = graph_result.get("query", graph_query)

                # Enhanced stats
                if len(_uri_cols) >= 2:
                    _src_nodes = {r.get(_uri_cols[0]) for r in rows if r.get(_uri_cols[0])}
                    _tgt_nodes = {r.get(_uri_cols[1]) for r in rows if r.get(_uri_cols[1])}
                    _unique_nodes = len(_src_nodes | _tgt_nodes)
                    _unique_edges = len({
                        (r.get(_uri_cols[0]), r.get(_uri_cols[1]))
                        for r in rows if r.get(_uri_cols[0]) and r.get(_uri_cols[1])
                    })
                    _degree: dict[str, int] = {}
                    for _r in rows:
                        for _col in (_uri_cols[0], _uri_cols[1]):
                            _v = _r.get(_col, "")
                            if _v:
                                _degree[_v] = _degree.get(_v, 0) + 1
                    _hub_id  = max(_degree, key=_degree.get) if _degree else ""
                    _hub_lbl_col = _label_map.get(_uri_cols[0]) or _label_map.get(_uri_cols[1])
                    _hub_lbl = next(
                        (r.get(_hub_lbl_col, _hub_id) for r in rows
                         if r.get(_uri_cols[0]) == _hub_id or r.get(_uri_cols[1]) == _hub_id),
                        _hub_id,
                    ) if _hub_lbl_col else _hub_id
                    _avg_deg = round(sum(_degree.values()) / len(_degree), 1) if _degree else 0
                    st.markdown(
                        f'<span class="s-label" style="margin-top:0.75rem;display:block;">'
                        f'{_unique_nodes} nodes &nbsp;·&nbsp; {_unique_edges} edges &nbsp;·&nbsp;'
                        f' avg degree {_avg_deg} &nbsp;·&nbsp; hub: <em>{_hub_lbl or _hub_id}</em></span>',
                        unsafe_allow_html=True,
                    )
                else:
                    _entity_k   = _uri_cols[0] if _uri_cols else list(rows[0].keys())[0]
                    _n_entities = len({r.get(_entity_k) for r in rows if r.get(_entity_k)})
                    st.markdown(
                        f'<span class="s-label" style="margin-top:0.75rem;display:block;">'
                        f'{_n_entities + 1} nodes &nbsp;·&nbsp; {_n_entities} edges (star layout)</span>',
                        unsafe_allow_html=True,
                    )

                _layout_key = "hierarchical" if _graph_layout == "Hierarchical" else "force"

                try:
                    _graph_html = build_pyvis_html(
                        rows, graph_query,
                        dark=st.session_state.dark_mode,
                        height_px=570,
                        layout=_layout_key,
                        show_physics_controls=_show_physics,
                    )
                    components.html(_graph_html, height=600, scrolling=False)

                    try:
                        ttl_data = build_turtle_export(rows, graph_result["query"], _uri_cols, _label_map)
                        st.download_button(
                            "Download Turtle (.ttl)",
                            data=ttl_data,
                            file_name="knowledge_graph.ttl",
                            mime="text/turtle",
                            use_container_width=False,
                        )
                    except Exception as export_error:
                        st.warning(f"Graph rendered, but Turtle export failed: {export_error}")

                except ImportError:
                    st.error("pyvis is not installed. Run: `pip install pyvis`")
                except Exception as graph_error:
                    st.error(f"Graph rendering failed: {graph_error}")

                with st.expander(f"Raw results · {len(rows)} rows", expanded=False):
                    _render_results_table(rows)

    # Path Finder — shown once a relational graph has been rendered
    if (
        st.session_state.get("_graph_rows")
        and len(st.session_state.get("_graph_uri_cols", [])) >= 2
    ):
        with st.expander("Path Finder", expanded=False):
            try:
                import networkx as nx

                _pf_rows     = st.session_state["_graph_rows"]
                _pf_uri_cols = st.session_state["_graph_uri_cols"]
                _pf_lmap     = st.session_state["_graph_label_map"]
                _pf_query    = st.session_state.get("_graph_query", "")

                _src_col  = _pf_uri_cols[0]
                _tgt_col  = _pf_uri_cols[1]
                _slbl_col = _pf_lmap.get(_src_col)
                _tlbl_col = _pf_lmap.get(_tgt_col)

                _id_to_label: dict[str, str] = {}
                for _r in _pf_rows:
                    _s = _r.get(_src_col, "")
                    _t = _r.get(_tgt_col, "")
                    if _s:
                        _id_to_label[_s] = (_r.get(_slbl_col, _s) or _s) if _slbl_col else _s
                    if _t:
                        _id_to_label[_t] = (_r.get(_tlbl_col, _t) or _t) if _tlbl_col else _t

                _node_options = sorted(_id_to_label.values())
                _label_to_id  = {v: k for k, v in _id_to_label.items()}

                _pf_c1, _pf_c2, _pf_c3 = st.columns([2, 2, 1])
                with _pf_c1:
                    _src_sel = st.selectbox("From node", _node_options, key="pf_src")
                with _pf_c2:
                    _tgt_sel = st.selectbox("To node", list(reversed(_node_options)), key="pf_tgt")
                with _pf_c3:
                    st.markdown('<div style="height:1.55rem"></div>', unsafe_allow_html=True)
                    _find_path = st.button("Find Path", key="pf_go", use_container_width=True)

                if _find_path:
                    _G = nx.DiGraph()
                    for _r in _pf_rows:
                        _s = _r.get(_src_col, "")
                        _t = _r.get(_tgt_col, "")
                        if _s and _t:
                            _G.add_edge(_s, _t)

                    _src_id = _label_to_id.get(_src_sel, _src_sel)
                    _tgt_id = _label_to_id.get(_tgt_sel, _tgt_sel)

                    try:
                        _path = nx.shortest_path(_G, source=_src_id, target=_tgt_id)
                        _path_labels = [_id_to_label.get(n, n) for n in _path]
                        st.success(
                            f"Path ({len(_path) - 1} hops): "
                            + " → ".join(f"**{l}**" for l in _path_labels)
                        )
                        _layout_key = "hierarchical" if st.session_state.get("graph_layout") == "Hierarchical" else "force"
                        _path_html = build_pyvis_html(
                            _pf_rows, _pf_query,
                            dark=st.session_state.dark_mode,
                            height_px=500,
                            layout=_layout_key,
                            highlight_path=_path,
                        )
                        components.html(_path_html, height=530, scrolling=False)
                    except nx.NetworkXNoPath:
                        st.warning(f"No path found from **{_src_sel}** to **{_tgt_sel}**.")
                    except nx.NodeNotFound as _e:
                        st.warning(f"Node not in graph: {_e}")

            except ImportError:
                st.info("Install networkx to use path finder: `pip install networkx`")

# ── Tab 3: SPARQL → NL ────────────────────────────────────────
with tab3:
    if _cross_domain_sparql_examples:
        st.markdown('<span class="s-label">Quick examples</span>', unsafe_allow_html=True)
        num_cols_s = 3
        rows_s = [_cross_domain_sparql_examples[i:i + num_cols_s] for i in range(0, len(_cross_domain_sparql_examples), num_cols_s)]

        for row_idx, row in enumerate(rows_s):
            cols = st.columns(num_cols_s, gap="small")
            for col_idx, ex in enumerate(row):
                label = ex.get("question", "")
                sparql_text = ex.get("sparql", "")
                tag = ex.get("tag", "")
                short_d = ex.get("domain_name", "").split("(")[0].strip()
                bg, fg = TAG_COLORS.get(tag, ("#2A2925", "#9E9790") if st.session_state.dark_mode else ("#F0EFEC", "#78716C"))
                idx = row_idx * num_cols_s + col_idx

                type_tag_html = (
                    f'<span class="qx-tag" style="background:{bg};color:{fg};">{tag}</span>'
                    if tag else ""
                )
                domain_tag_html = f'<span class="qx-tag qx-tag-domain">{short_d}</span>' if short_d else ""

                with cols[col_idx]:
                    st.markdown(
                        f'<div class="qx-card">'
                        f'  <div class="qx-tags">'
                        f'    {domain_tag_html}'
                        f'    {type_tag_html}'
                        f'  </div>'
                        f'  <div class="qx-q">{label}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                    st.button(
                        "Load query →",
                        key=f"sparql_ex_{idx}",
                        use_container_width=True,
                        on_click=_replace_widget_text,
                        args=("sparql_input", sparql_text.strip()),
                    )

    st.markdown('<span class="s-label" style="margin-top:1.5rem;display:block;">SPARQL query</span>', unsafe_allow_html=True)
    sparql_input = st.text_area(
        "SPARQL",
        key="sparql_input",
        placeholder="SELECT ?x ?xLabel WHERE { ... }",
        height=200,
        label_visibility="collapsed",
    )

    col_btn2, _ = st.columns([1, 3])
    with col_btn2:
        run_sparql = st.button("Explain in English", type="primary", key="sparql_go", use_container_width=True)

    if run_sparql:
        if not sparql_input.strip():
            st.warning("Please enter a SPARQL query.")
        else:
            _s2nl_fallback = list(configs.values())[0]
            _s2nl_endpoint, _s2nl_domain = detect_endpoint(sparql_input, configs, _s2nl_fallback)
            _s2nl_config = configs[_s2nl_domain] if _s2nl_domain else _s2nl_fallback

            with st.spinner("Translating..."):
                explanation = sparql_to_nl.translate(sparql_input, _s2nl_config, model=model)

            st.markdown('<span class="s-label" style="margin-top:1.25rem;display:block;">Explanation</span>', unsafe_allow_html=True)
            st.info(explanation)
            if _s2nl_domain:
                st.caption(f"Detected domain: {_s2nl_domain} — routing to {_s2nl_endpoint}")

            with st.spinner("Verifying query..."):
                result = sparql_executor.execute(sparql_input, _s2nl_endpoint)

            if result["success"]:
                n = len(result["results"])
                if result["results"]:
                    st.markdown(
                        f'<span class="s-label" style="margin-top:1.25rem;display:block;">Results · {n} row{"s" if n != 1 else ""}</span>',
                        unsafe_allow_html=True,
                    )
                    _render_results_table(result["results"])
                else:
                    st.info("Query executed successfully but returned no results.")
            else:
                st.warning(f"Could not execute: {result['error']}")

# ── Tab 4: Model Arena ────────────────────────────────────────
with tab4:
    st.header("Model Arena")
    st.markdown("Compare SPARQL generation across all monitored models concurrently.")

    # ── Vote persistence helpers ──────────────────────────────
    _VOTES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "arena_votes.json")

    def _load_votes() -> list:
        if not os.path.exists(_VOTES_FILE):
            return []
        try:
            with open(_VOTES_FILE) as _f:
                return json.load(_f)
        except Exception:
            return []

    def _save_rating(question: str, feedbacks: dict) -> None:
        votes = _load_votes()
        votes.append({"question": question, "ts": datetime.now().isoformat(), "ratings": feedbacks})
        with open(_VOTES_FILE, "w") as _f:
            json.dump(votes, _f, indent=2)

    def _leaderboard() -> list:
        totals: dict = {}
        for v in _load_votes():
            if "ratings" in v:
                for m, d in v["ratings"].items():
                    if m not in totals:
                        totals[m] = {"sum": 0, "count": 0}
                    totals[m]["sum"] += d.get("rating", 0)
                    totals[m]["count"] += 1
            elif "model" in v:  # backward-compat with old single-vote format
                m = v["model"]
                if m not in totals:
                    totals[m] = {"sum": 0, "count": 0}
                totals[m]["sum"] += 3
                totals[m]["count"] += 1
        rows = []
        for m, d in totals.items():
            avg = round(d["sum"] / d["count"], 1) if d["count"] else 0
            rows.append({"Model": m, "Avg rating": avg, "Total ratings": d["count"]})
        return sorted(rows, key=lambda x: (-x["Avg rating"], -x["Total ratings"]))

    def _first_val(rows: list):
        if not rows:
            return None
        row = rows[0]
        for k, v in row.items():
            if k.lower().endswith("label"):
                return v.lower().strip()
        return list(row.values())[0].lower().strip() if row else None

    def _sparql_complexity(sparql: str) -> int:
        where = re.search(r'WHERE\s*\{(.+)\}', sparql, re.DOTALL | re.IGNORECASE)
        if not where:
            return 0
        return max(1, len(re.findall(r'\?\w+\s+\S+\s+\S+\s*[.\}]', where.group(1))))

    # Domain selector for Arena
    arena_domain_val = st.selectbox(
        "Select Domain for Arena",
        options=_all_domain_options,
        index=_all_domain_options.index("Auto") if "Auto" in _all_domain_options else 0,
        key="arena_domain"
    )

    a_domain = _resolve_domain(arena_domain_val)
    a_config = configs[a_domain] if a_domain in configs else None

    arena_q = st.text_input("Question:", placeholder="Enter a natural language question...", key="arena_q")

    selected_models = st.multiselect(
        "Models to compare:",
        options=MONITORED_MODELS,
        default=MONITORED_MODELS,
        key="arena_models",
    )

    if st.button("Compare Models", key="arena_run") and arena_q and a_config and selected_models:
        # Reset rating flow so a fresh comparison always starts at step 1
        for _k in ("arena_ratings_submitted", "arena_pending_ratings", "arena_feedback_submitted"):
            st.session_state.pop(_k, None)

        st.markdown(f"**Executing concurrently against {len(selected_models)} models...**")

        endpoint = a_config.get("endpoint", "")

        def run_model_translation(m):
            start_time = time.time()
            try:
                # First attempt
                sparql_raw = nl_to_sparql.translate(arena_q, a_config, model=m)
                cleaned = sparql_executor.clean_sparql(sparql_raw)
                res_exec = sparql_executor.execute(cleaned, endpoint)

                retried = False
                # Retry on error OR 0 rows
                if not res_exec["success"] or len(res_exec.get("results", [])) == 0:
                    retry_prompt = nl_to_sparql.build_retry_prompt(arena_q, a_config, cleaned)
                    retry_raw = llm_client.chat(retry_prompt, model=m)
                    retry_cleaned = sparql_executor.clean_sparql(retry_raw)
                    retry_exec = sparql_executor.execute(retry_cleaned, endpoint)
                    if retry_exec["success"] and len(retry_exec.get("results", [])) > 0:
                        cleaned = retry_cleaned
                        res_exec = retry_exec
                        retried = True

                success = res_exec["success"]
                results = res_exec.get("results", [])[:10]
                row_count = len(res_exec.get("results", [])) if success else 0
                error_msg = res_exec.get("error", "")
                complexity = _sparql_complexity(cleaned)

                # Consistency check: run translation a second time
                try:
                    sparql2 = nl_to_sparql.translate(arena_q, a_config, model=m)
                    cleaned2 = sparql_executor.clean_sparql(sparql2)
                    res2 = sparql_executor.execute(cleaned2, endpoint)
                    results2 = res2.get("results", [])[:10] if res2["success"] else []
                    v1, v2 = _first_val(results), _first_val(results2)
                    consistent = (v1 == v2) if (v1 and v2) else None
                except Exception:
                    consistent = None

                # Explanation (always attempt)
                try:
                    explanation = nl_to_sparql.explain_query(cleaned, arena_q, model=m)
                except Exception:
                    explanation = ""

                # Natural-language answer — always set something
                if success and results:
                    try:
                        nl_answer = nl_to_sparql.results_to_nl(arena_q, results, model=m)
                    except Exception:
                        nl_answer = "No answer found"
                else:
                    nl_answer = "No answer found"

                elapsed = time.time() - start_time
                status = (
                    f"Success ({row_count} row{'s' if row_count != 1 else ''})"
                    if success else f"Error: {error_msg[:60]}"
                )

                return {
                    "model": m,
                    "sparql": cleaned,
                    "status": status,
                    "success": success,
                    "row_count": row_count,
                    "results": results,
                    "explanation": explanation,
                    "nl_answer": nl_answer,
                    "complexity": complexity,
                    "consistent": consistent,
                    "retried": retried,
                    "time": elapsed,
                }
            except Exception as e:
                return {
                    "model": m,
                    "sparql": f"Error: {e}",
                    "status": f"Generation failed: {str(e)[:60]}",
                    "success": False,
                    "row_count": 0,
                    "results": [],
                    "explanation": "",
                    "nl_answer": "No answer found",
                    "complexity": 0,
                    "consistent": None,
                    "retried": False,
                    "time": time.time() - start_time,
                }

        # Side-by-side placeholder columns
        cols = st.columns(len(selected_models))
        placeholders = {}
        for idx, m in enumerate(selected_models):
            with cols[idx]:
                st.markdown(f"### {m}")
                placeholders[m] = st.empty()
                placeholders[m].info("Thinking...")

        all_results = []

        # Run concurrently; update each column as its model finishes
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(selected_models)) as executor:
            future_to_model = {executor.submit(run_model_translation, m): m for m in selected_models}
            for future in concurrent.futures.as_completed(future_to_model):
                res = future.result()
                all_results.append(res)
                m = res["model"]

                with placeholders[m].container():
                    status_icon = "OK" if res["success"] else "FAIL"
                    retry_badge = " [Retried]" if res["retried"] else ""
                    st.markdown(
                        f"**{status_icon}** {res['status']}{retry_badge}  "
                        f"| **Time:** {res['time']:.2f}s"
                    )

                    if res["explanation"]:
                        st.markdown(f"**What it does:** {res['explanation']}")

                    st.info(f"**Answer:** {res['nl_answer']}")

                    if res["results"]:
                        st.dataframe(res["results"], use_container_width=True, hide_index=True)

                    with st.expander("SPARQL query", expanded=False):
                        st.code(res["sparql"], language="sparql")

        # Summary comparison table
        if all_results:
            successful = [r for r in all_results if r["success"] and r["row_count"] > 0]
            winner_model = min(successful, key=lambda r: r["time"])["model"] if successful else None

            first_answers = [_first_val(r["results"]) for r in all_results if r["success"] and r["results"]]
            unique_answers = set(a for a in first_answers if a)
            agreement = (
                "Agree" if len(unique_answers) == 1
                else "Differ" if len(unique_answers) > 1
                else "N/A"
            )

            st.markdown("---")
            st.markdown("**Comparison summary**")
            summary_rows = sorted(all_results, key=lambda r: (-r["success"], -r["row_count"], r["time"]))
            table_data = [
                {
                    "Model": r["model"],
                    "Status": "OK" if r["success"] else "FAIL",
                    "Rows": r["row_count"],
                    "Time (s)": round(r["time"], 2),
                    "Complexity": r["complexity"],
                    "Consistent": (
                        "yes" if r["consistent"] is True
                        else "no" if r["consistent"] is False
                        else "N/A"
                    ),
                    "Retried": "yes" if r["retried"] else "no",
                    "Winner": "Best" if r["model"] == winner_model else "",
                    "Agreement": agreement,
                }
                for r in summary_rows
            ]
            st.dataframe(table_data, use_container_width=True, hide_index=True)

        # Persist results for the voting section below
        st.session_state["arena_results"] = all_results
        st.session_state["arena_question"] = arena_q

    # ── Rating UI (persists across reruns via session state) ──
    _GOOD_REASONS = ["Correct answer", "Clear explanation", "Useful results", "Good SPARQL structure", "Fast response"]
    _BAD_REASONS  = ["Wrong / empty answer", "Bad SPARQL", "Too slow", "Confusing explanation", "Returned irrelevant results"]

    if "arena_results" in st.session_state:
        _res_list = st.session_state["arena_results"]
        _q        = st.session_state["arena_question"]
        _models   = [r["model"] for r in _res_list]

        st.markdown("---")

        # ── Step 1: sliders ──────────────────────────────────
        if not st.session_state.get("arena_ratings_submitted"):
            st.markdown("**Rate each model (0 = unusable · 5 = perfect)**")
            _rating_cols = st.columns(len(_models))
            _pending: dict = {}
            for _i, _m in enumerate(_models):
                with _rating_cols[_i]:
                    _short = _m.split(":")[0].split("/")[-1]
                    _pending[_m] = st.slider(_short, 0, 5, 3, key=f"arena_slider_{_m}")

            if st.button("Submit Ratings", key="arena_submit_ratings"):
                st.session_state["arena_pending_ratings"] = _pending
                st.session_state["arena_ratings_submitted"] = True
                st.rerun()

        # ── Step 2: why + free-text feedback ─────────────────
        elif not st.session_state.get("arena_feedback_submitted"):
            _ratings = st.session_state["arena_pending_ratings"]
            st.markdown("**Tell us more about your ratings**")
            _feedbacks: dict = {}
            for _m in _models:
                _r = _ratings.get(_m, 3)
                _short = _m.split(":")[0].split("/")[-1]
                st.markdown(f"**{_short}** — {_r}/5")
                _reasons_opts = _GOOD_REASONS if _r >= 3 else _BAD_REASONS
                _why_label    = "What did this model do well?" if _r >= 3 else "What went wrong?"
                _reasons      = st.multiselect(_why_label, _reasons_opts, key=f"arena_reasons_{_m}")
                _fb           = st.text_area("Additional feedback (optional)", key=f"arena_fb_{_m}", height=68)
                _feedbacks[_m] = {"rating": _r, "reasons": _reasons, "feedback": _fb}

            if st.button("Submit Feedback", key="arena_submit_feedback"):
                _save_rating(_q, _feedbacks)
                st.session_state["arena_feedback_submitted"] = True
                st.session_state.pop("arena_ratings_submitted", None)
                st.session_state.pop("arena_pending_ratings", None)
                st.rerun()

        # ── Step 3: thank-you then reset ─────────────────────
        else:
            st.success("Feedback saved — thank you!")
            if st.button("Rate another comparison", key="arena_reset_rating"):
                st.session_state.pop("arena_feedback_submitted", None)
                st.rerun()

        # ── Leaderboard (always visible) ──────────────────────
        _lb = _leaderboard()
        if _lb:
            st.markdown("**All-time leaderboard**")
            st.dataframe(_lb, use_container_width=False, hide_index=True)
