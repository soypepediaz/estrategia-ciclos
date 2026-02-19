import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import numpy as np
from datetime import datetime

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="DeFi Strategist: WBTC/USDC", layout="wide")

st.title("🛡️ DeFi Alpha Backtester: WBTC/USDC")
st.markdown("Simulación de Liquidez Concentrada + AAVE + Compras de Drawdown.")

# --- SIDEBAR: PARÁMETROS ---
with st.sidebar:
    st.header("⚙️ Parámetros")
    start_date = st.date_input("Fecha Inicio", value=datetime(2020, 1, 1))
    freq_label = st.selectbox("Periodicidad", ["Semanal", "Quincenal", "Mensual"], index=2)
    inv_amount = st.number_input("Inversión por Periodo ($)", value=1000.0)
    range_pct = st.slider("Rango Pool (±%)", 5, 50, 30) / 100
    pool_apr = st.number_input("APR Pool (%)", value=10.0) / 100
    aave_apr = st.number_input("APR Aave USDC (%)", value=3.0) / 100
    hf_target = st.number_input("Health Factor", value=2.5)
    dd_trigger = st.slider("Compra al Drawdown (%)", 20, 80, 50) / 100
    buy_from_aave = st.slider("% Capital Aave a Invertir", 10, 100, 50) / 100

# --- MOTOR DE DATOS ---
@st.cache_data
def load_data(start):
    try:
        df = yf.download("BTC-USD", start=start, interval="1d")
        if df.empty:
            return None
        # Aplanar MultiIndex de columnas si existe
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        # Limpiar y renombrar
        df = df[['Adj Close']].rename(columns={'Adj Close': 'Price'})
        return df
    except Exception as e:
        st.error(f"Error descargando datos: {e}")
        return None

data = load_data(start_date)

if data is not None and not data.empty:
    # --- MOTOR DE SIMULACIÓN ---
    def run_simulation(df, freq_days, inv, r_pct, p_apr, a_apr, hf, ddt, b_pct):
        cash_aave = 0
        wbtc_units = 0
        debt_usdc = 0
        active_pools = []
        history = []
        ath = 0
        
        days_map = {"Semanal": 7, "Quincenal": 15, "Mensual": 30}
        period = days_map[freq_days]
        last_inv_idx = -period
        
        prices = df['Price'].values
        dates = df.index

        for i in range(len(df)):
            price = float(prices[i])
            date = dates[i]
            
            # 1. ATH y Reset
            if price > ath:
                ath = price
                if wbtc_units > 0:
                    cash_aave += (wbtc_units * price) - debt_usdc
                    wbtc_units, debt_usdc = 0, 0

            drawdown = (price - ath) / ath
            cash_aave *= (1 + a_apr / 365)

            # 2. Compra en Caída
            if drawdown <= -ddt and cash_aave > 100:
                spent = cash_aave * b_pct
                cash_aave -= spent
                wbtc_units += (spent / price)
                new_loan = spent / hf
                debt_usdc += new_loan
                active_pools.append({'cap': new_loan, 'low': price*(1-r_pct), 'up': price*(1+r_pct), 'fees': 0})

            # 3. Inversión DCA
            if (i - last_inv_idx) >= period:
                active_pools.append({'cap': inv, 'low': price*(1-r_pct), 'up': price*(1+r_pct), 'fees': 0})
                last_inv_idx = i

            # 4. Procesar Pools
            still_active = []
            for p in active_pools:
                if p['low'] <= price <= p['up']:
                    p['fees'] += p['cap'] * (p_apr / 365)
                    still_active.append(p)
                elif price > p['up']:
                    profit = (p['cap'] * 0.5) * (r_pct * 0.5)
                    cash_aave += (p['cap'] + profit + p['fees'])
                elif price < p['low']:
                    wbtc_units += (p['cap'] / price)
                    loan = p['cap'] / hf
                    debt_usdc += loan
                    still_active.append({'cap': loan, 'low': price*(1-r_pct), 'up': price*(1+r_pct), 'fees': 0})
            active_pools = still_active

            # Valoración
            pool_val = sum([p['cap'] for p in active_pools])
            total_val = cash_aave + (wbtc_units * price) - debt_usdc + pool_val
            
            history.append({
                'Fecha': date, 'Precio': price, 'Cartera': total_val, 
                'Caja_AAVE': cash_aave, 'Drawdown': drawdown
            })
            
        return pd.DataFrame(history)

    # Ejecución
    res = run_simulation(data, freq_label, inv_amount, range_pct, pool_apr, aave_apr, hf_target, dd_trigger, buy_from_aave)

    # --- MÉTRICAS ---
    if not res.empty:
        c1, c2, c3 = st.columns(3)
        final_v = res['Cartera'].iloc[-1]
        # Cálculo de inversión total basada en periodos reales
        total_inv = (len(data) // {"Semanal": 7, "Quincenal": 15, "Mensual": 30}[freq_label]) * inv_amount
        
        c1.metric("Valor Portafolio", f"${final_v:,.0f}")
        c2.metric("Inversión Total", f"${total_inv:,.0f}")
        c3.metric("ROI", f"{((final_v/total_inv)-1)*100:.2f}%")

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=res['Fecha'], y=res['Cartera'], name="Cartera", line=dict(color="#00FFCC")))
        fig.add_trace(go.Scatter(x=res['Fecha'], y=res['Precio'], name="BTC", yaxis="y2", opacity=0.3))
        fig.update_layout(yaxis2=dict(overlaying="y", side="right"), template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.error("La simulación no generó resultados.")
else:
    st.warning("Esperando datos de Yahoo Finance...")
