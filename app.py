"""B2B NTRBD revenue impact dashboard - FC->DS and FC->RS.

Revenue/profit are counted only for SKUs that were inwarded for NTRBD AND sold
within that same NTRBD timestamp window, matching the AIR in/out log rule used in
the source xlsx/pptx deliverables.

Run locally:  streamlit run app.py
Deploy:       Streamlit Community Cloud (reads ./data/*.parquet from the repo)
"""

import altair as alt
import pandas as pd
import streamlit as st

st.set_page_config(page_title="B2B NTRBD Revenue Impact", page_icon="📦", layout="wide")

DATA_RAW = "data/ntrbd_dashboard.parquet"
DATA_SUM = "data/ntrbd_sku_summary.parquet"

CR = 1e7
BEFORE = "Before (May-Jun)"
AFTER = "After (Jul-Aug)"

NAVY = "#1F3864"
BLUE = "#2E75B6"
GREEN = "#2E7D32"
RED = "#C00000"
AMBER = "#9C6500"
GREY = "#595959"


@st.cache_data(show_spinner=False)
def load_raw():
    # dtypes and the label columns are already correct in the parquet, so this is
    # just a read. No post-hoc datetime coercion: the timestamp columns the old
    # version converted here were never used by any chart or table, and they cost
    # ~190 MB as object columns.
    return pd.read_parquet(DATA_RAW)


def month_label(values):
    """'2026-05' -> 'May 2026'. Handles the categorical dtype used in the parquet."""
    return pd.to_datetime(pd.Series(values).astype("string")).dt.strftime("%b %Y")


@st.cache_data(show_spinner=False)
def load_summary():
    return pd.read_parquet(DATA_SUM)


def cr(x):
    return round(float(x) / CR, 2)


def crs(x):
    """Rupees in -> formatted rupees in crores."""
    return f"₹{float(x) / CR:,.2f} Cr"


def delta_pct(before, after):
    if not before:
        return None
    return (after - before) / before * 100


@st.cache_data(show_spinner=False)
def classify_shift(frame):
    """Same before/after shift rules used in the pptx deliverable."""
    def cat(r):
        pb = r["po_before"] or 0
        pa = r["po_after"] or 0
        bb = r["breach_po_before"] or 0
        ba = r["breach_po_after"] or 0
        if pb and not pa:
            return "Only before"
        if pa and not pb:
            return "Only after"
        bp = bb / pb * 100 if pb else 0
        ap = ba / pa * 100 if pa else 0
        if bp == 0 and ap == 0:
            return "Always on time"
        if bp > 0 and ap == 0:
            return "Improved to on time"
        if bp > 0 and ap < bp:
            return "Improved, still breaching"
        if bp > 0 and ap > bp:
            return "Worsened"
        return "Neutral"

    out = frame.copy()
    out["shift"] = [cat(r) for r in out.to_dict("records")]
    return out


raw = load_raw()
summary = load_summary()

flows = raw["flow"].value_counts().sort_index()
FLOW_LABEL = {"ds": "FC → DS (dark store)", "rs": "FC → RS (retail store)"}

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("### Filters")

    available = sorted(flows.index.tolist())
    default_flow = [f for f in available if f == "ds"] or available[:1]
    picked = st.pills(
        "Flow", available, selection_mode="single", default=default_flow,
        format_func=lambda f: FLOW_LABEL.get(f, f.upper()),
    )
    flow = picked if picked in available else available[0]
    df_f = raw[raw["flow"] == flow]

    months = sorted(df_f["month"].dropna().unique())
    sel_months = st.multiselect(
        "Month", months, default=months,
        format_func=lambda m: month_label([m])[0],
    )

    fc_opts = sorted(df_f["fc"].dropna().astype(str).unique().tolist())
    sel_fc = st.multiselect("Source FC", fc_opts, default=fc_opts,
                            format_func=lambda v: f"FC {v}")

    dest_opts = sorted(df_f["destination"].dropna().astype(str).unique().tolist())
    sel_dest = st.multiselect("Destination (DS / store FC)", dest_opts, default=dest_opts)

    breach_mode = st.radio("NTRBD status", ["All", "Within NTRBD only", "Breached only"],
                           horizontal=False)
    couriers = sorted(df_f["courier_name"].dropna().astype(str).unique().tolist())
    sel_courier = st.multiselect("Courier", couriers, default=couriers)

    sku_search = st.text_input("SKU contains", placeholder="e.g. PPLB")
    top_n = st.slider("Top N SKUs by revenue", 10, 500, 50, step=10)

    st.divider()
    st.caption(
        "Revenue counts only units inwarded **and** sold within the same NTRBD "
        "window. Indicative bridge, not audited P&L."
    )

# ---------------------------------------------------------------- apply filters
df = df_f
if sel_months:
    df = df[df["month"].isin(sel_months)]
if sel_fc:
    df = df[df["fc"].astype(str).isin(sel_fc)]
if sel_dest:
    df = df[df["destination"].astype(str).isin(sel_dest)]
if sel_courier:
    df = df[df["courier_name"].astype(str).isin(sel_courier)]
if breach_mode == "Within NTRBD only":
    df = df[df["on_time"].fillna(False)]
elif breach_mode == "Breached only":
    df = df[~df["on_time"].fillna(False)]
if sku_search.strip():
    df = df[df["product_sku"].astype(str).str.contains(sku_search.strip(), case=False, na=False)]

if df.empty:
    st.warning("No rows match these filters. Widen the selection.")
    st.stop()

top_skus = (
    df.groupby("product_sku", observed=True)["revenue_ntrbd"].sum()
    .nlargest(top_n).index
)
df = df[df["product_sku"].isin(top_skus)]

# ---------------------------------------------------------------- header
st.title("B2B NTRBD revenue impact")
st.caption(
    f"{FLOW_LABEL.get(flow, flow.upper())} · May–Aug 2026 · "
    "Before (May–Jun) vs After (Jul–Aug) · top %d SKUs by revenue" % top_n
)

# ---------------------------------------------------------------- KPIs
po_level = df.groupby(["po_id", "period"], observed=True).agg(
    breach=("ntrbd_breach_flag", "max")
).reset_index()
po_tot = po_level.groupby("period", observed=True).agg(
    pos=("po_id", "nunique"), breach_pos=("breach", "sum")
)
po_tot["breach_pct"] = (po_tot["breach_pos"] / po_tot["pos"] * 100).round(2)

per = df.groupby("period", observed=True).agg(
    pos=("po_id", "nunique"),
    skus=("product_sku", "nunique"),
    qty=("po_qty", "sum"),
    sold=("sold_units_ntrbd", "sum"),
    revenue=("revenue_ntrbd", "sum"),
    profit=("profit_ntrbd", "sum"),
    tcv=("total_consignment_value", "sum"),
)

bp_b = int(po_tot.loc[BEFORE, "breach_pos"]) if BEFORE in po_tot.index else 0
bp_a = int(po_tot.loc[AFTER, "breach_pos"]) if AFTER in po_tot.index else 0
po_b = int(po_tot.loc[BEFORE, "pos"]) if BEFORE in po_tot.index else 0
po_a = int(po_tot.loc[AFTER, "pos"]) if AFTER in po_tot.index else 0
pct_b = bp_b / po_b * 100 if po_b else 0.0
pct_a = bp_a / po_a * 100 if po_a else 0.0

rev_b = float(per.loc[BEFORE, "revenue"]) if BEFORE in per.index else 0.0
rev_a = float(per.loc[AFTER, "revenue"]) if AFTER in per.index else 0.0
prof_b = float(per.loc[BEFORE, "profit"]) if BEFORE in per.index else 0.0
prof_a = float(per.loc[AFTER, "profit"]) if AFTER in per.index else 0.0
sold_b = int(per.loc[BEFORE, "sold"]) if BEFORE in per.index else 0
sold_a = int(per.loc[AFTER, "sold"]) if AFTER in per.index else 0
qty_b = int(per.loc[BEFORE, "qty"]) if BEFORE in per.index else 0
qty_a = int(per.loc[AFTER, "qty"]) if AFTER in per.index else 0

monthly_rev = (
    df.groupby("month", observed=True)["revenue_ntrbd"].sum().sort_index().tolist()
)
monthly_breach = []
for m in sel_months:
    sl = df[df["month"] == m]
    pol = sl.groupby("po_id", observed=True)["ntrbd_breach_flag"].max()
    monthly_breach.append(round(float((pol == 1).mean() * 100), 2) if len(pol) else 0.0)

with st.container(horizontal=True):
    st.metric(
        "Breach rate (PO)", f"{pct_b:.1f}% → {pct_a:.1f}%",
        None if pct_b == 0 else f"{pct_a - pct_b:+.1f} pp",
        border=True, delta_color="off", chart_data=monthly_breach, chart_type="line",
    )
    st.metric(
        "Units sold in window", f"{sold_b:,} → {sold_a:,}",
        f"{delta_pct(sold_b, sold_a):+.1f}%" if sold_b else None,
        border=True, delta_color="inverse",
    )
    st.metric(
        "Revenue in window", f"{crs(rev_b)} → {crs(rev_a)}",
        f"{delta_pct(rev_b, rev_a):+.1f}%" if rev_b else None,
        border=True, delta_color="normal", chart_data=[cr(x) for x in monthly_rev],
        chart_type="bar",
    )
    st.metric(
        "Profit in window", f"{crs(prof_b)} → {crs(prof_a)}",
        f"{delta_pct(prof_b, prof_a):+.1f}%" if prof_b else None,
        border=True, delta_color="normal",
    )

# ---------------------------------------------------------------- tab 1 overview
tab1, tab2, tab3, tab4 = st.tabs(["Overview", "Facilities", "Couriers", "SKU detail"])

with tab1:
    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.subheader("Monthly revenue and breach rate")
            m = (
                df.groupby("month", observed=True)
                .agg(revenue=("revenue_ntrbd", "sum"), profit=("profit_ntrbd", "sum"),
                     sold=("sold_units_ntrbd", "sum"))
                .reset_index()
                .sort_values("month")
            )
            m["Month"] = month_label(m["month"])
            m["Revenue (₹ Cr)"] = (m["revenue"] / CR).round(2)
            m["Profit (₹ Cr)"] = (m["profit"] / CR).round(2)
            chart = (
                alt.Chart(m)
                .mark_bar(color=BLUE)
                .encode(
                    x=alt.X("Month:N", sort=list(m["Month"]), title=None),
                    y=alt.Y("Revenue (₹ Cr):Q", title="Revenue (₹ Cr)"),
                    tooltip=["Month", "Revenue (₹ Cr)", "Profit (₹ Cr)", "sold"],
                )
            )
            st.altair_chart(chart)
    with right:
        with st.container(border=True):
            st.subheader("Breach rate by month")
            bm = (
                df.groupby("month", observed=True)["po_id"]
                .apply(lambda s: s.nunique())
                .reset_index(name="pos")
            )
            bflag = (
                df.groupby("month", observed=True)["ntrbd_breach_flag"].sum().reset_index(name="breach_rows")
            )
            bm = bm.merge(
                df[df["ntrbd_breach_flag"] == 1].groupby("month", observed=True)["po_id"]
                .nunique().reset_index(name="breach_pos"),
                on="month", how="left",
            ).fillna({"breach_pos": 0})
            bm["Breach %"] = (bm["breach_pos"] / bm["pos"] * 100).round(2)
            bm["Month"] = month_label(bm["month"])
            c2 = (
                alt.Chart(bm)
                .mark_line(point=True, color=RED, strokeWidth=3)
                .encode(
                    x=alt.X("Month:N", sort=list(bm["Month"]), title=None),
                    y=alt.Y("Breach %:Q", title="Breached POs (%)"),
                    tooltip=["Month", "Breach %", "breach_pos", "pos"],
                )
            )
            st.altair_chart(c2)

    with st.container(border=True):
        st.subheader("Before vs after, by measure")
        ba = pd.DataFrame({
            "Measure": ["Units sold in window", "Revenue (₹ Cr)", "Profit (₹ Cr)"],
            BEFORE: [sold_b, cr(rev_b), cr(prof_b)],
            AFTER: [sold_a, cr(rev_a), cr(prof_a)],
        })
        ba["Change"] = ba[AFTER] - ba[BEFORE]
        st.dataframe(
            ba,
            hide_index=True,
            column_config={
                "Measure": st.column_config.TextColumn("Measure", pinned=True),
                BEFORE: st.column_config.NumberColumn(BEFORE, format="%.2f"),
                AFTER: st.column_config.NumberColumn(AFTER, format="%.2f"),
                "Change": st.column_config.NumberColumn("Change", format="%+.2f"),
            },
        )

# ---------------------------------------------------------------- tab 2 facilities
with tab2:
    c1, c2 = st.columns(2)
    dim = "destination"
    label = "Destination (DS / store FC)"
    with c1:
        with st.container(border=True):
            st.subheader(f"In-window revenue by {label.lower()}")
            fd = (
                df.groupby(dim, observed=True)
                .agg(revenue=("revenue_ntrbd", "sum"), profit=("profit_ntrbd", "sum"))
                .reset_index().sort_values("revenue", ascending=False).head(25)
            )
            fd[dim] = fd[dim].astype(str)
            fd[label] = fd[dim]
            fd["Revenue (₹ Cr)"] = (fd["revenue"] / CR).round(2)
            ch = (
                alt.Chart(fd)
                .mark_bar(color=NAVY)
                .encode(
                    x=alt.X("Revenue (₹ Cr):Q", title="Revenue (₹ Cr)"),
                    y=alt.Y(f"{label}:N", sort=list(fd[label]), title=None),
                    tooltip=[label, "Revenue (₹ Cr)"],
                )
            )
            st.altair_chart(ch)
    with c2:
        with st.container(border=True):
            st.subheader(f"Breach rate by {label.lower()}")
            fb = []
            for k, g in df.groupby(dim, observed=True):
                pol = g.groupby("po_id", observed=True)["ntrbd_breach_flag"].max()
                if len(pol):
                    fb.append({label: str(k), "pos": len(pol),
                               "breach_pos": int((pol == 1).sum())})
            fb = pd.DataFrame(fb)
            if not fb.empty:
                fb["Breach %"] = (fb["breach_pos"] / fb["pos"] * 100).round(2)
                fb = fb.sort_values("Breach %", ascending=False).head(25)
                ch2 = (
                    alt.Chart(fb)
                    .mark_bar(color=RED)
                    .encode(
                        x=alt.X("Breach %:Q", title="Breached POs (%)"),
                        y=alt.Y(f"{label}:N", sort=list(fb[label]), title=None),
                        tooltip=[label, "Breach %", "breach_pos", "pos"],
                    )
                )
                st.altair_chart(ch2)
    if "region" in df.columns and df["region"].notna().any():
        with st.container(border=True):
            st.subheader("Revenue by region")
            rg = (
                df.groupby("region", observed=True)["revenue_ntrbd"].sum()
                .reset_index().sort_values("revenue_ntrbd", ascending=False)
            )
            rg["region"] = rg["region"].astype(str)
            rg["Revenue (₹ Cr)"] = (rg["revenue_ntrbd"] / CR).round(2)
            ch3 = (
                alt.Chart(rg)
                .mark_bar(color=GREEN)
                .encode(
                    x=alt.X("region:N", sort=list(rg["region"]), title=None),
                    y=alt.Y("Revenue (₹ Cr):Q", title="Revenue (₹ Cr)"),
                    tooltip=["region", "Revenue (₹ Cr)"],
                )
            )
            st.altair_chart(ch3)

# ---------------------------------------------------------------- tab 3 couriers
with tab3:
    cq = (
        df.groupby("courier_name", observed=True)
        .agg(pos=("po_id", "nunique"), qty=("po_qty", "sum"),
             sold=("sold_units_ntrbd", "sum"),
             revenue=("revenue_ntrbd", "sum"), profit=("profit_ntrbd", "sum"),
             tcv=("total_consignment_value", "sum"))
        .reset_index()
    )
    cq["courier_name"] = cq["courier_name"].astype(str).fillna("Unknown")
    bps = []
    for k, g in df.groupby("courier_name", observed=True):
        pol = g.groupby("po_id", observed=True)["ntrbd_breach_flag"].max()
        bps.append({"courier_name": str(k), "breach_pos": int((pol == 1).sum())})
    cq = cq.merge(pd.DataFrame(bps), on="courier_name", how="left")
    cq["Breach %"] = (cq["breach_pos"] / cq["pos"] * 100).round(2)
    cq["Revenue (₹ Cr)"] = (cq["revenue"] / CR).round(2)
    cq["Profit (₹ Cr)"] = (cq["profit"] / CR).round(2)

    a, b = st.columns(2)
    with a:
        with st.container(border=True):
            st.subheader("Revenue by courier")
            c1 = (
                alt.Chart(cq)
                .mark_bar(color=BLUE)
                .encode(
                    x=alt.X("Revenue (₹ Cr):Q", title="Revenue (₹ Cr)"),
                    y=alt.Y("courier_name:N", sort=list(cq["courier_name"]), title=None),
                    tooltip=["courier_name", "Revenue (₹ Cr)", "Breach %"],
                )
            )
            st.altair_chart(c1)
    with b:
        with st.container(border=True):
            st.subheader("Breach rate by courier")
            c2 = (
                alt.Chart(cq)
                .mark_bar(color=RED)
                .encode(
                    x=alt.X("Breach %:Q", title="Breached POs (%)"),
                    y=alt.Y("courier_name:N", sort=list(cq["courier_name"]), title=None),
                    tooltip=["courier_name", "Breach %", "breach_pos", "pos"],
                )
            )
            st.altair_chart(c2)

    with st.container(border=True):
        st.subheader("Courier detail")
        show = cq[["courier_name", "pos", "breach_pos", "Breach %", "qty", "sold",
                   "Revenue (₹ Cr)", "Profit (₹ Cr)"]].rename(columns={
                       "courier_name": "Courier", "pos": "POs",
                       "breach_pos": "Breached POs", "qty": "Units in",
                       "sold": "Units sold in window",
                   }).sort_values("Revenue (₹ Cr)", ascending=False)
        st.dataframe(
            show, hide_index=True,
            column_config={
                "Breach %": st.column_config.NumberColumn("Breach %", format="%.1f%%"),
                "Revenue (₹ Cr)": st.column_config.NumberColumn("Revenue (₹ Cr)", format="%.2f"),
                "Profit (₹ Cr)": st.column_config.NumberColumn("Profit (₹ Cr)", format="%.2f"),
            },
        )

# ---------------------------------------------------------------- tab 4 SKU detail
with tab4:
    s = summary[summary["flow"] == flow]
    if sku_search.strip():
        s = s[s["product_sku"].astype(str).str.contains(sku_search.strip(), case=False, na=False)]
    if not s.empty and sel_fc and "fc" in s.columns and s["fc"].notna().any():
        s = s[s["fc"].astype(str).isin(sel_fc)]
    s = classify_shift(s) if not s.empty else s

    if s.empty:
        st.info("No summary rows for these filters.")
    else:
        sc1, sc2 = st.columns([1, 2])
        with sc1:
            with st.container(border=True):
                st.subheader("Shift mix")
                sh = s["shift"].value_counts().rename_axis("Shift").reset_index(name="SKUs")
                sh["Share %"] = (sh["SKUs"] / len(s) * 100).round(1)
                ch = (
                    alt.Chart(sh)
                    .mark_bar(color=NAVY)
                    .encode(
                        x=alt.X("SKUs:Q", title="SKUs"),
                        y=alt.Y("Shift:N", sort=list(sh["Shift"]), title=None),
                        tooltip=["Shift", "SKUs", "Share %"],
                    )
                )
                st.altair_chart(ch)
        with sc2:
            with st.container(border=True):
                st.subheader("Before vs after revenue by shift group")
                g = s.groupby("shift", observed=True).agg(
                    before=("revenue_cr_before", "sum"), after=("revenue_cr_after", "sum")
                ).reset_index()
                melted = g.melt(id_vars=["shift"], value_vars=["before", "after"],
                                var_name="p", value_name="Revenue (₹ Cr)")
                melted["Period"] = melted["p"].map({"before": BEFORE, "after": AFTER})
                ch2 = (
                    alt.Chart(melted)
                    .mark_bar()
                    .encode(
                        x=alt.X("shift:N", sort=list(g["shift"]), title=None),
                        y=alt.Y("Revenue (₹ Cr):Q", title="Revenue (₹ Cr)"),
                        color=alt.Color("Period:N", scale=alt.Scale(
                            domain=[BEFORE, AFTER], range=[GREY, GREEN])),
                        xOffset="Period:N",
                        tooltip=["shift", "Period", "Revenue (₹ Cr)"],
                    )
                )
                st.altair_chart(ch2)

        st.subheader("SKU before / after")
        view = s[["product_sku", "shift", "po_before", "po_after", "breach_po_before",
                  "breach_po_after", "qty_before", "qty_after", "sold_units_before",
                  "sold_units_after", "revenue_cr_before", "revenue_cr_after",
                  "profit_cr_before", "profit_cr_after"]].copy()
        view["revenue_delta_cr"] = (
            view["revenue_cr_after"].fillna(0) - view["revenue_cr_before"].fillna(0)
        ).round(2)
        view = view.sort_values("revenue_delta_cr", ascending=False)
        view = view.rename(columns={
            "product_sku": "SKU", "shift": "Shift", "po_before": "POs before",
            "po_after": "POs after", "breach_po_before": "Breached before",
            "breach_po_after": "Breached after", "qty_before": "Units before",
            "qty_after": "Units after", "sold_units_before": "Sold before",
            "sold_units_after": "Sold after",
            "revenue_cr_before": "Revenue before (₹ Cr)",
            "revenue_cr_after": "Revenue after (₹ Cr)",
            "profit_cr_before": "Profit before (₹ Cr)",
            "profit_cr_after": "Profit after (₹ Cr)",
            "revenue_delta_cr": "Revenue delta (₹ Cr)",
        })
        st.dataframe(
            view, hide_index=True, height=520,
            column_config={
                "SKU": st.column_config.TextColumn("SKU", pinned=True, width="medium"),
                "Revenue before (₹ Cr)": st.column_config.NumberColumn(format="%.2f"),
                "Revenue after (₹ Cr)": st.column_config.NumberColumn(format="%.2f"),
                "Profit before (₹ Cr)": st.column_config.NumberColumn(format="%.2f"),
                "Profit after (₹ Cr)": st.column_config.NumberColumn(format="%.2f"),
                "Revenue delta (₹ Cr)": st.column_config.NumberColumn(
                    "Revenue delta (₹ Cr)", format="%+.2f"),
            },
        )
        st.download_button(
            "Download filtered SKUs (CSV)",
            view.to_csv(index=False).encode("utf-8"),
            file_name="ntrbd_sku_before_after.csv",
            mime="text/csv",
        )

with st.expander("Method & caveats"):
    st.markdown(
        """
- **Revenue rule:** a unit counts only if the SKU was inwarded for NTRBD *and* sold
  after inward but on or before `ntrbd_cutoff`. Breached POs therefore contribute 0.
- **Sell price:** `our_price` (avg from `shop_orderitem_modify`), falling back to
  `unit_price` (avg from `procurement_poitem`), then ₹275. Product-level average,
  not per-order ASP.
- **Cost:** `actual_cost_price` avg per product from `procurement_inventoryitem`.
- **Spine:** PO × SKU, so breach counts are on SKU lines rather than PO headers only.
- This is an **indicative revenue bridge, not an audited P&L.** Exact revenue needs
  an OMS/B2B sales join with per-order ASP and delivery pincode.
- Before = May–Jun 2026, After = Jul–Aug 2026.
        """
    )
