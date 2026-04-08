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
    # 將 value 設定為空字串 ""，取消預設代號
    symbol = st.text_input("請輸入股票代號", value="")
    period = st.selectbox("查詢區間", ["3mo", "6mo", "1y", "2y"], index=1)

# 主畫面
if not symbol:
    st.title("📈 股票行情查詢系統")
    st.info("請在左側輸入股票代號（例如：AAPL 或 2330）開始查詢。")
else:
    # 代號處理邏輯
    full_symbol = symbol.upper()
    if market == '台股上市 (TW)':
        full_symbol = f"{symbol}.TW"
    elif market == '台股上櫃 (TWO)':
        full_symbol = f"{symbol}.TWO"

    st.title(f"📊 股票行情: {full_symbol}")

    try:
        # 抓取資料
        data = yf.Ticker(full_symbol)
        df = data.history(period="2y")
        
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

            # 顯示目前價格
            curr_price = df['Close'].iloc[-1]
            st.metric("當前收盤價", f"{curr_price:.2f}")

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
                hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            
            # 移除假日空隙
            fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])

            st.plotly_chart(fig, use_container_width=True)
            
        else:
            st.error(f"找不到代號 '{full_symbol}' 的資料，請檢查代號與市場選擇是否正確。")

    except Exception as e:
        st.error(f"發生錯誤: {e}")

st.divider()
st.caption("提示：美股不需後綴；台股請依市場選擇「上市」或「上櫃」。")
