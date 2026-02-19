import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
from datetime import datetime

st.set_page_config(page_title="DeFi Auditor Final", layout="wide")

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Parámetros")
    start_date = st.date_input("Fecha Inicio", value=datetime(2020, 1, 1))
    freq_label = st.selectbox("Periodicidad", ["Semanal", "Quincenal", "Mensual"], index=2)
    inv_amount = st.number_input("Inversión ($)", value=1000.0)
    range_pct = st.slider("Rango Pool (±%)", 5, 50, 30) / 100
    pool_apr = st.number_input("APR Pool (%)", value=15.0) / 100
    dd_trigger = st.slider("Gatillo Drawdown (%)", 20, 80, 50) / 100
    hf_target = st.number_input("Health Factor", value=2.5)

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
        # Estados
        cash_usdc, wbtc_units, debt_usdc = 0.0, 0.0, 0.0
        active_pools, history, ops_log = [], [], []
        dca_units, dca_inv, ath = 0.0, 0.0, 0.0
        
        days_map = {"Semanal": 7, "Quincenal": 15, "Mensual": 30}
        period = days_map[freq_days]
        last_inv_idx = -period
        
        for i in range(len(df)):
            price = float(df['Price'].values[i])
            date = df.index[i]
            
            # 1. ATH y RESET LOGIC
            if price > ath:
                ath = price
                if wbtc_units > 0:
                    val_to_cash = (wbtc_units * price) - debt_usdc
                    cash_usdc += val_to_cash
                    wbtc_units, debt_usdc = 0.0, 0.0
                    ops_log.append({"Fecha": date, "Op": "RESET ATH", "Price": price, "Icon": "🔄"})

            drawdown = (price - ath) / ath

            # 2. COMPRA CRISIS (-50% DD)
            if drawdown <= -ddt and cash_usdc > 100:
                buy_vol = cash_usdc * 0.5
                cash_usdc -= buy_vol
                wbtc_units += (buy_vol / price)
                debt_usdc += (buy_vol / hf) # Borrow conservador
                active_pools.append({'cap': buy_vol/hf, 'low': price*(1-r_pct), 'up': price*(1+r_pct), 'fees': 0})
                ops_log.append({"Fecha": date, "Op": "CRISIS BUY", "Price": price, "Icon": "📉"})

            # 3. INVERSIÓN PERIÓDICA (OBLIGATORIA)
            if (i - last_inv_idx) >= period:
                active_pools.append({'cap': inv, 'low': price*(1-r_pct), 'up': price*(1+r_pct), 'fees': 0})
                dca_units += (inv / price)
                dca_inv += inv
                ops_log.append({"Fecha": date, "Op": "OPEN POOL", "Price": price, "Icon": "🟢"})
                last_inv_idx = i

            # 4. PROCESAR POOLS
            new_active = []
            for p in active_pools:
                if p['low'] <= price <= p['up']:
                    p['fees'] += p['cap'] * (p_apr / 365)
                    new_active.append(p)
                elif price > p['up']:
                    cash_usdc += (p['cap'] * 1.05) + p['fees'] # Profit estimado
                    ops_log.append({"Fecha": date, "Op": "TAKE PROFIT", "Price": price, "Icon": "🔴"})
                elif price < p['low']:
                    wbtc_units += (p['cap'] / price)
                    debt_usdc += (p['cap'] / hf)
                    new_active.append({'cap': p['cap']/hf, 'low': price*(1-r_pct), 'up': price*(1+r_pct), 'fees': 0})
                    ops_log.append({"Fecha": date, "Op": "SL -> COLLATERAL", "Price": price, "Icon": "🟠"})
            active_pools = new_active

            # 5. VALORACIÓN Y COMPOSICIÓN
            pool_val = sum([p['cap'] for p in active_pools])
            total_strat = cash_usdc + (wbtc_units * price) - debt_usdc + pool_val
            
            history.append({
                'Fecha': date, 'Precio': price, 'Estrategia': total_strat, 
                'DCA': dca_units * price, 'USDC': cash_usdc, 'WBTC_USD': wbtc_units * price,
                'Pools': pool_val, 'DD_BTC': drawdown * 100
            })
            
        return pd.DataFrame(history), pd.DataFrame(ops_log), dca_inv

    res, logs, total_inv = run_simulation(data, freq_label, inv_amount, range_pct, pool_apr, dd_trigger, hf_target)

    # --- MÉTRICAS ---
    c1, c2, c3 = st.columns(3)
    c1.metric("Estrategia", f"${res['Estrategia'].iloc[-1]:,.0f}")
    c2.metric("DCA Clásico", f"${res['DCA'].iloc[-1]:,.0f}")
    c3.metric("Inversión Total", f"${total_inv:,.0f}")

    # --- GRÁFICO 1: COMPARATIVA ---
    fig1 = make_subplots(specs=[[{"secondary_y": True}]])
    fig1.add_trace(go.Scatter(x=res['Fecha'], y=res['Estrategia'], name="Estrategia DeFi", line=dict(color="#00FFCC", width=3)))
    fig1.add_trace(go.Scatter(x=res['Fecha'], y=res['DCA'], name="DCA Clásico", line=dict(color="#FFA500", dash='dot')))
    fig1.add_trace(go.Scatter(x=res['Fecha'], y=res['Precio'], name="BTC (Eje Der.)", opacity=0.1, line=dict(color="white")), secondary_y=True)
    
    # Iconos de operaciones
    for icon in logs['Icon'].unique():
        df_op = logs[logs['Icon'] == icon]
        fig1.add_trace(go.Scatter(x=df_op['Fecha'], y=df_op['Price'], mode='markers', name=df_op['Op'].iloc[0], secondary_y=True))

    fig1.update_layout(title="Evolución Cartera vs BTC", template="plotly_dark", height=500)
    st.plotly_chart(fig1, use_container_width=True)

    # --- GRÁFICO 2: COMPOSICIÓN (ESTO EXPLICA LA LÍNEA RECTA) ---
    st.subheader("🏦 Composición Interna de la Estrategia")
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=res['Fecha'], y=res['USDC'], name="Caja USDC (Estable)", stackgroup='one', fillcolor='rgba(0, 255, 200, 0.4)'))
    fig2.add_trace(go.Scatter(x=res['Fecha'], y=res['WBTC_USD'], name="Exposición WBTC (Volátil)", stackgroup='one', fillcolor='rgba(255, 165, 0, 0.4)'))
    fig2.add_trace(go.Scatter(x=res['Fecha'], y=res['Pools'], name="En Pools Liquidez", stackgroup='one', fillcolor='rgba(255, 255, 255, 0.4)'))
    fig2.update_layout(title="Distribución del Capital", template="plotly_dark", height=400)
    st.plotly_chart(fig2, use_container_width=True)

    st.subheader("📜 Registro Detallado")
    st.dataframe(logs.sort_values("Fecha", ascending=False), use_container_width=True)
