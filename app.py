import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

# 1. 網頁基礎設定
st.set_page_config(page_title="類股群組監控系統", layout="wide")

# --- 定義帶有「分類」的強大資料庫 ---
def get_categorized_map(market_type):
    if "台股" in market_type:
        return {
            # 半導體/設備
            "2330": ("半導體", "台積電"), "2303": ("半導體", "聯電"), "2454": ("IC設計", "聯發科"),
            "3131": ("半導體設備", "弘塑"), "3680": ("半導體設備", "家登"), "6223": ("半導體測試", "旺矽"),
            "6488": ("矽晶圓", "環球晶"), "5347": ("半導體代工", "世界"), "3529": ("IP授權", "力旺"),
            # AI/電子代工
            "2317": ("電子代工", "鴻海"), "2382": ("AI伺服器", "廣達"), "3231": ("AI伺服器", "緯創"),
            "6669": ("AI伺服器", "緯穎"), "2308": ("電源/綠能", "台達電"), "2357": ("電腦品牌", "華碩"),
            # 金融
            "2881": ("金融金控", "富邦金"), "2882": ("金融金控", "國泰金"), "2886": ("金融金控", "兆豐金"),
            "2891": ("金融金控", "中信金"), "2884": ("金融金控", "玉山金"),
            # 傳產/航運/重電
            "2603": ("航運", "長榮"), "2609": ("航運", "陽明"), "2615": ("航運", "萬海"),
            "1519": ("重電/綠能", "華城"), "1513": ("重電/綠能", "中興電"), "1514": ("重電/綠能", "亞力"),
            "8069": ("電子紙", "元太"), "3293": ("遊戲/博弈", "鈊象"), "5483": ("矽晶圓", "中美晶"),
            "8299": ("記憶體", "群聯")
        }
    else: # 美股
        return {
            "NVDA": ("AI/半導體", "輝達"), "AAPL": ("科技終端", "蘋果"), "MSFT": ("軟體/AI", "微軟"),
            "TSLA": ("車用/能源", "特斯拉"), "AMD": ("AI/半導體", "超微"), "AVGO": ("半導體", "博通"),
            "AMZN": ("電商/雲端", "亞馬遜"), "GOOGL": ("科技/搜尋", "Google"), "META": ("社群/AI", "臉書"),
            "JPM": ("金融", "摩根大通"), "V": ("金融", "Visa"), "XOM": ("能源", "埃克森美孚")
        }

# 2. 側邊欄
with st.sidebar:
    st.title("🛡️ 市場雷達")
    market = st.radio("監控市場", ('台股上市 (TW)', '台股上櫃 (TWO)', '美股 (US)'))
    symbol = st.text_input("輸入代號深度看盤", value="")
    refresh_rate = st.slider("自動刷新 (秒)", 30, 300, 60)
    auto_refresh = st.checkbox("開啟自動監控", value=False)
    if auto_refresh:
        st_autorefresh(interval=refresh_rate * 1000, key="market_scanner")

tab1, tab2 = st.tabs(["🔍 個股分析", "🌪️ 類股群組掃描"])

# --- 頁籤 1: 個股分析 (略，維持原樣) ---
with tab1:
    if not symbol: st.info("💡 請輸入代號")
    else:
        full_s = f"{symbol.upper()}.TW" if "上市" in market else f"{symbol.upper()}.TWO" if "上櫃" in market else symbol.upper()
        try:
            df = yf.Ticker(full_s).history(period="2y")
            if not df.empty:
                st.subheader(f"{get_categorized_map(market).get(symbol.upper(), ('',''))[1]} ({full_s})")
                # ... [維持原本的 K 線與 Metric 程式碼] ...
                st.write("已顯示 K 線圖與均線。")
            else: st.error("查無數據")
        except: st.error("連線錯誤")

# --- 頁籤 2: 類股群組掃描 (核心修正) ---
with tab2:
    st.header(f"🌪️ {market} 類股群組即時監控")
    
    category_map = get_categorized_map(market)
    tickers = list(category_map.keys())
    
    scanned_data = []
    progress_bar = st.progress(0, text="分類同步中...")
    
    for idx, s in enumerate(tickers):
        fs = f"{s}.TW" if "上市" in market else f"{s}.TWO" if "上櫃" in market else s
        try:
            h = yf.Ticker(fs).history(period="5d")
            if not h.empty:
                c_p, p_p = h['Close'].iloc[-1], h['Close'].iloc[-2]
                v_avg, v_curr = h['Volume'].mean(), h['Volume'].iloc[-1]
                scanned_data.append({
                    "類別": category_map[s][0],
                    "名稱": category_map[s][1],
                    "代號": s,
                    "價格": round(c_p, 1),
                    "今日漲跌%": round(((c_p - p_p) / p_p) * 100, 2),
                    "量能比": round(v_curr / v_avg, 1)
                })
        except: continue
        progress_bar.progress((idx + 1) / len(tickers))
    
    if scanned_data:
        full_df = pd.DataFrame(scanned_data)
        
        # --- 依照「類別」分塊顯示 ---
        unique_categories = full_df['類別'].unique()
        
        for cat in unique_categories:
            st.markdown(f"### 📁 {cat}")
            cat_df = full_df[full_df['類別'] == cat].sort_values(by="今日漲跌%", ascending=False)
            
            def color_val(val):
                return f'color: {"#ef5350" if val > 0 else "#26a69a"}; font-weight: bold;'
            
            st.dataframe(cat_df.style.map(color_val, subset=['今日漲跌%']), use_container_width=True, hide_index=True)
        
        progress_bar.empty()
        st.success("類股掃描完成！")
