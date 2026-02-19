import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import numpy as np
from datetime import datetime

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="DeFi Alpha PRO", layout="wide")

st.title("🛡️ DeFi Alpha Strategist: WBTC/USDC")

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Configuración")
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
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        for col in ['Adj Close', 'Close']:
            if col in df.columns:
                df = df[[col]].rename(columns={col: 'Price'})
                return df
        return df.iloc[:, [0]].rename(columns={df.columns[0]: 'Price'})
    except Exception: return None

data = load_data(start_date)

if data is not None and not data.empty:
    def run_simulation(df, freq_days, inv, r_pct, p_apr, a_apr, hf, ddt, b_pct):
        cash_aave, wbtc_units, debt_usdc = 0.0, 0.0, 0.0
        active_pools, history, ops_log = [], [], []
        dca_wbtc_units, dca_invested = 0.0, 0.0
        ath = 0.0
        
        days_map = {"Semanal": 7, "Quincenal": 15, "Mensual": 30}
        period = days_map[freq_days]
        last_inv_idx = -period
        
        prices = df['Price'].values
        dates = df.index

        for i in range(len(df)):
            price = float(prices[i])
            date = dates[i]
            
            if price > ath:
                ath = price
                if wbtc_units > 0:
                    cash_aave += (wbtc_units * price) - debt_usdc
                    wbtc_units, debt_usdc = 0.0, 0.0
                    ops_log.append({"Fecha": date, "Operación": "RESET ATH", "Detalle": f"Cierre total en ${price:,.0f}"})

            strat_dd = (price - ath) / ath
            cash_aave *= (1 + a_apr / 365)

            if strat_dd <= -ddt and cash_aave > 100:
                spent = cash_aave * b_pct
                cash_aave -= spent
                wbtc_units += (spent / price)
                new_loan = spent / hf
                debt_usdc += new_loan
                active_pools.append({'cap': new_loan, 'low': price*(1-r_pct), 'up': price*(1+r_pct), 'fees': 0})
                ops_log.append({"Fecha": date, "Operación": "COMPRA CRISIS", "Detalle": f"Inversión ${spent:,.0f} (DD {strat_dd:.1%})"})

            if (i - last_inv_idx) >= period:
                active_pools.append({'cap': inv, 'low': price*(1-r_pct), 'up': price*(1+r_pct), 'fees': 0})
                dca_wbtc_units += (inv / price)
                dca_invested += inv
                last_inv_idx = i

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
                    debt_usdc += (p['cap'] / hf)
                    still_active.append({'cap': p['cap']/hf, 'low': price*(1-r_pct), 'up': price*(1+r_pct), 'fees': 0})
            active_pools = still_active

            strat_val = cash_aave + (wbtc_units * price) - debt_usdc + sum([p['cap'] for p in active_pools])
            dca_val = dca_wbtc_units * price
            
            history.append({
                'Fecha': date, 'Precio': price, 'Estrategia': strat_val, 
                'DCA': dca_val, 'DD_BTC': strat_dd * 100,
                'Max_Strat': max([h['Estrategia'] for h in history] + [strat_val])
            })
            
        res_df = pd.DataFrame(history)
        res_df['DD_Strat'] = ((res_df['Estrategia'] / res_df['Max_Strat']) - 1) * 100
        return res_df, pd.DataFrame(ops_log), dca_invested

    res, logs, total_inv = run_simulation(data, freq_label, inv_amount, range_pct, pool_apr, aave_apr, hf_target, dd_trigger, buy_from_aave)

    # --- MÉTRICAS ---
    c1, c2, c3 = st.columns(3)
    v_strat, v_dca = res['Estrategia'].iloc[-1], res['DCA'].iloc[-1]
    c1.metric("Estrategia DeFi", f"${v_strat:,.0f}", f"{(v_strat/total_inv-1)*100:.1f}%")
    c2.metric("DCA Clásico", f"${v_dca:,.0f}", f"{(v_dca/total_inv-1)*100:.1f}%")
    c3.metric("Inversión Total", f"${total_inv:,.0f}")

    # --- GRÁFICO 1: EVOLUCIÓN ---
    st.subheader("📈 Evolución de Cartera")
    fig1 = go.Figure()
    fig1.add_trace(go.Scatter(x=res['Fecha'], y=res['Estrategia'], name="Estrategia", line=dict(color="#00FFCC", width=3)))
    fig1.add_trace(go.Scatter(x=res['Fecha'], y=res['DCA'], name="DCA Clásico", line=dict(color="#FFA500", dash='dot')))
    fig1.update_layout(template="plotly_dark", height=450, margin=dict(l=20, r=20, t=20, b=20))
    st.plotly_chart(fig1, use_container_width=True)

    # --- GRÁFICO 2: DRAWDOWN ---
    st.subheader("📉 Comparativa de Drawdown (%)")
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=res['Fecha'], y=res['DD_Strat'], name="DD Estrategia", fill='tozeroy', line=dict(color="#00FFCC")))
    fig2.add_trace(go.Scatter(x=res['Fecha'], y=res['DD_BTC'], name="DD Mercado (BTC)", line=dict(color="red", dash='dash')))
    fig2.update_layout(template="plotly_dark", height=300, margin=dict(l=20, r=20, t=20, b=20))
    st.plotly_chart(fig2, use_container_width=True)

    # --- LOGS ---
    st.subheader("📜 Registro de Operaciones")
    st.dataframe(logs.sort_values(by="Fecha", ascending=False), use_container_width=True)

else:
    st.error("Error cargando datos. Revisa requirements.txt y la conexión.")
