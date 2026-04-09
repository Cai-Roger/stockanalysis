import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

# 1. 網頁基礎設定
st.set_page_config(page_title="專業級即時監控 & 30檔領先指標", layout="wide")

# --- 擴充至 30 檔的代碼對照表 ---
@st.cache_data(ttl=3600)
def get_market_data(market_type):
    if market_type == "美股 (US)":
        return {
            "AAPL": "蘋果", "NVDA": "輝達", "MSFT": "微軟", "AMZN": "亞馬遜", 
            "GOOGL": "Google", "META": "臉書", "TSLA": "特斯拉", "AVGO": "博通", 
            "AMD": "超微", "NFLX": "網飛", "COST": "好市多", "LLY": "禮來",
            "JPM": "摩根大通", "V": "Visa", "MA": "萬事達卡", "UNH": "聯合健康",
            "HD": "家得寶", "PG": "寶潔", "XOM": "埃克森美孚", "ORCL": "甲骨文",
            "ADBE": "Adobe", "ASML": "艾司摩爾", "CRM": "賽富時", "BAC": "美國銀行",
            "KO": "可口可口", "PEP": "百事可樂", "WMT": "沃爾瑪", "T": "AT&T",
            "CSCO": "思科", "INTC": "英特爾"
        }
    elif market_type == "台股上市 (TW)":
        return {
            "2330": "台積電", "2317": "鴻海", "2454": "聯發科", "2308": "台達電", 
            "2382": "廣達", "3231": "緯創", "2603": "長榮", "1513": "中興電",
            "2881": "富邦金", "2882": "國泰金", "2357": "華碩", "2891": "中信金",
            "2412": "中華電", "1301": "台塑", "1303": "南亞", "2005": "燁輝",
            "2609": "陽明", "2615": "萬海", "2379": "瑞昱", "3034": "聯詠",
            "2301": "光寶科", "2303": "聯電", "2395": "研華", "2408": "南亞科",
            "2884": "玉山金", "2886": "兆豐金", "3008": "大立光", "3711": "日月光",
            "4938": "和碩", "6669": "緯穎"
        }
    else: # 台股上櫃
        return {
            "8069": "元太", "6488": "環球晶", "3105": "穩懋", "3529": "力旺", 
            "8299": "群聯", "6182": "合晶", "3293": "鈊象", "6223": "旺矽",
            "5483": "中美晶", "5347": "世界", "6147": "頎邦", "4147": "龍巖",
            "6415": "矽力-KY", "3653": "健策", "3016": "嘉晶", "3680": "家登",
            "5274": "信驊", "3131": "弘塑", "3479": "安勤", "4966": "譜瑞-KY",
            "6510": "精測", "6274": "台燿", "8358": "金居", "6138": "茂達",
            "3081": "聯亞", "3141": "晶宏", "3558": "神準", "5425": "台半",
            "6188": "廣明", "8936": "國統"
        }

# 2. 側邊欄設定
with st.sidebar:
    st.title("⚙️ 控制面板")
    market = st.radio("監控市場", ('美股 (US)', '台股上市 (TW)', '台股上櫃 (TWO)'))
    symbol = st.text_input("輸入股票代號 (看盤用)", value="")
    
    st.divider()
    refresh_rate = st.slider("更新頻率 (秒)", 5, 60, 15)
    auto_refresh = st.checkbox("開啟極速更新", value=False)
    
    if auto_refresh:
        st_autorefresh(interval=refresh_rate * 1000, key="global_refresh")

# 3. 設定頁籤
tab1, tab2 = st.tabs(["📈 即時看盤", "🔥 市場 30 檔動態推薦"])

# --- 頁籤 1: 即時看盤 ---
with tab1:
    if not symbol:
        st.info("💡 請在左側輸入代號開始監控。")
    else:
        full_symbol = symbol.upper()
        if market == '台股上市 (TW)': full_symbol = f"{symbol}.TW"
        elif market == '台股上櫃 (TWO)': full_symbol = f"{symbol}.TWO"

        try:
            stock = yf.Ticker(full_symbol)
            company_name = stock.info.get('longName', '未知公司')
            df = stock.history(period="2y", interval="1d")
            if not df.empty:
                df['MA5'] = df['Close'].rolling(5).mean()
                df['MA10'] = df['Close'].rolling(10).mean()
                df['MA20'] = df['Close'].rolling(20).mean()
                df['MA60'] = df['Close'].rolling(60).mean()
                df['Pct'] = df['Close'].pct_change() * 100
                
                curr_p, prev_c = df['Close'].iloc[-1], df['Close'].iloc[-2]
                chg, pct = curr_p - prev_c, ((curr_p - prev_c) / prev_c) * 100

                st.subheader(f"{company_name} ({full_symbol})")
                st.metric("即時股價", f"{curr_p:.2f}", f"{chg:.2f} ({pct:.2f}%)")

                fig = go.Figure()
                display_df = df.tail(65)
                fig.add_trace(go.Candlestick(
                    x=display_df.index, open=display_df['Open'], high=display_df['High'],
                    low=display_df['Low'], close=display_df['Close'], name='日K',
                    increasing_line_color='#ef5350', decreasing_line_color='#26a69a',
                    customdata=display_df['Pct'],
                    hovertemplate="漲跌幅: %{customdata:.2f}%<extra></extra>"
                ))
                for ma, col in zip(['MA5', 'MA10', 'MA20', 'MA60'], ['#FFD700', '#FF8C00', '#FF00FF', '#00BFFF']):
                    fig.add_trace(go.Scatter(x=display_df.index, y=display_df[ma], name=ma, line=dict(color=col, width=1.3)))

                fig.update_layout(height=600, template="plotly_dark", uirevision=full_symbol, xaxis_rangeslider_visible=False)
                fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
                st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': True})
            else: st.error("查無數據")
        except Exception as e: st.error(f"連線錯誤: {e}")

# --- 頁籤 2: 市場 30 檔動態推薦 ---
with tab2:
    st.header(f"🚀 {market} 領先指標 (30檔即時掃描)")
    
    market_map = get_market_data(market)
    tickers = list(market_map.keys())

    if tickers:
        rec_data = []
        progress_text = "正在掃描市場數據，請稍候..."
        progress_bar = st.progress(0, text=progress_text)
        
        for idx, s in enumerate(tickers):
            fs = s
            if "台股" in market:
                suffix = ".TW" if "上市" in market else ".TWO"
                fs = f"{s}{suffix}"
            
            try:
                t = yf.Ticker(fs)
                h = t.history(period="5d")
                if len(h) >= 2:
                    c_p, p_p = h['Close'].iloc[-1], h['Close'].iloc[-2]
                    p_pct = ((c_p - p_p) / p_p) * 100
                    ma5 = h['Close'].rolling(5).mean().iloc[-1]
                    status = "📈 多頭" if c_p > ma5 else "📉 整理"
                    
                    rec_data.append({
                        "公司": market_map[s],
                        "代號": s,
                        "最新價": round(c_p, 2),
                        "漲跌幅%": round(p_pct, 2),
                        "趨勢評級": status
                    })
            except: continue
            # 更新進度條
            progress_bar.progress((idx + 1) / len(tickers), text=f"已掃描 {idx+1}/{len(tickers)} 檔...")
        
        if rec_data:
            df_rec = pd.DataFrame(rec_data).sort_values(by="漲跌幅%", ascending=False)
            def apply_color(val):
                color = '#ef5350' if val > 0 else '#26a69a' if val < 0 else ''
                return f'color: {color}; font-weight: bold;'

            styled_df = df_rec.style.map(apply_color, subset=['漲跌幅%'])
            st.dataframe(styled_df, use_container_width=True, hide_index=True)
            progress_bar.empty() # 掃描完後隱藏進度條
        else: st.error("掃描失敗。")
    else: st.warning("查無名單。")

st.divider()
st.caption("數據來源：Yahoo Finance | 更新時間：" + pd.Timestamp.now().strftime('%H:%M:%S'))
