"""All Plotly chart builders for live RFC-based analysis."""
from __future__ import annotations
import plotly.graph_objects as go
import pandas as pd

_DARK  = "#002A45"
_BLUE  = "#0070F2"
_STATUS_COLORS = {
    "Applicable":           "#EF5350",
    "Not Applicable":       "#66BB6A",
    "Already Implemented":  "#42A5F5",
    "Needs Manual Review":  "#FFA726",
    "Insufficient Data":    "#AB47BC",
}
_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Inter,Arial,sans-serif", color=_DARK),
    margin=dict(l=10, r=10, t=40, b=10),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
)


def single_result_gauge(result) -> go.Figure:
    """Confidence gauge for a single applicability result."""
    color = _STATUS_COLORS.get(result.status, _BLUE)
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=result.confidence * 100,
        domain={"x": [0, 1], "y": [0, 1]},
        title={"text": f"<b>{result.status}</b><br><span style='font-size:11px'>Confidence</span>"},
        number={"suffix": "%"},
        gauge={
            "axis": {"range": [0, 100]},
            "bar": {"color": color},
            "steps": [
                {"range": [0,  40], "color": "#FFEBEE"},
                {"range": [40, 70], "color": "#FFF8E1"},
                {"range": [70, 100],"color": "#E8F5E9"},
            ],
        },
    ))
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", height=240,
                      margin=dict(l=20, r=20, t=60, b=10))
    return fig


def evidence_radar(result) -> go.Figure:
    """Radar chart showing evidence dimensions."""
    ev = result.evidence

    comp_score = 1.0 if ev.component.component_found else 0.0
    rel_score  = (1.0 if ev.component.release_match is True
                  else 0.0 if ev.component.release_match is False else 0.5)
    sp_score   = (1.0 if ev.sp.in_range is True
                  else 0.0 if ev.sp.in_range is False else 0.5)
    impl_score = 0.0 if ev.implementation.already_implemented else 1.0
    conf_score = result.confidence

    categories = ["Component<br>Found", "Release<br>Match", "SP<br>In Range",
                  "Not Yet<br>Impl.", "Confidence"]
    values = [comp_score, rel_score, sp_score, impl_score, conf_score]

    fig = go.Figure(go.Scatterpolar(
        r=values + [values[0]],
        theta=categories + [categories[0]],
        fill="toself",
        fillcolor="rgba(0,112,242,0.15)",
        line_color=_BLUE,
        name="Evidence",
    ))
    fig.update_layout(**_LAYOUT, title_text="Evidence Dimensions",
                      polar=dict(radialaxis=dict(range=[0, 1], showticklabels=False)),
                      height=280, showlegend=False)
    return fig


def history_trend(history: list) -> go.Figure:
    """Line chart of run history status counts."""
    if not history:
        return go.Figure()
    df = pd.DataFrame([{
        "Run": r["run_id"],
        "Applicable": r.get("counts", {}).get("Applicable", 0),
        "Not Applicable": r.get("counts", {}).get("Not Applicable", 0),
        "Already Impl.": r.get("counts", {}).get("Already Implemented", 0),
        "Manual Review": r.get("counts", {}).get("Needs Manual Review", 0),
    } for r in reversed(history)])

    fig = go.Figure()
    color_map = {
        "Applicable": "#EF5350",
        "Not Applicable": "#66BB6A",
        "Already Impl.": "#42A5F5",
        "Manual Review": "#FFA726",
    }
    for col, color in color_map.items():
        fig.add_trace(go.Scatter(x=df["Run"], y=df[col], name=col,
                                 line_color=color, mode="lines+markers"))
    fig.update_layout(**_LAYOUT, title_text="Results Over Time", height=280,
                      xaxis_tickangle=-30, xaxis_tickfont_size=9)
    return fig


def component_sp_bar(system) -> go.Figure:
    """Bar chart of top components by SP level number."""
    if not system or not system.components:
        return go.Figure()
    import re
    rows = []
    for c in system.components:
        sp_num = int(re.sub(r"[^0-9]", "", c.sp_level or "0") or "0")
        rows.append({"Component": c.name, "SP Level": sp_num})
    df = pd.DataFrame(rows).sort_values("SP Level", ascending=False).head(20)

    fig = go.Figure(go.Bar(
        x=df["Component"], y=df["SP Level"],
        marker_color=_BLUE, opacity=0.85,
        text=df["SP Level"], textposition="outside",
        hovertemplate="%{x}: SP %{y}<extra></extra>",
    ))
    fig.update_layout(**_LAYOUT, title_text="Top Components by SP Level",
                      height=300, xaxis_tickangle=-45, xaxis_tickfont_size=8,
                      yaxis=dict(showgrid=True, gridcolor="#EEF0F4"))
    return fig


def implemented_notes_pie(system) -> go.Figure:
    """Donut: implemented notes vs total CVERS components count."""
    impl  = len(system.implemented_notes) if system else 0
    comps = len(system.components) if system else 1
    fig = go.Figure(go.Pie(
        labels=["Implemented Notes", "Total Components"],
        values=[impl, comps],
        hole=0.55,
        marker_colors=["#42A5F5", "#EEF0F4"],
        textinfo="label+value",
        hovertemplate="%{label}: <b>%{value}</b><extra></extra>",
    ))
    fig.add_annotation(text=f"<b>{impl}</b><br><span style='font-size:10px'>impl.</span>",
                       x=0.5, y=0.5, showarrow=False, font_size=18)
    fig.update_layout(**_LAYOUT, title_text="System Overview", height=280, showlegend=True)
    return fig


def risk_gauge(score: float, sid: str = "") -> go.Figure:
    """Gauge for a single SID's risk score (0-100)."""
    color = "#EF5350" if score >= 70 else "#FFA726" if score >= 40 else "#66BB6A"
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=round(score, 1),
        domain={"x": [0, 1], "y": [0, 1]},
        title={"text": f"<b>{sid}</b><br><span style='font-size:11px'>Risk Score</span>"},
        gauge={
            "axis": {"range": [0, 100]},
            "bar": {"color": color},
            "steps": [
                {"range": [0,  40], "color": "#E8F5E9"},
                {"range": [40, 70], "color": "#FFF8E1"},
                {"range": [70, 100],"color": "#FFEBEE"},
            ],
        },
    ))
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", height=220,
                      margin=dict(l=20, r=20, t=60, b=10))
    return fig


def risk_bar(risk_list: list) -> go.Figure:
    """Horizontal bar chart of risk scores per SID."""
    if not risk_list:
        return go.Figure()
    sids   = [r.sid for r in risk_list]
    scores = [round(r.risk_score, 1) for r in risk_list]
    colors = ["#EF5350" if s >= 70 else "#FFA726" if s >= 40 else "#66BB6A" for s in scores]
    fig = go.Figure(go.Bar(
        x=scores, y=sids, orientation="h",
        marker_color=colors, text=scores, textposition="outside",
        hovertemplate="%{y}: <b>%{x}</b><extra></extra>",
    ))
    fig.update_layout(**_LAYOUT, title_text="Risk Score by SID", height=max(250, len(sids) * 35),
                      xaxis=dict(range=[0, 105]))
    return fig


def exposure_scatter(risk_list: list) -> go.Figure:
    """Scatter: applicable count vs CVSS avg per SID."""
    if not risk_list:
        return go.Figure()
    fig = go.Figure(go.Scatter(
        x=[getattr(r, "applicable_count", 0) for r in risk_list],
        y=[getattr(r, "avg_cvss", 0) for r in risk_list],
        mode="markers+text",
        text=[r.sid for r in risk_list],
        textposition="top center",
        marker=dict(
            size=[max(10, getattr(r, "applicable_count", 1) * 4) for r in risk_list],
            color=[r.risk_score for r in risk_list],
            colorscale="RdYlGn_r",
            showscale=True,
            colorbar=dict(title="Risk"),
        ),
        hovertemplate="SID: %{text}<br>Applicable: %{x}<br>Avg CVSS: %{y:.1f}<extra></extra>",
    ))
    fig.update_layout(**_LAYOUT, title_text="Exposure: Applicable Notes vs Avg CVSS",
                      xaxis_title="Applicable Notes Count",
                      yaxis_title="Avg CVSS Score", height=300)
    return fig


def severity_per_sid(risk_list: list) -> go.Figure:
    """Stacked bar of severity counts per SID."""
    if not risk_list:
        return go.Figure()
    severities = ["Critical", "High", "Medium", "Low"]
    colors_map = {"Critical": "#EF5350", "High": "#FFA726", "Medium": "#FFEE58", "Low": "#66BB6A"}
    sids = [r.sid for r in risk_list]
    fig = go.Figure()
    for sev in severities:
        counts = [getattr(r, "severity_counts", {}).get(sev, 0) for r in risk_list]
        fig.add_trace(go.Bar(name=sev, x=sids, y=counts,
                             marker_color=colors_map[sev],
                             hovertemplate=f"{sev}: %{{y}}<extra></extra>"))
    fig.update_layout(**_LAYOUT, title_text="Severity Stack per SID",
                      barmode="stack", height=320, xaxis_tickangle=-30)
    return fig


def status_donut(results: list) -> go.Figure:
    """Donut chart for a list of LiveApplicabilityResult objects."""
    counts: dict = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    labels = list(counts.keys())
    values = list(counts.values())
    colors = [_STATUS_COLORS.get(lbl, _BLUE) for lbl in labels]
    fig = go.Figure(go.Pie(
        labels=labels, values=values, hole=0.6,
        marker_colors=colors, textinfo="label+percent",
        hovertemplate="%{label}: <b>%{value}</b><extra></extra>",
    ))
    fig.add_annotation(
        text=f"<b>{sum(values)}</b><br><span style='font-size:10px'>checks</span>",
        x=0.5, y=0.5, showarrow=False, font_size=18)
    fig.update_layout(**_LAYOUT, title_text="Result Breakdown", height=300, showlegend=True)
    return fig
