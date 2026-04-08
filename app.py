import streamlit as st
import yfinance as yf
import pandas as pd

# 設定網頁標題
st.set_page_config(page_title="台美股自動查詢器", page_icon="💰")

st.title("💰 台美股自動查詢工具")
st.write("只需輸入代碼，系統會自動處理後綴！")

# 第一步：選擇市場
market = st.radio(
    "請選擇市場：",
    ('美股 (US)', '台股上市 (TW)', '台股上櫃 (TWO)'),
    horizontal=True
)

# 第二步：輸入代號 (不需手動加點)
raw_symbol = st.text_input("請輸入股票代號（例如: AAPL 或 2330）", value="").strip()

# 第三步：自動拼接後綴邏輯
processed_symbol = raw_symbol.upper()
if raw_symbol:
    if market == '台股上市 (TW)':
        processed_symbol = f"{raw_symbol}.TW"
    elif market == '台股上櫃 (TWO)':
        processed_symbol = f"{raw_symbol}.TWO"
    # 美股則保持原樣

# 查詢按鈕
if st.button("立即查詢"):
    if not raw_symbol:
        st.warning("請先輸入代號！")
    else:
        try:
            with st.spinner(f'正在搜尋 {processed_symbol} ...'):
                stock = yf.Ticker(processed_symbol)
                info = stock.info
                
                # 檢查是否真的抓到資料
                if 'currentPrice' in info or 'regularMarketPrice' in info:
                    long_name = info.get('longName', '未知公司')
                    price = info.get('currentPrice') or info.get('regularMarketPrice')
                    currency = info.get('currency', 'USD')
                    
                    # 顯示資訊卡片
                    st.success(f"查詢成功：{processed_symbol}")
                    col1, col2 = st.columns(2)
                    col1.metric("公司名稱", long_name)
                    col2.metric("當前股價", f"{price} {currency}")
                    
                    # 顯示簡易走勢圖
                    hist = stock.history(period="1mo")
                    if not hist.empty:
                        st.subheader("最近一個月走勢圖")
                        st.line_chart(hist['Close'])
                else:
                    st.error(f"找不到 '{processed_symbol}'，請確認代號與市場是否匹配。")
                    
        except Exception as e:
            st.error(f"發生錯誤：請檢查網路或代號是否正確。")
            st.expander("錯誤細節").write(e)

st.divider()
st.caption("提示：美股如 AAPL, TSLA；台股如 2330, 0050")
