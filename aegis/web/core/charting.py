# aegis/web/core/charting.py
# Plotly chart serialization and helpers for Mission Control

import json
from typing import Any, Dict, List, Optional, Union
from datetime import datetime
from pydantic import BaseModel, Field
import plotly.graph_objects as go
import plotly.utils


class ChartData(BaseModel):
    """Standardized chart data response."""

    figure_json: str = Field(description="Plotly figure serialized as JSON")
    config: Dict[str, Any] = Field(
        default_factory=lambda: {
            "displayModeBar": True,
            "displaylogo": False,
            "modeBarButtonsToRemove": ["pan2d", "lasso2d", "select2d", "autoScale2d"],
            "responsive": True,
        },
        description="Plotly.js config options",
    )
    title: Optional[str] = None
    description: Optional[str] = None


def serialize_plotly_figure(fig: go.Figure) -> str:
    """Serialize a Plotly figure to JSON string."""
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


def create_chart_response(
    fig: go.Figure,
    title: Optional[str] = None,
    description: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> ChartData:
    """Create a standardized ChartData response from a Plotly figure."""
    return ChartData(
        figure_json=serialize_plotly_figure(fig),
        config=config or {},
        title=title,
        description=description,
    )


# --- Chart Theme Helpers ---

MISSION_CONTROL_THEME = {
    "layout": {
        "font": {"family": "Inter, system-ui, sans-serif", "size": 12},
        "plot_bgcolor": "rgba(0,0,0,0)",
        "paper_bgcolor": "rgba(0,0,0,0)",
        "margin": {"l": 50, "r": 30, "t": 50, "b": 50},
        "hovermode": "x unified",
        "hoverlabel": {
            "bgcolor": "rgba(30, 30, 30, 0.9)",
            "font": {"color": "white", "size": 11},
            "bordercolor": "rgba(255,255,255,0.1)",
        },
        "xaxis": {
            "showgrid": True,
            "gridcolor": "rgba(255,255,255,0.05)",
            "zeroline": False,
            "showline": True,
            "linecolor": "rgba(255,255,255,0.1)",
        },
        "yaxis": {
            "showgrid": True,
            "gridcolor": "rgba(255,255,255,0.05)",
            "zeroline": False,
            "showline": True,
            "linecolor": "rgba(255,255,255,0.1)",
        },
        "legend": {
            "bgcolor": "rgba(30, 30, 30, 0.8)",
            "bordercolor": "rgba(255,255,255,0.1)",
            "font": {"size": 11},
        },
    }
}

MISSION_CONTROL_DARK_THEME = {
    **MISSION_CONTROL_THEME,
    "layout": {
        **MISSION_CONTROL_THEME["layout"],
        "template": "plotly_dark",
    },
}

COLOR_PALETTE = [
    "#00D4AA",  # Teal (primary)
    "#FF6B6B",  # Coral
    "#4ECDC4",  # Turquoise
    "#FFD93D",  # Yellow
    "#6BCB77",  # Green
    "#FF8E72",  # Orange
    "#A8E6CF",  # Mint
    "#FFB7B2",  # Pink
    "#C7CEEA",  # Lavender
    "#FFEAA7",  # Cream
]

SEQUENTIAL_COLORS = [
    "#08306B", "#08519C", "#2171B5", "#4292C6", "#6BAED6",
    "#9ECAE1", "#C6DBEF", "#DEEBF7", "#F7FBFF"
]

DIVERGING_COLORS = [
    "#67001F", "#B2182B", "#D6604D", "#F4A582", "#FDDBC7",
    "#F7F7F7", "#D1E5F0", "#92C5DE", "#4393C3", "#2166AC", "#053061"
]


def apply_mc_theme(fig: go.Figure, dark: bool = False) -> go.Figure:
    """Apply Mission Control theme to a Plotly figure."""
    theme = MISSION_CONTROL_DARK_THEME if dark else MISSION_CONTROL_THEME
    fig.update_layout(**theme["layout"])
    return fig


def create_empty_chart(message: str = "No data available") -> go.Figure:
    """Create an empty chart with a message."""
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        xref="paper", yref="paper",
        x=0.5, y=0.5,
        showarrow=False,
        font={"size": 16, "color": "rgba(255,255,255,0.5)"},
    )
    return apply_mc_theme(fig)


# --- Common Chart Builders ---

def create_time_series_chart(
    x: List[datetime],
    y_series: Dict[str, List[float]],
    title: str = "",
    x_title: str = "Time",
    y_title: str = "Value",
    chart_type: str = "line",  # line, bar, area
    stack: bool = False,
    colors: Optional[List[str]] = None,
) -> go.Figure:
    """Create a multi-series time series chart."""
    fig = go.Figure()
    colors = colors or COLOR_PALETTE

    for i, (name, y) in enumerate(y_series.items()):
        color = colors[i % len(colors)]

        if chart_type == "line":
            fig.add_trace(go.Scatter(
                x=x, y=y, name=name, mode="lines",
                line={"color": color, "width": 2},
                hovertemplate=f"<b>{name}</b><br>%{{x}}<br>%{{y:,.0f}}<extra></extra>",
            ))
        elif chart_type == "area":
            fig.add_trace(go.Scatter(
                x=x, y=y, name=name, mode="lines",
                line={"color": color, "width": 1},
                fill="tonexty" if stack and i > 0 else "tozeroy",
                fillcolor=color.replace(")", ", 0.3)").replace("rgb", "rgba").replace("#", "rgba("),
                hovertemplate=f"<b>{name}</b><br>%{{x}}<br>%{{y:,.0f}}<extra></extra>",
            ))
        elif chart_type == "bar":
            fig.add_trace(go.Bar(
                x=x, y=y, name=name,
                marker_color=color,
                hovertemplate=f"<b>{name}</b><br>%{{x}}<br>%{{y:,.0f}}<extra></extra>",
            ))

    if stack:
        fig.update_layout(barmode="stack")

    fig.update_layout(
        title=title,
        xaxis_title=x_title,
        yaxis_title=y_title,
    )

    return apply_mc_theme(fig)


def create_dual_axis_chart(
    x: List[datetime],
    left_y: Dict[str, List[float]],
    right_y: Dict[str, List[float]],
    title: str = "",
    x_title: str = "Time",
    left_title: str = "Left Axis",
    right_title: str = "Right Axis",
) -> go.Figure:
    """Create a chart with dual Y axes."""
    fig = go.Figure()
    colors = COLOR_PALETTE

    # Left axis traces
    for i, (name, y) in enumerate(left_y.items()):
        color = colors[i % len(colors)]
        fig.add_trace(go.Scatter(
            x=x, y=y, name=name, mode="lines",
            line={"color": color, "width": 2},
            yaxis="y",
            hovertemplate=f"<b>{name}</b><br>%{{x}}<br>%{{y:,.0f}}<extra></extra>",
        ))

    # Right axis traces
    offset = len(left_y)
    for i, (name, y) in enumerate(right_y.items()):
        color = colors[(offset + i) % len(colors)]
        fig.add_trace(go.Scatter(
            x=x, y=y, name=name, mode="lines",
            line={"color": color, "width": 2, "dash": "dot"},
            yaxis="y2",
            hovertemplate=f"<b>{name}</b><br>%{{x}}<br>%{{y:,.0f}}<extra></extra>",
        ))

    fig.update_layout(
        title=title,
        xaxis_title=x_title,
        yaxis={"title": left_title, "side": "left"},
        yaxis2={"title": right_title, "side": "right", "overlaying": "y", "showgrid": False},
    )

    return apply_mc_theme(fig)


def create_bar_chart(
    x: List[str],
    y: List[float],
    title: str = "",
    x_title: str = "",
    y_title: str = "",
    color: str = COLOR_PALETTE[0],
    hover_template: Optional[str] = None,
) -> go.Figure:
    """Create a simple bar chart."""
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=x, y=y,
        marker_color=color,
        hovertemplate=hover_template or "%{x}: %{y:,.0f}<extra></extra>",
    ))

    fig.update_layout(
        title=title,
        xaxis_title=x_title,
        yaxis_title=y_title,
    )

    return apply_mc_theme(fig)


def create_stacked_bar_chart(
    x: List[str],
    y_series: Dict[str, List[float]],
    title: str = "",
    x_title: str = "",
    y_title: str = "",
    colors: Optional[List[str]] = None,
) -> go.Figure:
    """Create a stacked bar chart."""
    fig = go.Figure()
    colors = colors or COLOR_PALETTE

    for i, (name, y) in enumerate(y_series.items()):
        color = colors[i % len(colors)]
        fig.add_trace(go.Bar(
            x=x, y=y, name=name,
            marker_color=color,
            hovertemplate=f"<b>{name}</b><br>%{{x}}<br>%{{y:,.0f}}<extra></extra>",
        ))

    fig.update_layout(
        title=title,
        xaxis_title=x_title,
        yaxis_title=y_title,
        barmode="stack",
    )

    return apply_mc_theme(fig)


def create_sankey_chart(
    labels: List[str],
    source: List[int],
    target: List[int],
    value: List[float],
    title: str = "",
    colors: Optional[List[str]] = None,
) -> go.Figure:
    """Create a Sankey diagram for flow visualization."""
    fig = go.Figure(data=[go.Sankey(
        node=dict(
            pad=15,
            thickness=20,
            line=dict(color="rgba(255,255,255,0.1)", width=1),
            label=labels,
            color=colors or ["rgba(0, 212, 170, 0.8)"] * len(labels),
        ),
        link=dict(
            source=source,
            target=target,
            value=value,
            color="rgba(0, 212, 170, 0.3)",
            hovertemplate="%{source.label} → %{target.label}<br>%{value:,.0f}<extra></extra>",
        ),
    )])

    fig.update_layout(title=title, font=dict(size=11))
    return apply_mc_theme(fig)


def create_gauge_chart(
    value: float,
    max_value: float = 100,
    title: str = "",
    thresholds: Optional[List[Dict[str, Any]]] = None,
) -> go.Figure:
    """Create a gauge/indicator chart."""
    thresholds = thresholds or [
        {"range": [0, max_value * 0.5], "color": "#00D4AA"},
        {"range": [max_value * 0.5, max_value * 0.8], "color": "#FFD93D"},
        {"range": [max_value * 0.8, max_value], "color": "#FF6B6B"},
    ]

    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=value,
        domain={"x": [0, 1], "y": [0, 1]},
        title={"text": title, "font": {"size": 16}},
        gauge={
            "axis": {"range": [None, max_value], "tickwidth": 1},
            "bar": {"color": "rgba(0, 212, 170, 0.8)"},
            "bgcolor": "rgba(255,255,255,0.05)",
            "borderwidth": 1,
            "bordercolor": "rgba(255,255,255,0.1)",
            "steps": thresholds,
            "threshold": {
                "line": {"color": "white", "width": 3},
                "thickness": 0.8,
                "value": value,
            },
        },
    ))

    fig.update_layout(height=250, margin={"l": 20, "r": 20, "t": 50, "b": 20})
    return apply_mc_theme(fig)


def create_funnel_chart(
    stages: List[str],
    values: List[float],
    title: str = "",
) -> go.Figure:
    """Create a funnel chart for pipeline visualization."""
    fig = go.Figure(go.Funnel(
        y=stages,
        x=values,
        textinfo="value+percent initial",
        textposition="inside",
        marker={"color": COLOR_PALETTE[:len(stages)]},
        connector={"line": {"color": "rgba(255,255,255,0.1)", "dash": "dot", "width": 2}},
        hovertemplate="<b>%{y}</b><br>Count: %{x:,.0f}<br>%{percentInitial:.1%} of initial<extra></extra>",
    ))

    fig.update_layout(title=title, margin={"l": 100, "r": 20, "t": 50, "b": 20})
    return apply_mc_theme(fig)