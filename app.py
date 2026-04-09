import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

# 1. 網頁基礎設定
st.set_page_config(page_title="全市場動態監控系統", layout="wide")

# --- 建立一個更強大的公司名稱對照表 (確保不顯示 "掃描中") ---
def get_company_name(symbol):
    names = {
        # 美股
        "AAPL": "蘋果", "NVDA": "輝達", "TSLA": "特斯拉", "MSFT": "微軟", "GOOGL": "Google",
        "META": "臉書", "AMZN": "亞馬遜", "AVGO": "博通", "AMD": "超微", "NFLX": "網飛",
        # 台股上市
        "2330": "台積電", "2317": "鴻海", "2454": "聯發科", "2308": "台達電", "2382": "廣達",
        "3231": "緯創", "2603": "長榮", "1513": "中興電", "2881": "富邦金", "2882": "國泰金",
        "1519": "華城", "1514": "亞力", "6669": "緯穎", "2609": "陽明", "2615": "萬海",
        # 台股上櫃
        "3131": "弘塑", "3680": "家登", "6223": "旺矽", "3529": "力旺", "5274": "信驊",
        "6488": "環球晶", "3293": "鈊象", "3105": "穩懋", "5347": "世界", "5483": "中美晶",
        "8069": "元太", "8299": "群聯", "6182": "合晶", "3081": "聯亞", "3558": "神準"
    }
    return names.get(symbol, symbol) # 如果名單沒有，就顯示代號

@st.cache_data(ttl=600)
def get_dynamic_market_tickers(market_type):
    try:
        if market_type == "美股 (US)":
            url = "https://finance.yahoo.com/screener/predefined/most_actives?count=40"
            df_list = pd.read_html(url)
            return df_list[0][['Symbol']]
        else:
            # 台股熱門樣本
            tickers = ["2330","2317","2454","2308","2382","3231","2603","1513","2881","2882",
                       "1519","1514","6669","2609","2615","3131","3680","6223","3529","5274",
                       "6488","3293","3105","5347","5483","8069","8299","6182","3081","3558"]
            return pd.DataFrame({"Symbol": tickers})
    except:
        return pd.DataFrame()

# 2. 側邊欄設定
with st.sidebar:
    st.title("🛡️ 市場雷達")
    market = st.radio("監控市場", ('美股 (US)', '台股上市 (TW)', '台股上櫃 (TWO)'))
    symbol = st.text_input("輸入代號進行深度看盤", value="")
    refresh_rate = st.slider("自動刷新頻率 (秒)", 30, 300, 60)
    auto_refresh = st.checkbox("開啟自動監控", value=False)
    if auto_refresh:
        st_autorefresh(interval=refresh_rate * 1000, key="market_scanner")

# 3. 頁籤設定
tab1, tab2 = st.tabs(["🔍 個股 K 線分析", "🌪️ 全市場動態推薦"])

# --- 頁籤 1: 即時看盤 ---
with tab1:
    if not symbol:
        st.info("💡 請輸入代號以顯示 K 線與即時漲跌幅。")
    else:
        full_symbol = symbol.upper()
        if market == '台股上市 (TW)': full_symbol = f"{symbol}.TW"
        elif market == '台股上櫃 (TWO)': full_symbol = f"{symbol}.TWO"
        try:
            stock = yf.Ticker(full_symbol)
            df = stock.history(period="2y", interval="1d")
            if not df.empty:
                for m in [5, 10, 20, 60]: df[f'MA{m}'] = df['Close'].rolling(m).mean()
                df['Pct'] = df['Close'].pct_change() * 100
                st.subheader(f"即時報價: {get_company_name(symbol.upper())} ({full_symbol})")
                curr_p, prev_c = df['Close'].iloc[-1], df['Close'].iloc[-2]
                st.metric("股價", f"{curr_p:.2f}", f"{curr_p-prev_c:.2f} ({(curr_p-prev_c)/prev_c*100:.2f}%)")
                
                fig = go.Figure()
                d_df = df.tail(80)
                fig.add_trace(go.Candlestick(x=d_df.index, open=d_df['Open'], high=d_df['High'], low=d_df['Low'], close=d_df['Close'], name='K線', increasing_line_color='#ef5350', decreasing_line_color='#26a69a'))
                colors = ['#FFD700', '#FF8C00', '#FF00FF', '#00BFFF']
                for m, c in zip([5, 10, 20, 60], colors):
                    fig.add_trace(go.Scatter(x=d_df.index, y=d_df[f'MA{m}'], name=f'MA{m}', line=dict(color=c, width=1.5)))
                fig.update_layout(height=650, template="plotly_dark", uirevision=full_symbol, xaxis_rangeslider_visible=False)
                fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
                st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': True})
            else: st.error("查無數據")
        except Exception as e: st.error(f"錯誤: {e}")

# --- 頁籤 2: 全市場動態掃描 (修正名稱問題) ---
with tab2:
    st.header(f"🌪️ {market} 即時熱門股掃描")
    raw_list = get_dynamic_market_tickers(market)
    if not raw_list.empty:
        scanned_data = []
        progress_bar = st.progress(0, text="正在獲取最新報價...")
        tickers = raw_list['Symbol'].tolist()
        for idx, s in enumerate(tickers):
            fs = f"{s}.TW" if "上市" in market else f"{s}.TWO" if "上櫃" in market else s
            try:
                h = yf.Ticker(fs).history(period="5d")
                if not h.empty:
                    c_p, p_p = h['Close'].iloc[-1], h['Close'].iloc[-2]
                    v_avg, v_curr = h['Volume'].mean(), h['Volume'].iloc[-1]
                    scanned_data.append({
                        "名稱": get_company_name(s), # 使用內建函數獲取名稱
                        "代號": s,
                        "價格": round(c_p, 2),
                        "今日漲跌%": round(((c_p - p_p) / p_p) * 100, 2),
                        "量能比": round(v_curr / v_avg, 2)
                    })
            except: continue
            progress_bar.progress((idx + 1) / len(tickers))

        if scanned_data:
            res_df = pd.DataFrame(scanned_data).sort_values(by="今日漲跌%", ascending=False)
            def color_val(val):
                return f'color: {"#ef5350" if val > 0 else "#26a69a"}; font-weight: bold;'
            st.dataframe(res_df.style.map(color_val, subset=['今日漲跌%']), use_container_width=True, hide_index=True)
            st.success(f"掃描完成！")
            progress_bar.empty()
    else: st.error("無法取得清單")
