import streamlit as st
import pandas as pd
import yfinance as yf
import numpy as np
import plotly.graph_objects as go
from datetime import datetime

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="DeFi Strategist: WBTC/USDC", layout="wide")

st.title("🛡️ DeFi Alpha Backtester: WBTC/USDC")
st.markdown("""
Esta aplicación simula una estrategia avanzada de **Liquidez Concentrada** integrada con **AAVE** y **Compras de Drawdown**.
Calcula ATH diarios y gestiona colaterales dinámicamente.
""")

# --- SIDEBAR: PARÁMETROS DINÁMICOS ---
with st.sidebar:
    st.header("⚙️ Parámetros del Sistema")
    start_date = st.date_input("Fecha Inicio", value=datetime(2020, 1, 1))
    
    freq_label = st.selectbox("Periodicidad de Inversión", ["Semanal", "Quincenal", "Mensual"], index=2)
    inv_amount = st.number_input("Inversión por Periodo ($)", value=1000)
    
    st.subheader("📊 Pool de Liquidez")
    range_pct = st.slider("Rango del Pool (±%)", 5, 50, 30) / 100
    pool_apr = st.number_input("APR Pool (%)", value=10.0) / 100
    
    st.subheader("👻 Configuración AAVE")
    aave_apr = st.number_input("APR Lending USDC (%)", value=3.0) / 100
    hf_target = st.number_input("Health Factor Objetivo", value=2.5, step=0.1)
    
    st.subheader("📉 Estrategia de Drawdown")
    dd_trigger = st.slider("Gatillo Compra (%)", 20, 80, 50) / 100
    buy_from_aave = st.slider("% Capital AAVE a Invertir", 10, 100, 50) / 100

# --- MOTOR DE DATOS ---
@st.cache_data
def load_data(start):
    # Descarga datos diarios para máxima precisión en ATH y Drawdown
    df = yf.download("BTC-USD", start=start, interval="1d")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[['Adj Close']].rename(columns={'Adj Close': 'Price'})
    return df

data = load_data(start_date)

# --- MOTOR DE SIMULACIÓN ---
def run_simulation(df, freq_days, inv, r_pct, p_apr, a_apr, hf, ddt, b_pct):
    cash_aave = 0  # USDC estable
    wbtc_units = 0 # WBTC como colateral
    debt_usdc = 0  # Deuda en AAVE
    active_pools = []
    history = []
    
    ath = 0
    days_map = {"Semanal": 7, "Quincenal": 15, "Mensual": 30}
    period = days_map[freq_days]
    
    last_inv_idx = -period
    
    for i in range(len(df)):
        price = float(df['Price'].values[i])
        date = df.index[i]
        
        # 1. Gestión de ATH y Reset
        if price > ath:
            ath = price
            # REBALANCEO TOTAL EN ATH: Limpiar deuda y colateral
            if wbtc_units > 0:
                final_val = (wbtc_units * price) - debt_usdc
                cash_aave += final_val
                wbtc_units = 0
                debt_usdc = 0

        drawdown = (price - ath) / ath
        
        # 2. Interés AAVE diario
        cash_aave *= (1 + a_apr / 365)
        
        # 3. Gatillo de Compra en Caída (Buy the Dip)
        if drawdown <= -ddt and cash_aave > 100:
            spent = cash_aave * b_pct
            cash_aave -= spent
            wbtc_units += (spent / price)
            # Generar Borrow para nuevas pools
            new_loan = spent / hf
            debt_usdc += new_loan
            active_pools.append({
                'cap': new_loan, 'entry': price, 'fees': 0,
                'up': price * (1 + r_pct), 'low': price * (1 - r_pct)
            })

        # 4. Inversión Recurrente
        if (i - last_inv_idx) >= period:
            active_pools.append({
                'cap': inv, 'entry': price, 'fees': 0,
                'up': price * (1 + r_pct), 'low': price * (1 - r_pct)
            })
            last_inv_idx = i

        # 5. Procesar Pools
        still_active = []
        for p in active_pools:
            if p['low'] <= price <= p['up']:
                p['fees'] += p['cap'] * (p_apr / 365)
                still_active.append(p)
            elif price > p['up']: # Salida por arriba (USDC)
                profit = (p['cap'] * 0.5) * (r_pct * 0.5) # Profit medio WBTC vendido
                cash_aave += (p['cap'] + profit + p['fees'])
            elif price < p['low']: # Salida por abajo (WBTC a Colateral)
                units = p['cap'] / price
                wbtc_units += units
                loan = p['cap'] / hf
                debt_usdc += loan
                # Abrir nueva pool con el préstamo
                still_active.append({
                    'cap': loan, 'entry': price, 'fees': 0,
                    'up': price * (1 + r_pct), 'low': price * (1 - r_pct)
                })
        active_pools = still_active

        # Valoración
        pool_val = sum([p['cap'] for p in active_pools])
        portfolio_val = cash_aave + (wbtc_units * price) - debt_usdc + pool_val
        
        history.append({
            'Fecha': date, 'Precio': price, 'ATH': ath,
            'Cartera': portfolio_val, 'Aave_USDC': cash_aave,
            'Drawdown': drawdown
        })
        
    return pd.DataFrame(history)

# Ejecución
res = run_simulation(data, freq_label, inv_amount, range_pct, pool_apr, aave_apr, hf_target, dd_trigger, buy_from_aave)

# --- UI: MÉTRICAS Y GRÁFICOS ---
c1, c2, c3 = st.columns(3)
final_v = res['Cartera'].iloc[-1]
total_periods = len(data) // (7 if freq_label=="Semanal" else 15 if freq_label=="Quincenal" else 30)
total_inv = total_periods * inv_amount
c1.metric("Valor Portafolio", f"${final_v:,.0f}")
c2.metric("Inversión Total", f"${total_inv:,.0f}")
c3.metric("ROI Estrategia", f"{((final_v/total_inv)-1)*100:.2f}%")

# Gráfico Principal
fig = go.Figure()
fig.add_trace(go.Scatter(x=res['Fecha'], y=res['Cartera'], name="Valor Cartera ($)", line=dict(color='#00ffcc')))
fig.add_trace(go.Scatter(x=res['Fecha'], y=res['Precio'], name="Precio BTC ($)", yaxis="y2", line=dict(color='rgba(255,255,255,0.2)')))
fig.update_layout(
    title="Evolución de la Cartera vs BTC",
    yaxis=dict(title="Cartera USD"),
    yaxis2=dict(title="BTC Price", overlaying="y", side="right"),
    template="plotly_dark"
)
st.plotly_chart(fig, use_container_width=True)

# Tabla de Auditoría
with st.expander("📄 Ver desglose de operaciones diarias"):
    st.write(res)
