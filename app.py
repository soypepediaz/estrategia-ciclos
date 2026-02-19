import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
from datetime import datetime

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="DeFi Auditor PRO", layout="wide")

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Configuración")
    start_date = st.date_input("Fecha Inicio", value=datetime(2020, 1, 1))
    freq_label = st.selectbox("Periodicidad", ["Semanal", "Quincenal", "Mensual"], index=2)
    inv_amount = st.number_input("Inversión Periodo ($)", value=1000.0)
    range_pct = st.slider("Rango Pool (±%)", 5, 50, 30) / 100
    pool_apr = st.number_input("APR Pool (%)", value=10.0) / 100
    dd_trigger = st.slider("Gatillo Compra Drawdown (%)", 20, 80, 50) / 100
    hf_target = st.number_input("Health Factor", value=2.5)

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
    def run_simulation(df, freq_days, inv, r_pct, p_apr, ddt, hf):
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
            
            # 1. Gestión ATH
            if price > ath:
                ath = price
                if wbtc_units > 0:
                    val = (wbtc_units * price) - debt_usdc
                    cash_aave += val
                    wbtc_units, debt_usdc = 0.0, 0.0
                    ops_log.append({"Fecha": date, "Op": "RESET ATH", "Desc": f"Liquidación en ${price:,.0f}", "Price": price, "Icon": "🔄"})

            mkt_dd = (price - ath) / ath

            # 2. Compra Crisis
            if mkt_dd <= -ddt and cash_aave > 100:
                spent = cash_aave * 0.5
                cash_aave -= spent
                wbtc_units += (spent / price)
                debt_usdc += (spent / hf)
                active_pools.append({'cap': spent/hf, 'low': price*(1-r_pct), 'up': price*(1+r_pct), 'fees': 0})
                ops_log.append({"Fecha": date, "Op": "CRISIS BUY", "Desc": f"Compra al -{ddt*100}%", "Price": price, "Icon": "📉"})

            # 3. DCA e Inversión
            if (i - last_inv_idx) >= period:
                active_pools.append({'cap': inv, 'low': price*(1-r_pct), 'up': price*(1+r_pct), 'fees': 0})
                dca_units += (inv / price)
                dca_inv += inv
                ops_log.append({"Fecha": date, "Op": "OPEN POOL", "Desc": "Inversión Recurrente", "Price": price, "Icon": "🟢"})
                last_inv_idx = i

            # 4. Gestión Pools (CORREGIDA)
            still_active = []
            for p in active_pools:
                if p['low'] <= price <= p['up']:
                    p['fees'] += p['cap'] * (p_apr / 365)
                    still_active.append(p)
                elif price > p['up']:
                    cash_aave += (p['cap'] * 1.05) + p['fees']
                    ops_log.append({"Fecha": date, "Op": "TP", "Desc": "Cierre Superior", "Price": price, "Icon": "🔴"})
                elif price < p['low']:
                    wbtc_units += (p['cap'] / price)
                    debt_usdc += (p['cap'] / hf)
                    still_active.append({'cap': p['cap']/hf, 'low': price*(1-r_pct), 'up': price*(1+r_pct), 'fees': 0})
            active_pools = still_active

            # 5. Valoración
            strat_val = cash_aave + (wbtc_units * price) - debt_usdc + sum([p['cap'] for p in active_pools])
            history.append({
                'Fecha': date, 'Precio': price, 'Estrategia': strat_val, 
                'DCA': dca_units * price, 'DD_BTC': mkt_dd * 100, 'Cash': cash_aave
            })
            
        return pd.DataFrame(history), pd.DataFrame(ops_log), dca_inv

    res, logs, total_inv = run_simulation(data, freq_label, inv_amount, range_pct, pool_apr, dd_trigger, hf_target)

    # Gráficos
    st.header("📈 Análisis de Resultados")
    
    # Subplots para separar Valor de Drawdown
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1, 
                        subplot_titles=("Evolución de Cartera", "Drawdown Mercado (%)"), row_heights=[0.7, 0.3])

    fig.add_trace(go.Scatter(x=res['Fecha'], y=res['Estrategia'], name="Estrategia", line=dict(color="#00FFCC", width=3)), row=1, col=1)
    fig.add_trace(go.Scatter(x=res['Fecha'], y=res['DCA'], name="DCA Clásico", line=dict(color="#FFA500", dash='dot')), row=1, col=1)
    
    # Marcadores de operaciones sobre el precio (eje secundario)
    for icon in logs['Icon'].unique():
        df_op = logs[logs['Icon'] == icon]
        fig.add_trace(go.Scatter(x=df_op['Fecha'], y=df_op['Price'], mode='markers', name=df_op['Op'].iloc[0], 
                                 marker=dict(size=8), yaxis="y2"), row=1, col=1)

    fig.add_trace(go.Scatter(x=res['Fecha'], y=res['DD_BTC'], name="DD Mercado", fill='tozeroy', line=dict(color="red")), row=2, col=1)

    fig.update_layout(height=800, template="plotly_dark", yaxis2=dict(overlaying="y", side="right", title="BTC Price"))
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("📜 Libro de Órdenes")
    st.dataframe(logs.sort_values("Fecha", ascending=False), use_container_width=True)
