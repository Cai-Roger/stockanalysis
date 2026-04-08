import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

# 1. 網頁基礎設定
st.set_page_config(page_title="專業級即時監控 & 選股", layout="wide")

# 定義熱門觀察名單 (你可以自行修改這份清單)
HOT_LIST = {
    "美股": ["AAPL", "NVDA", "TSLA", "MSFT", "GOOGL", "META", "AMZN"],
    "台股上市": ["2330", "2317", "2454", "2308", "2382", "3231", "1513"],
    "台股上櫃": ["8069", "6488", "3105", "3529", "8299", "6182"]
}

# 2. 側邊欄設定
with st.sidebar:
    st.title("⚙️ 控制面板")
    market = st.radio("市場選擇", ('美股 (US)', '台股上市 (TW)', '台股上櫃 (TWO)'))
    symbol = st.text_input("輸入股票代號 (僅限即時看盤)", value="")
    
    st.divider()
    refresh_rate = st.slider("更新頻率 (秒)", 1, 60, 10)
    auto_refresh = st.checkbox("開啟極速更新", value=False)
    
    if auto_refresh:
        st_autorefresh(interval=refresh_rate * 1000, key="global_refresh")

# 3. 設定頁籤
tab1, tab2 = st.tabs(["📈 即時看盤", "🚀 強勢推薦"])

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
            df = stock.history(period="2y", interval="1d")
            if not df.empty:
                # 均線計算
                df['MA5'] = df['Close'].rolling(5).mean()
                df['MA10'] = df['Close'].rolling(10).mean()
                df['MA20'] = df['Close'].rolling(20).mean()
                df['MA60'] = df['Close'].rolling(60).mean()
                df['Pct'] = df['Close'].pct_change() * 100
                
                curr_p = df['Close'].iloc[-1]
                prev_c = df['Close'].iloc[-2]
                chg = curr_p - prev_c
                pct = (chg / prev_c) * 100

                st.metric(f"{full_symbol}", f"{curr_p:.2f}", f"{chg:.2f} ({pct:.2f}%)")

                # 繪圖
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

                fig.update_layout(height=650, template="plotly_dark", uirevision=full_symbol, xaxis_rangeslider_visible=False)
                fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
                st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': True})
            else:
                st.error("查無數據")
        except Exception as e:
            st.error(f"連線錯誤: {e}")

# --- 頁籤 2: 股票推薦 (強勢股掃描) ---
with tab2:
    st.header("🔥 市場強勢股觀察名單")
    st.write("以下為系統掃描的熱門標的當日漲跌表現：")

    # 決定抓取哪一組清單
    target_market = market.split(' ')[0] # 取得 "美股", "台股上市", "台股上櫃"
    symbols_to_check = HOT_LIST.get(target_market, [])

    if symbols_to_check:
        rec_data = []
        with st.spinner('正在分析強勢股...'):
            for s in symbols_to_check:
                # 補後綴
                fs = s
                if target_market == "台股上市": fs = f"{s}.TW"
                elif target_market == "台股上櫃": fs = f"{s}.TWO"
                
                t = yf.Ticker(fs)
                h = t.history(period="5d")
                if len(h) >= 2:
                    c_p = h['Close'].iloc[-1]
                    p_p = h['Close'].iloc[-2]
                    p_pct = ((c_p - p_p) / p_p) * 100
                    
                    # 簡單判斷：若收盤價 > 5日均線 則標記為強勢
                    ma5 = h['Close'].rolling(5).mean().iloc[-1]
                    status = "📈 多頭" if c_p > ma5 else "📉 整理"
                    
                    rec_data.append({
                        "代號": s,
                        "最新價": round(c_p, 2),
                        "漲跌幅%": round(p_pct, 2),
                        "短線趨勢": status
                    })
        
        # 轉成 DataFrame 顯示
        res_df = pd.DataFrame(rec_data)
        # 按漲跌幅排序
        res_df = res_df.sort_values(by="漲跌幅%", ascending=False)
        
        # 顯示漂亮的表格
        st.dataframe(
            res_df, 
            column_config={
                "漲跌幅%": st.column_config.NumberColumn(format="%.2f%%"),
            },
            hide_index=True,
            use_container_width=True
        )
        
        st.success("💡 提示：建議關注「多頭」且「漲跌幅%」為正值的標的。")
    else:
        st.warning("目前無預設清單")

st.divider()
st.caption("警語：本程式僅供技術分析參考，不代表任何投資建議，投資人應獨立判斷並自負風險。")
