import streamlit as st
import pandas as pd
import yfinance as yf
import numpy as np
from datetime import datetime, timedelta

# Configuración de página
st.set_page_config(page_title="DeFi Strategy Backtester", layout="wide")

st.title("🛡️ Estrategia DeFi: Liquidez Concentrada + AAVE (WBTC/USDC)")
st.markdown("""
Esta aplicación simula una estrategia de inversión recurrente en el par WBTC/USDC con gestión activa de colateral y compras oportunistas.
""")

# --- SIDEBAR: PARÁMETROS ---
with st.sidebar:
    st.header("⚙️ Configuración")
    start_date = st.date_input("Fecha de inicio", value=datetime(2020, 1, 1))
    end_date = st.date_input("Fecha de fin", value=datetime(2026, 1, 31))
    
    freq = st.selectbox("Periodicidad de inversión", ["Semanal", "Quincenal", "Mensual"], index=2)
    investment_per_period = st.number_input("Inversión por periodo (USD)", value=1000)
    
    st.subheader("📊 Parámetros del Pool")
    range_pct = st.slider("Rango del Pool (±%)", 5, 50, 30) / 100
    pool_apr = st.number_input("APR estimado del Pool (%)", value=10.0) / 100
    
    st.subheader("👻 Parámetros AAVE")
    aave_lending_apr = st.number_input("APR Depósito USDC (%)", value=3.0) / 100
    health_factor_target = st.number_input("Health Factor objetivo (Borrow)", value=2.5, step=0.1)
    # LTV estándar de WBTC en AAVE es ~70-75%
    ltv_wbtc = 0.73 
    
    st.subheader("📉 Compra en Drawdown")
    dd_trigger = st.slider("Compra al Drawdown (%)", 20, 80, 50) / 100
    buy_pct_from_aave = st.slider("% de Caja USDC a invertir en caída", 10, 100, 50) / 100

# --- LÓGICA DE BACKTESTING ---

@st.cache_data
def get_data(start, end):
    df = yf.download("BTC-USD", start=start, end=end, interval="1d")
    if isinstance(df.columns, pd.MultiIndex): # Limpieza para nuevas versiones de yfinance
        df.columns = df.columns.get_level_values(0)
    df = df[['Adj Close']].rename(columns={'Adj Close': 'Price'})
    return df

data = get_data(start_date, end_date)

def run_simulation():
    # Variables de estado
    cash_aave = 0  # USDC en Lending
    wbtc_collateral_value = 0 # Valor en USD del WBTC en AAVE
    wbtc_units = 0 # Unidades de WBTC
    debt_usdc = 0 # Deuda en USDC
    active_pools = []
    history = []
    
    # Métrica de frecuencia
    days_map = {"Semanal": 7, "Quincenal": 15, "Mensual": 30}
    period_days = days_map[freq]
    
    current_ath = 0
    last_investment_day = -period_days
    
    # Iteración diaria (Backtesting de alta fidelidad)
    prices = data['Price'].values
    dates = data.index
    
    for i in range(len(data)):
        current_price = float(prices[i])
        current_date = dates[i]
        
        # 1. Actualizar ATH y calcular Drawdown
        if current_price > current_ath:
            current_ath = current_price
            # GATILLO: RESET TOTAL EN ATH
            if debt_usdc > 0 or wbtc_units > 0:
                # Vender todo el WBTC, pagar deuda y meter a AAVE
                final_sale = (wbtc_units * current_price) - debt_usdc
                cash_aave += final_sale
                wbtc_units = 0
                wbtc_collateral_value = 0
                debt_usdc = 0

        drawdown = (current_price - current_ath) / current_ath
        
        # 2. Rendimiento AAVE (Lending)
        cash_aave *= (1 + aave_lending_apr / 365)
        
        # 3. GATILLO: COMPRA EN DRAWDOWN CRÍTICO
        if drawdown <= -dd_trigger and cash_aave > 100:
            buy_amount = cash_aave * buy_pct_from_aave
            cash_aave -= buy_amount
            new_wbtc = buy_amount / current_price
            wbtc_units += new_wbtc
            # Abrir Borrow para generar más liquidez
            # Borrow = (Valor / HF) * LTV (aprox simplificado por HF target)
            new_debt = (buy_amount / health_factor_target)
            debt_usdc += new_debt
            # Esa deuda abre una nueva pool extra
            active_pools.append({
                'entry_price': current_price,
                'capital': new_debt,
                'upper': current_price * (1 + range_pct),
                'lower': current_price * (1 - range_pct),
                'fees': 0
            })

        # 4. Inversión Recurrente (DCA)
        days_since_last = (current_date - dates[max(0, i+last_investment_day)]).days
        if i == 0 or (i - last_investment_day) >= period_days:
            active_pools.append({
                'entry_price': current_price,
                'capital': investment_per_period,
                'upper': current_price * (1 + range_pct),
                'lower': current_price * (1 - range_pct),
                'fees': 0
            })
            last_investment_day = i

        # 5. Gestión de Pools Activas
        still_active = []
        for pool in active_pools:
            # Acumular fees si está en rango
            if pool['lower'] <= current_price <= pool['upper']:
                pool['fees'] += pool['capital'] * (pool_apr / 365)
                still_active.append(pool)
            
            # Salida por ARRIBA (USDC)
            elif current_price > pool['upper']:
                # Venta de la mitad WBTC con profit medio + capital original + fees
                profit_wbtc = (pool['capital'] / 2) * (range_pct / 2) # Profit medio
                exit_value = pool['capital'] + profit_wbtc + pool['fees']
                cash_aave += exit_value
            
            # Salida por ABAJO (WBTC)
            elif current_price < pool['lower']:
                # Se convierte en WBTC colateral
                units = pool['capital'] / current_price
                wbtc_units += units
                # Abrir borrow del 1/HF para seguir invirtiendo
                borrowed = (pool['capital'] / health_factor_target)
                debt_usdc += borrowed
                # Re-invertir el borrow en una nueva pool
                still_active.append({
                    'entry_price': current_price,
                    'capital': borrowed,
                    'upper': current_price * (1 + range_pct),
                    'lower': current_price * (1 - range_pct),
                    'fees': 0
                })
        
        active_pools = still_active
        
        # Valoración total de la cartera
        total_pool_val = sum([p['capital'] for p in active_pools])
        total_value = cash_aave + (wbtc_units * current_price) - debt_usdc + total_pool_val
        
        history.append({
            'Date': current_date,
            'Price': current_price,
            'Cash_Aave': cash_aave,
            'Total_Value': total_value,
            'Drawdown': drawdown
        })
        
    return pd.DataFrame(history)

# Ejecutar Simulación
results = run_simulation()

# --- VISUALIZACIÓN ---
col1, col2, col3 = st.columns(3)
final_val = results['Total_Value'].iloc[-1]
total_invested = (len(results) // (30 if freq=="Mensual" else 15 if freq=="Quincenal" else 7)) * investment_per_period
roi = (final_val - total_invested) / total_invested * 100

col1.metric("Valor Final Cartera", f"${final_val:,.2f}")
col2.metric("Inversión Total", f"${total_invested:,.2f}")
col3.metric("ROI Total", f"{roi:.2f}%")

st.subheader("Evolución del Portafolio vs Precio BTC")
# Crear gráfico con dos ejes
st.line_chart(results.set_index('Date')[['Total_Value']])

st.subheader("Métricas de Riesgo")
max_dd = results['Drawdown'].min() * 100
st.warning(f"El Max Drawdown histórico de Bitcoin en este periodo fue de {max_dd:.2f}%")

# Mostrar tabla de datos
with st.expander("Ver desglose diario"):
    st.dataframe(results)

st.success(f"Estrategia finalizada. ATH detectado en el periodo: ${results['Price'].max():,.2f}")
