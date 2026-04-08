import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

# 1. 網頁基礎設定
st.set_page_config(page_title="專業級即時監控", layout="wide")

# 2. 側邊欄設定
with st.sidebar:
    st.title("⚙️ 看盤設定")
    market = st.radio("市場", ('美股 (US)', '台股上市 (TW)', '台股上櫃 (TWO)'))
    symbol = st.text_input("輸入股票代號", value="")
    period = st.selectbox("圖表長度", ["1mo", "3mo", "6mo", "1y"], index=0)
    
    st.divider()
    refresh_rate = st.slider("更新頻率 (秒)", 1, 60, 5)
    auto_refresh = st.checkbox("開啟極速更新", value=False)
    
    if auto_refresh and symbol:
        st_autorefresh(interval=refresh_rate * 1000, key="stock_refresh")

# 3. 主畫面邏輯
if not symbol:
    st.title("⚡ 專業即時監控系統")
    st.info("請輸入代號以顯示 K 線與均線指標。")
else:
    full_symbol = symbol.upper()
    if market == '台股上市 (TW)': full_symbol = f"{symbol}.TW"
    elif market == '台股上櫃 (TWO)': full_symbol = f"{symbol}.TWO"

    try:
        stock = yf.Ticker(full_symbol)
        
        # 為了計算 MA60，我們固定抓取比顯示範圍更長的資料
        df = stock.history(period="2y", interval="1d")

        if not df.empty:
            # 計算均線
            df['MA5'] = df['Close'].rolling(5).mean()
            df['MA20'] = df['Close'].rolling(20).mean()
            df['MA60'] = df['Close'].rolling(60).mean()
            
            # 根據選擇的區間切分資料，但保留計算好的 MA
            if period == "1mo": display_df = df.tail(22)
            elif period == "3mo": display_df = df.tail(65)
            elif period == "6mo": display_df = df.tail(125)
            else: display_df = df.tail(255)

            # 顯示報價卡片
            curr_price = df['Close'].iloc[-1]
            prev_close = df['Close'].iloc[-2]
            change = curr_price - prev_close
            st.metric(f"{full_symbol}", f"{curr_price:.2f}", f"{change:.2f}")

            # 4. 繪製圖表
            fig = go.Figure()

            # K線
            fig.add_trace(go.Candlestick(
                x=display_df.index, open=display_df['Open'], high=display_df['High'],
                low=display_df['Low'], close=display_df['Close'], name='日K',
                increasing_line_color='#ef5350', decreasing_line_color='#26a69a'
            ))

            # 均線
            fig.add_trace(go.Scatter(x=display_df.index, y=display_df['MA5'], name='MA5', line=dict(color='#FFD700', width=1.2)))
            fig.add_trace(go.Scatter(x=display_df.index, y=display_df['MA20'], name='MA20', line=dict(color='#FF00FF', width=1.2)))
            fig.add_trace(go.Scatter(x=display_df.index, y=display_df['MA60'], name='MA60', line=dict(color='#00BFFF', width=1.2)))

            # 關鍵設定：uirevision 讓圖表刷新時不重置縮放大小
            fig.update_layout(
                height=700,
                template="plotly_dark",
                uirevision=full_symbol, # 只要代號不變，視圖狀態就不會重置
                xaxis_rangeslider_visible=False,
                hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )

            fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])

            # 使用 config 增加互動體驗
            st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': True})

    except Exception as e:
        st.error(f"數據抓取失敗：{e}")
