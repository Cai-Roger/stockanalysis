import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta

# 1. 網頁基礎設定
st.set_page_config(page_title="台美股 K線自訂查詢", page_icon="📊", layout="wide")

# 2. 側邊導覽列
with st.sidebar:
    st.title("🔍 查詢參數")
    market = st.radio("選擇交易市場", ('美股 (US)', '台股上市 (TW)', '台股上櫃 (TWO)'))
    raw_symbol = st.text_input("輸入股票代號", value="2330").strip()
    
    st.divider()
    st.subheader("📅 設定時間區間")
    # 預設顯示過去半年的資料
    end_date = datetime.now()
    start_date_default = end_date - timedelta(days=180)
    
    # 讓使用者自由選擇日期
    date_range = st.date_input(
        "選擇起始與結束日期",
        value=(start_date_default, end_date),
        max_value=end_date
    )

# 3. 代號與日期處理
processed_symbol = raw_symbol.upper()
if raw_symbol:
    if market == '台股上市 (TW)':
        processed_symbol = f"{raw_symbol}.TW"
    elif market == '台股上櫃 (TWO)':
        processed_symbol = f"{raw_symbol}.TWO"

# 4. 主要顯示邏輯
st.title(f"📊 股票行情自訂查詢：{processed_symbol}")

if raw_symbol and len(date_range) == 2:
    try:
        start_date, end_date = date_range
        # 為了計算均線 MA60，我們必須比使用者的起始日期再往前多抓 60 天的資料
        fetch_start = start_date - timedelta(days=100)
        
        stock = yf.Ticker(processed_symbol)
        df = stock.history(start=fetch_start, end=end_date)
        
        if not df.empty:
            # 計算均線
            df['MA5'] = df['Close'].rolling(window=5).mean()
            df['MA20'] = df['Close'].rolling(window=20).mean()
            df['MA60'] = df['Close'].rolling(window=60).mean()
            
            # 過濾掉為了計算均線而多抓的資料，只顯示使用者選定的區間
            df = df.loc[pd.to_datetime(start_date):]

            # 顯示即時股價卡片
            curr_price = df['Close'].iloc[-1]
            prev_price = df['Close'].iloc[-2] if len(df) > 1 else curr_price
            change = curr_price - prev_price
            
            st.metric("當前收盤價", f"{curr_price:.2f}", f"{change:.2f}")

            # 5. 繪製 K 線圖
            fig = go.Figure()

            # K線
            fig.add_trace(go.Candlestick(
                x=df.index, open=df['Open'], high=df['High'],
                low=df['Low'], close=df['Close'], name='日K',
                increasing_line_color='#ef5350', decreasing_line_color='#26a69a'
            ))

            # 均線
            fig.add_trace(go.Scatter(x=df.index, y=df['MA5'], name='MA5', line=dict(color='#FFD700', width=1.5)))
            fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], name='MA20', line=dict(color='#FF00FF', width=1.5)))
            fig.add_trace(go.Scatter(x=df.index, y=df['MA60'], name='MA60', line=dict(color='#00BFFF', width=1.5)))

            # 設定佈局
            fig.update_layout(
                height=700,
                xaxis_rangeslider_visible=True, # 開啟下方的滑動條，可以二次縮放
                template="plotly_white",
                hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )

            # 移除假日空隙
            fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])

            st.plotly_chart(fig, use_container_width=True)

        else:
            st.error("此日期區間內查無數據，請調整日期或代號。")
    except Exception as e:
        st.error(f"查詢出錯：{e}")
else:
    st.info("💡 請在左側選取完整的起始與結束日期。")
