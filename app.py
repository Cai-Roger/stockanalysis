import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

# 1. 網頁基礎設定
st.set_page_config(
    page_title="專業台美股 K線查詢器", 
    page_icon="📈", 
    layout="wide"
)

# 2. 側邊導覽列
with st.sidebar:
    st.title("🔍 查詢參數")
    market = st.radio(
        "選擇交易市場", 
        ('美股 (US)', '台股上市 (TW)', '台股上櫃 (TWO)'),
        help="系統會自動為台股加上 .TW 或 .TWO 後綴"
    )
    
    raw_symbol = st.text_input("輸入股票代號", value="2330").strip()
    
    period = st.selectbox(
        "查詢區間", 
        options=["3mo", "6mo", "1y", "2y", "5y"], 
        index=1,
        format_func=lambda x: {"3mo":"三個月", "6mo":"半年", "1y":"一年", "2y":"兩年", "5y":"五年"}[x]
    )

# 3. 代號預處理邏輯
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
        # 抓取比選擇區間稍長的資料，以確保均線起點正常 (例如計算MA60需要多往前抓60天)
        stock = yf.Ticker(processed_symbol)
        df = stock.history(period="2y") # 預抓兩年
        
        if not df.empty:
            # --- 計算均線 ---
            df['MA5'] = df['Close'].rolling(window=5).mean()
            df['MA20'] = df['Close'].rolling(window=20).mean()
            df['MA60'] = df['Close'].rolling(window=60).mean()
            
            # 根據使用者選擇的區間切過濾資料
            if period == "3mo": df = df.last("3M")
            elif period == "6mo": df = df.last("6M")
            elif period == "1y": df = df.last("1Y")
            elif period == "2y": df = df.last("2Y")
            elif period == "5y": df = df.last("5Y")

            # 獲取基本資訊
            info = stock.info
            company_name = info.get('longName', processed_symbol)
            curr_price = info.get('currentPrice') or info.get('regularMarketPrice')
            currency = info.get('currency', 'USD')
            prev_close = info.get('previousClose', 0)
            
            # 計算漲跌幅
            change = curr_price - prev_close if curr_price and prev_close else 0
            change_pct = (change / prev_close) * 100 if prev_close else 0

            # 顯示上方數據卡片
            col1, col2, col3 = st.columns(3)
            col1.metric("公司名稱", company_name)
            col2.metric("目前股價", f"{curr_price} {currency}", f"{change:.2f} ({change_pct:.2f}%)")
            col3.metric("今日成交量", f"{df['Volume'].iloc[-1]:,.0f}")

            # 5. 繪製圖表
            fig = go.Figure()

            # 加入 K 線
            fig.add_trace(go.Candlestick(
                x=df.index,
                open=df['Open'], high=df['High'],
                low=df['Low'], close=df['Close'],
                name='日K',
                increasing_line_color='#ef5350', decreasing_line_color='#26a69a'
            ))

            # 加入均線
            fig.add_trace(go.Scatter(x=df.index
