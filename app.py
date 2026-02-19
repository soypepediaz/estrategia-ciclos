import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import numpy as np
from datetime import datetime

st.set_page_config(page_title="DeFi Auditor Pro", layout="wide")
st.title("🛡️ Auditoría de Estrategia: Rangos y Operaciones")

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Parámetros")
    start_date = st.date_input("Fecha Inicio", value=datetime(2020, 1, 1))
    freq_label = st.selectbox("Periodicidad", ["Semanal", "Quincenal", "Mensual"], index=2)
    inv_amount = st.number_input("Inversión ($)", value=1000.0)
    range_pct = st.slider("Rango Pool (±%)", 5, 50, 30) / 100
    dd_trigger = st.slider("Gatillo Drawdown (%)", 20, 80, 50) / 100
    hf_target = st.number_input("Health Factor", value=2.5)

@st.cache_data
def load_data(start):
    df = yf.download("BTC-USD", start=start, interval="1d")
    if df.empty: return None
    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
    col = 'Adj Close' if 'Adj Close' in df.columns else 'Close'
    return df[[col]].rename(columns={col: 'Price'})

data = load_data(start_date)

if data is not None:
    def run_simulation(df, freq_days, inv, r_pct, ddt, hf):
        cash_aave, wbtc_units, debt_usdc = 0.0, 0.0, 0.0
        active_pools, history, ops_log = [], [], []
        ath = 0.0
        
        days_map = {"Semanal": 7, "Quincenal": 15, "Mensual": 30}
        period = days_map[freq_days]
        last_inv_idx = -period
        
        for i in range(len(df)):
            price = float(df['Price'].values[i])
            date = df.index[i]
            
            # Gestión de ATH
            if price > ath:
                ath = price
                if wbtc_units > 0:
                    cash_aave += (wbtc_units * price) - debt_usdc
                    wbtc_units, debt_usdc = 0.0, 0.0
                    ops_log.append({"Fecha": date, "Op": "RESET ATH", "Detalle": f"ATH ${price:,.0f}. Volvemos a Cash.", "Price": price, "Icon": "🔄"})

            drawdown = (price - ath) / ath

            # Compra en Caída
            if drawdown <= -ddt and cash_aave > 100:
                spent = cash_aave * 0.5
                cash_aave -= spent
                wbtc_units += (spent / price)
                debt_usdc += (spent / hf)
                active_pools.append({'cap': spent/hf, 'low': price*(1-r_pct), 'up': price*(1+r_pct), 'entry': price, 'date': date})
                ops_log.append({"Fecha": date, "Op": "CRISIS BUY", "Detalle": f"Compra al -{ddt*100}% DD", "Price": price, "Icon": "📉"})

            # Inversión Periódica Obligatoria
            if (i - last_inv_idx) >= period:
                active_pools.append({'cap': inv, 'low': price*(1-r_pct), 'up': price*(1+r_pct), 'entry': price, 'date': date})
                ops_log.append({"Fecha": date, "Op": "OPEN POOL", "Detalle": f"Inversión recurrente", "Price": price, "Icon": "🟢"})
                last_inv_idx = i

            # Evaluar Pools
            still_active = []
            for p in active_pools:
                if p['low'] <= price <= p['up']:
                    still_active.append(p)
                elif price > p['up']:
                    cash_aave += p['cap'] * 1.05 # Simplificado profit
                    ops_log.append({"Fecha": date, "Op": "TAKE PROFIT", "Detalle": "Salida superior", "Price": price, "Icon": "🔴"})
                elif price < p['low']:
                    wbtc_units += (p['cap'] / price)
                    debt_usdc += (p['cap'] / hf)
                    still_active.append({'cap': p['cap']/hf, 'low': price*(1-r_pct), 'up': price*(1+r_pct), 'entry': price, 'date': date})
                    ops_log.append({"Fecha": date, "Op": "LIQUIDITY DOWN", "Detalle": "Salida inferior -> Colateral", "Price": price, "Icon": "🟠"})
            active_pools = still_active

            total_val = cash_aave + (wbtc_units * price) - debt_usdc + sum([p['cap'] for p in active_pools])
            history.append({'Fecha': date, 'Price': price, 'Cartera': total_val, 'Active_Pools': len(active_pools)})
            
        return pd.DataFrame(history), pd.DataFrame(ops_log), active_pools

    res, logs, current_pools = run_simulation(data, freq_label, inv_amount, range_pct, dd_trigger, hf_target)

    # --- GRÁFICO CON RANGOS ---
    fig = go.Figure()
    
    # Precio BTC
    fig.add_trace(go.Scatter(x=res['Fecha'], y=res['Price'], name="Precio BTC", line=dict(color="white", width=1.5)))
    
    # Pintar rangos de las pools que están abiertas actualmente
    for i, p in enumerate(current_pools):
        fig.add_hline(y=p['up'], line_dash="dot", line_color="green", opacity=0.3)
        fig.add_hline(y=p['low'], line_dash="dot", line_color="red", opacity=0.3)
        fig.add_vrect(x0=p['date'], x1=res['Fecha'].iloc[-1], fillcolor="green", opacity=0.05, layer="below", line_width=0)

    # Marcadores de operaciones
    for icon in logs['Icon'].unique():
        df_op = logs[logs['Icon'] == icon]
        fig.add_trace(go.Scatter(x=df_op['Fecha'], y=df_op['Price'], mode='markers', name=df_op['Op'].iloc[0], 
                                 marker=dict(size=10, symbol='diamond' if icon=="🔄" else 'circle')))

    fig.update_layout(template="plotly_dark", height=600, title="Auditoría Visual: Rangos y Eventos")
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("📋 Registro Detallado")
    st.dataframe(logs.sort_values("Fecha", ascending=False))
