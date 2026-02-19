import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
from datetime import datetime

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="DeFi Auditor Final PRO", layout="wide")

st.title("🛡️ DeFi Alpha Strategist: WBTC/USDC vs DCA")
st.markdown("Auditoría técnica: Liquidez Concentrada + AAVE + Compras de Drawdown (Datos Diarios).")

# --- SIDEBAR: PARÁMETROS ---
with st.sidebar:
    st.header("⚙️ Configuración")
    start_date = st.date_input("Fecha Inicio", value=datetime(2020, 1, 1))
    freq_label = st.selectbox("Periodicidad Inversión", ["Semanal", "Quincenal", "Mensual"], index=2)
    inv_amount = st.number_input("Inversión por Periodo ($)", value=1000.0)
    
    st.subheader("📊 Uniswap V3")
    range_pct = st.slider("Rango Pool (±%)", 5, 50, 30) / 100
    pool_apr = st.number_input("APR Pool (%)", value=15.0) / 100
    
    st.subheader("📉 Estrategia Crisis")
    dd_trigger = st.slider("Gatillo Compra Drawdown (%)", 20, 80, 50) / 100
    hf_target = st.number_input("Health Factor", value=2.5)
    aave_apr = st.number_input("APR Aave USDC (%)", value=3.0) / 100

# --- MOTOR DE DATOS ---
@st.cache_data
def load_data(start):
    try:
        df = yf.download("BTC-USD", start=start, interval="1d")
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        # Búsqueda robusta de columna de precio
        for col in ['Adj Close', 'Close']:
            if col in df.columns:
                return df[[col]].rename(columns={col: 'Price'})
        return df.iloc[:, [0]].rename(columns={df.columns[0]: 'Price'})
    except:
        return None

data = load_data(start_date)

if data is not None and not data.empty:
    def run_simulation(df, freq_days, inv, r_pct, p_apr, ddt, hf, a_apr):
        # Variables Estrategia
        cash_usdc, wbtc_units, debt_usdc = 0.0, 0.0, 0.0
        active_pools, history, ops_log = [], [], []
        # Variables DCA
        dca_units, dca_inv, ath = 0.0, 0.0, 0.0
        
        days_map = {"Semanal": 7, "Quincenal": 15, "Mensual": 30}
        period = days_map[freq_days]
        last_inv_idx = -period
        
        prices = df['Price'].values
        dates = df.index
        
        for i in range(len(df)):
            price = float(prices[i])
            date = dates[i]
            
            # 1. Gestión ATH y RESET
            if price > ath:
                ath = price
                if wbtc_units > 0:
                    val_to_cash = (wbtc_units * price) - debt_usdc
                    cash_usdc += val_to_cash
                    wbtc_units, debt_usdc = 0.0, 0.0
                    ops_log.append({"Fecha": date, "Op": "RESET ATH", "Price": price, "Desc": f"Nuevo ATH en ${price:,.0f}"})

            current_dd = (price - ath) / ath
            cash_usdc *= (1 + a_apr / 365) # Interés AAVE

            # 2. Compra en Drawdown Crítico
            if current_dd <= -ddt and cash_usdc > 100:
                buy_vol = cash_usdc * 0.5
                cash_usdc -= buy_vol
                wbtc_units += (buy_vol / price)
                debt_usdc += (buy_vol / hf)
                active_pools.append({'cap': buy_vol/hf, 'low': price*(1-r_pct), 'up': price*(1+r_pct), 'fees': 0})
                ops_log.append({"Fecha": date, "Op": "CRISIS BUY", "Price": price, "Desc": f"Compra al -{ddt*100}% DD"})

            # 3. Inversión Periódica
            if (i - last_inv_idx) >= period:
                active_pools.append({'cap': inv, 'low': price*(1-r_pct), 'up': price*(1+r_pct), 'fees': 0})
                dca_units += (inv / price)
                dca_inv += inv
                ops_log.append({"Fecha": date, "Op": "OPEN POOL", "Price": price, "Desc": f"Inversión de ${inv}"})
                last_inv_idx = i

            # 4. Gestión de Pools
            new_active = []
            for p in active_pools:
                if p['low'] <= price <= p['up']:
                    p['fees'] += p['cap'] * (p_apr / 365)
                    new_active.append(p)
                elif price > p['up']:
                    cash_usdc += (p['cap'] * 1.05) + p['fees']
                    ops_log.append({"Fecha": date, "Op": "TAKE PROFIT", "Price": price, "Desc": "Salida superior"})
                elif price < p['low']:
                    wbtc_units += (p['cap'] / price)
                    debt_usdc += (p['cap'] / hf)
                    new_active.append({'cap': p['cap']/hf, 'low': price*(1-r_pct), 'up': price*(1+r_pct), 'fees': 0})
                    ops_log.append({"Fecha": date, "Op": "STOP LOSS", "Price": price, "Desc": "Salida inferior -> Colateral"})
            active_pools = new_active

            # 5. Valoración y Registro
            pool_val = sum([p['cap'] for p in active_pools])
            total_strat = cash_usdc + (wbtc_units * price) - debt_usdc + pool_val
            
            history.append({
                'Fecha': date, 'Precio': price, 'Estrategia': total_strat, 
                'DCA': dca_units * price, 'USDC': cash_usdc, 'WBTC_USD': wbtc_units * price,
                'Pools': pool_val, 'DD_BTC': current_dd * 100,
                'Max_Strat': max([h['Estrategia'] for h in history] + [total_strat])
            })
            
        res_df = pd.DataFrame(history)
        res_df['DD_Strat'] = ((res_df['Estrategia'] / res_df['Max_Strat']) - 1) * 100
        return res_df, pd.DataFrame(ops_log), dca_inv

    # Ejecutar Simulación
    res, logs, total_inv = run_simulation(data, freq_label, inv_amount, range_pct, pool_apr, dd_trigger, hf_target, aave_apr)

    # --- MÉTRICAS ---
    c1, c2, c3, c4 = st.columns(4)
    v_strat, v_dca = res['Estrategia'].iloc[-1], res['DCA'].iloc[-1]
    c1.metric("Estrategia", f"${v_strat:,.0f}", f"{(v_strat/total_inv-1)*100:.1f}%")
    c2.metric("DCA Clásico", f"${v_dca:,.0f}", f"{(v_dca/total_inv-1)*100:.1f}%")
    c3.metric("Inversión Total", f"${total_inv:,.0f}")
    c4.metric("Diferencia Alpha", f"${v_strat - v_dca:,.0f}")

    # --- GRÁFICO 1: COMPARATIVA Y PRECIO ---
    st.subheader("📈 Evolución y Auditoría")
    fig1 = make_subplots(specs=[[{"secondary_y": True}]])
    fig1.add_trace(go.Scatter(x=res['Fecha'], y=res['Estrategia'], name="Estrategia DeFi", line=dict(color="#00FFCC", width=3)))
    fig1.add_trace(go.Scatter(x=res['Fecha'], y=res['DCA'], name="DCA Clásico", line=dict(color="#FFA500", dash='dot')))
    fig1.add_trace(go.Scatter(x=res['Fecha'], y=res['Precio'], name="BTC (Der.)", opacity=0.1, line=dict(color="white")), secondary_y=True)
    
    if not logs.empty:
        for op_type in logs['Op'].unique():
            df_op = logs[logs['Op'] == op_type]
            fig1.add_trace(go.Scatter(x=df_op['Fecha'], y=df_op['Price'], mode='markers', name=op_type, secondary_y=True))

    fig1.update_layout(template="plotly_dark", height=500, margin=dict(l=20, r=20, t=20, b=20))
    st.plotly_chart(fig1, use_container_width=True)

    # --- GRÁFICO 2: COMPOSICIÓN Y DRAWDOWN ---
    st.subheader("🏦 Estructura de Capital y Riesgo")
    col_a, col_b = st.columns(2)
    
    with col_a:
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=res['Fecha'], y=res['USDC'], name="USDC (Caja)", stackgroup='one'))
        fig2.add_trace(go.Scatter(x=res['Fecha'], y=res['WBTC_USD'], name="WBTC (Colateral)", stackgroup='one'))
        fig2.add_trace(go.Scatter(x=res['Fecha'], y=res['Pools'], name="En Pools", stackgroup='one'))
        fig2.update_layout(title="Composición de Cartera", template="plotly_dark", height=350)
        st.plotly_chart(fig2, use_container_width=True)
        
    with col_b:
        fig3 = go.Figure()
        fig3.add_trace(go.Scatter(x=res['Fecha'], y=res['DD_Strat'], name="DD Estrategia", fill='tozeroy', line=dict(color="#00FFCC")))
        fig3.add_trace(go.Scatter(x=res['Fecha'], y=res['DD_BTC'], name="DD Mercado (BTC)", line=dict(color="red", dash='dash')))
        fig3.update_layout(title="Comparativa Drawdown (%)", template="plotly_dark", height=350)
        st.plotly_chart(fig3, use_container_width=True)

    st.subheader("📜 Registro Detallado")
    st.dataframe(logs.sort_values("Fecha", ascending=False), use_container_width=True)

else:
    st.error("Error al cargar datos. Verifica la conexión con Yahoo Finance.")
