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

# 自定義 CSS 讓介面更美觀
st.markdown("""
    <style>
    .main {
        background-color: #f5f7f9;
    }
    .stMetric {
        background-color: #ffffff;
        padding: 15px;
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    </style>
    """, unsafe_allow_html=True)

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
        options=["1mo", "3mo", "6mo", "1y", "2y", "5y"], 
        index=1,
        format_func=lambda x: {"1mo":"一個月", "3mo":"三個月", "6mo":"半年", "1y":"一年", "2y":"兩年", "5y":"五年"}[x]
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
        # 抓取資料
        stock = yf.Ticker(processed_symbol)
        df = stock.history(period=period)
        
        if not df.empty:
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

            # 5. 繪製 K 線圖 (使用 Plotly)
            fig = go.Figure(data=[go.Candlestick(
                x=df.index,
                open=df['Open'],
                high=df['High'],
                low=df['Low'],
                close=df['Close'],
                name='日K',
                increasing_line_color='#ef5350',  # 漲：紅
                decreasing_line_color='#26a69a'   # 跌：綠
            )])

            # 設定圖表格式與過濾非交易日
            fig.update_layout(
                height=600,
                margin=dict(l=10, r=10, t=30, b=10),
                xaxis_rangeslider_visible=False, # 關閉下方滑桿，讓畫面更專業
                template="plotly_white",
                hovermode="x unified"
            )

            # 關鍵：移除週末與非交易日（避免出現長直線）
            fig.update_xaxes(
                rangebreaks=[
                    dict(bounds=["sat", "mon"]), # 隱藏週六到週一
                ],
                tickformat="%Y-%m-%d"
            )

            st.plotly_chart(fig, use_container_width=True)

            # 6. 數據表格
            with st.expander("📊 查看原始歷史數據"):
                st.dataframe(df.sort_index(ascending=False), use_container_width=True)

        else:
            st.error(f"找不到代號 '{processed_symbol}' 的數據，請檢查代號是否輸入正確。")

    except Exception as e:
        st.error(f"連線或抓取資料時發生錯誤：{e}")
else:
    st.info("💡 請在左側輸入框輸入股票代號，例如美股輸入 'AAPL' 或台股輸入 '2454'。")

st.divider()
st.caption(f"最後更新時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 數據來源：Yahoo Finance")
