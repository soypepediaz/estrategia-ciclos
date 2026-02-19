import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
from datetime import datetime

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="DeFi Alpha Strategist PRO", layout="wide")

st.title("🛡️ DeFi Alpha Strategist: WBTC/USDC vs DCA Clásico")
st.markdown("Simulación avanzada: Liquidez Concentrada + AAVE + Compras de Oportunidad.")

# --- SIDEBAR: PARÁMETROS ---
with st.sidebar:
    st.header("⚙️ Configuración del Sistema")
    start_date = st.date_input("Fecha Inicio", value=datetime(2020, 1, 1))
    freq_label = st.selectbox("Periodicidad", ["Semanal", "Quincenal", "Mensual"], index=2)
    inv_amount = st.number_input("Inversión por Periodo ($)", value=1000.0)
    
    st.subheader("📊 Uniswap V3")
    range_pct = st.slider("Rango Pool (±%)", 5, 50, 30) / 100
    pool_apr = st.number_input("APR Pool (%)", value=10.0) / 100
    
    st.subheader("👻 AAVE & Riesgo")
    aave_apr = st.number_input("APR Aave USDC (%)", value=3.0) / 100
    hf_target = st.number_input("Health Factor", value=2.5)
    
    st.subheader("📉 Estrategia de Crisis")
    dd_trigger = st.slider("Compra al Drawdown (%)", 20, 80, 50) / 100
    buy_from_aave = st.slider("% Caja Aave a Invertir", 10, 100, 50) / 100

# --- MOTOR DE DATOS ---
@st.cache_data
def load_data(start):
    try:
        df = yf.download("BTC-USD", start=start, interval="1d")
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        # Búsqueda robusta de columna de precio
        for col in ['Adj Close', 'Close']:
            if col in df.columns:
                df = df[[col]].rename(columns={col: 'Price'})
                return df
        return df.iloc[:, [0]].rename(columns={df.columns[0]: 'Price'})
    except Exception as e:
        st.error(f"Error en datos: {e}")
        return None

data = load_data(start_date)

if data is not None and not data.empty:
    def run_simulation(df, freq_days, inv, r_pct, p_apr, a_apr, hf, ddt, b_pct):
        # Variables Estrategia
        cash_aave, wbtc_units, debt_usdc = 0, 0, 0
        active_pools, history, ops_log = [], [], []
        
        # Variables DCA Clásico
        dca_wbtc_units, dca_invested = 0, 0
        
        ath = 0
        days_map = {"Semanal": 7, "Quincenal": 15, "Mensual": 30}
        period = days_map[freq_days]
        last_inv_idx = -period
        
        prices = df['Price'].values
        dates = df.index

        for i in range(len(df)):
            price = float(prices[i])
            date = dates[i]
            
            # 1. ATH y Reset Estrategia
            if price > ath:
                ath = price
                if wbtc_units > 0 or debt_usdc > 0:
                    val = (wbtc_units * price) - debt_usdc
                    cash_aave += val
                    wbtc_units, debt_usdc = 0, 0
                    ops_log.append({"Fecha": date, "Operación": "RESET ATH", "Detalle": f"Venta colateral y cierre deuda en ${price:,.0f}"})

            strat_dd = (price - ath) / ath
            cash_aave *= (1 + a_apr / 365)

            # 2. Compra en Caída (Estrategia)
            if strat_dd <= -ddt and cash_aave > 100:
                spent = cash_aave * b_pct
                cash_aave -= spent
                wbtc_units += (spent / price)
                new_loan = spent / hf
                debt_usdc += new_loan
                active_pools.append({'cap': new_loan, 'low': price*(1-r_pct), 'up': price*(1+r_pct), 'fees': 0})
                ops_log.append({"Fecha": date, "Operación": "COMPRA CRISIS", "Detalle": f"Inversión de ${spent:,.0f} por Drawdown >{ddt*100}%"})

            # 3. Inversión Periódica (DCA vs Estrategia)
            if (i - last_inv_idx) >= period:
                # Estrategia
                active_pools.append({'cap': inv, 'low': price*(1-r_pct), 'up': price*(1+r_pct), 'fees': 0})
                ops_log.append({"Fecha": date, "Operación": "APERTURA POOL", "Detalle": f"Nueva pool de ${inv:,.0f} (Rango ${price*(1-r_pct):,.0f} - ${price*(1+r_pct):,.0f})"})
                
                # DCA Clásico
                dca_wbtc_units += (inv / price)
                dca_invested += inv
                last_inv_idx = i

            # 4. Gestión de Pools
            still_active = []
            for p in active_pools:
                if p['low'] <= price <= p['up']:
                    p['fees'] += p['cap'] * (p_apr / 365)
                    still_active.append(p)
                elif price > p['up']:
                    profit = (p['cap'] * 0.5) * (r_pct * 0.5)
                    cash_aave += (p['cap'] + profit + p['fees'])
                    ops_log.append({"Fecha": date, "Operación": "TAKE PROFIT", "Detalle": f"Pool cerrada por arriba. Retorno: ${p['cap'] + profit:,.0f}"})
                elif price < p['low']:
                    wbtc_units += (p['cap'] / price)
                    loan = p['cap'] / hf
                    debt_usdc += loan
                    still_active.append({'cap': loan, 'low': price*(1-r_pct), 'up': price*(1+r_pct), 'fees': 0})
                    ops_log.append({"Fecha": date, "Operación": "STOP LOSS (COLATERAL)", "Detalle": f"Pool a AAVE y apertura de nueva pool con préstamo de ${loan:,.0f}"})
            active_pools = still_active

            # 5. Valoraciones Finales
            strat_val = cash_aave + (wbtc_units * price) - debt_usdc + sum([p['cap'] for p in active_pools])
            dca_val = dca_wbtc_units * price
            
            # Cálculo de Drawdowns para gráfico
            # Usamos el máximo histórico del valor de cartera para el DD de la estrategia
            # pero el del precio de BTC para el DD de mercado
            history.append({
                'Fecha': date, 'Precio': price, 'Estrategia': strat_val, 
                'DCA_Clasico': dca_val, 'DD_BTC': strat_dd * 100,
                'DD_Strat': ((strat_val / max([h['Estrategia'] for h in history]+[strat_val])) - 1) * 100
            })
            
        return pd.DataFrame(history), pd.DataFrame(ops_log), dca_invested

    res, logs, total_inv = run_simulation(data, freq_label, inv_amount, range_pct, pool_apr, aave_apr, hf_target, dd_trigger, buy_from_aave)

    # --- MÉTRICAS DE CABECERA ---
    c1, c2, c3, c4 = st.columns(4)
    v_strat = res['Estrategia'].iloc[-1]
    v_dca = res['DCA_Clasico'].iloc[-1]
    c1.metric("Valor Estrategia", f"${v_strat:,.0f}", f"{(v_strat/total_inv-1)*100:.1f}%")
    c2.metric("Valor DCA Clásico", f"${v_dca:,.0f}", f"{(v_dca/total_inv-1)*100:.1f}%")
    c3.metric("Inversión Total", f"${total_inv:,.0f}")
    c4.metric("Alfa (Estrat. vs DCA)", f"${v_strat - v_dca:,.0f}")

    # --- GRÁFICOS ---
    # Crear Subplots (Carteras y Drawdown)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1, row_heights=[0.7, 0.3],
                        subplot_titles=("Evolución de Cartera", "Comparativa de Drawdown (%)"))

    # Fila 1: Evolución
    fig
