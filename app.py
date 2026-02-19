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
                    p['fees'] += p['cap'] * (p_apr / 36
