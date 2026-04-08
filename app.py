import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

# 網頁設定
st.set_page_config(page_title="台美股查詢器", layout="wide")

# 側邊欄
with st.sidebar:
    st.title("設定")
    market = st.radio("市場", ('美股 (US)', '台股上市 (TW)', '台股上櫃 (TWO)'))
    symbol = st.text_input("股票代號", value="2330")
    period = st.selectbox("區間", ["3mo", "6mo", "1y", "2y"], index=1)

# 代號處理
full_symbol = symbol.upper()
if symbol:
    if market == '台股上市 (TW)':
        full_symbol = f"{symbol}.TW"
    elif market == '台股上櫃 (TWO)':
        full_symbol = f"{symbol}.TWO"

# 主畫面
st.title(f"股票行情: {full_symbol}")

if symbol:
    try:
        # 抓取資料
        data = yf.Ticker(full_symbol)
        df = data.history(period="2y") # 多抓一點算均線
        
        if not df.empty:
            # 計算均線
            df['MA5'] = df['Close'].rolling(5).mean()
            df['MA20'] = df['Close'].rolling(20).mean()
            df['MA60'] = df['Close'].rolling(60).mean()
            
            # 切割顯示範圍
            if period == "3mo": display_df = df.tail(65)
            elif period == "6mo": display_df = df.tail(125)
            elif period == "1y": display_df = df.tail(255)
            else: display_df = df.tail(510)

            # 顯示價格
            curr_price = df['Close'].iloc[-1]
            st.metric("目前股價", f"{curr_price:.2f}")

            # 畫圖
            fig = go.Figure()
            
            # K線
            fig.add_trace(go.Candlestick(
                x=display_df.index,
                open=display_df['Open'], high=display_df['High'],
                low=display_df['Low'], close=display_df['Close'],
                name='K線', increasing_line_color='#ef5350', decreasing_line_color='#26a69a'
            ))

            # 均線
            fig.add_trace(go.Scatter(x=display_df.index, y=display_df['MA5'], name='MA5', line=dict(color='#FFD700', width=1.5)))
            fig.add_trace(go.Scatter(x=display_df.index, y=display_df['MA20'], name='MA20', line=dict(color='#FF00FF', width=1.5)))
            fig.add_trace(go.Scatter(x=display_df.index, y=display_df['MA60'], name='MA60', line=dict(color='#00BFFF', width=1.5)))

            # 圖表設定
            fig.update_layout(
                height=600,
                xaxis_rangeslider_visible=False,
                template="plotly_white",
                hovermode="x unified"
            )
            
            # 移除假日
            fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])

            st.plotly_chart(fig, use_container_width=True)
            
        else:
            st.error("查無資料")

    except Exception as e:
        st.error(f"發生錯誤: {e}")
