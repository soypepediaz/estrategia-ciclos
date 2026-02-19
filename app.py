import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
from datetime import datetime

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="DeFi Auditor & Strategist PRO", layout="wide")
st.title("🛡️ DeFi Strategist PRO: Auditoría Completa de Ciclos")

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Configuración")
    start_date = st.date_input("Fecha Inicio", value=datetime(2020, 1, 1))
    freq_label = st.selectbox("Periodicidad", ["Semanal", "Quincenal", "Mensual"], index=2)
    inv_amount = st.number_input("Inversión Mensual ($)", value=1000.0)
    range_pct = st.slider("Rango Pool (±%)", 5, 50, 30) / 100
    pool_apr = st.number_input("APR Pool (%)", value=10.0) / 100
    aave_apr = st.number_input("APR Aave USDC (%)", value=3.0) / 100
    hf_target = st.number_input("Health Factor", value=2.5)
    dd_trigger = st.slider("Gatillo Drawdown (%)", 20, 80, 50) / 100

# --- MOTOR DE DATOS ---
@st.cache_data
def load_data(start):
    try:
        df = yf.download("BTC-USD", start=start, interval="1d")
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        col = 'Adj Close' if 'Adj Close' in df.columns else 'Close'
        return df[[col]].rename(columns={col: 'Price'})
    except: return None

data = load_data(start_date)

if data is not None:
    def run_simulation(df, freq_days, inv, r_pct, p_apr, a_apr, hf, ddt):
        cash_aave, wbtc_units, debt_usdc = 0.0, 0.0, 0.0
        active_pools, history, ops_log = [], [], []
        dca_units, dca_inv = 0.0, 0.0
        ath = 0.0
        
        days_map = {"Semanal": 7, "Quincenal": 15, "Mensual": 30}
        period = days_map[freq_days]
        last_inv_idx = -period
        
        for i in range(len(df)):
            price = float(df['Price'].values[i])
            date = df.index[i]
            
            # Reset en ATH
            if price > ath:
                ath = price
                if wbtc_units > 0:
                    val = (wbtc_units * price) - debt_usdc
                    cash_aave += val
                    wbtc_units, debt_usdc = 0.0, 0.0
                    ops_log.append({"Fecha": date, "Op": "RESET ATH", "Desc": "Consolidación a USDC", "Price": price, "Icon": "🔄"})

            mkt_dd = (price - ath) / ath
            cash_aave *= (1 + a_apr / 365)

            # Compra en Caída
            if mkt_dd <= -ddt and cash_aave > 100:
                spent = cash_aave * 0.5
                cash_aave -= spent
                wbtc_units += (spent / price)
                debt_usdc += (spent / hf)
                active_pools.append({'cap': spent/hf, 'low': price*(1-r_pct), 'up': price*(1+r_pct), 'fees': 0})
                ops_log.append({"Fecha": date, "Op": "CRISIS BUY", "Desc": f"Compra al -{ddt*100}% DD", "Price": price, "Icon": "📉"})

            # Inversión DCA y Estrategia
            if (i - last_inv_idx) >= period:
                active_pools.append({'cap': inv, 'low': price*(1-r_pct), 'up': price*(1+r_pct), 'fees': 0})
                dca_units += (inv / price)
                dca_inv += inv
                ops_log.append({"Fecha": date, "Op": "OPEN POOL", "Desc": "Nueva Posición", "Price": price, "Icon": "🟢"})
                last_inv_idx = i

            # Gestión de Pools
            still_active = []
            for p in active_pools:
                if p['low'] <= price <= p['up']:
                    p['fees'] += p['cap'] * (p_apr / 365)
                    still_active.append(p)
                elif price > p['up']:
                    cash_aave += (p['cap'] * 1.05) + p['fees']
                    ops_log.append({"Fecha": date, "Op": "TP", "Desc": "Salida Superior", "Price": price, "Icon": "🔴"})
                elif price < p['low']:
                    wbtc_units += (p['cap'] / price)
                    debt_usdc += (p['cap'] / hf)
                    still_active.append({'cap': p['cap']/hf, 'low': price*(1-r_pct), 'up': price*(1+r_pct), 'fees': 0})
                    ops_log.append({"Fecha": date, "Op": "SL", "Desc": "Salida Inferior", "Price": price, "Icon": "🟠"})
            active_pools = still_active

            strat_val = cash_aave + (wbtc_units * price) - debt_usdc + sum([p['cap'] for p in active_pools])
            dca_val = dca_units * price
            
            history.append({
                'Fecha': date, 'Price': price, 'Estrategia': strat_val, 
                'DCA': dca_val, 'DD_BTC': mkt_dd * 100,
                'Max_Strat': max([h['Estrategia'] for h in history] + [strat_val])
            })
            
        res_df = pd.DataFrame(history)
        res_df['DD_Strat'] = ((res_df['Estrategia'] / res_df['Max_Strat']) - 1) * 100
        return res_df, pd.DataFrame(ops_log), dca_inv

    res, logs, total_inv = run_simulation(data, freq_label, inv_amount, range_pct, pool_apr, aave_apr, hf_target, dd_trigger)

    # --- MÉTRICAS ---
    c1, c2, c3, c4 = st.columns(4)
    v_strat, v_dca = res['Estrategia'].iloc[-1], res['DCA'].iloc[-1]
    c1.metric("Valor Estrategia", f"${v_strat:,.0f}", f"{(v_strat/total_inv-1)*100:.1f}%")
    c2.metric("Valor DCA Clásico", f"${v_dca:,.0f}", f"{(v_dca/total_inv-1)*100:.1f}%")
    c3.metric("Inversión Total", f"${total_inv:,.0f}")
    c4.metric("Alpha", f"${v_strat - v_dca:,.0f}")

    # --- GRÁFICOS ---
    st.subheader("📈 Evolución y Auditoría de Operaciones")
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08, row_heights=[0.7, 0.3])

    # Fila 1: Cartera + Precio + Marcadores
    fig.add_trace(go.Scatter(x=res['Fecha'], y=res['Estrategia'], name="Estrategia", line=dict(color="#00FFCC", width=3)), row=1, col=1)
    fig.add_trace(go.Scatter(x=res['Fecha'], y=res['DCA'], name="DCA Clásico", line=dict(color="#FFA500", dash='dot')), row=1, col=1)
    fig.add_trace(go.Scatter(x=res['Fecha'], y=res['Price'], name="Precio BTC", opacity=0.1, line=dict(color="white"), yaxis="y2"), row=1, col=1)

    # Añadir marcadores de operaciones sobre el precio
    for icon in logs['Icon'].unique():
        df_op = logs[logs['Icon'] == icon]
        fig.add_trace(go.Scatter(x=df_op['Fecha'], y=df_op['Price'], mode='markers', name=df_op['Op'].iloc[0], 
                                 marker=dict(size=8, symbol='diamond' if icon=="🔄" else 'circle')), row=1, col=1)

    # Fila 2: Drawdown
    fig.add_trace(go.Scatter(x=res['Fecha'], y=res['DD_Strat'], name="DD Estrategia", fill='tozeroy', line=dict(color="#00FFCC")), row=2, col=1)
    fig.add_trace(go.Scatter(x=res['Fecha'], y=res['DD_BTC'], name="DD Mercado (BTC)", line=dict(color="red", dash='dash')), row=2, col=1)

    fig.update_layout(height=850, template="plotly_dark", 
                      yaxis=dict(title="Valor USD"), yaxis2=dict(overlaying="y", side="right", title="BTC Price"),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    st.plotly_chart(fig, use_container_width=True)

    # --- LOGS ---
    st.subheader("📜 Registro Detallado de Señales")
    st.dataframe(logs.sort_values(by="Fecha", ascending=False), use_container_width=True)

else:
    st.error("Error al cargar los datos.")
