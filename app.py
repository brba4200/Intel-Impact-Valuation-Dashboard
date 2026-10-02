"""
Intel Impact Monetization Dashboard
-----------------------------------
Applies TSMC's 2025 Sustainability Impact Valuation methodology (EP&L / Impact-Weighted
Accounts) to Intel's disclosed, non-monetized data for three impact factors:
GHG (carbon), water, and occupational health & safety.

Run:  pip install -r requirements.txt
      streamlit run app.py
"""
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Intel Impact Monetization", layout="wide", page_icon="📊")

# Escape "$" so Streamlit markdown does not render dollar amounts as LaTeX
def _esc(fn):
    def w(body, *a, **k):
        return fn(body.replace("$", "\\$") if isinstance(body, str) else body, *a, **k)
    return w
for _n in ["markdown", "caption", "success", "warning", "info"]:
    setattr(st, _n, _esc(getattr(st, _n)))

DATA = Path(__file__).parent / "data"
GAL_TO_M3 = 3_785_411.784          # m3 per billion US gallons
HIST_END = 2025

# Colours (validated categorical palette, fixed order) -----------------------
C_CARBON, C_WATER, C_OHS = "#2a78d6", "#1baf7a", "#eb6834"
C_BAU, C_TGT, C_CUS = "#4a3aa7", "#e34948", "#008300"
C_TSMC = "#eda100"
GRID = "rgba(128,128,128,0.18)"


@st.cache_data
def load():
    h = pd.read_csv(DATA / "intel_history.csv")
    raw = pd.read_excel(DATA / "Intel__TSMC_Impact_Valuation.xlsx",
                    sheet_name="TSMC & Intel Trends", header=3, nrows=12)
    names = ["ghg_cost_ntdm", "renewable_benefit_ntdm", "energy_saving_benefit_ntdm",
         "supply_chain_ghg_ntdm", "water_consumption_cost_ntdm", "wastewater_cost_ntdm",
         "water_saving_benefit_ntdm", "reclaimed_benefit_ntdm", "health_mgmt_benefit_ntdm",
         "harassment_cost_ntdm", "employee_injury_cost_ntdm", "contractor_injury_cost_ntdm"]
    years = [c for c in raw.columns if str(c).isdigit()]
    t = raw[years].T
    t.columns = names
    t.index = t.index.astype(int)
    t = t.rename_axis("year").reset_index()
    
    xlsx = DATA / "Intel__TSMC_Impact_Valuation.xlsx"

    w = pd.read_excel(xlsx, sheet_name="Intel Water by Site", header=3, nrows=20)
    w = w.rename(columns={"Site": "site", "Water stress": "stress",
                          "Fresh water withdrawn (ML)": "fresh_withdrawn_ml"})
    w["stress"] = w["stress"].fillna("Low-Medium")

    g = pd.read_excel(xlsx, sheet_name="Intel GHG by Site", header=3, nrows=20)
    g = g.rename(columns={"Site": "site", "Fluorinated GHGs": "fgas_t",
                          "Combustion / fuels": "combustion_t", "Heat transfer fluids": "htf_t",
                          "N2O": "n2o_t", "Other": "other_t",
                          "Total Scope 1": "scope1_t", "Scope 2 (market)": "scope2_t"})
    return h, t, w, g


hist, tsmc, wsites, gsites = load()
stress_share = wsites.loc[wsites.stress.isin(["High", "Extremely high"]), "fresh_withdrawn_ml"].sum() / wsites.fresh_withdrawn_ml.sum()


def fig_style(fig, title, ytitle, height=380):
    fig.update_layout(
        title=dict(text=title, x=0, font=dict(size=15)), height=height,
        margin=dict(l=10, r=10, t=50, b=10), hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_xaxes(showgrid=False, dtick=1 if fig.layout.xaxis.type != "category" else None)
    fig.update_yaxes(title=ytitle, gridcolor=GRID, zeroline=True, zerolinecolor="rgba(128,128,128,0.5)")
    return fig


def money(x):
    s = "-" if x < 0 else ""
    x = abs(x)
    return f"{s}${x/1e3:,.2f}B" if x >= 1000 else f"{s}${x:,.1f}M"


# =============================================================================
# SIDEBAR: value factors & scenario assumptions
# =============================================================================
st.sidebar.title("Assumptions")
st.sidebar.caption("Defaults = TSMC 2025 Impact Valuation Report coefficients (converted at 31.16 NT\\$ per US\\$). Drag to test sensitivity.")

with st.sidebar.expander("1 · Carbon value factors", expanded=True):
    scc = st.slider("Social cost of carbon, 2025 (US$/tCO2e)", 0, 500, 244, 1,
                    help="TSMC uses US$244/t for 2025 (US EPA 2023; IFVI/VBA). EPA's 2023 central estimate at 2% discount ≈ US$190-230.")
    scc_g = st.slider("SCC real growth per year (%)", 0.0, 5.0, 2.0, 0.1,
                      help="Applied backwards and forwards from 2025. TSMC's own table rises 205 → 244 (2021-25).") / 100
    renew_rate = st.slider("Renewable electricity benefit (US$/MWh)", 0.0, 100.0, 11.84, 0.5,
                           help="TSMC implied NT$0.369/kWh ≈ US$11.8/MWh (NT$21,317m / 57.8 bn kWh).")
    scope3_on = st.checkbox("Also show upstream Scope 3 (purchased + capital goods) cost", value=False)

with st.sidebar.expander("2 · Water value factors", expanded=True):
    w_cost = st.slider("Fresh-water withdrawal cost (US$/m³)", 0.0, 10.0, 1.44, 0.01,
                       help="TSMC: NT$5,709m / 127M m³ tap water = US$1.44/m³ (stress-weighted DALY + ecosystem model).")
    stress_mult = st.slider("Water-stress multiplier for High / Extremely-high stress sites", 1.0, 5.0, 1.0, 0.1,
                            help=f"TSMC weights by local water stress. {stress_share:.0%} of Intel's 2025 fresh water is drawn at high/extremely-high stress sites (WRI Aqueduct).")
    d_cost = st.slider("Discharge cost (US$/m³)", 0.0, 2.0, 0.19, 0.01, help="TSMC: NT$573m / 98M m³ wastewater.")
    c_ben = st.slider("Conservation benefit (US$/m³)", 0.0, 10.0, 1.52, 0.01, help="TSMC water-saving: NT$15,135m / 319M m³.")
    r_ben = st.slider("Watershed restoration benefit (US$/m³)", 0.0, 10.0, 1.44, 0.01,
                      help="TSMC does not value restoration; its reclaimed-water rate (US$1.44/m³) is used as a proxy.")
    restore_on = st.checkbox("Count restored water as a benefit", value=True)

with st.sidebar.expander("3 · Health & safety value factors", expanded=True):
    cost_day = st.slider("Cost per lost workday (US$)", 0, 2000, 72, 1,
                         help="TSMC implied: NT$1.43m / 636 days = US$72 (human cost + insurance, Taiwan wages). US-based estimates are far higher — test it.")
    days_case = st.slider("Lost workdays per days-away case", 1.0, 60.0, 10.97, 0.5,
                          help="Intel does not disclose lost days. Default = TSMC 636 / 58.")
    cost_rec = st.slider("Additional cost per recordable case (US$)", 0, 50000, 0, 500,
                         help="TSMC only values lost-time injuries. Set >0 to also value medical-treatment cases.")
    fatal_n = st.slider("Assumed workplace fatalities per year (employees + contractors)", 0, 5, 0,
                        help="Intel does not disclose fatalities. TSMC had 1 contractor fatality in 2025.")
    fatal_cost = st.slider("Socioeconomic loss per fatality (US$M)", 0.0, 60.0, 47.0, 0.5,
                           help="TSMC: NT$1,464m human-capital loss (YPLL/WYPLL) ≈ US$47M. OECD VSL = US$2.7M.")

with st.sidebar.expander("4 · Human-dignity harms (optional)"):
    dignity_on = st.checkbox("Include sexual-harassment cost in OHS (as TSMC does)", value=False)
    har_n = st.slider("Assumed substantiated harassment cases per year", 0, 200, 0,
                      help="Intel does not disclose. TSMC: 28 substantiated of 45 complaints.")
    har_cost = st.slider("Cost per case (US$)", 0, 500000, 65010, 1000, help="TSMC: NT$56.72m / 28 cases.")

st.sidebar.markdown("---")
st.sidebar.subheader("Future pathway (2026-2040)")
scenario = st.sidebar.radio("Scenario shown in detail", ["Business as usual", "Intel stated targets", "Custom"], index=2)
with st.sidebar.expander("Custom scenario levers", expanded=True):
    cu = dict(
        s1_g=st.slider("Scope 1 change per year (%)", -20.0, 10.0, -3.0, 0.5) / 100,
        el_g=st.slider("Electricity demand growth per year (%)", -5.0, 15.0, 3.0, 0.5) / 100,
        re_2030=st.slider("Renewable electricity share by 2030 (%)", 90, 100, 100) / 100,
        w_g=st.slider("Fresh-water withdrawal growth per year (%)", -10.0, 15.0, 1.0, 0.5) / 100,
        c_g=st.slider("Water conserved growth per year (%)", -10.0, 15.0, 4.0, 0.5) / 100,
        r_g=st.slider("Water restored growth per year (%)", -10.0, 20.0, 5.0, 0.5) / 100,
        emp_g=st.slider("Workforce growth per year (%)", -10.0, 10.0, 0.0, 0.5) / 100,
        rr_g=st.slider("Recordable-rate change per year (%)", -20.0, 10.0, -5.0, 0.5) / 100,
    )
disc = st.sidebar.slider("Discount rate for NPV (%)", 0.0, 10.0, 2.0, 0.25) / 100
end_year = st.sidebar.slider("Projection end year", 2030, 2050, 2040)

# =============================================================================
# MODEL
# =============================================================================
def scc_at(y):
    return scc * (1 + scc_g) ** (y - 2025)


water_stress_factor = 1 + (stress_mult - 1) * stress_share
returned_share = (hist.water_returned_bgal / hist.water_withdrawn_bgal).dropna().iloc[-1]   # 2025 ≈ 77%
dar_ratio = 0.19 / 0.78


def monetize(df):
    """Return a frame of monetized impacts in US$ millions (positive = benefit)."""
    o = pd.DataFrame({"year": df.year})
    elec = df.electricity_bkwh.fillna(df.energy_bkwh * 0.85)
    o["carbon_cost"] = -(df.ghg_scope12_mt * 1e6) * df.year.map(scc_at) / 1e6
    o["renewable_benefit"] = (elec * df.renewable_pct * 1e6 * renew_rate / 1e6).fillna(0)
    o["scope3_cost"] = -(df.get("scope3_up_t", pd.Series(np.nan, index=df.index))) * df.year.map(scc_at) / 1e6
    wd = df.water_withdrawn_bgal * GAL_TO_M3
    ret = df.water_returned_bgal.fillna(df.water_withdrawn_bgal * returned_share) * GAL_TO_M3
    o["water_cost"] = -wd * w_cost * water_stress_factor / 1e6
    o["discharge_cost"] = -ret * d_cost / 1e6
    o["conserve_benefit"] = (df.water_conserved_bgal * GAL_TO_M3 * c_ben / 1e6).fillna(0)
    o["restore_benefit"] = (df.water_restored_bgal * GAL_TO_M3 * r_ben / 1e6).fillna(0) if restore_on else 0.0
    emp = df.employees_k * 1000
    lt_cases = df.days_away_rate * emp / 100
    rec_cases = df.recordable_rate * emp / 100
    o["lt_cases"], o["rec_cases"] = lt_cases, rec_cases
    o["injury_cost"] = -(lt_cases * days_case * cost_day + rec_cases * cost_rec) / 1e6
    o["fatality_cost"] = -fatal_n * fatal_cost
    o["dignity_cost"] = -(har_n * har_cost / 1e6) if dignity_on else 0.0
    o["Carbon"] = o.carbon_cost + o.renewable_benefit
    o["Water"] = o.water_cost + o.discharge_cost + o.conserve_benefit + o.restore_benefit
    o["OHS"] = o.injury_cost + o.fatality_cost + o.dignity_cost
    o["Net"] = o.Carbon + o.Water + o.OHS
    return o


def project(kind):
    last = hist[hist.year == HIST_END].iloc[0]
    yrs = list(range(HIST_END + 1, end_year + 1))
    if kind == "Business as usual":
        p = dict(s1_g=0.025, el_g=0.03, re_2030=0.99, w_g=0.01, c_g=0.03, r_g=0.0, emp_g=0.0, rr_g=0.0)
    elif kind == "Intel stated targets":
        p = dict(s1_g=None, el_g=0.03, re_2030=1.0, w_g=0.0, c_g=0.05, r_g=0.05, emp_g=0.0, rr_g=None)
    else:
        p = cu
    ef_res = last.scope2_market_t / (last.electricity_bkwh * 1e6 * (1 - last.renewable_pct))  # t/MWh, residual mix
    rows = []
    s1, el, re = last.scope1_t, last.electricity_bkwh, last.renewable_pct
    w, c, r, emp, rr = last.water_withdrawn_bgal, last.water_conserved_bgal, last.water_restored_bgal, last.employees_k, last.recordable_rate
    s3 = 10_900_000
    for y in yrs:
        n = y - HIST_END
        if p["s1_g"] is None:                       # linear to net zero (S1+S2) in 2040
            s1 = max(last.scope1_t * (1 - n / (2040 - HIST_END)), 0)
        else:
            s1 = s1 * (1 + p["s1_g"])
        el = el * (1 + p["el_g"])
        re = min(last.renewable_pct + (p["re_2030"] - last.renewable_pct) * min(n / 5, 1), 1.0)
        s2 = el * 1e6 * (1 - re) * ef_res * (0.98 ** n)
        if kind == "Intel stated targets" and y >= 2040:
            s2 = 0
        w *= 1 + p["w_g"]; c *= 1 + p["c_g"]; r *= 1 + p["r_g"]; emp *= 1 + p["emp_g"]
        if p["rr_g"] is None:
            rr = max(last.recordable_rate + (0.5 - last.recordable_rate) * min(n / 5, 1), 0.5) if y <= 2030 else 0.5
        else:
            rr = rr * (1 + p["rr_g"])
        rows.append(dict(year=y, scope1_t=s1, scope2_market_t=s2, ghg_scope12_mt=(s1 + s2) / 1e6,
                         electricity_bkwh=el, energy_bkwh=el / 0.85, renewable_pct=re,
                         water_withdrawn_bgal=w, water_conserved_bgal=c, water_restored_bgal=r,
                         water_returned_bgal=w * returned_share, employees_k=emp,
                         recordable_rate=rr, days_away_rate=rr * dar_ratio, scope3_up_t=s3))
    return pd.DataFrame(rows)


hist2 = hist.copy()
hist2["scope3_up_t"] = np.nan
hist2.loc[hist2.year == 2025, "scope3_up_t"] = 10_900_000
hist2.loc[hist2.year == 2024, "scope3_up_t"] = 7_730_000 + 2_880_000
hist2.loc[hist2.year == 2023, "scope3_up_t"] = 5_800_000 + 2_500_000
H = monetize(hist2)
scen_inputs = {k: project(k) for k in ["Business as usual", "Intel stated targets", "Custom"]}
P = {k: monetize(v) for k, v in scen_inputs.items()}
PS, PSin = P[scenario], scen_inputs[scenario]


def npv(df):
    return sum(v / (1 + disc) ** (y - HIST_END) for y, v in zip(df.year, df.Net))


# =============================================================================
# HEADER & KPIs
# =============================================================================
st.title("Intel impact monetization dashboard")
st.caption("Intel's disclosed GHG, water and safety data (2011-2025 CSR reports) valued with TSMC's 2025 Impact Valuation coefficients. "
           "Positive = benefit to society, negative = cost. All values US$ millions unless stated.")

h25 = H[H.year == 2025].iloc[0]
k = st.columns(5)
k[0].metric("2025 net monetized impact", money(h25.Net),
            f"{money(h25.Net - H[H.year == 2024].iloc[0].Net)} vs 2024", delta_color="normal")
k[1].metric("Carbon (net)", money(h25.Carbon), f"cost {money(h25.carbon_cost)}", delta_color="off")
k[2].metric("Water (net)", money(h25.Water), f"withdrawal cost {money(h25.water_cost)}", delta_color="off")
k[3].metric("Health & safety", money(h25.OHS), f"{h25.lt_cases:,.0f} est. lost-time cases", delta_color="off")
k[4].metric(f"NPV 2026-{end_year} · {scenario}", money(npv(PS)), f"{disc:.1%} discount", delta_color="off")

tabs = st.tabs(["Overview", "Carbon", "Water", "Health & safety", "Scenarios", "TSMC benchmark", "Human dignity", "Recommendations", "Data & methods"])

# ---------------------------------------------------------------- Overview
with tabs[0]:
    fig = go.Figure()
    for col, colr in [("Carbon", C_CARBON), ("Water", C_WATER), ("OHS", C_OHS)]:
        fig.add_bar(x=H.year, y=H[col], name=col, marker_color=colr,
                    hovertemplate="%{y:$,.1f}M")
        fig.add_bar(x=PS.year, y=PS[col], name=f"{col} (projected)", marker_color=colr, opacity=0.4,
                    showlegend=False, hovertemplate="%{y:$,.1f}M")
    fig.add_scatter(x=pd.concat([H.year, PS.year]), y=pd.concat([H.Net, PS.Net]), name="Net",
                    mode="lines+markers", line=dict(color="#333", width=2), hovertemplate="%{y:$,.1f}M")
    fig.add_vline(x=HIST_END + 0.5, line_dash="dot", line_color="gray")
    fig.add_annotation(x=HIST_END + 0.6, y=1, yref="paper", text=f"Projection: {scenario} →", showarrow=False, xanchor="left")
    fig.update_layout(barmode="relative")
    st.plotly_chart(fig_style(fig, "Monetized impact by factor, history and projection", "US$ millions", 460), width="stretch")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**What the 2025 numbers say**")
        st.markdown(
            f"- Carbon dominates: Scope 1+2 of **{hist.iloc[-1].ghg_scope12_mt:.2f} MtCO2e** costs **{money(-h25.carbon_cost)}** at US${scc}/t; "
            f"renewable electricity offsets **{money(h25.renewable_benefit)}**.\n"
            f"- Scope 1 (process F-GHGs, N2O, combustion) is now **{hist.iloc[-1].scope1_t/hist.iloc[-1].ghg_scope12_mt/1e6:.0%}** of the total because electricity is 99% renewable — "
            "the remaining lever is process abatement.\n"
            f"- Water is close to net neutral: conservation and restoration benefits ({money(h25.conserve_benefit + h25.restore_benefit)}) vs withdrawal and discharge costs ({money(h25.water_cost + h25.discharge_cost)}).\n"
            f"- Health & safety looks small only because TSMC's Taiwan-based cost per lost day (US${cost_day}) is low and Intel discloses no fatalities, contractor injuries or lost days."
        )
    with c2:
        if scope3_on:
            st.metric("Upstream Scope 3 cost (purchased + capital goods), 2025", money(h25.scope3_cost),
                      "10.9 MtCO2e — not in net, shown for scale", delta_color="off")
        st.markdown("**Data quality by factor**")
        st.dataframe(pd.DataFrame({
            "Factor": ["Carbon", "Water", "Health & safety"],
            "Intel data fit to TSMC method": ["Strong (tonnes by site and gas)", "Medium (volumes by site; no pollutant loads)", "Weak (rates only; no counts, lost days, contractors)"],
            "Years monetized": ["2011-2025", "2011-2025 (benefits from 2020)", "2011-2025 (estimated cases)"],
        }), hide_index=True, width="stretch")

# ---------------------------------------------------------------- Carbon
with tabs[1]:
    c1, c2 = st.columns(2)
    with c1:
        fig = go.Figure()
        fig.add_scatter(x=hist.year, y=hist.ghg_scope12_mt, name="Actual (market-based)", mode="lines+markers",
                        line=dict(color=C_CARBON, width=2), hovertemplate="%{y:.2f} Mt")
        for kname, colr in [("Business as usual", C_BAU), ("Intel stated targets", C_TGT), ("Custom", C_CUS)]:
            d = scen_inputs[kname]
            fig.add_scatter(x=[HIST_END, *d.year], y=[hist.iloc[-1].ghg_scope12_mt, *d.ghg_scope12_mt], name=kname,
                            mode="lines", line=dict(color=colr, width=2, dash="dash"), hovertemplate="%{y:.2f} Mt")
        fig.add_hline(y=1.57 * 0.9, line_dash="dot", line_color="gray", annotation_text="2030 goal: -10% vs 2019", annotation_position="top right")
        st.plotly_chart(fig_style(fig, "Scope 1+2 emissions (MtCO2e)", "MtCO2e"), width="stretch")
    with c2:
        fig = go.Figure()
        fig.add_bar(x=H.year, y=H.carbon_cost, name="Emissions cost", marker_color=C_CARBON, hovertemplate="%{y:$,.1f}M")
        fig.add_bar(x=H.year, y=H.renewable_benefit, name="Renewable benefit", marker_color="#86b6ef", hovertemplate="%{y:$,.1f}M")
        if scope3_on:
            fig.add_scatter(x=H.year, y=H.scope3_cost, name="Upstream Scope 3 cost (memo)", mode="markers",
                            marker=dict(color=C_OHS, size=10), hovertemplate="%{y:$,.0f}M")
        fig.update_layout(barmode="relative")
        st.plotly_chart(fig_style(fig, "Monetized carbon impact (US$M)", "US$ millions"), width="stretch")
    c1, c2 = st.columns(2)
    with c1:
        g = gsites.assign(total=gsites.scope1_t + gsites.scope2_t).sort_values("total", ascending=True).tail(10)
        g["cost"] = g.total * scc / 1e6
        fig = go.Figure(go.Bar(y=g.site, x=g.cost, orientation="h", marker_color=C_CARBON,
                               customdata=g.total, hovertemplate="%{y}: %{x:$,.1f}M (%{customdata:,.0f} t)<extra></extra>"))
        st.plotly_chart(fig_style(fig, f"2025 carbon cost by site, top 10 (at US${scc}/t)", ""), width="stretch")
    with c2:
        sccs = np.arange(0, 501, 25)
        fig = go.Figure(go.Scatter(x=sccs, y=-hist.iloc[-1].ghg_scope12_mt * sccs, mode="lines+markers",
                                   line=dict(color=C_CARBON, width=2), hovertemplate="SCC $%{x}/t → %{y:$,.0f}M<extra></extra>"))
        fig.add_vline(x=scc, line_dash="dot", annotation_text=f"current ${scc}")
        f = fig_style(fig, "Sensitivity: 2025 emissions cost vs social cost of carbon", "US$ millions")
        f.update_xaxes(title="SCC (US$/tCO2e)", dtick=50); f.update_layout(hovermode="closest")
        st.plotly_chart(f, width="stretch")
    fg = gsites[["fgas_t", "combustion_t", "htf_t", "n2o_t", "other_t", "scope2_t"]].sum()
    st.caption(f"2025 Scope 1+2 by source: F-GHGs {fg.fgas_t/1e3:,.0f} kt · combustion {fg.combustion_t/1e3:,.0f} kt · N2O {fg.n2o_t/1e3:,.0f} kt · "
               f"heat-transfer fluids {fg.htf_t/1e3:,.0f} kt · Scope 2 {fg.scope2_t/1e3:,.0f} kt (Intel report p. 62). "
               "Four fabs (Rio Rancho, Ocotillo, Leixlip, Qiryat Gat, Ronler Acres) drive ~90% of emissions.")

# ---------------------------------------------------------------- Water
with tabs[2]:
    c1, c2 = st.columns(2)
    with c1:
        fig = go.Figure()
        for col, nm, colr in [("water_withdrawn_bgal", "Withdrawn", C_WATER), ("water_conserved_bgal", "Conserved", C_CARBON),
                              ("water_restored_bgal", "Restored", C_TSMC)]:
            fig.add_scatter(x=hist.year, y=hist[col], name=nm, mode="lines+markers", line=dict(color=colr, width=2),
                            hovertemplate="%{y:.1f} bn gal")
            fig.add_scatter(x=[HIST_END, *PSin.year], y=[hist.iloc[-1][col], *PSin[col]], name=f"{nm} ({scenario})",
                            mode="lines", line=dict(color=colr, width=2, dash="dash"), showlegend=False, hovertemplate="%{y:.1f} bn gal")
        st.plotly_chart(fig_style(fig, "Water volumes (billion gallons)", "billion gallons"), width="stretch")
    with c2:
        fig = go.Figure()
        for col, nm, colr in [("water_cost", "Withdrawal cost", C_WATER), ("discharge_cost", "Discharge cost", "#0f6b4a"),
                              ("conserve_benefit", "Conservation benefit", C_CARBON), ("restore_benefit", "Restoration benefit", C_TSMC)]:
            fig.add_bar(x=H.year, y=H[col], name=nm, marker_color=colr, hovertemplate="%{y:$,.1f}M")
        fig.add_scatter(x=H.year, y=H.Water, name="Net water", mode="lines+markers", line=dict(color="#333", width=2), hovertemplate="%{y:$,.1f}M")
        fig.update_layout(barmode="relative")
        st.plotly_chart(fig_style(fig, "Monetized water impact (US$M)", "US$ millions"), width="stretch")
    ws = wsites.assign(cost=lambda d: d.fresh_withdrawn_ml * 1000 * w_cost * np.where(d.stress.isin(["High", "Extremely high"]), stress_mult, 1) / 1e6)
    ws = ws.sort_values("cost")
    colors = ws.stress.map({"Extremely high": C_OHS, "High": C_TSMC, "Low-Medium": C_WATER})
    fig = go.Figure(go.Bar(y=ws.site, x=-ws.cost, orientation="h", marker_color=colors, customdata=np.stack([ws.stress, ws.fresh_withdrawn_ml], -1),
                           hovertemplate="%{y}: %{x:$,.2f}M · %{customdata[1]:,} ML · stress: %{customdata[0]}<extra></extra>"))
    st.plotly_chart(fig_style(fig, "2025 fresh-water cost by site (orange = extremely high stress, yellow = high)", "", 520), width="stretch")
    st.caption(f"{stress_share:.0%} of Intel's fresh water comes from high or extremely-high stress basins (Arizona, Israel, India, New Mexico, Chengdu). "
               "Raise the stress multiplier to see how TSMC-style stress weighting changes the cost. Note: Intel's 'net positive water' (103%) counts discharged water as returned; "
               "TSMC's 'Water Positive' rate (21%) is a stricter definition.")

# ---------------------------------------------------------------- OHS
with tabs[3]:
    c1, c2 = st.columns(2)
    with c1:
        fig = go.Figure()
        fig.add_scatter(x=hist.year, y=hist.recordable_rate, name="Recordable rate", mode="lines+markers", line=dict(color=C_OHS, width=2), hovertemplate="%{y:.2f}")
        fig.add_scatter(x=hist.year, y=hist.days_away_rate, name="Days-away rate", mode="lines+markers", line=dict(color=C_BAU, width=2), hovertemplate="%{y:.2f}")
        fig.add_scatter(x=[HIST_END, *PSin.year], y=[hist.iloc[-1].recordable_rate, *PSin.recordable_rate], name=f"Recordable ({scenario})",
                        mode="lines", line=dict(color=C_OHS, dash="dash"), hovertemplate="%{y:.2f}")
        fig.add_hline(y=0.5, line_dash="dot", annotation_text="Intel goal < 0.5")
        fig.add_hline(y=0.9, line_dash="dot", line_color="gray", annotation_text="US semi industry 0.9", annotation_position="bottom right")
        st.plotly_chart(fig_style(fig, "Injury rates per 100 employees (OSHA)", "rate per 100 FTE"), width="stretch")
    with c2:
        fig = go.Figure()
        fig.add_bar(x=H.year, y=H.injury_cost, name="Injury cost", marker_color=C_OHS, hovertemplate="%{y:$,.2f}M")
        fig.add_bar(x=H.year, y=H.fatality_cost, name="Fatality loss (assumed)", marker_color="#a33a12", hovertemplate="%{y:$,.1f}M")
        if dignity_on:
            fig.add_bar(x=H.year, y=[H.dignity_cost] * len(H) if np.isscalar(H.dignity_cost) else H.dignity_cost, name="Harassment (assumed)",
                        marker_color=C_BAU, hovertemplate="%{y:$,.2f}M")
        fig.update_layout(barmode="relative")
        st.plotly_chart(fig_style(fig, "Monetized health & safety impact (US$M)", "US$ millions"), width="stretch")
    st.dataframe(H[["year", "lt_cases", "rec_cases", "injury_cost"]].rename(columns={
        "lt_cases": "Est. days-away cases", "rec_cases": "Est. recordable cases", "injury_cost": "Injury cost (US$M)"}).round(2).tail(8),
        hide_index=True, width="stretch")
    st.info("Intel publishes only rates. Cases = rate × employees ÷ 100 (approximation; OSHA rates use 200,000 hours). "
            "TSMC's largest OHS cost in 2025 was one contractor fatality (US$47M) — Intel reports no contractor or fatality data, so this tab is a lower bound.")

# ---------------------------------------------------------------- Scenarios
with tabs[4]:
    fig = go.Figure()
    fig.add_scatter(x=H.year, y=H.Net, name="Historical", mode="lines+markers", line=dict(color="#333", width=2), hovertemplate="%{y:$,.1f}M")
    for kname, colr in [("Business as usual", C_BAU), ("Intel stated targets", C_TGT), ("Custom", C_CUS)]:
        d = P[kname]
        fig.add_scatter(x=[HIST_END, *d.year], y=[h25.Net, *d.Net], name=kname, mode="lines", line=dict(color=colr, width=2, dash="dash"),
                        hovertemplate="%{y:$,.1f}M")
    st.plotly_chart(fig_style(fig, "Net monetized impact: history and three pathways", "US$ millions", 440), width="stretch")
    summ = pd.DataFrame([{
        "Scenario": kname, f"Net impact {end_year} (US$M)": P[kname].Net.iloc[-1],
        f"Cumulative 2026-{end_year} (US$M)": P[kname].Net.sum(), f"NPV @ {disc:.1%} (US$M)": npv(P[kname]),
        f"Scope 1+2 in {end_year} (Mt)": scen_inputs[kname].ghg_scope12_mt.iloc[-1],
    } for kname in P]).round(1)
    st.dataframe(summ, hide_index=True, width="stretch")
    gap = npv(P["Intel stated targets"]) - npv(P["Business as usual"])
    st.success(f"Delivering Intel's stated targets instead of business-as-usual is worth **{money(gap)}** in avoided societal cost (NPV 2026-{end_year}). "
               "That is the business case to set against abatement capex.")
    st.markdown("**Scenario definitions** — *BAU*: Scope 1 +2.5%/yr (2021-25 trend), electricity +3%/yr, renewables 99%, water +1%/yr, injury rates flat. "
                "*Intel stated targets*: Scope 1+2 linear to net zero by 2040, 100% renewables by 2030, flat water use, conservation +5%/yr, recordable rate to 0.5 by 2030. "
                "*Custom*: sidebar levers.")

# ---------------------------------------------------------------- TSMC benchmark
with tabs[5]:
    fx = 31.16
    tb = tsmc.copy()
    tb["Carbon"] = (tb.ghg_cost_ntdm + tb.renewable_benefit_ntdm + tb.energy_saving_benefit_ntdm) / fx
    tb["Water"] = (tb.water_consumption_cost_ntdm + tb.wastewater_cost_ntdm + tb.water_saving_benefit_ntdm + tb.reclaimed_benefit_ntdm) / fx
    tb["OHS"] = (tb.health_mgmt_benefit_ntdm + tb.harassment_cost_ntdm + tb.employee_injury_cost_ntdm + tb.contractor_injury_cost_ntdm) / fx
    c1, c2 = st.columns(2)
    with c1:
        fig = go.Figure()
        for f_ in ["Carbon", "Water", "OHS"]:
            fig.add_bar(x=[f"{f_}"], y=[tb[tb.year == 2025][f_].iloc[0]], name="TSMC", marker_color=C_TSMC, showlegend=f_ == "Carbon", hovertemplate="TSMC %{y:$,.0f}M")
            fig.add_bar(x=[f"{f_}"], y=[h25[f_]], name="Intel", marker_color=C_CARBON, showlegend=f_ == "Carbon", hovertemplate="Intel %{y:$,.0f}M")
        fig.update_layout(barmode="group")
        f = fig_style(fig, "2025 net monetized impact: TSMC (reported) vs Intel (this model)", "US$ millions")
        f.update_xaxes(dtick=None)
        st.plotly_chart(f, width="stretch")
    with c2:
        fig = go.Figure()
        fig.add_scatter(x=tb.year, y=tb.ghg_cost_ntdm / fx, name="TSMC emissions cost", mode="lines+markers", line=dict(color=C_TSMC, width=2), hovertemplate="%{y:$,.0f}M")
        hh = H[H.year >= 2021]
        fig.add_scatter(x=hh.year, y=hh.carbon_cost, name="Intel emissions cost", mode="lines+markers", line=dict(color=C_CARBON, width=2), hovertemplate="%{y:$,.0f}M")
        st.plotly_chart(fig_style(fig, "Scope 1+2 emissions cost, 2021-2025", "US$ millions"), width="stretch")
    st.markdown(
        "| | TSMC 2025 | Intel 2025 |\n|---|---|---|\n"
        f"| Scope 1+2 (MtCO2e) | 15.83 | {hist.iloc[-1].ghg_scope12_mt:.2f} |\n"
        f"| Renewable electricity | 20.1% | {hist.iloc[-1].renewable_pct:.0%} |\n"
        f"| Fresh water (M m³) | 127 | {hist.iloc[-1].water_withdrawn_bgal*3.785:.1f} |\n"
        "| Monetizes impacts? | Yes — Integrated P&L across 6 capitals | No — volumes and rates only |\n"
        "| Lost-time injuries / fatalities disclosed | 58 + 48 contractor / 1 | Rates only / not disclosed |\n"
        "| External cost per US$100 revenue | ≈ US$2.7 (TSMC p. 45) | " + (f"≈ US${-H[H.year==2023].carbon_cost.iloc[0]/542:.2f} (2023, carbon only)" ) + " |"
    )
    st.caption("TSMC is ~12x Intel's Scope 1+2 because it buys mostly grid power (20% renewable) and runs far more fab capacity. "
               "Intel's advantage is renewables; its gap is disclosure (no monetization, no pollutant loads, no contractor safety data).")

# ---------------------------------------------------------------- Human dignity
with tabs[6]:
    st.subheader("Should harms to human dignity be monetized?")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**What TSMC does**\n\n"
                    "- Values 28 substantiated sexual-harassment cases at NT$56.72m (≈US$65k per case) for victims' physical and mental harm and lost well-being.\n"
                    "- Values supply-chain forced-labour risk at NT$-1,053m and child-labour risk at NT$-0.3m (Integrated P&L).\n\n"
                    "**What Intel discloses**\n\n"
                    "- No harassment counts. Supply chain: 637 audit findings closed (49 priority/major), US$52,000 in recruitment fees returned to 170+ workers in 2025; US$27M+ since 2014.")
    with c2:
        st.markdown("**Benefits of monetizing**\n- Makes the harm visible in the same units as capital decisions.\n- Lets boards track trends and fund prevention.\n\n"
                    "**Risks**\n- Implies a harm can be 'paid for' — a dignity violation is not a fungible cost of doing business.\n"
                    "- Low per-case values (US$65k) can make prevention look 'uneconomic'.\n- Under-reporting makes the number look better than reality.\n\n"
                    "**Our approach in this dashboard**: dignity harms are **off by default** and kept outside the net total unless the user chooses to include them. "
                    "We recommend reporting them as counts with zero-tolerance targets, plus a monetized figure only as a floor, never as a trade-off.")
    if dignity_on:
        st.warning(f"Dignity harms included: {har_n} assumed cases × ${har_cost:,} = {money(har_n*har_cost/1e6)} per year added to OHS.")

# ---------------------------------------------------------------- Recommendations
with tabs[7]:
    st.subheader("Strategic recommendations for Intel leadership")
    st.markdown(f"""
**1. Carbon: shift the effort from electricity to process emissions.**
Electricity is 99% renewable, so Scope 1 now makes up {hist.iloc[-1].scope1_t/1e6/hist.iloc[-1].ghg_scope12_mt:.0%} of Scope 1+2 and rose 15% in 2025.
At US${scc}/t, each 100 kt of F-GHG or N2O abated avoids **{money(0.1*scc)}** per year in societal cost. Prioritise abatement at Rio Rancho, Ocotillo, Leixlip, Qiryat Gat and Ronler Acres.
Use an internal carbon price near the SCC for fab capex decisions, and pursue SBTi validation to close the credibility gap with TSMC.

**2. Water: weight decisions by water stress, not volume.**
{stress_share:.0%} of fresh water comes from high or extremely-high stress basins. Target reclaimed water and conservation investment at Arizona, Israel and New Mexico first.
Publish wastewater pollutant loads so the toxicity side of TSMC's method can be applied, and report a stricter replenishment metric next to "net positive".

**3. Health & safety: disclose what can be valued.**
Publish injury counts, lost workdays, contractor injury rates and fatalities. Under TSMC's method, contractor fatalities are the largest OHS cost, and Intel is building new fabs.
Keep the target of a recordable rate below 0.5; ergonomic injuries (57%) are the main lever.

**4. Adopt impact accounting.** Publish an annual Integrated P&L like TSMC's, with these three factors as a start, and link executive pay to the monetized net-impact trend.

**5. Treat dignity harms as non-fungible.** Report harassment and forced-labour findings as counts with zero-tolerance targets, and do not net them against benefits.

*Value at stake:* delivering stated targets vs business-as-usual = **{money(npv(P['Intel stated targets']) - npv(P['Business as usual']))}** NPV of avoided societal cost to {end_year}.
""")

# ---------------------------------------------------------------- Data & methods
with tabs[8]:
    st.subheader("Valuation factors in use")
    st.dataframe(pd.DataFrame([
        ["Social cost of carbon (2025)", f"US${scc}/tCO2e", "TSMC IVR p.58-59; US EPA 2023 (US$212 in 2020 $ → NT$7,588 in 2023 NT$)"],
        ["SCC growth", f"{scc_g:.1%}/yr", "Assumption"],
        ["Renewable electricity benefit", f"US${renew_rate:.2f}/MWh", "TSMC IVR p.49: NT$21,317m / 57.8 bn kWh"],
        ["Fresh-water withdrawal cost", f"US${w_cost:.2f}/m³ × stress factor {water_stress_factor:.2f}", "TSMC IVR p.27: NT$5,709m / 127M m³"],
        ["Discharge cost", f"US${d_cost:.2f}/m³", "TSMC IVR p.28: NT$573m / 98M m³"],
        ["Conservation benefit", f"US${c_ben:.2f}/m³", "TSMC IVR p.49-50: NT$15,135m / 319M m³"],
        ["Restoration benefit", f"US${r_ben:.2f}/m³", "Proxy: TSMC reclaimed-water rate NT$1,016m / 22.7M m³"],
        ["Cost per lost workday", f"US${cost_day}", "TSMC IVR p.39: NT$1.43m / 636 days"],
        ["Lost days per case", f"{days_case}", "TSMC 636 / 58"],
        ["Fatality loss", f"US${fatal_cost}M", "TSMC IVR p.38: NT$1,464m (human-capital approach)"],
        ["FX", "31.16 NT$/US$", "2023 average (TSMC values are in 2023 NT$)"],
    ], columns=["Factor", "Value", "Source"]), hide_index=True, width="stretch")
    st.subheader("Intel historical data (CSV)")
    st.dataframe(hist, hide_index=True, width="stretch")
    st.download_button("Download monetized history + projection (CSV)",
                       pd.concat([H.assign(type="history"), PS.assign(type=scenario)]).to_csv(index=False), "intel_monetized.csv")
    st.markdown("""
**Method notes**
- Carbon = (Scope 1 + market-based Scope 2) × SCC(year). Renewable benefit = renewable MWh × TSMC's implied rate. For 2019-2020, electricity is estimated as 85% of total energy.
- Water = −withdrawal × cost × stress factor − returned water × discharge cost + conserved × benefit + restored × benefit. Before 2021, returned water is estimated at the 2025 return share (77%).
- OHS = days-away cases × lost days × cost/day + recordables × cost/recordable + fatalities × loss + (optional) harassment cases × cost.
- Historical data use the latest restated figure for each year (2025-26 report for 2021-25; 2024-25 for 2020; 2023-24 for 2019; 2018 report for 2014-18; 2015 report for 2011-13).
- Projections start from 2025 actuals. Scope 2 = electricity × (1 − renewable share) × residual emission factor (calibrated to 2025), falling 2%/yr with grid decarbonisation.
- Limits: TSMC's water and OHS models are site-specific (DALYs, water-stress index, human capital); unit rates implied from its totals are a first-order approximation.
""")
