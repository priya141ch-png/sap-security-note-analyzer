"""
Global CSS injected once at app startup.
Uses SAP Fiori-inspired colour palette.
"""

CSS = """
<style>
/* ── Palette ───────────────────────────────────────────────── */
:root {
  --sap-blue:      #0070F2;
  --sap-dark:      #002A45;
  --sap-light:     #F5F7FA;
  --sap-border:    #D9DDE3;
  --critical-bg:   #FFEBEE;
  --critical-fg:   #C62828;
  --high-bg:       #FFF3E0;
  --high-fg:       #E65100;
  --medium-bg:     #FFFDE7;
  --medium-fg:     #F57F17;
  --low-bg:        #E8F5E9;
  --low-fg:        #2E7D32;
  --ok-bg:         #E8F5E9;
  --ok-fg:         #2E7D32;
  --manual-bg:     #FFF8E1;
  --manual-fg:     #F57F17;
}

/* ── Sidebar ───────────────────────────────────────────────── */
section[data-testid="stSidebar"] {
  background: var(--sap-dark) !important;
  min-width: 240px !important;
}
section[data-testid="stSidebar"] * { color: #E8EDF2 !important; }
section[data-testid="stSidebar"] .stRadio > label { font-size: 0.78rem; opacity: 0.7; text-transform: uppercase; letter-spacing: .08em; }
section[data-testid="stSidebar"] .stRadio div[role="radiogroup"] label {
  padding: 8px 12px;
  border-radius: 6px;
  margin-bottom: 2px;
  cursor: pointer;
  transition: background .15s;
}
section[data-testid="stSidebar"] .stRadio div[role="radiogroup"] label:hover { background: rgba(255,255,255,.08); }

/* ── KPI Cards ─────────────────────────────────────────────── */
.kpi-grid { display:flex; gap:14px; flex-wrap:wrap; margin-bottom:20px; }
.kpi-card {
  flex: 1 1 160px;
  background: #fff;
  border: 1px solid var(--sap-border);
  border-radius: 10px;
  padding: 16px 20px;
  box-shadow: 0 1px 4px rgba(0,0,0,.06);
  position: relative;
  overflow: hidden;
}
.kpi-card::before {
  content:"";
  position:absolute; top:0; left:0; right:0; height:3px;
  background: var(--sap-blue);
}
.kpi-card.critical::before { background: var(--critical-fg); }
.kpi-card.high::before     { background: var(--high-fg); }
.kpi-card.medium::before   { background: var(--medium-fg); }
.kpi-card.low::before      { background: var(--low-fg); }
.kpi-card.ok::before       { background: var(--ok-fg); }
.kpi-label { font-size:.72rem; font-weight:600; text-transform:uppercase; letter-spacing:.06em; color:#6E7880; margin-bottom:4px; }
.kpi-value { font-size:2rem; font-weight:700; color:var(--sap-dark); line-height:1.1; }
.kpi-sub   { font-size:.72rem; color:#6E7880; margin-top:4px; }

/* ── Section headers ───────────────────────────────────────── */
.section-header {
  font-size:1.1rem; font-weight:700; color:var(--sap-dark);
  border-left:4px solid var(--sap-blue); padding-left:10px;
  margin: 18px 0 10px;
}

/* ── Status badges ─────────────────────────────────────────── */
.badge {
  display:inline-block; padding:2px 9px; border-radius:12px;
  font-size:.72rem; font-weight:600; white-space:nowrap;
}
.badge-applicable   { background:var(--critical-bg); color:var(--critical-fg); }
.badge-notapplicable{ background:var(--ok-bg);       color:var(--ok-fg); }
.badge-manual       { background:var(--manual-bg);   color:var(--manual-fg); }

/* ── Upload zones ──────────────────────────────────────────── */
div[data-testid="stFileUploader"] {
  border: 2px dashed var(--sap-border);
  border-radius: 8px;
  padding: 10px;
  background: var(--sap-light);
}

/* ── Progress bar colour ───────────────────────────────────── */
div[data-testid="stProgress"] > div > div { background: var(--sap-blue) !important; }

/* ── Metric delta colours ──────────────────────────────────── */
[data-testid="stMetricDelta"] { font-size:.72rem !important; }

/* ── Expander borders ──────────────────────────────────────── */
details { border:1px solid var(--sap-border); border-radius:8px; padding:0 10px; }

/* ── Table hover ───────────────────────────────────────────── */
.stDataFrame tbody tr:hover td { background: #EEF4FF !important; }

/* ── Divider ───────────────────────────────────────────────── */
hr { border-color: var(--sap-border) !important; margin: 10px 0 !important; }

/* ── Toast / alert tweaks ──────────────────────────────────── */
div[data-testid="stAlert"] { border-radius: 8px; }
</style>
"""


def inject() -> None:
    import streamlit as st
    st.markdown(CSS, unsafe_allow_html=True)
