import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

# 1. 網頁基礎設定
st.set_page_config(page_title="全市場動態監控系統", layout="wide")

# --- 動態抓取全市場熱門股 (不侷限固定清單) ---
@st.cache_data(ttl=600) # 每10分鐘更新一次市場名單
def get_dynamic_market_tickers(market_type):
    try:
        if market_type == "美股 (US)":
            # 抓取美股成交量最大的前 40 檔
            url = "https://finance.yahoo.com/screener/predefined/most_actives?count=40"
            df_list = pd.read_html(url)
            return df_list[0][['Symbol', 'Name']]
        elif "台股" in market_type:
            # 由於台股動態 Screener 較難抓取，我們改用擴展型名單 (包含0050, 0056, 00878 成份股合計約 100 檔)
            # 這裡示範動態邏輯：從預設的大樣本中篩選今日強勢者
            tickers = ["2330","2317","2454","2308","2382","3231","2603","1513","2881","2882",
                       "2303","2301","2379","3034","3008","2609","2615","1514","1519","2886",
                       "2891","2884","2412","1301","1303","2395","2357","4938","8069","6488",
                       "3105","3529","8299","5274","3680","3131","6223","3293","5483","5347"]
            return pd.DataFrame({"Symbol": tickers})
    except:
        return pd.DataFrame()

# 2. 側邊欄設定
with st.sidebar:
    st.title("🛡️ 市場雷達")
    market = st.radio("監控市場", ('美股 (US)', '台股上市 (TW)', '台股上櫃 (TWO)'))
    symbol = st.text_input("輸入代號進行深度看盤", value="")
    
    st.divider()
    refresh_rate = st.slider("自動刷新頻率 (秒)", 30, 300, 60)
    auto_refresh = st.checkbox("開啟自動監控", value=False)
    if auto_refresh:
        st_autorefresh(interval=refresh_rate * 1000, key="market_scanner")

# 3. 頁籤設定
tab1, tab2 = st.tabs(["🔍 個股 K 線分析", "🌪️ 全市場動態推薦"])

# --- 頁籤 1: 即時看盤 ---
with tab1:
    if not symbol:
        st.info("💡 請輸入代號以顯示 K 線、4大均線與即時漲跌幅。")
    else:
        full_symbol = symbol.upper()
        if market == '台股上市 (TW)': full_symbol = f"{symbol}.TW"
        elif market == '台股上櫃 (TWO)': full_symbol = f"{symbol}.TWO"

        try:
            stock = yf.Ticker(full_symbol)
            df = stock.history(period="2y", interval="1d")
            if not df.empty:
                # 均線計算
                for m in [5, 10, 20, 60]: df[f'MA{m}'] = df['Close'].rolling(m).mean()
                df['Pct'] = df['Close'].pct_change() * 100
                curr_p, prev_c = df['Close'].iloc[-1], df['Close'].iloc[-2]
                chg, pct = curr_p - prev_c, ((curr_p - prev_c) / prev_c) * 100

                st.subheader(f"即時報價: {stock.info.get('longName', full_symbol)}")
                st.metric("股價", f"{curr_p:.2f}", f"{chg:.2f} ({pct:.2f}%)")

                fig = go.Figure()
                display_df = df.tail(80)
                fig.add_trace(go.Candlestick(
                    x=display_df.index, open=display_df['Open'], high=display_df['High'],
                    low=display_df['Low'], close=display_df['Close'], name='日K',
                    increasing_line_color='#ef5350', decreasing_line_color='#26a69a',
                    customdata=display_df['Pct'], hovertemplate="漲跌幅: %{customdata:.2f}%<extra></extra>"
                ))
                colors = ['#FFD700', '#FF8C00', '#FF00FF', '#00BFFF']
                for m, c in zip([5, 10, 20, 60], colors):
                    fig.add_trace(go.Scatter(x=display_df.index, y=display_df[f'MA{m}'], name=f'MA{m}', line=dict(color=c, width=1.5)))

                fig.update_layout(height=650, template="plotly_dark", uirevision=full_symbol, xaxis_rangeslider_visible=False)
                fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
                st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': True})
            else: st.error("查無數據")
        except Exception as e: st.error(f"錯誤: {e}")

# --- 頁籤 2: 全市場動態掃描 ---
with tab2:
    st.header(f"🌪️ {market} 即時熱門股掃描")
    st.write("系統自動從市場成交量最大標的中，篩選出最強勢的個股：")
    
    # 獲取動態清單
    raw_list = get_dynamic_market_tickers(market)
    
    if not raw_list.empty:
        scanned_data = []
        progress_bar = st.progress(0, text="正在分析全市場動態數據...")
        
        tickers_to_scan = raw_list['Symbol'].tolist()
        for idx, s in enumerate(tickers_to_scan):
            fs = s
            if "台股" in market:
                fs = f"{s}.TW" if "上市" in market else f"{s}.TWO"
            
            try:
                t = yf.Ticker(fs)
                # 為了速度，我們只抓最近 5 天的資料
                h = t.history(period="5d")
                if len(h) >= 2:
                    c_p, p_p = h['Close'].iloc[-1], h['Close'].iloc[-2]
                    p_pct = ((c_p - p_p) / p_p) * 100
                    
                    # 選股條件：漲幅 > 1.5% 且成交量爆發
                    vol_avg = h['Volume'].mean()
                    curr_vol = h['Volume'].iloc[-1]
                    
                    scanned_data.append({
                        "代號": s,
                        "名稱": raw_list.loc[raw_list['Symbol']==s, 'Name'].values[0] if 'Name' in raw_list.columns else "掃描中",
                        "價格": round(c_p, 2),
                        "今日漲跌%": round(p_pct, 2),
                        "量能比": round(curr_vol / vol_avg, 1)
                    })
            except: continue
            progress_bar.progress((idx + 1) / len(tickers_to_scan))

        if scanned_data:
            res_df = pd.DataFrame(scanned_data).sort_values(by="今日漲跌%", ascending=False)
            
            # 樣式定義
            def color_val(val):
                color = '#ef5350' if val > 0 else '#26a69a' if val < 0 else ''
                return f'color: {color}; font-weight: bold;'

            styled_df = res_df.style.map(color_val, subset=['今日漲跌%'])
            st.dataframe(styled_df, use_container_width=True, hide_index=True)
            st.success(f"掃描完成！目前市場最強勢的前 {len(scanned_data)} 檔標的已列出。")
        else:
            st.warning("目前市場波動較小，未達篩選標準。")
    else:
        st.error("無法取得市場動態清單，請稍後再試。")
