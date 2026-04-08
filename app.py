import os
try:
    import yfinance as yf
except ImportError:
    os.system('pip install yfinance pandas matplotlib')
import streamlit as st
import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt

# 設定網頁標題
st.set_page_config(page_title="簡易股市分析小工具", layout="wide")

st.title("📈 簡易股市分析小工具")
st.markdown("這是一個基於 Python 的自動化股市分析程式，支援台股與美股。")

# --- 側邊欄設定 ---
st.sidebar.header("參數設定")
stock_id = st.sidebar.text_input("請輸入股票代號", value="2330.TW")
st.sidebar.info("提示：台股請加 .TW (如 2330.TW)，美股直接輸入 (如 AAPL)")

period_options = {
    "1個月": "1mo",
    "3個月": "3mo",
    "6個月": "6mo",
    "1年": "1y",
    "2年": "2y"
}
selected_period = st.sidebar.selectbox("選擇分析時間範圍", list(period_options.keys()))

# --- 抓取數據 ---
@st.cache_data # 快取數據，避免重複下載
def load_data(symbol, range):
    data = yf.download(symbol, period=period_options[range])
    return data

try:
    df = load_data(stock_id, selected_period)

    if df.empty:
        st.error("找不到該股票代號，請檢查格式是否正確。")
    else:
        # --- 數據處理 ---
        df['MA5'] = df['Close'].rolling(window=5).mean()
        df['MA20'] = df['Close'].rolling(window=20).mean()

        # --- 顯示關鍵指標 ---
        col1, col2, col3 = st.columns(3)
        latest_price = df['Close'].iloc[-1]
        latest_ma5 = df['MA5'].iloc[-1]
        latest_ma20 = df['MA20'].iloc[-1]

        col1.metric("最新收盤價", f"{latest_price:.2f}")
        col2.metric("5日均線 (MA5)", f"{latest_ma5:.2f}")
        col3.metric("20日均線 (MA20)", f"{latest_ma20:.2f}")

        # --- 多空趨勢判斷 ---
        if latest_ma5 > latest_ma20:
            st.success("🔥 目前趨勢：**多頭排列** (5MA > 20MA)")
        else:
            st.warning("❄️ 目前趨勢：**空頭排列** (5MA < 20MA)")

        # --- 繪製圖表 ---
        st.subheader(f"{stock_id} 股價走勢與均線")
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(df.index, df['Close'], label='Close Price', color='gray', alpha=0.3)
        ax.plot(df.index, df['MA5'], label='5-Day MA', color='blue', linewidth=1.5)
        ax.plot(df.index, df['MA20'], label='20-Day MA', color='red', linewidth=1.5)
        ax.legend()
        ax.grid(True, linestyle='--', alpha=0.6)
        st.pyplot(fig)

        # --- 顯示數據表格 ---
        with st.expander("查看原始數據"):
            st.dataframe(df.tail(20))

except Exception as e:
    st.error(f"發生錯誤: {e}")

st.sidebar.markdown("---")
st.sidebar.write("Powered by Gemini & Streamlit")
