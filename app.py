"""
台股每日資料抓取 — Streamlit 網頁介面
執行方式：streamlit run app.py
"""
 
import io
import time
import datetime
import streamlit as st
import pandas as pd
import sys
from pathlib import Path
 
# 引入核心抓取函式
sys.path.insert(0, str(Path(__file__).parent))
from twse_daily_fetch import (
    fetch_stock_all, fetch_taiex, fetch_institutional, fetch_margin,
    fetch_tpex_stock_all, fetch_tpex_index, fetch_tpex_institutional, fetch_tpex_margin,
    compute_ta_for_stock, merge_stock_data, OUTPUT_DIR,
    is_trading_day, setup_logging,
)
 
# ─── 頁面設定 ────────────────────────────────────────────────────────────────
 
st.set_page_config(
    page_title="台股每日資料",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)
 
setup_logging()
 
# ─── 工具函式 ────────────────────────────────────────────────────────────────
 
def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    """DataFrame → UTF-8 BOM CSV bytes（Excel 可直接開啟）。"""
    buf = io.BytesIO()
    df.to_csv(buf, index=False, encoding="utf-8-sig")
    return buf.getvalue()
 
 
def show_table(df: pd.DataFrame, label: str, filename: str):
    """顯示資料表格 + 下載按鈕。"""
    if df is None or df.empty:
        st.warning(f"{label}：無資料（可能非交易日或尚未發布）")
        return
    st.caption(f"共 {len(df):,} 筆")
    st.dataframe(df, use_container_width=True, height=400)
    st.download_button(
        label=f"⬇ 下載 {label} CSV",
        data=df_to_csv_bytes(df),
        file_name=filename,
        mime="text/csv",
        key=f"dl_{filename}",
    )
 
 
# ─── 側邊欄 ──────────────────────────────────────────────────────────────────
 
with st.sidebar:
    st.title("📈 台股每日資料")
    st.divider()
 
    # 日期選擇
    today = datetime.date.today()
    selected_date = st.date_input(
        "選擇日期",
        value=today,
        min_value=datetime.date(2010, 1, 1),
        max_value=today,
        format="YYYY/MM/DD",
    )
    date_str = selected_date.strftime("%Y%m%d")
 
    if not is_trading_day(date_str):
        st.warning("⚠️ 所選日期為週末，可能無資料")
 
    st.divider()
 
    # 要抓的資料項目
    st.subheader("抓取項目")
    chk_twse_stock = st.checkbox("上市個股收盤",      value=True)
    chk_twse_index = st.checkbox("加權指數",          value=True)
    chk_twse_inst  = st.checkbox("上市三大法人",       value=True)
    chk_twse_marg  = st.checkbox("上市融資融券",       value=True)
    st.divider()
    chk_tpex_stock = st.checkbox("上櫃個股收盤",      value=True)
    chk_tpex_index = st.checkbox("櫃買指數",          value=True)
    chk_tpex_inst  = st.checkbox("上櫃三大法人",       value=True)
    chk_tpex_marg  = st.checkbox("上櫃融資融券",       value=True)
 
    st.divider()
    fetch_btn = st.button("🚀 開始抓取", use_container_width=True, type="primary")
 
    st.divider()
    st.subheader("技術指標")
    ta_stock = st.text_input("股票代號（需先抓取歷史）", placeholder="例：2330")
    ta_btn   = st.button("計算技術指標", use_container_width=True)
 
 
# ─── 主畫面 ──────────────────────────────────────────────────────────────────
 
st.header(f"台股每日資料  {selected_date.strftime('%Y/%m/%d')}")
 
# Session state 儲存抓到的 DataFrame
if "data" not in st.session_state:
    st.session_state.data = {}
 
# ── 抓取按鈕 ──────────────────────────────────────────────────────────────────
if fetch_btn:
    tasks = []
    if chk_twse_stock: tasks.append(("上市個股",   fetch_stock_all,         f"上市個股_{date_str}.csv"))
    if chk_twse_index: tasks.append(("加權指數",   fetch_taiex,             f"加權指數_{date_str}.csv"))
    if chk_twse_inst:  tasks.append(("上市三大法人", fetch_institutional,    f"上市三大法人_{date_str}.csv"))
    if chk_twse_marg:  tasks.append(("上市融資融券", fetch_margin,           f"上市融資融券_{date_str}.csv"))
    if chk_tpex_stock: tasks.append(("上櫃個股",   fetch_tpex_stock_all,    f"上櫃個股_{date_str}.csv"))
    if chk_tpex_index: tasks.append(("櫃買指數",   fetch_tpex_index,        f"櫃買指數_{date_str}.csv"))
    if chk_tpex_inst:  tasks.append(("上櫃三大法人", fetch_tpex_institutional, f"上櫃三大法人_{date_str}.csv"))
    if chk_tpex_marg:  tasks.append(("上櫃融資融券", fetch_tpex_margin,      f"上櫃融資融券_{date_str}.csv"))
 
    progress = st.progress(0, text="準備中…")
    status   = st.status("抓取中…", expanded=True)
 
    st.session_state.data = {}
    for i, (label, fn, fname) in enumerate(tasks):
        progress.progress((i) / len(tasks), text=f"正在抓取：{label}")
        status.write(f"⏳ {label}…")
        try:
            df = fn(date_str)
        except Exception as e:
            status.write(f"❌ {label} 發生錯誤：{e}")
            df = None
 
        if df is not None and not df.empty:
            # 同時存 CSV 到本地
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            df.to_csv(OUTPUT_DIR / fname, index=False, encoding="utf-8-sig")
            st.session_state.data[label] = (df, fname)
            status.write(f"✅ {label}：{len(df):,} 筆")
        else:
            status.write(f"⚠️ {label}：無資料")
 
        time.sleep(1.0)
 
    progress.progress(1.0, text="完成！")
    status.update(label="抓取完成", state="complete")
 
# ── 顯示結果 ─────────────────────────────────────────────────────────────────
if st.session_state.data:
    tabs = st.tabs(list(st.session_state.data.keys()))
    for tab, (label, (df, fname)) in zip(tabs, st.session_state.data.items()):
        with tab:
            show_table(df, label, fname)
else:
    st.info("請選擇日期與抓取項目，再按「🚀 開始抓取」。")
 
# ── 技術指標 ─────────────────────────────────────────────────────────────────
if ta_btn and ta_stock.strip():
    code = ta_stock.strip()
    with st.spinner(f"計算 {code} 技術指標中…"):
        try:
            compute_ta_for_stock(code)
            ta_path = OUTPUT_DIR / f"ta_{code}.csv"
            if ta_path.exists():
                df_ta = pd.read_csv(ta_path, encoding="utf-8-sig", dtype=str)
                st.subheader(f"📊 {code} 技術指標")
                st.dataframe(df_ta, use_container_width=True, height=400)
                st.download_button(
                    "⬇ 下載技術指標 CSV",
                    data=df_to_csv_bytes(df_ta),
                    file_name=f"ta_{code}.csv",
                    mime="text/csv",
                )
            else:
                st.warning(f"找不到 {code} 的歷史資料，請先用 --range 批次抓取後再試。")
        except Exception as e:
            st.error(f"技術指標計算失敗：{e}")
