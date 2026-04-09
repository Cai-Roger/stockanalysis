import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

# 1. 網頁基礎設定
st.set_page_config(page_title="類股輪動全監控", layout="wide")

# --- 定義「類股全覆蓋」資料庫 ---
def get_extended_categorized_map(market_type):
    if "台股" in market_type:
        return {
            # --- 半導體族群 ---
            "2330": ("半導體-權值", "台積電"), "2303": ("半導體-代工", "聯電"), "2454": ("半導體-IC設計", "聯發科"),
            "3131": ("半導體-設備", "弘塑"), "3680": ("半導體-設備", "家登"), "6223": ("半導體-測試", "旺矽"),
            "6488": ("半導體-矽晶圓", "環球晶"), "3529": ("半導體-IP授權", "力旺"), "3034": ("半導體-IC設計", "聯詠"),
            # --- AI 概念股 ---
            "2317": ("AI-電子代工", "鴻海"), "2382": ("AI-伺服器", "廣達"), "3231": ("AI-伺服器", "緯創"),
            "6669": ("AI-伺服器", "緯穎"), "2308": ("AI-電源", "台達電"), "2357": ("AI-品牌", "華碩"),
            "2376": ("AI-主機板", "技嘉"), "2395": ("AI-工業電腦", "研華"),
            # --- 航運/傳產 ---
            "2603": ("航運-貨櫃", "長榮"), "2609": ("航運-貨櫃", "陽明"), "2618": ("航運-航空", "長榮航"),
            "2610": ("航運-航空", "華航"), "1301": ("傳產-塑膠", "台塑"), "2002": ("傳產-鋼鐵", "中鋼"),
            # --- 重電/綠能 ---
            "1519": ("綠能-重電", "華城"), "1513": ("綠能-重電", "中興電"), "1514": ("綠能-重電", "亞力"),
            "6806": ("綠能-風電", "森崴能源"),
            # --- 金融 ---
            "2881": ("金融-金控", "富邦金"), "2882": ("金融-金控", "國泰金"), "2891": ("金融-金控", "中信金"),
            "2886": ("金融-金控", "兆豐金"), "2884": ("金融-金控", "玉山金"),
            # --- 其它 ---
            "8069": ("電子紙", "元太"), "3293": ("遊戲博弈", "鈊象"), "8299": ("記憶體", "群聯")
        }
    else: # 美股
        return {
            "NVDA": ("AI/晶片", "輝達"), "AAPL": ("消費電子", "蘋果"), "MSFT": ("雲端/AI", "微軟"),
            "TSLA": ("電動車", "特斯拉"), "AMD": ("AI/晶片", "超微"), "AVGO": ("通信/晶片", "博通"),
            "AMZN": ("電商/雲端", "亞馬遜"), "GOOGL": ("軟體/廣告", "Google"), "META": ("社群/AI", "臉書"),
            "JPM": ("金融", "摩根大通"), "V": ("金融/支付", "Visa"), "XOM": ("能源", "埃克森美孚")
        }

# 2. 側邊欄
with st.sidebar:
    st.title("🛡️ 專業雷達")
    market = st.radio("監控市場", ('台股上市 (TW)', '台股上櫃 (TWO)', '美股 (US)'))
    symbol = st.text_input("輸入代號看 K 線", value="")
    refresh_rate = st.slider("更新頻率 (秒)", 30, 300, 45)
    auto_refresh = st.checkbox("自動監控", value=False)
    if auto_refresh:
        st_autorefresh(interval=refresh_rate * 1000, key="market_scanner")

tab1, tab2 = st.tabs(["🔍 個股分析", "🏘️ 類股輪動狀態"])

# --- 頁籤 1: 個股分析 ---
with tab1:
    if not symbol: st.info("💡 請在左側輸入代號。")
    else:
        full_s = f"{symbol.upper()}.TW" if "上市" in market else f"{symbol.upper()}.TWO" if "上櫃" in market else symbol.upper()
        try:
            stock = yf.Ticker(full_s)
            df = stock.history(period="2y")
            if not df.empty:
                for m in [5, 10, 20, 60]: df[f'MA{m}'] = df['Close'].rolling(m).mean()
                df['Pct'] = df['Close'].pct_change() * 100
                st.subheader(f"即時報價: {full_s}")
                curr_p, prev_c = df['Close'].iloc[-1], df['Close'].iloc[-2]
                st.metric("股價", f"{curr_p:.2f}", f"{curr_p-prev_c:.2f} ({(curr_p-prev_c)/prev_c*100:.2f}%)")
                
                fig = go.Figure()
                d_df = df.tail(80)
                fig.add_trace(go.Candlestick(x=d_df.index, open=d_df['Open'], high=d_df['High'], low=d_df['Low'], close=d_df['Close'], name='K線', increasing_line_color='#ef5350', decreasing_line_color='#26a69a'))
                colors = ['#FFD700', '#FF8C00', '#FF00FF', '#00BFFF']
                for m, c in zip([5, 10, 20, 60], colors):
                    fig.add_trace(go.Scatter(x=d_df.index, y=d_df[f'MA{m}'], name=f'MA{m}', line=dict(color=c, width=1.5)))
                fig.update_layout(height=650, template="plotly_dark", uirevision=full_s, xaxis_rangeslider_visible=False)
                fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
                st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': True})
            else: st.error("查無數據")
        except: st.error("錯誤")

# --- 頁籤 2: 類股輪動 (修正排序錯誤) ---
with tab2:
    st.header(f"🏘️ {market} 類股動態一覽")
    category_map = get_extended_categorized_map(market)
    tickers = list(category_map.keys())
    
    scanned_data = []
    progress_bar = st.progress(0, text="同步各類股數據中...")
    
    for idx, s in enumerate(tickers):
        fs = f"{s}.TW" if "上市" in market else f"{s}.TWO" if "上櫃" in market else s
        try:
            h = yf.Ticker(fs).history(period="5d")
            if not h.empty:
                c_p, p_p = h['Close'].iloc[-1], h['Close'].iloc[-2]
                v_avg, v_curr = h['Volume'].mean(), h['Volume'].iloc[-1]
                scanned_data.append({
                    "族群": category_map[s][0],
                    "公司": category_map[s][1],
                    "代號": s,
                    "價格": round(c_p, 1),
                    "今日漲跌%": round(((c_p - p_p) / p_p) * 100, 2),
                    "量能比": round(v_curr / v_avg, 1)
                })
        except: continue
        progress_bar.progress((idx + 1) / len(tickers))
    
    if scanned_data:
        full_df = pd.DataFrame(scanned_data)
        
        # 1. 族群排行 (頂部小卡片)
        st.subheader("📊 今日強勢族群排行")
        group_perf = full_df.groupby("族群")["今日漲跌%"].mean().sort_values(ascending=False)
        cols = st.columns(4)
        for i, (grp, val) in enumerate(group_perf.items()):
            if i < 4: cols[i].metric(grp, f"{val:.2f}%", delta=f"{val:.2f}%")

        # 2. 分類清單 (修正點：先將陣列轉為清單再排序)
        st.write("---")
        unique_groups = sorted(list(full_df['族群'].unique())) # 關鍵修正：轉 list 並用內建 sorted
        
        for group in unique_groups:
            st.markdown(f"#### 📁 {group}")
            group_df = full_df[full_df['族群'] == group].sort_values(by="今日漲跌%", ascending=False)
            
            def color_val(val):
                color = "#ef5350" if val > 0 else "#26a69a" if val < 0 else "gray"
                return f'color: {color}; font-weight: bold;'
            
            st.dataframe(group_df.style.map(color_val, subset=['今日漲跌%']), use_container_width=True, hide_index=True)
        progress_bar.empty()
