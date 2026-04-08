import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

# 1. 網頁基礎設定
st.set_page_config(page_title="即時台美股看盤", layout="wide")

# 2. 側邊欄：設定自動重新整理
with st.sidebar:
    st.title("⚙️ 設定")
    market = st.radio("選擇市場", ('美股 (US)', '台股上市 (TW)', '台股上櫃 (TWO)'))
    symbol = st.text_input("輸入股票代號", value="")
    period = st.selectbox("圖表區間", ["1d", "5d", "1mo", "6mo", "1y"], index=2)
    
    st.divider()
    auto_refresh = st.checkbox("開啟自動重新整理 (每 60 秒)", value=False)
    
    if auto_refresh:
        # 每 60000 毫秒 (60秒) 重新整理一次頁面
        st_autorefresh(interval=60000, key="stock_refresh")

# 3. 主畫面邏輯
if not symbol:
    st.title("🚀 即時股價監控系統")
    st.info("請在左側輸入代號並開啟「自動重新整理」來追蹤即時行情。")
else:
    # 代號補綴
    full_symbol = symbol.upper()
    if market == '台股上市 (TW)': full_symbol = f"{symbol}.TW"
    elif market == '台股上櫃 (TWO)': full_symbol = f"{symbol}.TWO"

    try:
        stock = yf.Ticker(full_symbol)
        
        # 獲取最即時的報價 (fast_info)
        fast = stock.fast_info
        curr_price = fast.last_price
        prev_close = fast.previous_close
        change = curr_price - prev_close
        change_pct = (change / prev_close) * 100 if prev_close else 0

        # 顯示大大的即時價格卡片
        st.title(f"📊 {full_symbol} 即時行情")
        col1, col2 = st.columns([1, 2])
        with col1:
            st.metric(
                label="成交價 (即時)", 
                value=f"{curr_price:.2f}", 
                delta=f"{change:.2f} ({change_pct:.2f}%)"
            )
        with col2:
            st.caption(f"數據最後更新: {pd.Timestamp.now().strftime('%H:%M:%S')}")
            if auto_refresh:
                st.write("🔄 自動更新已開啟，每 60 秒刷新一次。")

        # 繪製 K 線圖
        # 如果選 1d 或 5d，間隔改為分鐘 (5m, 15m)
        interval = "1m" if period == "1d" else "1d"
        df = stock.history(period=period, interval=interval)

        if not df.empty:
            # 計算均線 (僅在日K模式下計算 MA)
            if interval == "1d":
                df['MA5'] = df['Close'].rolling(5).mean()
                df['MA20'] = df['Close'].rolling(20).mean()

            fig = go.Figure()
            fig.add_trace(go.Candlestick(
                x=df.index, open=df['Open'], high=df['High'],
                low=df['Low'], close=df['Close'], name='K線',
                increasing_line_color='#ef5350', decreasing_line_color='#26a69a'
            ))

            if 'MA5' in df.columns:
                fig.add_trace(go.Scatter(x=df.index, y=df['MA5'], name='MA5', line=dict(color='#FFD700', width=1)))
                fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], name='MA20', line=dict(color='#FF00FF', width=1)))

            fig.update_layout(height=600, xaxis_rangeslider_visible=False, template="plotly_white", hovermode="x unified")
            fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
            st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"查詢失敗: {e}")

st.divider()
st.caption("註：免費數據可能有 15 分鐘延遲。如需秒級更新，建議盤中開啟自動重新整理。")
