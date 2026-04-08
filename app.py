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
    
    # 固定區間下拉選單
    period = st.selectbox(
        "查詢區間", 
        options=["3mo", "6mo", "1y", "2y", "5y"], 
        index=1,
        format_func=lambda x: {"3mo":"三個月", "6mo":"半年", "1y":"一年", "2y":"兩年", "5y":"五年"}[x]
    )

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
        # 預抓足夠長的資料以計算均線 (固定抓兩年，再根據選單切割顯示)
        df = stock.history(period="2y")
        
        if not df.empty:
            # 計算均線
            df['MA5'] = df['Close'].rolling(window=5).mean()
            df['MA20'] = df['Close'].rolling(window=20).mean()
            df['MA60'] = df['Close'].rolling(window=60).mean()
            
            # 根據選擇區間過濾顯示的資料
            if period == "3mo": df = df.tail(65)
            elif period == "6mo": df = df.tail(125)
            elif period == "1y": df = df.tail(255)
            elif period == "2y": df = df.tail(510)
            else: df = df.tail(1260) # 5y

            # 獲取資訊顯示卡片
            info = stock.info
            curr_price = info.get('currentPrice') or info.get('regularMarketPrice')
            currency = info.get('currency', 'USD')
            
            st.metric("目前股價", f"{curr_price} {currency}")

            # 5. 繪製圖表
            fig = go.Figure()

            # K線
            fig.add_trace(go.Candlestick(
                x=df.index, open=df['Open'], high=df['High'],
                low=df['Low'], close=df['Close'], name='日K',
                increasing_line_color='#ef5350', decreasing_line_color='#26a69a'
            ))

            # 均線 (確保括號完整)
            fig.add
