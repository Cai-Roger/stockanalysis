import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

# 設定網頁標題
st.set_page_config(page_title="台美股 K線查詢器", page_icon="📊", layout="wide")

st.title("📊 專業級 K 線指標查詢")

# 側邊欄設定
with st.sidebar:
    st.header("查詢設定")
    market = st.radio("選擇市場", ('美股 (US)', '台股上市 (TW)', '台股上櫃 (TWO)'))
    raw_symbol = st.text_input("輸入代號", value="2330").strip()
    period = st.selectbox("時間範圍", ("1mo", "3mo", "6mo", "1y", "2y"), index=1)

# 自動拼接後綴
processed_symbol = raw_symbol.upper()
if raw_symbol:
    if market == '台股上市 (TW)':
        processed_symbol = f"{raw_symbol}.TW"
    elif market == '台股上櫃 (TWO)':
        processed_symbol = f"{raw_symbol}.TWO"

if raw_symbol:
    try:
        stock = yf.Ticker(processed_symbol)
        # 抓取歷史資料
        df = stock.history(period=period)
        
        if not df.empty:
            # 顯示基本資訊
            info = stock.info
            name = info.get('longName', processed_symbol)
            price = info.get('currentPrice') or info.get('regularMarketPrice')
            currency = info.get('currency', 'USD')
            
            st.metric(label=name, value=f"{price} {currency}")

            # 繪製 K 線圖
            fig = go.Figure(data=[go.Candlestick(
                x=df.index,
                open=df['Open'],
                high=df['High'],
                low=df['Low'],
                close=df['Close'],
                name='K線',
                increasing_line_color= '#ef5350', # 上漲紅 (符合台股習慣)
                decreasing_line_color= '#26a69a'  # 下跌綠
            )])

            fig.update_layout(
                title=f"{name} ({processed_symbol}) 歷史走勢",
                yaxis_title="價格",
                xaxis_rangeslider_visible=False, # 隱藏下方的滑桿讓畫面乾淨點
                template="plotly_white",
                height=600
            )

            st.plotly_chart(fig, use_container_width=True)
            
            # 顯示原始數據表格
            with st.expander("查看歷史數據明細"):
                st.dataframe(df.sort_index(ascending=False))
        else:
            st.error("查無資料，請確認代號是否正確。")
            
    except Exception as e:
        st.error(f"查詢失敗：{e}")
else:
    st.info("請在左側輸入代號開始查詢")
