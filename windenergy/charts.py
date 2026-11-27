"""Server-side Plotly charts for the dashboard (no custom JavaScript).

Plotly renders the figure in Python and returns an HTML snippet that loads the
Plotly library itself. Form: ranked horizontal bars in one hue (comparing many
manufacturers), with the long tail folded into "Übrige" - the full list stays
available in the table view.
"""

import plotly.graph_objects as go

TOP_N = 15
BAR_COLOR = "#059669"     # dashboard emerald (single hue: one series)
OTHER_COLOR = "#94a3b8"   # muted grey for the folded tail
TEXT_PRIMARY = "#0f172a"
TEXT_SECONDARY = "#475569"
GRID_COLOR = "#eef2f6"
FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'


def _german(value, decimals):
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "\0").replace(".", ",").replace("\0", ".")


def manufacturer_chart(items, mode, include_plotlyjs=False):
    """Return an HTML snippet with a ranked bar chart.

    items: manufacturer summary rows from the dashboard view, each with
           "name", "count" and "capacity" (capacity in kW).
    mode:  "count" (number of units) or "capacity" (gross capacity in MW).
    include_plotlyjs: True for the first chart on the page only, so the
           Plotly library is loaded once.
    """
    if not items:
        return ""

    def value_of(item):
        return item["count"] if mode == "count" else item["capacity"] / 1000

    ranked = sorted(items, key=lambda item: (-value_of(item), item["name"]))
    top, tail = ranked[:TOP_N], ranked[TOP_N:]

    names = [item["name"] for item in top]
    values = [value_of(item) for item in top]
    hover = [
        f"{_german(item['count'], 0)} Anlagen · {_german(item['capacity'] / 1000, 2)} MW"
        for item in top
    ]
    colors = [BAR_COLOR] * len(top)
    if tail:
        names.append(f"Übrige ({len(tail)} Hersteller)")
        values.append(sum(value_of(item) for item in tail))
        tail_count = sum(item["count"] for item in tail)
        tail_capacity = sum(item["capacity"] for item in tail) / 1000
        hover.append(f"{_german(tail_count, 0)} Anlagen · {_german(tail_capacity, 2)} MW")
        colors.append(OTHER_COLOR)

    unit = "Anlagen" if mode == "count" else "MW"
    figure = go.Figure(
        go.Bar(
            x=values,
            y=names,
            orientation="h",
            marker={"color": colors, "cornerradius": 4},
            customdata=hover,
            hovertemplate="<b>%{y}</b><br>%{customdata}<extra></extra>",
        )
    )
    figure.update_layout(
        height=60 + 26 * len(names),
        margin={"l": 8, "r": 16, "t": 8, "b": 36},
        bargap=0.35,
        separators=",.",  # German decimal comma and thousands point
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": FONT, "size": 12, "color": TEXT_SECONDARY},
        hoverlabel={"bgcolor": "#ffffff", "bordercolor": "#e2e8f0",
                    "font": {"family": FONT, "size": 12, "color": TEXT_PRIMARY}},
        showlegend=False,
    )
    figure.update_xaxes(
        title={"text": unit, "font": {"size": 11}},
        showgrid=True, gridcolor=GRID_COLOR, zeroline=False,
        tickformat=",d" if mode == "count" else ",.0f",
        fixedrange=True,
    )
    figure.update_yaxes(
        autorange="reversed",  # largest first, "Übrige" last
        automargin=True, ticks="", showline=False, fixedrange=True,
        tickfont={"color": TEXT_PRIMARY},
    )
    return figure.to_html(
        full_html=False,
        include_plotlyjs="cdn" if include_plotlyjs else False,
        config={"displayModeBar": False, "responsive": True},
    )


# Fixed colour per operating status (validated as a ring: neighbouring slices,
# including last-to-first, stay distinguishable for colour-blind readers).
STATUS_COLORS = {
    "In Betrieb": "#1baf7a",
    "In Planung": "#eb6834",
    "Vorübergehend stillgelegt": "#2a78d6",
    "Endgültig stillgelegt": "#eda100",
}


def plotly_script_tag():
    """One <script> tag for the Plotly library, placed in the page <head>."""
    from plotly.offline import get_plotlyjs_version

    return (
        f'<script src="https://cdn.plot.ly/plotly-{get_plotlyjs_version()}.min.js" '
        'charset="utf-8"></script>'
    )


SMALL_SLICE_SHARE = 0.02   # donut slices below 2 % get an outside label


def status_donut_figure(rows):
    """Donut of one wind type split by operating status.

    rows: dicts with "label", "count" and "capacity_mw"; rows with count 0
    are left out (the status table below the donut still lists them).
    Returns "" when there is nothing to draw.

    Every legend entry carries its count and share, so even a slice too thin
    to see in the ring (e.g. 88 of 33,829 = 0,3 %) is listed with its value.
    """
    rows = [row for row in rows if row["count"]]
    if not rows:
        return None
    total = sum(row["count"] for row in rows)

    def share(count):
        percent = count / total * 100
        return "<0,1 %" if percent < 0.1 else f"{_german(percent, 1)} %"

    # Slices under 2 % are only 1-2 px wide in the ring. They get a label
    # outside the ring (with a short leader line) so they can be found;
    # larger slices stay unlabelled and are explained by the legend.
    small = [row["count"] / total < SMALL_SLICE_SHARE for row in rows]

    figure = go.Figure(
        go.Pie(
            labels=[f"{row['label']}: {_german(row['count'], 0)} ({share(row['count'])})"
                    for row in rows],
            values=[row["count"] for row in rows],
            hole=0.62,
            sort=False,
            direction="clockwise",
            automargin=True,          # room for the outside labels
            marker={
                "colors": [STATUS_COLORS.get(row["label"], OTHER_COLOR) for row in rows],
                # No white gap lines: on a ring this size even 1 px would
                # cover a 0.3 % slice. The validated colours separate slices.
                "line": {"width": 0},
            },
            text=[f"{row['label']} {share(row['count'])}" if is_small else ""
                  for row, is_small in zip(rows, small)],
            textinfo="text",
            textposition=["outside" if is_small else "none" for is_small in small],
            outsidetextfont={"size": 11, "color": TEXT_PRIMARY},
            customdata=[
                [row["label"],
                 f"{_german(row['count'], 0)} Anlagen · {_german(row['capacity_mw'], 2)} MW",
                 share(row["count"])]
                for row in rows
            ],
            hovertemplate=("<b>%{customdata[0]}</b><br>%{customdata[1]}<br>"
                           "%{customdata[2]}<extra></extra>"),
        )
    )
    figure.update_layout(
        height=340,
        margin={"l": 8, "r": 8, "t": 8, "b": 8},
        separators=",.",
        paper_bgcolor="rgba(0,0,0,0)",
        font={"family": FONT, "size": 12, "color": TEXT_SECONDARY},
        hoverlabel={"bgcolor": "#ffffff", "bordercolor": "#e2e8f0",
                    "font": {"family": FONT, "size": 12, "color": TEXT_PRIMARY}},
        # One legend entry per line under the ring, with count and share.
        legend={"orientation": "v", "x": 0.5, "xanchor": "center", "y": -0.02,
                "yanchor": "top", "font": {"color": TEXT_PRIMARY}},
        annotations=[{
            "text": f"<b>{_german(total, 0)}</b><br>Anlagen",
            "showarrow": False, "font": {"size": 15, "color": TEXT_PRIMARY},
        }],
    )
    return figure


def status_donut(rows):
    """HTML snippet of status_donut_figure() ("" when there is nothing to draw)."""
    figure = status_donut_figure(rows)
    if figure is None:
        return ""
    return figure.to_html(
        full_html=False,
        include_plotlyjs=False,
        config={"displayModeBar": False, "responsive": True},
    )


def catalog_chart(labels, values, unit=""):
    """Horizontal bar chart for a catalogue answer, in the SQL result's order."""
    if not labels:
        return ""
    labels = [str(label) for label in labels]
    numbers = [float(value or 0) for value in values]
    decimals = 0 if all(number.is_integer() for number in numbers) else 1
    suffix = f" {unit}" if unit else ""
    figure = go.Figure(
        go.Bar(
            x=numbers,
            y=labels,
            orientation="h",
            marker={"color": BAR_COLOR, "cornerradius": 4},
            customdata=[f"{_german(number, decimals)}{suffix}" for number in numbers],
            hovertemplate="<b>%{y}</b><br>%{customdata}<extra></extra>",
        )
    )
    figure.update_layout(
        height=60 + 26 * len(labels),
        margin={"l": 8, "r": 16, "t": 8, "b": 36},
        bargap=0.35,
        separators=",.",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": FONT, "size": 12, "color": TEXT_SECONDARY},
        hoverlabel={"bgcolor": "#ffffff", "bordercolor": "#e2e8f0",
                    "font": {"family": FONT, "size": 12, "color": TEXT_PRIMARY}},
        showlegend=False,
    )
    figure.update_xaxes(
        title={"text": unit or "Anzahl", "font": {"size": 11}},
        showgrid=True, gridcolor=GRID_COLOR, zeroline=False,
        tickformat=",d" if decimals == 0 else ",.0f", fixedrange=True,
    )
    figure.update_yaxes(
        type="category",          # years such as 1998 stay labels, not a number axis
        autorange="reversed",     # first SQL row on top
        automargin=True, ticks="", showline=False, fixedrange=True,
        tickfont={"color": TEXT_PRIMARY},
    )
    return figure.to_html(
        full_html=False,
        include_plotlyjs=False,
        config={"displayModeBar": False, "responsive": True},
    )


# Two clearly different hues for the wind types (validated: distinguishable
# for colour-blind readers, >= 3:1 contrast). Blue = offshore (sea), orange = onshore (land).
WIND_TYPE_COLORS = {
    "Onshore": "#eb6834",
    "Offshore": "#2a78d6",
}


def status_windtype_chart(status_cards, measure):
    """Horizontal stacked bars: one bar per operating status, split by wind type.

    status_cards: the dashboard's status cards (label, wind_types with count /
    capacity_mw / included). measure: "count" (Anlagen) or "capacity" (MW).
    """
    if not status_cards:
        return ""
    unit = "Anlagen" if measure == "count" else "MW"
    decimals = 0 if measure == "count" else 2
    statuses = [card["label"] for card in status_cards]
    wind_type_labels = [row["label"] for row in status_cards[0]["wind_types"] if row["included"]]
    if not wind_type_labels:
        return ""

    def value(row):
        return row["count"] if measure == "count" else row["capacity_mw"]

    figure = go.Figure()
    totals = [0.0] * len(statuses)
    for wind_label in wind_type_labels:
        values = []
        hover = []
        for position, card in enumerate(status_cards):
            row = next(r for r in card["wind_types"] if r["label"] == wind_label)
            amount = value(row)
            totals[position] += amount
            values.append(amount)
            hover.append(f"{_german(row['count'], 0)} Anlagen · {_german(row['capacity_mw'], 2)} MW")
        figure.add_trace(go.Bar(
            name=wind_label, x=values, y=statuses, orientation="h",
            marker={"color": WIND_TYPE_COLORS.get(wind_label, OTHER_COLOR),
                    "line": {"color": "#ffffff", "width": 1}},
            customdata=hover,
            hovertemplate=f"<b>%{{y}}</b><br>{wind_label}<br>%{{customdata}}<extra></extra>",
        ))
    largest = max(totals) or 1
    figure.update_layout(
        barmode="stack",
        height=110 + 52 * len(statuses),
        margin={"l": 8, "r": 24, "t": 8, "b": 40},
        bargap=0.4,
        separators=",.",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": FONT, "size": 12, "color": TEXT_SECONDARY},
        hoverlabel={"bgcolor": "#ffffff", "bordercolor": "#e2e8f0",
                    "font": {"family": FONT, "size": 12, "color": TEXT_PRIMARY}},
        legend={"orientation": "h", "x": 0, "y": -0.18, "yanchor": "top",
                "font": {"color": TEXT_PRIMARY}},
        # Total at the end of every bar, so small values stay readable.
        annotations=[{
            "x": total, "y": status, "xanchor": "left", "xshift": 6, "showarrow": False,
            "text": f"{_german(total, decimals)} {unit}",
            "font": {"size": 12, "color": TEXT_PRIMARY},
        } for status, total in zip(statuses, totals)],
    )
    figure.update_xaxes(
        title={"text": unit, "font": {"size": 11}},
        range=[0, largest * 1.22],          # room for the total labels
        showgrid=True, gridcolor=GRID_COLOR, zeroline=False,
        tickformat=",d" if measure == "count" else ",.0f", fixedrange=True,
    )
    figure.update_yaxes(
        type="category", autorange="reversed", automargin=True,
        ticks="", showline=False, fixedrange=True, tickfont={"color": TEXT_PRIMARY},
    )
    return figure.to_html(
        full_html=False,
        include_plotlyjs=False,
        config={"displayModeBar": False, "responsive": True},
    )


def commissioning_line_figure(years, counts):
    """Line chart: number of wind turbines commissioned per year."""
    if not years:
        return None
    many_years = len(years) > 30          # markers only when they stay readable
    span = years[-1] - years[0]
    step = 1 if span <= 12 else 2 if span <= 24 else 5 if span <= 60 else 10
    figure = go.Figure(
        go.Scatter(
            x=years,
            y=counts,
            mode="lines" if many_years else "lines+markers",
            line={"color": BAR_COLOR, "width": 2},
            marker={"size": 8, "color": BAR_COLOR, "line": {"color": "#ffffff", "width": 2}},
            customdata=[_german(count, 0) for count in counts],
            hovertemplate="<b>%{x}</b><br>%{customdata} Anlagen in Betrieb genommen<extra></extra>",
        )
    )
    figure.update_layout(
        height=340,
        margin={"l": 8, "r": 16, "t": 8, "b": 40},
        separators=",.",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": FONT, "size": 12, "color": TEXT_SECONDARY},
        hoverlabel={"bgcolor": "#ffffff", "bordercolor": "#e2e8f0",
                    "font": {"family": FONT, "size": 12, "color": TEXT_PRIMARY}},
        hovermode="x unified",
        showlegend=False,
    )
    figure.update_xaxes(
        title={"text": "Jahr der Inbetriebnahme", "font": {"size": 11}},
        tickformat="d",              # 2014, not 2.014
        tick0=years[0] - years[0] % step, dtick=step,   # round years: 1950, 1960, ...
        range=[years[0] - 0.5, years[-1] + 0.5],         # no empty ticks past the data
        showgrid=False, zeroline=False, fixedrange=True,
    )
    figure.update_yaxes(
        title={"text": "Anlagen", "font": {"size": 11}},
        rangemode="tozero", tickformat=",d",
        showgrid=True, gridcolor=GRID_COLOR, zeroline=False, fixedrange=True,
    )
    return figure


def commissioning_line_chart(years, counts):
    """HTML snippet of commissioning_line_figure() ("" when there is nothing to draw)."""
    figure = commissioning_line_figure(years, counts)
    if figure is None:
        return ""
    return figure.to_html(
        full_html=False,
        include_plotlyjs=False,
        config={"displayModeBar": False, "responsive": True},
    )
