import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

# 1. 網頁基礎設定
st.set_page_config(page_title="市場動態掃描看盤", layout="wide")

# --- 動態抓取清單函數 ---
@st.cache_data(ttl=3600) # 快取一小時，避免重複抓取影響效能
def get_market_tickers(market_type):
    if market_type == "美股 (US)":
        # 抓取標普 500 前 20 檔 (簡化示範)
        return ["AAPL", "NVDA", "MSFT", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "LLY", "JPM", "V", "MA", "UNH", "COST", "HD"]
    else:
        # 抓取台灣 50 (0050) 的主要成份股代碼
        tw_50 = ["2330", "2317", "2454", "2308", "2382", "3231", "2881", "2882", "2357", "2886", "2603", "2891", "2412", "1301", "1303", "2005"]
        return tw_50

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

# --- 頁籤 1: 即時看盤 (維持原本功能) ---
with tab1:
    if not symbol:
        st.info("💡 請在左側輸入代號開始監控。")
    else:
        full_symbol = symbol.upper()
        if market == '台股上市 (TW)': full_symbol = f"{symbol}.TW"
        elif market == '台股上櫃 (TWO)': full_symbol = f"{symbol}.TWO"

        try:
            stock = yf.Ticker(full_symbol)
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

                st.metric(f"{full_symbol}", f"{curr_p:.2f}", f"{chg:.2f} ({pct:.2f}%)")

                fig = go.Figure()
                display_df = df.tail(65)
                fig.add_trace(go.Candlestick(
                    x=display_df.index, open=display_df['Open'], high=display_df['High'],
                    low=display_df['Low'], close=display_df['Close'], name='日K',
                    increasing_line_color='#ef5350', decreasing_line_color='#26a69a',
                    customdata=display_df['Pct'],
                    hovertemplate="漲跌幅: %{customdata:.2f}%<extra></extra>"
                ))
                fig.add_trace(go.Scatter(x=display_df.index, y=display_df['MA5'], name='MA5', line=dict(color='#FFD700', width=1.3)))
                fig.add_trace(go.Scatter(x=display_df.index, y=display_df['MA10'], name='MA10', line=dict(color='#FF8C00', width=1.3)))
                fig.add_trace(go.Scatter(x=display_df.index, y=display_df['MA20'], name='MA20', line=dict(color='#FF00FF', width=1.3)))
                fig.add_trace(go.Scatter(x=display_df.index, y=display_df['MA60'], name='MA60', line=dict(color='#00BFFF', width=1.3)))

                fig.update_layout(height=650, template="plotly_dark", uirevision=full_symbol, xaxis_rangeslider_visible=False)
                fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
                st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': True})
            else:
                st.error("查無數據")
        except Exception as e:
            st.error(f"連線錯誤: {e}")

# --- 頁籤 2: 市場動態推薦 (自動抓取市場領頭羊) ---
with tab2:
    st.header(f"🚀 {market} 動態領先指標")
    st.write("系統自動掃描目前市場權值股，並依即時強度排序：")

    # 根據目前的市場選擇，自動獲取一組動態代號
    current_tickers = get_market_tickers(market)

    if current_tickers:
        rec_data = []
        progress_bar = st.progress(0) # 進度條增加使用者體驗
        
        for idx, s in enumerate(current_tickers):
            fs = s
            if "台股" in market:
                suffix = ".TW" if "上市" in market else ".TWO"
                fs = f"{s}{suffix}"
            
            try:
                t = yf.Ticker(fs)
                h = t.history(period="10d") # 抓取稍微長一點確保 MA 計算正確
                if len(h) >= 5:
                    c_p = h['Close'].iloc[-1]
                    p_p = h['Close'].iloc[-2]
                    p_pct = ((c_p - p_p) / p_p) * 100
                    
                    # 計算短線強弱：站上 5MA 且今日上漲
                    ma5 = h['Close'].rolling(5).mean().iloc[-1]
                    vol_avg = h['Volume'].mean()
                    curr_vol = h['Volume'].iloc[-1]
                    
                    strength = "🔥 強勢" if (c_p > ma5 and p_pct > 0) else "☁️ 整理"
                    if curr_vol > vol_avg * 1.5: strength = "💎 爆量起飛"

                    rec_data.append({
                        "代號": s,
                        "最新價": round(c_p, 2),
                        "漲跌幅%": round(p_pct, 2),
                        "趨勢評級": strength,
                        "相對音量": round(curr_vol / vol_avg, 1)
                    })
            except:
                continue
            progress_bar.progress((idx + 1) / len(current_tickers))
        
        if rec_data:
            df_rec = pd.DataFrame(rec_data).sort_values(by="漲跌幅%", ascending=False)

            def apply_color(val):
                color = '#ef5350' if val > 0 else '#26a69a' if val < 0 else ''
                return f'color: {color}; font-weight: bold;'

            styled_df = df_rec.style.map(apply_color, subset=['漲跌幅%'])
            st.dataframe(styled_df, use_container_width=True, hide_index=True)
            st.success(f"已完成 {len(rec_data)} 檔權值股即時掃描。")
        else:
            st.error("掃描過程中發生錯誤，請稍後再試。")
    else:
        st.warning("目前該市場無可掃描的動態名單。")

st.divider()
st.caption("備註：動態推薦由標普 500 與 台灣 50 成份股組成，代表市場整體趨勢。")
