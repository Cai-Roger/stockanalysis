import streamlit as st
import yfinance as yf
import pandas as pd

# 設定網頁標題
st.set_page_config(page_title="簡易股價查詢器", page_icon="📈")

st.title("📈 簡易股價查詢工具")
st.write("輸入美股代號（如 AAPL）或台股代號（如 2330.TW）來獲取即時行情。")

# 側邊輸入框
symbol = st.text_input("請輸入股票代號", value="2330.TW").upper()

if st.button("開始查詢"):
    try:
        # 獲取資料
        stock = yf.Ticker(symbol)
        
        # 顯示公司基本資訊
        info = stock.info
        long_name = info.get('longName', '未知公司')
        current_price = info.get('currentPrice') or info.get('regularMarketPrice')
        currency = info.get('currency', 'USD')
        
        if current_price:
            # 建立大大的數字卡片
            st.metric(label=f"公司名稱: {long_name}", value=f"{current_price} {currency}")
            
            # 抓取歷史數據畫圖
            hist = stock.history(period="1mo") # 抓取最近一個月
            if not hist.empty:
                st.subheader("最近一個月走勢圖")
                st.line_chart(hist['Close'])
            else:
                st.warning("無法取得歷史走勢圖數據。")
        else:
            st.error("找不到該股票的當前價格，請確認代號是否正確。")

    except Exception as e:
        st.error(f"發生錯誤：{e}")
        st.info("提示：台股上市請加 .TW，上櫃請加 .TWO")

# 頁尾說明
st.divider()
st.caption("數據來源：Yahoo Finance (yfinance)")
