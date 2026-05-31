"""Reusable Plotly chart builders for the Transit Insight dashboard."""
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

MAPBOX_STYLE = "carto-darkmatter"
TTC_RED = "#E53935"
TORONTO_CENTER = {"lat": 43.7, "lon": -79.42}

_HOUR_AXIS_CITY = {
    "ttc": "Toronto",
    "translink": "Vancouver",
    "edmonton": "Edmonton",
}


def _hour_of_day_axis_label() -> str:
    """Local time label for chart axes (matches agency GTFS timezone)."""
    try:
        from utils.agency_loader import get_current_agency_id
        from utils.agency_config import AGENCIES

        aid = get_current_agency_id()
        city = _HOUR_AXIS_CITY.get(aid)
        if not city:
            cfg = AGENCIES.get(aid, {})
            city = (cfg.get("city") or "local").split(",")[0].strip()
        return f"Hour of day ({city} time)"
    except Exception:
        return "Hour of day (local time)"


def _heatmap_annotation_text(value_col: str, label: str) -> str:
    if value_col == "relative_deviation":
        return "Relative deviation by route and hour"
    return f"{label} by route and hour — low-sample hours may look extreme"


def _route_sort_key(route_id: str) -> int:
    return int(route_id) if str(route_id).isdigit() else 0


def _route_display_label(route_id: str) -> str:
    """Human-readable route label for categorical chart axes."""
    try:
        from utils.route_config import get_route_config

        cfg = get_route_config(str(route_id))
        if cfg:
            return f"{route_id} — {cfg['name']}"
    except ImportError:
        pass
    return str(route_id)


def _ordered_route_labels(route_ids) -> list[str]:
    ids = sorted({str(r) for r in route_ids}, key=_route_sort_key)
    return [_route_display_label(r) for r in ids]


def vehicle_scatter_map(df: pd.DataFrame) -> go.Figure:
    """Scatter map of live/recent vehicle positions."""
    if df.empty:
        return _empty_map()
    fig = px.scatter_mapbox(
        df,
        lat="latitude",
        lon="longitude",
        color="route_id",
        hover_data=["vehicle_id", "route_id", "speed", "timestamp"],
        zoom=11,
        center=TORONTO_CENTER,
        mapbox_style=MAPBOX_STYLE,
        title="Vehicle Positions",
    )
    fig.update_traces(marker=dict(size=8, opacity=0.85))
    fig.update_layout(**_map_layout())
    return fig


def _empty_chart(title: str) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(title=title, **_dark_layout())
    return fig


_METRIC_LABELS = {
    "on_time_pct": "Adherence score",
    "adherence_score": "Adherence score",
    "relative_deviation": "Relative deviation",
    "abs_headway_deviation_sec": "Absolute deviation (sec)",
    "headway_deviation_sec": "Signed deviation (sec)",
}


def headway_heatmap(df: pd.DataFrame, value_col: str = "adherence_score") -> go.Figure:
    """Heatmap: route × hour coloured by schedule-comparison metric."""
    if df.empty:
        return _empty_chart("No headway data")

    if value_col not in df.columns and value_col == "adherence_score" and "on_time_pct" in df.columns:
        value_col = "on_time_pct"

    plot_df = df.copy()
    plot_df["route_id"] = plot_df["route_id"].astype(str)
    plot_df["route_label"] = plot_df["route_id"].map(_route_display_label)

    pivot = plot_df.pivot_table(
        index="route_label",
        columns="hour",
        values=value_col,
        aggfunc="mean",
    )
    order = _ordered_route_labels(plot_df["route_id"])
    pivot = pivot.reindex([lbl for lbl in order if lbl in pivot.index])

    label = _METRIC_LABELS.get(value_col, value_col)
    score_cols = {"on_time_pct", "adherence_score"}
    zmax = 100 if value_col in score_cols else (2.0 if value_col == "relative_deviation" else 900)
    zmin = 0
    colorscale = "RdYlGn" if value_col in score_cols else "RdBu_r"

    fig = go.Figure(
        go.Heatmap(
            z=pivot.values,
            x=[f"{int(h):02d}:00" for h in pivot.columns],
            y=pivot.index.tolist(),
            colorscale=colorscale,
            colorbar=dict(title=label),
            hoverongaps=False,
            zmin=zmin,
            zmax=zmax,
        )
    )
    fig.update_layout(
        title=f"{label} by route and hour",
        xaxis_title=_hour_of_day_axis_label(),
        yaxis_title="Route",
        yaxis=dict(type="category"),
        legend=dict(title=""),
        **_dark_layout(),
    )
    fig.add_annotation(
        text=_heatmap_annotation_text(value_col, label),
        xref="paper", yref="paper", x=0, y=1.08, showarrow=False,
        font=dict(size=11, color="#8B949E"), xanchor="left",
    )
    return fig


def on_time_bar(df: pd.DataFrame, value_col: str = "adherence_score") -> go.Figure:
    """Horizontal bar chart of mean adherence score per route."""
    if df.empty:
        return _empty_chart("No schedule comparison data")

    if value_col not in df.columns:
        value_col = "on_time_pct" if "on_time_pct" in df.columns else value_col

    plot_df = df.copy()
    plot_df["route_id"] = plot_df["route_id"].astype(str)
    agg = plot_df.groupby("route_id", as_index=False)[value_col].mean()
    agg["route_label"] = agg["route_id"].map(_route_display_label)
    agg = agg.sort_values(value_col, ascending=True)
    agg["route_label"] = pd.Categorical(
        agg["route_label"],
        categories=_ordered_route_labels(agg["route_id"]),
        ordered=True,
    )

    ylabel = _METRIC_LABELS.get(value_col, "Adherence score")
    fig = px.bar(
        agg,
        x=value_col,
        y="route_label",
        orientation="h",
        color=value_col,
        color_continuous_scale="RdYlGn",
        range_color=[0, 100],
        labels={value_col: ylabel, "route_label": "Route"},
        title="Mean adherence score by route",
    )
    fig.update_layout(
        showlegend=False,
        coloraxis_showscale=False,
        xaxis=dict(range=[0, 100], title=ylabel, dtick=10),
        yaxis=dict(type="category", title="Route"),
        **_dark_layout(),
    )
    fig.add_annotation(
        text="Higher = smaller relative deviation from scheduled (hourly means)",
        xref="paper", yref="paper", x=0, y=1.06, showarrow=False,
        font=dict(size=11, color="#8B949E"), xanchor="left",
    )
    return fig


def headway_deviation_line(df: pd.DataFrame, route_id: str) -> go.Figure:
    """Line chart of scheduled vs actual headway over hours for a single route."""
    sub = df[df["route_id"].astype(str) == str(route_id)].copy()
    if sub.empty:
        return _empty_chart(f"Route {route_id} — no headway data")
    agg = sub.groupby("hour")[["scheduled_headway_sec", "actual_headway_sec"]].mean().reset_index()
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=agg["hour"], y=agg["scheduled_headway_sec"] / 60,
        mode="lines", name="Scheduled (min)", line=dict(dash="dash", color="#90CAF9"),
    ))
    fig.add_trace(go.Scatter(
        x=agg["hour"], y=agg["actual_headway_sec"] / 60,
        mode="lines+markers", name="Actual (min)", line=dict(color=TTC_RED),
    ))
    fig.update_layout(
        title=f"Route {route_id} — headway comparison",
        xaxis_title=_hour_of_day_axis_label(),
        yaxis_title="Mean headway (minutes)",
        xaxis=dict(dtick=2),
        legend=dict(title="", orientation="h", yanchor="bottom", y=1.02, x=0),
        **_dark_layout(),
    )
    fig.add_annotation(
        text="Solid = observed pass-event mean · dashed = GTFS scheduled mean",
        xref="paper", yref="paper", x=0, y=1.06, showarrow=False,
        font=dict(size=11, color="#8B949E"), xanchor="left",
    )
    return fig


def stops_map(df: pd.DataFrame) -> go.Figure:
    """Map of transit stops."""
    if df.empty:
        return _empty_map()
    fig = px.scatter_mapbox(
        df,
        lat="stop_lat",
        lon="stop_lon",
        hover_name="stop_name",
        hover_data=["stop_id"],
        zoom=11,
        center=TORONTO_CENTER,
        mapbox_style=MAPBOX_STYLE,
        title="TTC Stops",
    )
    fig.update_traces(marker=dict(size=5, color=TTC_RED, opacity=0.7))
    fig.update_layout(**_map_layout())
    return fig


def speed_histogram(df: pd.DataFrame, route_id: str = None) -> go.Figure:
    """Distribution of vehicle speeds."""
    sub = df if route_id is None else df[df["route_id"] == route_id]
    if sub.empty:
        return go.Figure()
    fig = px.histogram(
        sub, x="speed", nbins=30,
        color_discrete_sequence=[TTC_RED],
        title="Vehicle Speed Distribution (km/h)",
        labels={"speed": "Speed (km/h)"},
    )
    fig.update_layout(**_dark_layout())
    return fig


def _map_layout() -> dict:
    return dict(
        margin=dict(l=0, r=0, t=40, b=0),
        height=500,
        paper_bgcolor="#0D1117",
        font_color="#E6EDF3",
    )


def _dark_layout() -> dict:
    return dict(
        paper_bgcolor="#161B22",
        plot_bgcolor="#161B22",
        font_color="#E6EDF3",
        margin=dict(l=40, r=20, t=50, b=40),
        height=400,
    )


def _empty_map() -> go.Figure:
    fig = go.Figure(go.Scattermapbox())
    fig.update_layout(
        mapbox=dict(style=MAPBOX_STYLE, center=TORONTO_CENTER, zoom=11),
        **_map_layout(),
    )
    return fig
