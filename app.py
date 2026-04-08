import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

# 1. 網頁基礎設定
st.set_page_config(page_title="專業台美股 K線查詢器", page_icon="📈", layout="wide")

# 2. 側邊導覽列
with st.sidebar:
    st.title("🔍 查詢參數")
    market = st.radio("選擇交易市場", ('美股 (US)', '台股上市 (TW)', '台股上櫃 (TWO)'))
    raw_symbol = st.text_input("輸入股票代號", value="2330").strip()
    period = st.selectbox("查詢區間", options=["3mo", "6mo", "1y", "2y", "5y"], index=1)

# 3. 代號預處理
processed_symbol = raw_symbol.upper()
if raw_symbol:
    if market == '台股上市 (TW)':
        processed_symbol = f"{raw_symbol}.TW"
    elif market == '台股上櫃 (TWO)':
        processed_symbol = f"{raw_symbol}.TWO"

# 4. 主要顯示邏輯
st.title(f"📈 股票即時行情：{processed_symbol}")

if raw_symbol:
    try:
        stock = yf.Ticker(processed_symbol)
        # 預抓足夠長的資料以計算均線
        df = stock.history(period="2y")
        
        if not df.empty:
            # 計算均線
            df['MA5'] = df['Close'].rolling(window=5).mean()
            df['MA20'] = df['Close'].rolling(window=20).mean()
            df['MA60'] = df['Close'].rolling(window=60).mean()
            
            # 根據選擇區間過濾顯示的資料
            if period == "3mo": df = df.tail(60)
            elif period == "6mo": df = df.tail(120)
            elif period == "1y": df = df.tail(250)
            else: df = df.tail(500)

            # 獲取資訊
            info = stock.info
            curr_price = info.get('currentPrice') or info.get('regularMarketPrice')
            
            st.metric("目前股價", f"{curr_price} {info.get('currency', '')}")

            # 5. 繪製圖表
            fig = go.Figure()

            # K線
            fig.add_trace(go.Candlestick(
                x=df.index, open=df['Open'], high=df['High'],
                low=df['Low'], close=df['Close'], name='日K',
                increasing_line_color='#ef5350', decreasing_line_color='#26a69a'
            ))

            # 均線 (這幾行最容易漏括號，請確保複製完整)
            fig.add_trace(go.Scatter(x=df.index, y=df['MA5'], name='MA5', line=dict(color='#FFD700', width=1)))
            fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], name='MA20', line=dict(color='#FF00FF', width=1)))
            fig.add_trace(go.Scatter(x=df.index, y=df['MA60'], name='MA60', line=dict(color='#00BFFF', width=1)))

            # 設定佈局
            fig.update_layout(
                height=600,
                xaxis_rangeslider_visible=False,
                template="plotly_white",
                hovermode="x unified"
            )

            # 移除假日空隙
            fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])

            st.plotly_chart(fig, use_container_width=True)

        else:
            st.error("找不到資料")
    except Exception as e:
        st.error(f"錯誤：{e}")
