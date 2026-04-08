import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

# 1. 網頁基礎設定
st.set_page_config(page_title="秒級即時監控", layout="wide")

# 2. 側邊欄設定
with st.sidebar:
    st.title("⚙️ 極速監控設定")
    market = st.radio("市場", ('美股 (US)', '台股上市 (TW)', '台股上櫃 (TWO)'))
    symbol = st.text_input("輸入股票代號", value="")
    
    st.divider()
    # 這裡設定更新頻率 (毫秒)。5000ms = 5秒
    # 若要 1 秒請改為 1000，但建議維持 5000 以防被封鎖
    refresh_rate = st.slider("更新頻率 (秒)", 1, 60, 5)
    auto_refresh = st.checkbox("開啟極速更新", value=False)
    
    if auto_refresh and symbol:
        st_autorefresh(interval=refresh_rate * 1000, key="stock_refresh")

# 3. 主畫面邏輯
if not symbol:
    st.title("⚡ 極速股價監控")
    st.info("請輸入代號並開啟「極速更新」。建議設定為 5 秒以上以維持連線穩定。")
else:
    full_symbol = symbol.upper()
    if market == '台股上市 (TW)': full_symbol = f"{symbol}.TW"
    elif market == '台股上櫃 (TWO)': full_symbol = f"{symbol}.TWO"

    try:
        # 使用更輕量的 Ticker 物件
        stock = yf.Ticker(full_symbol)
        
        # 僅抓取當前報價，不抓取完整 info 以提升速度
        fast = stock.fast_info
        curr_price = fast.last_price
        
        # 顯示頂部大字報價
        st.subheader(f"📊 {full_symbol} 當前報價")
        st.write(f"### `{curr_price:.2f}`")
        st.caption(f"最後更新：{pd.Timestamp.now().strftime('%H:%M:%S')}")

        # 繪製圖表 (為了效能，即時監控建議看 1d 或 5d)
        # 只抓取當天 1 分鐘 K 線
        df = stock.history(period="1d", interval="1m")

        if not df.empty:
            fig = go.Figure()
            fig.add_trace(go.Candlestick(
                x=df.index, open=df['Open'], high=df['High'],
                low=df['Low'], close=df['Close'], name='1分K',
                increasing_line_color='#ef5350', decreasing_line_color='#26a69a'
            ))

            fig.update_layout(
                height=500, 
                xaxis_rangeslider_visible=False, 
                template="plotly_dark", # 即時監控建議用深色模式，比較不傷眼
                margin=dict(l=10, r=10, t=10, b=10)
            )
            st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"連線頻率過快或代號錯誤：{e}")

st.warning("⚠️ 提醒：極速重新整理會對 Yahoo 伺服器造成壓力。若出現 Error，請調低頻率。")
