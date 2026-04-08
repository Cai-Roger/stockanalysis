import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

# 1. 網頁基礎設定
st.set_page_config(page_title="專業級即時監控 & 選股", layout="wide")

# --- 動態抓取清單與名稱函數 ---
@st.cache_data(ttl=3600)
def get_market_data(market_type):
    # 定義代碼與名稱的對照，減少 API 請求負擔
    if market_type == "美股 (US)":
        return {
            "AAPL": "蘋果", "NVDA": "輝達", "MSFT": "微軟", "AMZN": "亞馬遜", 
            "GOOGL": "Google", "META": "臉書", "TSLA": "特斯拉", "AVGO": "博通", 
            "AMD": "超微", "NFLX": "網飛", "COST": "好市多"
        }
    elif market_type == "台股上市 (TW)":
        return {
            "2330": "台積電", "2317": "鴻海", "2454": "聯發科", "2308": "台達電", 
            "2382": "廣達", "3231": "緯創", "2603": "長榮", "1513": "中興電",
            "2881": "富邦金", "2882": "國泰金", "2357": "華碩"
        }
    else: # 台股上櫃
        return {
            "8069": "元太", "6488": "環球晶", "3105": "穩懋", "3529": "力旺", 
            "8299": "群聯", "6182": "合晶", "3293": "鈊象", "6223": "旺矽"
        }

# 2. 側邊欄設定
with st.sidebar:
    st.title("⚙️ 控制面板")
    market = st.radio("監控市場", ('美股 (US)', '台股上市 (TW)', '台股上櫃 (TWO)'))
    symbol = st.text_input("輸入股票代號 (看盤用)", value="")
    
    st.divider()
    refresh_rate = st.slider("更新頻率 (秒)", 5, 60, 10)
    auto_refresh = st.checkbox("開啟極速更新", value=False)
    
    if auto_refresh:
        st_autorefresh(interval=refresh_rate * 1000, key="global_refresh")

# 3. 設定頁籤
tab1, tab2 = st.tabs(["📈 即時看盤", "🔥 市場動態推薦"])

# --- 頁籤 1: 即時看盤 (加入公司名稱) ---
with tab1:
    if not symbol:
        st.info("💡 請在左側輸入代號開始監控。")
    else:
        full_symbol = symbol.upper()
        if market == '台股上市 (TW)': full_symbol = f"{symbol}.TW"
        elif market == '台股上櫃 (TWO)': full_symbol = f"{symbol}.TWO"

        try:
            stock = yf.Ticker(full_symbol)
            # 獲取公司名稱
            company_name = stock.info.get('longName', '未知公司')
            
            df = stock.history(period="2y", interval="1d")
            if not df.empty:
                df['MA5'] = df['Close'].rolling(5).mean()
                df['MA10'] = df['Close'].rolling(10).mean()
                df['MA20'] = df['Close'].rolling(20).mean()
                df['MA60'] = df['Close'].rolling(60).mean()
                df['Pct'] = df['Close'].pct_change() * 100
                
                curr_p, prev_c = df['Close'].iloc[-1], df['Close'].iloc[-2]
                chg = curr_p - prev_c
                pct = (chg / prev_c) * 100

                # 標題顯示 公司名稱 + 代號
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
                # 均線
                fig.add_trace(go.Scatter(x=display_df.index, y=display_df['MA5'], name='MA5', line=dict(color='#FFD700', width=1.3)))
                fig.add_trace(go.Scatter(x=display_df.index, y=display_df['MA10'], name='MA10', line=dict(color='#FF8C00', width=1.3)))
                fig.add_trace(go.Scatter(x=display_df.index, y=display_df['MA20'], name='MA20', line=dict(color='#FF00FF', width=1.3)))
                fig.add_trace(go.Scatter(x=display_df.index, y=display_df['MA60'], name='MA60', line=dict(color='#00BFFF', width=1.3)))

                fig.update_layout(height=600, template="plotly_dark", uirevision=full_symbol, xaxis_rangeslider_visible=False)
                fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
                st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': True})
            else:
                st.error("查無數據")
        except Exception as e:
            st.error(f"連線錯誤: {e}")

# --- 頁籤 2: 市場動態推薦 (加入公司名稱列) ---
with tab2:
    st.header(f"🚀 {market} 動態領先指標")
    
    market_map = get_market_data(market)
    tickers = list(market_map.keys())

    if tickers:
        rec_data = []
        progress_bar = st.progress(0)
        
        for idx, s in enumerate(tickers):
            fs = s
            if "台股" in market:
                suffix = ".TW" if "上市" in market else ".TWO"
                fs = f"{s}{suffix}"
            
            try:
                t = yf.Ticker(fs)
                h = t.history(period="5d")
                if len(h) >= 2:
                    c_p = h['Close'].iloc[-1]
                    p_p = h['Close'].iloc[-2]
                    p_pct = ((c_p - p_p) / p_p) * 100
                    ma5 = h['Close'].rolling(5).mean().iloc[-1]
                    
                    status = "📈 多頭" if c_p > ma5 else "☁️ 整理"
                    
                    rec_data.append({
                        "公司": market_map[s], # 加入中文名稱
                        "代號": s,
                        "最新價": round(c_p, 2),
                        "漲跌幅%": round(p_pct, 2),
                        "趨勢評級": status
                    })
            except:
                continue
            progress_bar.progress((idx + 1) / len(tickers))
        
        if rec_data:
            df_rec = pd.DataFrame(rec_data).sort_values(by="漲跌幅%", ascending=False)

            def apply_color(val):
                color = '#ef5350' if val > 0 else '#26a69a' if val < 0 else ''
                return f'color: {color}; font-weight: bold;'

            styled_df = df_rec.style.map(apply_color, subset=['漲跌幅%'])
            st.dataframe(styled_df, use_container_width=True, hide_index=True)
        else:
            st.error("掃描失敗。")
    else:
        st.warning("查無名單。")

st.divider()
st.caption("數據來源：Yahoo Finance | 更新時間：" + pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S'))
