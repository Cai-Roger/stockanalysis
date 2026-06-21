"""
台灣股市（上市 + 上櫃）每日資料抓取 + Streamlit 網頁介面  v4.0
=======================================================
功能：
  1. 個股每日收盤資料（TWSE + TPEx）
  2. 大盤指數（加權 / 櫃買）
  3. 三大法人買賣超
  4. 融資融券餘額
  5. 即時報價 + 五檔 + 當日走勢
  6. 技術指標（MA/RSI/MACD/KD）
  7. 選股掃描（MACD+KD 糾結向上 / 創高後回測月線有撐）

執行方式：
  streamlit run app.py
"""

import sys
import io
import re
import time
import json
import logging
import threading
import requests
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta, date as date_cls
from concurrent.futures import ThreadPoolExecutor, as_completed


# ─── 設定區 ──────────────────────────────────────────────────────────────────

OUTPUT_DIR      = Path("stock_data")
LOG_FILE        = OUTPUT_DIR / "fetch.log"
REQUEST_DELAY   = 1.5
REQUEST_TIMEOUT = 30
MAX_RETRY       = 3
SCHEDULE_TIME   = "14:45"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

BASE_URL         = "https://www.twse.com.tw"
OPENAPI_URL      = "https://openapi.twse.com.tw/v1"
TPEX_BASE_URL    = "https://www.tpex.org.tw"
TPEX_OPENAPI_URL = "https://www.tpex.org.tw/openapi/v1"
REALTIME_URL     = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"

ENDPOINTS = {
    "stock_all":          f"{OPENAPI_URL}/exchangeReport/STOCK_DAY_ALL",
    "taiex_index":        f"{BASE_URL}/exchangeReport/MI_INDEX",
    "institutional":      f"{BASE_URL}/fund/T86",
    "margin":             f"{BASE_URL}/exchangeReport/MI_MARGN",
    "stock_day":          f"{BASE_URL}/exchangeReport/STOCK_DAY",
    "tpex_stock_all":     f"{TPEX_OPENAPI_URL}/tpex_mainboard_daily_close_quotes",
    "tpex_index":         f"{TPEX_OPENAPI_URL}/tpex_mainboard_index_daily_close_quotes",
    "tpex_institutional": f"{TPEX_BASE_URL}/web/stock/3insti/daily_trade/3itrade_hedge_result.php",
    "tpex_margin":        f"{TPEX_BASE_URL}/web/stock/margin_trading/margin_balance/margin_bal_result.php",
}

WEEKDAYS = {0, 1, 2, 3, 4}


# ─── 日誌設定 ────────────────────────────────────────────────────────────────

def setup_logging():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

logger = logging.getLogger(__name__)


# ─── 共用工具 ────────────────────────────────────────────────────────────────

def fetch_json(url, params=None, retry=MAX_RETRY):
    for attempt in range(1, retry + 1):
        try:
            resp = requests.get(url, params=params, headers=HEADERS,
                                timeout=REQUEST_TIMEOUT, stream=False)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return {"data": data, "stat": "OK"}
            if data.get("stat") == "OK":
                return data
            stat_msg = data.get("stat", "未知")
            if "沒有符合條件" in stat_msg or "很抱歉" in stat_msg:
                logger.warning("無資料：%s", stat_msg)
            else:
                logger.warning("無資料回應：%s", stat_msg)
            return None
        except requests.exceptions.ChunkedEncodingError:
            logger.warning("[傳輸錯誤] 第 %d 次重試…", attempt)
        except (requests.exceptions.HTTPError,
                requests.exceptions.ConnectionError,
                requests.exceptions.ReadTimeout) as e:
            logger.warning("[請求錯誤] %s（第 %d 次）", e, attempt)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("[解析錯誤] %s（第 %d 次）", e, attempt)
        if attempt < retry:
            time.sleep(3)
    return None


def fetch_json_tpex(url, params=None, retry=MAX_RETRY):
    if params is None:
        params = {}
    params.setdefault("_", int(time.time() * 1000))
    for attempt in range(1, retry + 1):
        try:
            resp = requests.get(url, params=params, headers=HEADERS,
                                timeout=REQUEST_TIMEOUT, stream=False)
            resp.raise_for_status()
            if not resp.text.strip():
                logger.warning("TPEx 回傳空內容")
                return None
            data = resp.json()
            if isinstance(data, list):
                return {"aaData": data, "fields": [], "stat": "OK"}
            if "aaData" in data:
                if not data["aaData"]:
                    return None
                data.setdefault("fields", [])
                data["stat"] = "OK"
                return data
            if "tables" in data and isinstance(data["tables"], list) and data["tables"]:
                table  = data["tables"][0]
                rows   = table.get("data",   table.get("aaData", []))
                fields = table.get("fields", table.get("field",  []))
                if not rows:
                    return None
                return {"aaData": rows, "fields": fields, "stat": "OK"}
            logger.warning("TPEx 未知格式：%s", str(data)[:80])
            return None
        except requests.exceptions.ChunkedEncodingError:
            logger.warning("[TPEx 傳輸錯誤] 第 %d 次重試…", attempt)
        except (requests.exceptions.HTTPError,
                requests.exceptions.ConnectionError,
                requests.exceptions.ReadTimeout) as e:
            logger.warning("[TPEx 請求錯誤] %s（第 %d 次）", e, attempt)
        except (json.JSONDecodeError, ValueError):
            logger.warning("[TPEx 解析錯誤]（第 %d 次）", attempt)
            return None
        if attempt < retry:
            time.sleep(3)
    return None


def save_csv(df, filename):
    df = fix_duplicate_columns(df)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / filename
    df.to_csv(path, index=False, encoding="utf-8-sig")
    logger.info("已存檔：%s  (%d 筆)", path, len(df))
    return path


def is_trading_day(date_str):
    dt = datetime.strptime(date_str, "%Y%m%d")
    return dt.weekday() in WEEKDAYS


def to_roc_date(date_str):
    dt = datetime.strptime(date_str, "%Y%m%d")
    return f"{dt.year - 1911}/{dt.month:02d}/{dt.day:02d}"


def safe_insert(df, pos, col, value):
    if col in df.columns:
        df[col] = value
    else:
        df.insert(pos, col, value)
    return df


def fix_duplicate_columns(df):
    seen, keep = set(), []
    for i, col in enumerate(df.columns):
        if col not in seen:
            seen.add(col)
            keep.append(i)
    return df.iloc[:, keep]


def clean_number(series):
    return (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("+", "", regex=False)
        .str.strip()
        .replace("--", np.nan)
        .replace("", np.nan)
        .pipe(pd.to_numeric, errors="coerce")
    )


# ─── 每日資料抓取（TWSE）────────────────────────────────────────────────────

def fetch_stock_all(date_str):
    logger.info("[1/4] 上市個股收盤  date=%s", date_str)
    today = datetime.today().strftime("%Y%m%d")
    if date_str == today:
        data = fetch_json(ENDPOINTS["stock_all"])
        if not data:
            return None
        rows = data.get("data", [])
        if not rows:
            return None
        df = pd.DataFrame(rows)
        rename_map = {
            "Code": "股票代號", "Name": "股票名稱",
            "TradeVolume": "成交量(股)", "TradeValue": "成交金額(元)",
            "OpeningPrice": "開盤價", "HighestPrice": "最高價",
            "LowestPrice": "最低價", "ClosingPrice": "收盤價",
            "Change": "漲跌", "Transaction": "成交筆數",
            "LastBestBidPrice": "最後買進價", "LastBestBidVolume": "最後買進量(張)",
            "LastBestAskPrice": "最後賣出價", "LastBestAskVolume": "最後賣出量(張)",
            "PriceEarningRatio": "本益比", "YieldRatio": "殖利率(%)",
            "BookToMarketRatio": "股價淨值比",
            "UpperLimitPrice": "漲停價", "LowerLimitPrice": "跌停價",
        }
        df.rename(columns=rename_map, inplace=True)
    else:
        data = fetch_json(f"{BASE_URL}/exchangeReport/MI_INDEX",
                          {"response": "json", "date": date_str, "type": "ALLBUT0999"})
        if not data:
            return None
        fields = data.get("fields9", data.get("fields", []))
        rows   = data.get("data9",   data.get("data",   []))
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=fields)
    df.insert(0, "日期", date_str)
    return df


def fetch_taiex(date_str):
    logger.info("[2/4] 加權指數  date=%s", date_str)
    for idx_type in ("IND", "MS", "ALLBUT0999"):
        params = {"response": "json", "date": date_str, "type": idx_type}
        data = fetch_json(ENDPOINTS["taiex_index"], params)
        if data:
            for suffix in ("", "0", "1", "2"):
                fields = data.get(f"fields{suffix}", [])
                rows   = data.get(f"data{suffix}",   [])
                if rows:
                    df = pd.DataFrame(rows, columns=fields if fields else None)
                    df.insert(0, "日期", date_str)
                    return df
        time.sleep(0.5)
    return None


def fetch_institutional(date_str):
    logger.info("[3/4] 三大法人  date=%s", date_str)
    data = fetch_json(ENDPOINTS["institutional"],
                      {"response": "json", "date": date_str, "selectType": "ALL"})
    if not data:
        return None
    df = pd.DataFrame(data.get("data", []), columns=data.get("fields", []))
    df.insert(0, "日期", date_str)
    return df


def fetch_margin(date_str):
    logger.info("[4/4] 融資融券  date=%s", date_str)
    data = fetch_json(ENDPOINTS["margin"],
                      {"response": "json", "date": date_str, "selectType": "ALL"})
    if not data:
        return None
    fields, rows = [], []
    for suffix in ("3", "4", ""):
        fields = data.get(f"fields{suffix}", [])
        rows   = data.get(f"data{suffix}",   [])
        if rows:
            break
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=fields if fields else None)
    df.insert(0, "日期", date_str)
    return df


# ─── 每日資料抓取（TPEx）────────────────────────────────────────────────────

def fetch_tpex_stock_all(date_str):
    logger.info("[TPEx 1/4] 上櫃個股收盤  date=%s", date_str)
    today = datetime.today().strftime("%Y%m%d")
    if date_str == today:
        data = fetch_json_tpex(ENDPOINTS["tpex_stock_all"])
        if not data:
            return None
        rows = data.get("aaData", [])
        if not rows:
            return None
        df = pd.DataFrame(rows)
        rename_map = {
            "SecuritiesCompanyCode": "股票代號", "CompanyName": "股票名稱",
            "Open": "開盤價", "High": "最高價", "Low": "最低價", "Close": "收盤價",
            "Change": "漲跌", "ChangePercent": "漲跌幅(%)",
            "Average": "均價", "TradeVolume": "成交量(股)", "TradingShares": "成交股數",
            "TradeValue": "成交金額(元)", "TransactionAmount": "成交金額(元)",
            "TransactionCount": "成交筆數", "TransactionNumber": "成交筆數",
            "LatestBidPrice": "最後買進價", "LatestBidVolume": "最後買進量(張)",
            "LatestAskPrice": "最後賣出價", "LatesAskPrice": "最後賣出價",
            "LatestAskVolume": "最後賣出量(張)", "Capitals": "市值(元)",
            "MarketCapitalization": "市值(元)", "IssuedShares": "發行股數",
            "NextReference": "次日參考價", "NextLimitUp": "次日漲停價",
            "NextLimitDown": "次日跌停價", "PERatio": "本益比",
            "DividendYield": "殖利率(%)", "PBRatio": "股價淨值比",
        }
        df.rename(columns=rename_map, inplace=True)
    else:
        roc_date = to_roc_date(date_str)
        url = (f"{TPEX_BASE_URL}/web/stock/aftertrading/otc_quotes_no1430/"
               "stk_wn1430_result.php")
        data = fetch_json_tpex(url, {"l": "zh-tw", "d": roc_date, "se": "EW"})
        if not data:
            return None
        rows = data.get("aaData", [])
        if not rows:
            return None
        cols = ["股票代號", "股票名稱", "收盤價", "漲跌", "開盤價",
                "最高價", "最低價", "成交量(股)", "成交金額", "成交筆數",
                "本益比", "殖利率(%)", "股價淨值比"]
        df = pd.DataFrame(rows, columns=cols[:len(rows[0])])
    safe_insert(df, 0, "日期", date_str)
    safe_insert(df, 1, "市場", "上櫃")
    return df


def fetch_tpex_index(date_str):
    logger.info("[TPEx 2/4] 櫃買指數  date=%s", date_str)
    roc_date = to_roc_date(date_str)
    url = f"{TPEX_BASE_URL}/web/stock/aftertrading/daily_trading_index/st41_result.php"
    data = fetch_json_tpex(url, {"l": "zh-tw", "d": roc_date})
    if not data:
        return None
    rows   = data.get("aaData", [])
    fields = data.get("fields", [])
    if not rows:
        return None
    if not fields:
        fields = ["指數名稱", "收盤指數", "漲跌", "漲跌幅(%)", "成交量(千股)", "成交金額(千元)"]
    n = len(rows[0]) if rows else len(fields)
    df = pd.DataFrame(rows, columns=fields[:n])
    safe_insert(df, 0, "日期", date_str)
    return df


def fetch_tpex_institutional(date_str):
    logger.info("[TPEx 3/4] 上櫃三大法人  date=%s", date_str)
    roc_date = to_roc_date(date_str)
    url = f"{TPEX_BASE_URL}/web/stock/3insti/daily_trade/3itrade_hedge_result.php"
    data = fetch_json_tpex(url, {"l": "zh-tw", "se": "EW", "t": "D", "d": roc_date})
    if not data:
        return None
    rows   = data.get("aaData", [])
    fields = data.get("fields", [])
    if not rows:
        return None
    if not fields:
        fields = ["股票代號", "股票名稱",
                  "外資買進", "外資賣出", "外資買賣超",
                  "投信買進", "投信賣出", "投信買賣超",
                  "自營商買進", "自營商賣出", "自營商買賣超", "三大法人買賣超"]
    n = len(rows[0]) if rows else len(fields)
    df = pd.DataFrame(rows, columns=fields[:n])
    safe_insert(df, 0, "日期", date_str)
    safe_insert(df, 1, "市場", "上櫃")
    return df


def fetch_tpex_margin(date_str):
    logger.info("[TPEx 4/4] 上櫃融資融券  date=%s", date_str)
    roc_date = to_roc_date(date_str)
    url = f"{TPEX_BASE_URL}/web/stock/margin_trading/margin_balance/margin_bal_result.php"
    data = fetch_json_tpex(url, {"l": "zh-tw", "d": roc_date})
    if not data:
        return None
    rows   = data.get("aaData", [])
    fields = data.get("fields", [])
    if not rows:
        return None
    if not fields:
        fields = ["股票代號", "股票名稱",
                  "融資買進", "融資賣出", "融資現金償還", "融資餘額", "融資限額",
                  "融券買進", "融券賣出", "融券現券償還", "融券餘額", "融券限額", "資券互抵"]
    n = len(rows[0]) if rows else len(fields)
    df = pd.DataFrame(rows, columns=fields[:n])
    safe_insert(df, 0, "日期", date_str)
    safe_insert(df, 1, "市場", "上櫃")
    return df


# ─── 全市場股票代號 ──────────────────────────────────────────────────────────

def fetch_all_stock_codes(include_twse=True, include_tpex=True, stock_type="一般股票"):
    """
    一次抓取全市場所有股票代號。
    stock_type:
      "一般股票" → 4 碼數字，排除 ETF（00xxxx）
      "含ETF"    → 4~6 碼數字（含 ETF、指數型基金）
      "全部"     → 不過濾
    回傳 list[str]，去重、保序。
    """
    result, seen = [], set()

    def _add(code):
        code = str(code).strip()
        if code in seen:
            return
        if stock_type == "一般股票":
            if not (code.isdigit() and len(code) == 4 and not code.startswith("00")):
                return
        elif stock_type == "含ETF":
            if not (code.isdigit() and 4 <= len(code) <= 6):
                return
        seen.add(code)
        result.append(code)

    if include_twse:
        try:
            data = fetch_json(ENDPOINTS["stock_all"])
            if data:
                for row in data.get("data", []):
                    if isinstance(row, dict):
                        _add(row.get("Code", ""))
        except Exception as e:
            logger.warning("取得上市代號失敗：%s", e)

    if include_tpex:
        try:
            data = fetch_json_tpex(ENDPOINTS["tpex_stock_all"])
            if data:
                for row in data.get("aaData", []):
                    if isinstance(row, dict):
                        _add(row.get("SecuritiesCompanyCode", ""))
        except Exception as e:
            logger.warning("取得上櫃代號失敗：%s", e)

    return result


# ─── 即時報價 ────────────────────────────────────────────────────────────────

def fetch_realtime_quote(codes):
    if not codes:
        return []
    ex_ch = "|".join(
        f"tse_{c.strip()}.tw|otc_{c.strip()}.tw"
        for c in codes if c.strip()
    )
    params = {"ex_ch": ex_ch, "json": "1", "delay": "0",
              "_": int(time.time() * 1000)}
    try:
        resp = requests.get(REALTIME_URL, params=params, headers=HEADERS,
                            timeout=10, stream=False)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("[即時報價] 失敗：%s", e)
        return []

    def _flt(item, key, default=None):
        val = item.get(key, "")
        if val in ("-", "--", "", None):
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    results_map = {}
    for item in data.get("msgArray", []):
        code = item.get("c", "").strip()
        if not code:
            continue
        z = _flt(item, "z")
        y = _flt(item, "y")
        if code in results_map and results_map[code]["最新價"] is not None and z is None:
            continue
        change     = round(z - y, 2) if z is not None and y else None
        change_pct = round((z - y) / y * 100, 2) if z is not None and y else None
        ex = item.get("ex", "tse")
        bid_ps = [p for p in item.get("b", "").split("_") if p not in ("", "-")]
        bid_qs = [q for q in item.get("g", "").split("_") if q not in ("", "-")]
        bids = []
        for p, q in zip(bid_ps[:5], bid_qs[:5]):
            try:
                bids.append({"委買價": float(p), "委買量(張)": int(q)})
            except ValueError:
                pass
        ask_ps = [p for p in item.get("a", "").split("_") if p not in ("", "-")]
        ask_qs = [q for q in item.get("f", "").split("_") if q not in ("", "-")]
        asks = []
        for p, q in zip(ask_ps[:5], ask_qs[:5]):
            try:
                asks.append({"委賣價": float(p), "委賣量(張)": int(q)})
            except ValueError:
                pass
        v_raw = _flt(item, "v", 0)
        results_map[code] = {
            "代號": code, "名稱": item.get("n", ""),
            "市場": "上市" if ex == "tse" else "上櫃",
            "最新價": z, "昨收": y, "漲跌": change, "漲跌幅(%)": change_pct,
            "開盤": _flt(item, "o"), "最高": _flt(item, "h"), "最低": _flt(item, "l"),
            "成交量(張)": int(v_raw) if v_raw else 0,
            "漲停": _flt(item, "u"), "跌停": _flt(item, "w"),
            "更新時間": item.get("t", ""),
            "_bids": bids, "_asks": asks,
        }
    return [results_map[c.strip()] for c in codes if c.strip() in results_map]


def fetch_intraday_chart(code, exchange="tse"):
    suffix = ".TW" if exchange == "tse" else ".TWO"
    url    = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}{suffix}"
    try:
        resp = requests.get(url, params={"interval": "1m", "range": "1d",
                                         "_": int(time.time() * 1000)},
                            headers=HEADERS, timeout=10, stream=False)
        resp.raise_for_status()
        data   = resp.json()
        result = data["chart"]["result"]
        if not result:
            return None
        r     = result[0]
        ts    = r.get("timestamp", [])
        quote = r["indicators"]["quote"][0]
        if not ts:
            return None
        df = pd.DataFrame({
            "時間":       [datetime.fromtimestamp(t).strftime("%H:%M") for t in ts],
            "開盤":       quote.get("open",   [None] * len(ts)),
            "最高":       quote.get("high",   [None] * len(ts)),
            "最低":       quote.get("low",    [None] * len(ts)),
            "收盤":       quote.get("close",  [None] * len(ts)),
            "成交量(張)": [int(v / 1000) if v else 0
                           for v in quote.get("volume", [0] * len(ts))],
        })
        return df.dropna(subset=["收盤"]).reset_index(drop=True)
    except Exception as e:
        logger.warning("[當日走勢] 失敗 %s%s：%s", code, suffix, e)
        return None


# ─── 技術指標 ────────────────────────────────────────────────────────────────

def calc_ma(series, window):
    return series.rolling(window=window, min_periods=1).mean().round(2)


def calc_rsi(series, period=14):
    delta    = series.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).round(2)


def calc_macd(series, fast=12, slow=26, signal=9):
    ema_fast  = series.ewm(span=fast,   adjust=False).mean()
    ema_slow  = series.ewm(span=slow,   adjust=False).mean()
    dif       = (ema_fast - ema_slow).round(4)
    macd_line = dif.ewm(span=signal, adjust=False).mean().round(4)
    osc       = (dif - macd_line).round(4)
    return dif, macd_line, osc


def calc_kd(high, low, close, period=9):
    lowest_low   = low.rolling(window=period, min_periods=1).min()
    highest_high = high.rolling(window=period, min_periods=1).max()
    denom = (highest_high - lowest_low).replace(0, np.nan)
    rsv   = ((close - lowest_low) / denom * 100).fillna(50)
    k     = rsv.ewm(com=2, adjust=False).mean().round(2)
    d     = k.ewm(com=2, adjust=False).mean().round(2)
    return k, d


def add_technical_indicators(df):
    col_map = {}
    for col in df.columns:
        if "收盤" in col:   col_map[col] = "收盤價"
        elif "最高" in col: col_map[col] = "最高價"
        elif "最低" in col: col_map[col] = "最低價"
    df = df.rename(columns=col_map)
    close = clean_number(df["收盤價"])
    high  = clean_number(df["最高價"])
    low   = clean_number(df["最低價"])
    df["MA5"]  = calc_ma(close, 5)
    df["MA10"] = calc_ma(close, 10)
    df["MA20"] = calc_ma(close, 20)
    df["RSI14"] = calc_rsi(close, 14)
    dif, macd, osc = calc_macd(close)
    df["MACD_DIF"]  = dif
    df["MACD_MACD"] = macd
    df["MACD_OSC"]  = osc
    k, d = calc_kd(high, low, close)
    df["KD_K"] = k
    df["KD_D"] = d
    return df


def compute_ta_for_stock(stock_no):
    merged_path = OUTPUT_DIR / f"merged_{stock_no}.csv"
    if not merged_path.exists():
        merge_stock_data(stock_no)
    if not merged_path.exists():
        logger.error("無法取得 %s 的歷史資料", stock_no)
        return
    df = pd.read_csv(merged_path, encoding="utf-8-sig")
    date_col = [c for c in df.columns if "日期" in c]
    if date_col:
        df = df.sort_values(date_col[0]).reset_index(drop=True)
    df = add_technical_indicators(df)
    save_csv(df, f"ta_{stock_no}.csv")


def merge_stock_data(stock_no):
    csv_files = sorted(
        list(OUTPUT_DIR.glob("上市個股_*.csv")) +
        list(OUTPUT_DIR.glob("上櫃個股_*.csv")) +
        list(OUTPUT_DIR.glob("stock_all_*.csv"))
    )
    if not csv_files:
        return None
    frames = []
    for f in csv_files:
        try:
            tmp = pd.read_csv(f, encoding="utf-8-sig", dtype=str)
            code_col = next((c for c in tmp.columns if "代號" in c or c == "Code"), None)
            if code_col is None:
                continue
            subset = tmp[tmp[code_col] == stock_no]
            if not subset.empty:
                frames.append(subset)
        except Exception as e:
            logger.warning("讀取 %s 失敗：%s", f, e)
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True).drop_duplicates()
    save_csv(df, f"merged_{stock_no}.csv")
    return df


# ─── 選股掃描 ─────────────────────────────────────────────────────────────────

def fetch_stock_history(code, months=4, req_delay=0.5):
    """
    抓取單支股票近 months 個月日 K 資料。
    自動嘗試 TWSE STOCK_DAY → TPEx stk_quote_result。
    req_delay：每次請求後的休眠秒數（平行掃描時可縮短）。
    回傳 (DataFrame, 股票名稱str)。DataFrame 含 日期/開盤/最高/最低/收盤/成交量。
    """
    frames     = []
    exchange   = None
    stock_name = ""
    today      = datetime.today()

    for i in range(months - 1, -1, -1):
        # 計算第 i 個月前的 1 日
        y = today.year
        m = today.month - i
        while m <= 0:
            m += 12
            y -= 1
        date_q = f"{y}{m:02d}01"

        # ── TWSE ────────────────────────────────────────────────────────────
        data = fetch_json(
            f"{BASE_URL}/exchangeReport/STOCK_DAY",
            {"response": "json", "date": date_q, "stockNo": code}
        )
        if data:
            fields = data.get("fields", [])
            rows   = data.get("data",   [])
            if rows:
                df = pd.DataFrame(rows, columns=fields)
                frames.append(df)
                exchange = exchange or "twse"
                # 從 title 解析股票名稱，例如 "113年01月 2330 台積電  各日成交資訊"
                if not stock_name:
                    title = data.get("title", "")
                    m = re.search(rf'{re.escape(code)}\s+(\S+)', title)
                    if m:
                        stock_name = m.group(1)
                time.sleep(req_delay)
                continue

        # ── TPEx ────────────────────────────────────────────────────────────
        roc = to_roc_date(date_q)
        data = fetch_json_tpex(
            f"{TPEX_BASE_URL}/web/stock/aftertrading/daily_close_quotes/"
            "stk_quote_result.php",
            {"l": "zh-tw", "d": roc, "s": code}
        )
        if data:
            rows   = data.get("aaData", [])
            fields = data.get("fields", []) or [
                "日期", "收盤價", "漲跌", "開盤價", "最高價", "最低價",
                "成交量(千股)", "成交金額(千元)", "成交筆數"
            ]
            # TPEx 名稱通常在 stkName 或 title
            if not stock_name:
                stock_name = (data.get("stkName") or data.get("stk_name") or
                              data.get("title", "")).strip()
            if rows:
                n  = min(len(rows[0]), len(fields))
                df = pd.DataFrame(rows, columns=fields[:n])
                frames.append(df)
                exchange = exchange or "tpex"
        time.sleep(req_delay)

    if not frames:
        return None, stock_name

    df = pd.concat(frames, ignore_index=True)

    # ── 日期欄解析 ──────────────────────────────────────────────────────────
    date_col = next((c for c in df.columns if "日期" in c), None)
    if not date_col:
        return None, stock_name

    def _parse(d):
        d = str(d).strip()
        if "/" in d:
            parts = d.split("/")
            if len(parts) == 3 and len(parts[0]) <= 3:
                return f"{int(parts[0]) + 1911}/{parts[1]}/{parts[2]}"
        return d

    df["日期"] = df[date_col].apply(_parse)
    df["日期"] = pd.to_datetime(df["日期"], format="%Y/%m/%d", errors="coerce")

    # ── 欄位統一 ────────────────────────────────────────────────────────────
    rename = {
        "開盤價": "開盤", "最高價": "最高", "最低價": "最低", "收盤價": "收盤",
        "成交股數": "成交量", "成交量(千股)": "成交量_千股",
    }
    df.rename(columns=rename, inplace=True)

    for col in ["開盤", "最高", "最低", "收盤"]:
        if col in df.columns:
            df[col] = clean_number(df[col])

    # 成交量統一為「股」
    if "成交量" in df.columns:
        df["成交量"] = clean_number(df["成交量"])
    elif "成交量_千股" in df.columns:
        df["成交量"] = clean_number(df["成交量_千股"]) * 1000

    df = (df.dropna(subset=["日期", "收盤"])
            .sort_values("日期")
            .drop_duplicates(subset=["日期"])
            .reset_index(drop=True))

    keep = [c for c in ["日期", "開盤", "最高", "最低", "收盤", "成交量"] if c in df.columns]
    return df[keep], stock_name


def check_cond_macd_kd(df):
    """
    條件 1：MACD + KD 糾結向上
      ① DIF > 0（在零軸上方）
      ② K > D（黃金交叉）
      ③ OSC 由負轉正（近 4 根內有 neg→pos 轉換）
      ④ K < 50 糾結後向上（近 5 日 K 曾低於 50 且 K 正在上升）
    """
    if len(df) < 26:
        return {"passed": False, "reason": "資料不足"}

    close = df["收盤"].astype(float)
    high  = df["最高"].astype(float) if "最高" in df.columns else close
    low   = df["最低"].astype(float) if "最低" in df.columns else close

    dif, _, osc = calc_macd(close)
    k, d = calc_kd(high, low, close)

    c1 = bool(dif.iloc[-1] > 0)
    c2 = bool(k.iloc[-1] > d.iloc[-1])
    # OSC 由負轉正：最近 4 根中有一次 neg→pos
    osc_v = osc.iloc[-4:].values
    c3 = any(osc_v[i] <= 0 and osc_v[i + 1] > 0 for i in range(len(osc_v) - 1))
    # K 在 50 以下糾結後向上
    k_recent = k.iloc[-5:].values
    c4 = bool(len(k_recent) >= 3 and k_recent.min() < 50 and k.iloc[-1] > k.iloc[-3])

    return {
        "passed":     c1 and c2 and c3 and c4,
        "DIF":        round(float(dif.iloc[-1]), 4),
        "OSC":        round(float(osc.iloc[-1]), 4),
        "K":          round(float(k.iloc[-1]), 2),
        "D":          round(float(d.iloc[-1]), 2),
        "①DIF>0":    c1,
        "②K>D":      c2,
        "③OSC轉正":  c3,
        "④K<50向上": c4,
    }


def check_cond_ma_support(df, min_vol_lot=1000):
    """
    條件 2：上升軌道站上月線（MA20）＋成交量篩選
      ① MA20 向上傾斜：今日 MA20 > 5 日前 MA20
      ② 收盤站上 MA20
      ③ 最新成交量 ≥ min_vol_lot 張（1張=1000股）
      三者同時成立才通過。
    """
    if len(df) < 26:
        return {"passed": False, "reason": "資料不足"}

    close    = df["收盤"].astype(float)
    ma20     = calc_ma(close, 20)

    cur_c    = float(close.iloc[-1])
    cur_m20  = float(ma20.iloc[-1])
    prev_m20 = float(ma20.iloc[-6])   # 5 個交易日前的 MA20
    dist20   = (cur_c - cur_m20) / cur_m20

    rising   = cur_m20 > prev_m20     # ① MA20 向上傾斜
    above    = cur_c   > cur_m20      # ② 收盤站上 MA20

    # ③ 成交量（資料以「股」儲存，1張=1000股）
    if "成交量" in df.columns:
        cur_vol_shares = float(df["成交量"].iloc[-1])
    else:
        cur_vol_shares = 0.0
    cur_vol_lot  = cur_vol_shares / 1000
    enough_vol   = cur_vol_lot >= min_vol_lot

    return {
        "passed":      rising and above and enough_vol,
        "MA20":        round(cur_m20, 2),
        "距MA20(%)":   round(dist20 * 100, 2),
        "成交量(張)":  int(cur_vol_lot),
        "①MA20上升":  rising,
        "②站MA20":    above,
        "③量≥門檻":   enough_vol,
    }


def scan_stock(code, use_cond1=True, use_cond2=True,
               months=4, n_days=20, tol=0.03, req_delay=0.5, min_vol_lot=1000):
    """掃描單一股票，回傳結果 dict（無論是否符合）。"""
    df, stock_name = fetch_stock_history(code, months=months, req_delay=req_delay)
    if df is None or len(df) < 20:
        return {"代號": code, "名稱": stock_name, "狀態": "❓ 無資料", "整體符合": "─"}

    cur_close = float(df["收盤"].iloc[-1])
    cur_date  = df["日期"].iloc[-1]
    cur_date  = cur_date.strftime("%Y/%m/%d") if hasattr(cur_date, "strftime") else str(cur_date)

    result = {
        "代號":     code,
        "名稱":     stock_name,
        "最新收盤": cur_close,
        "資料日期": cur_date,
        "狀態":     "✅ 有資料",
    }

    cond1_pass = True
    cond2_pass = True

    if use_cond1:
        r1 = check_cond_macd_kd(df)
        result.update({
            "MACD+KD": "✅" if r1.get("passed") else "❌",
            "①DIF>0":    "✅" if r1.get("①DIF>0")    else "❌",
            "②K>D":      "✅" if r1.get("②K>D")      else "❌",
            "③OSC轉正":  "✅" if r1.get("③OSC轉正")  else "❌",
            "④K<50向上": "✅" if r1.get("④K<50向上") else "❌",
            "DIF值":  r1.get("DIF", "─"),
            "OSC值":  r1.get("OSC", "─"),
            "K值":    r1.get("K",   "─"),
            "D值":    r1.get("D",   "─"),
        })
        cond1_pass = r1.get("passed", False)

    if use_cond2:
        r2 = check_cond_ma_support(df, min_vol_lot=min_vol_lot)
        result.update({
            "上升軌道站月線": "✅" if r2.get("passed")    else "❌",
            "①MA20上升":     "✅" if r2.get("①MA20上升") else "❌",
            "②站MA20":       "✅" if r2.get("②站MA20")   else "❌",
            "③量≥門檻":      "✅" if r2.get("③量≥門檻")  else "❌",
            "MA20值":         r2.get("MA20",       "─"),
            "距MA20(%)":      r2.get("距MA20(%)",  "─"),
            "成交量(張)":     r2.get("成交量(張)", "─"),
        })
        cond2_pass = r2.get("passed", False)

    both = (cond1_pass or not use_cond1) and (cond2_pass or not use_cond2)
    result["整體符合"] = "✅ 符合" if both else "❌ 不符"
    return result


# ─── Streamlit 介面 ──────────────────────────────────────────────────────────

import streamlit as st

st.set_page_config(
    page_title="台股看盤系統",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

try:
    setup_logging()
except Exception:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)s  %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


# ─── CSS 注入 ────────────────────────────────────────────────────────────────

def inject_css():
    st.markdown("""
<style>
.main .block-container { padding-top: 0.6rem; padding-bottom: 1rem; }
.app-header {
    display:flex; align-items:center; gap:12px;
    padding:14px 20px; margin-bottom:12px;
    background:linear-gradient(135deg,#1a1a2e 0%,#16213e 100%);
    border-radius:14px; border-left:4px solid #e84d4d;
}
.app-header h1 { margin:0; font-size:1.5rem !important;
    font-weight:700 !important; color:#f0f0f0 !important; }
.app-header .subtitle { font-size:.8rem; color:#888; margin-top:2px; }
.stock-card {
    background:#1e1e2e; border:1px solid #2a2a3e; border-radius:14px;
    padding:16px 20px; margin-bottom:8px;
    transition:border-color .2s,transform .15s;
}
.stock-card:hover { border-color:#444; transform:translateY(-1px); }
.sc-code { font-size:1rem; font-weight:700; color:#ddd; }
.sc-mkt  { font-size:.7rem; color:#666; background:#2a2a3e;
            border-radius:4px; padding:2px 6px; margin-left:6px; }
.sc-name  { font-size:.78rem; color:#888; margin-top:2px; }
.sc-price { font-size:2rem; font-weight:800; margin-top:8px; line-height:1; }
.sc-change{ font-size:.88rem; margin-top:4px; }
.sc-vol   { font-size:.72rem; color:#555; margin-top:8px; }
.up   { color:#ff4b4b !important; }
.down { color:#26c95a !important; }
.flat { color:#888    !important; }
.limit-up   { color:#ff1744 !important; font-weight:700; }
.limit-down { color:#00e676 !important; font-weight:700; }
.rt-table { width:100%; border-collapse:collapse; font-size:.88rem; margin-top:4px; }
.rt-table thead tr { background:#1a1a2e; color:#aaa; border-bottom:2px solid #2a2a3e; }
.rt-table th { padding:9px 12px; text-align:right; font-weight:500; white-space:nowrap; }
.rt-table th:nth-child(1),.rt-table th:nth-child(2) { text-align:left; }
.rt-table td { padding:10px 12px; text-align:right; border-bottom:1px solid #1e1e2e; }
.rt-table td:nth-child(1),.rt-table td:nth-child(2) { text-align:left; }
.rt-table tbody tr:hover { background:rgba(255,255,255,.04); }
.rt-table .code-cell { font-weight:700; font-size:.95rem; }
.rt-table .price-cell { font-size:1.05rem; font-weight:700; }
.live-dot {
    display:inline-block; width:8px; height:8px;
    background:#26c95a; border-radius:50%;
    animation:pulse-green 1.6s infinite; margin-right:6px; vertical-align:middle;
}
.idle-dot {
    display:inline-block; width:8px; height:8px;
    background:#555; border-radius:50%; margin-right:6px; vertical-align:middle;
}
@keyframes pulse-green {
    0%  { box-shadow:0 0 0 0 rgba(38,201,90,.7); }
    70% { box-shadow:0 0 0 8px rgba(38,201,90,0); }
    100%{ box-shadow:0 0 0 0 rgba(38,201,90,0); }
}
.orderbook { width:100%; border-collapse:collapse; font-size:.85rem; }
.orderbook th { padding:6px 10px; text-align:center;
    background:#1a1a2e; color:#aaa; font-weight:500; border-bottom:1px solid #2a2a3e; }
.orderbook td { padding:7px 10px; text-align:right; border-bottom:1px solid #1a1a2e; }
.orderbook td:first-child { text-align:left; }
.bid-price { color:#ff4b4b !important; font-weight:600; }
.ask-price { color:#26c95a !important; font-weight:600; }
.mkt-status { display:inline-flex; align-items:center; gap:6px;
    padding:4px 10px; border-radius:20px; font-size:.78rem; font-weight:600; margin-bottom:4px; }
.mkt-open   { background:rgba(38,201,90,.15); color:#26c95a; }
.mkt-closed { background:rgba(136,136,136,.15); color:#888; }
/* 掃描結果表格 */
.scan-table { width:100%; border-collapse:collapse; font-size:.86rem; }
.scan-table thead tr { background:#1a1a2e; color:#aaa; border-bottom:2px solid #2a2a3e; }
.scan-table th { padding:8px 10px; text-align:center; font-weight:500; white-space:nowrap; }
.scan-table td { padding:8px 10px; text-align:center; border-bottom:1px solid #1e1e2e; }
.scan-table td:first-child { text-align:left; font-weight:700; }
.scan-table tbody tr:hover { background:rgba(255,255,255,.04); }
.match-yes { color:#ff4b4b; font-weight:700; font-size:1rem; }
.match-no  { color:#444; }
.sub-yes   { color:#ff4b4b; }
.sub-no    { color:#444; }
</style>
""", unsafe_allow_html=True)


# ─── 渲染工具 ─────────────────────────────────────────────────────────────────

def _cls(chg):
    if chg is None: return "flat"
    if chg > 0:     return "up"
    if chg < 0:     return "down"
    return "flat"


def render_stock_cards(quotes):
    n    = min(len(quotes), 8)
    ncol = min(n, 4)
    cols = st.columns(ncol)
    for i, q in enumerate(quotes[:n]):
        z, chg, chgp = q["最新價"], q["漲跌"], q["漲跌幅(%)"]
        css   = _cls(chg)
        arrow = "▲" if chg and chg > 0 else ("▼" if chg and chg < 0 else "─")
        z_s   = f"{z:.2f}"                    if z    is not None else "─"
        c_s   = f"{arrow} {abs(chg):.2f}"     if chg  is not None else "─"
        p_s   = f"({chgp:+.2f}%)"             if chgp is not None else ""
        with cols[i % ncol]:
            st.markdown(f"""
<div class="stock-card">
  <div><span class="sc-code">{q['代號']}</span><span class="sc-mkt">{q['市場']}</span></div>
  <div class="sc-name">{q['名稱']}</div>
  <div class="sc-price {css}">{z_s}</div>
  <div class="sc-change {css}">{c_s} {p_s}</div>
  <div class="sc-vol">成交 {q['成交量(張)']:,} 張</div>
</div>""", unsafe_allow_html=True)


def render_quote_table(quotes):
    def fmt(v, d=2): return f"{v:.{d}f}" if v is not None else "─"
    thead = "".join(f"<th>{h}</th>" for h in
                    ["代號","名稱","市場","最新價","漲跌","漲跌幅","開盤","最高","最低","成交量(張)","漲停","跌停"])
    tbody = ""
    for q in quotes:
        z, chg, chgp = q["最新價"], q["漲跌"], q["漲跌幅(%)"]
        css   = _cls(chg)
        arrow = "▲" if chg and chg > 0 else ("▼" if chg and chg < 0 else "─")
        chg_s = f"{arrow} {abs(chg):.2f}" if chg  is not None else "─"
        pct_s = f"{chgp:+.2f}%"           if chgp is not None else "─"
        tbody += f"""<tr>
  <td class="code-cell">{q['代號']}</td><td>{q['名稱']}</td>
  <td style="color:#888;font-size:.8rem">{q['市場']}</td>
  <td class="price-cell {css}">{fmt(z)}</td>
  <td class="{css}">{chg_s}</td><td class="{css}">{pct_s}</td>
  <td>{fmt(q['開盤'])}</td><td class="up">{fmt(q['最高'])}</td>
  <td class="down">{fmt(q['最低'])}</td>
  <td style="color:#aaa">{q['成交量(張)']:,}</td>
  <td class="limit-up">{fmt(q['漲停'])}</td>
  <td class="limit-down">{fmt(q['跌停'])}</td>
</tr>"""
    return f"<table class='rt-table'><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table>"


def render_orderbook(bids, asks):
    rows = max(len(bids), len(asks))
    if rows == 0:
        return "<p style='color:#666;font-size:.85rem'>暫無五檔資料</p>"
    def pad(lst, n): return lst + [{}] * (n - len(lst))
    html = """<table class="orderbook"><thead><tr>
<th>委買量(張)</th><th>委買價</th><th>委賣價</th><th>委賣量(張)</th>
</tr></thead><tbody>"""
    for b, a in zip(pad(bids, rows), pad(asks, rows)):
        bp = f"<span class='bid-price'>{b['委買價']:.2f}</span>" if b else "─"
        bq = str(b.get("委買量(張)", "─")) if b else "─"
        ap = f"<span class='ask-price'>{a['委賣價']:.2f}</span>" if a else "─"
        aq = str(a.get("委賣量(張)", "─")) if a else "─"
        html += f"<tr><td>{bq}</td><td>{bp}</td><td>{ap}</td><td>{aq}</td></tr>"
    return html + "</tbody></table>"


def render_scan_table(results, use_cond1, use_cond2):
    """生成掃描結果 HTML 表格，符合條件的格子標紅。"""
    def _td(val, is_sub=False):
        if val == "✅":
            cls = "sub-yes" if is_sub else "match-yes"
            return f"<td class='{cls}'>✅</td>"
        if val == "❌":
            return f"<td class='sub-no'>❌</td>"
        return f"<td>{val}</td>"

    # 動態表頭
    heads = ["代號", "名稱", "最新收盤", "資料日期"]
    if use_cond1:
        heads += ["MACD+KD", "①DIF>0", "②K>D", "③OSC轉正", "④K<50向上",
                  "DIF值", "OSC值", "K值", "D值"]
    if use_cond2:
        heads += ["上升軌道站月線", "①MA20上升", "②站MA20", "③量≥門檻",
                  "MA20值", "距MA20(%)", "成交量(張)"]
    heads += ["整體符合"]

    thead = "".join(f"<th>{h}</th>" for h in heads)
    tbody = ""
    for r in results:
        row = f"<td style='font-weight:700'>{r.get('代號','─')}</td>"
        row += f"<td style='color:#ccc'>{r.get('名稱','')}</td>"
        row += f"<td>{r.get('最新收盤','─')}</td>"
        row += f"<td style='font-size:.78rem;color:#888'>{r.get('資料日期','─')}</td>"
        if use_cond1:
            row += _td(r.get("MACD+KD", "─"))
            for k in ["①DIF>0","②K>D","③OSC轉正","④K<50向上"]:
                row += _td(r.get(k, "─"), is_sub=True)
            for k in ["DIF值","OSC值","K值","D值"]:
                row += f"<td style='color:#aaa;font-size:.82rem'>{r.get(k,'─')}</td>"
        if use_cond2:
            row += _td(r.get("上升軌道站月線", "─"))
            for k in ["①MA20上升", "②站MA20", "③量≥門檻"]:
                row += _td(r.get(k, "─"), is_sub=True)
            for k in ["MA20值", "距MA20(%)", "成交量(張)"]:
                row += f"<td style='color:#aaa;font-size:.82rem'>{r.get(k,'─')}</td>"
        # 整體符合
        match = r.get("整體符合", "─")
        if match == "✅ 符合":
            row += "<td class='match-yes'>✅ 符合</td>"
        elif match == "❌ 不符":
            row += "<td class='sub-no'>❌ 不符</td>"
        else:
            row += f"<td>{match}</td>"
        tbody += f"<tr>{row}</tr>"

    return f"""
<div style='overflow-x:auto'>
<table class='scan-table'>
  <thead><tr>{thead}</tr></thead>
  <tbody>{tbody}</tbody>
</table>
</div>"""


def df_to_csv_bytes(df):
    buf = io.BytesIO()
    df.to_csv(buf, index=False, encoding="utf-8-sig")
    return buf.getvalue()


def dedup_columns(df):
    seen, new_cols = {}, []
    for col in df.columns:
        if col in seen:
            seen[col] += 1
            new_cols.append(f"{col}_{seen[col]}")
        else:
            seen[col] = 1
            new_cols.append(col)
    df = df.copy()
    df.columns = new_cols
    return df


def show_table(df, label, filename):
    if df is None or df.empty:
        st.warning(f"{label}：無資料（可能非交易日或尚未發布）")
        return
    df = dedup_columns(df)
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
    inject_css()
    st.markdown("## 📈 台股看盤")
    _now = datetime.now()
    _trade = (_now.weekday() < 5
              and (9, 0) <= (_now.hour, _now.minute) <= (13, 30))
    if _trade:
        st.markdown('<span class="mkt-status mkt-open">● 交易中</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="mkt-status mkt-closed">● 已收盤</span>', unsafe_allow_html=True)
    st.divider()

    st.markdown("**📅 每日資料抓取**")
    today = date_cls.today()
    selected_date = st.date_input(
        "日期", value=today,
        min_value=date_cls(2010, 1, 1), max_value=today,
        format="YYYY/MM/DD", label_visibility="collapsed",
    )
    date_str = selected_date.strftime("%Y%m%d")
    if not is_trading_day(date_str):
        st.warning("⚠️ 週末 / 假日，可能無資料")

    with st.expander("🏦 上市（TWSE）", expanded=True):
        chk_twse_stock = st.checkbox("個股收盤", value=True, key="c1")
        chk_twse_index = st.checkbox("加權指數", value=True, key="c2")
        chk_twse_inst  = st.checkbox("三大法人", value=True, key="c3")
        chk_twse_marg  = st.checkbox("融資融券", value=True, key="c4")

    with st.expander("🏪 上櫃（TPEx）", expanded=True):
        chk_tpex_stock = st.checkbox("個股收盤", value=True, key="c5")
        chk_tpex_index = st.checkbox("櫃買指數", value=True, key="c6")
        chk_tpex_inst  = st.checkbox("三大法人", value=True, key="c7")
        chk_tpex_marg  = st.checkbox("融資融券", value=True, key="c8")

    fetch_btn = st.button("🚀 開始抓取", use_container_width=True, type="primary")
    st.divider()

    st.markdown("**📊 技術指標**")
    ta_stock = st.text_input("股票代號", placeholder="例：2330", label_visibility="collapsed")
    ta_btn   = st.button("計算 MA / RSI / MACD / KD", use_container_width=True)


# ─── 主畫面 ──────────────────────────────────────────────────────────────────

st.markdown("""
<div class="app-header">
  <div>
    <h1>台灣股市看盤系統</h1>
    <div class="subtitle">上市 TWSE + 上櫃 TPEx　｜　每日收盤 + 即時報價 + 選股掃描</div>
  </div>
</div>
""", unsafe_allow_html=True)

tab_daily, tab_rt, tab_scan = st.tabs(["📊 每日資料抓取", "📡 即時股價", "🔍 選股掃描"])


# ══════════════════════════════════════════════════════════════════════════════
# Tab 1：每日資料抓取
# ══════════════════════════════════════════════════════════════════════════════
with tab_daily:
    st.subheader(f"每日資料  {selected_date.strftime('%Y/%m/%d')}")

    if "data" not in st.session_state:
        st.session_state.data = {}

    if fetch_btn:
        tasks = []
        if chk_twse_stock: tasks.append(("上市個股",    fetch_stock_all,          f"上市個股_{date_str}.csv"))
        if chk_twse_index: tasks.append(("加權指數",    fetch_taiex,              f"加權指數_{date_str}.csv"))
        if chk_twse_inst:  tasks.append(("上市三大法人", fetch_institutional,      f"上市三大法人_{date_str}.csv"))
        if chk_twse_marg:  tasks.append(("上市融資融券", fetch_margin,             f"上市融資融券_{date_str}.csv"))
        if chk_tpex_stock: tasks.append(("上櫃個股",    fetch_tpex_stock_all,     f"上櫃個股_{date_str}.csv"))
        if chk_tpex_index: tasks.append(("櫃買指數",    fetch_tpex_index,         f"櫃買指數_{date_str}.csv"))
        if chk_tpex_inst:  tasks.append(("上櫃三大法人", fetch_tpex_institutional, f"上櫃三大法人_{date_str}.csv"))
        if chk_tpex_marg:  tasks.append(("上櫃融資融券", fetch_tpex_margin,        f"上櫃融資融券_{date_str}.csv"))

        progress = st.progress(0, text="準備中…")
        status   = st.status("抓取中…", expanded=True)
        st.session_state.data = {}

        for i, (label, fn, fname) in enumerate(tasks):
            progress.progress(i / len(tasks), text=f"正在抓取：{label}")
            status.write(f"⏳ {label}…")
            try:
                df = fn(date_str)
            except Exception as e:
                status.write(f"❌ {label} 發生錯誤：{e}")
                df = None
            if df is not None and not df.empty:
                df = fix_duplicate_columns(df)
                try:
                    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                    df.to_csv(OUTPUT_DIR / fname, index=False, encoding="utf-8-sig")
                except Exception:
                    pass
                st.session_state.data[label] = (df, fname)
                status.write(f"✅ {label}：{len(df):,} 筆")
            else:
                status.write(f"⚠️ {label}：無資料")
            time.sleep(1.0)

        progress.progress(1.0, text="完成！")
        status.update(label="抓取完成", state="complete")

    if st.session_state.data:
        data_tabs = st.tabs(list(st.session_state.data.keys()))
        for dtab, (label, (df, fname)) in zip(data_tabs, st.session_state.data.items()):
            with dtab:
                show_table(df, label, fname)
    else:
        st.info("請選擇日期與抓取項目，再按「🚀 開始抓取」。")

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
                    st.download_button("⬇ 下載技術指標 CSV",
                                       data=df_to_csv_bytes(df_ta),
                                       file_name=f"ta_{code}.csv",
                                       mime="text/csv")
                else:
                    st.warning(f"找不到 {code} 的歷史資料。")
            except Exception as e:
                st.error(f"技術指標計算失敗：{e}")


# ══════════════════════════════════════════════════════════════════════════════
# Tab 2：即時股價
# ══════════════════════════════════════════════════════════════════════════════
with tab_rt:
    st.subheader("📡 即時股價監看")
    st.caption("資料來源：證交所 MIS API（延遲約 20 秒）| 走勢圖：Yahoo Finance")

    col_inp, col_ctrl = st.columns([3, 2])
    with col_inp:
        rt_input = st.text_input(
            "股票代號（逗號分隔）",
            value=st.session_state.get("rt_input_val", "2330,2317,0050"),
            placeholder="例：2330,2317,0050,3008",
            key="rt_input_box",
        )
    with col_ctrl:
        ca, cb = st.columns(2)
        with ca:
            rt_auto = st.toggle("自動更新", value=False, key="rt_auto")
        with cb:
            rt_sec = st.selectbox("間隔(秒)", [5, 10, 30, 60], index=1, key="rt_sec")

    btn1, btn2, _ = st.columns([1, 1, 5])
    with btn1:
        rt_query = st.button("🔍 查詢", type="primary", use_container_width=True, key="rt_query")
    with btn2:
        rt_stop = st.button("⏹ 停止", use_container_width=True, key="rt_stop")

    if "rt_running"   not in st.session_state: st.session_state.rt_running   = False
    if "rt_quotes"    not in st.session_state: st.session_state.rt_quotes    = []
    if "rt_history"   not in st.session_state: st.session_state.rt_history   = {}
    if "rt_input_val" not in st.session_state: st.session_state.rt_input_val = "2330,2317,0050"

    if rt_query:
        st.session_state.rt_running   = rt_auto
        st.session_state.rt_history   = {}
        st.session_state.rt_input_val = rt_input
    if rt_stop:
        st.session_state.rt_running = False

    rt_codes  = [c.strip() for c in rt_input.replace("，", ",").split(",") if c.strip()]
    do_fetch  = rt_query or st.session_state.rt_running
    if rt_codes and do_fetch:
        with st.spinner("抓取即時報價…"):
            fresh = fetch_realtime_quote(rt_codes)
        if fresh:
            st.session_state.rt_quotes = fresh
            now_ts = datetime.now().strftime("%H:%M:%S")
            for q in fresh:
                c = q["代號"]
                st.session_state.rt_history.setdefault(c, [])
                if q["最新價"] is not None:
                    st.session_state.rt_history[c].append({"時間": now_ts, "價格": q["最新價"]})

    quotes = st.session_state.rt_quotes
    if quotes:
        last_t  = quotes[0].get("更新時間", "")
        running = st.session_state.rt_running
        dot     = '<span class="live-dot"></span>' if running else '<span class="idle-dot"></span>'
        mode    = f"自動更新中（每 {rt_sec} 秒）" if running else "手動模式"
        st.markdown(f'{dot}<span style="color:#888;font-size:.82rem">最後更新：{last_t}　{mode}</span>',
                    unsafe_allow_html=True)

        render_stock_cards(quotes)

        with st.expander("📋 完整報價明細", expanded=True):
            st.markdown(render_quote_table(quotes), unsafe_allow_html=True)

        st.divider()
        opt_list  = [f"{q['代號']}  {q['名稱']}" for q in quotes]
        sel_label = st.selectbox("選擇股票查看詳細資訊", opt_list, key="rt_sel")
        sel_idx   = opt_list.index(sel_label)
        sel_q     = quotes[sel_idx]
        sel_code  = sel_q["代號"]
        sel_ex    = "tse" if sel_q["市場"] == "上市" else "otc"

        col_ob, col_chart = st.columns([1, 2])
        with col_ob:
            st.markdown("**📒 五檔委買 / 委賣**")
            st.markdown(render_orderbook(sel_q.get("_bids", []), sel_q.get("_asks", [])),
                        unsafe_allow_html=True)
        with col_chart:
            st.markdown(f"**📈 {sel_code} 當日走勢**")
            history = st.session_state.rt_history.get(sel_code, [])
            if len(history) >= 2:
                st.line_chart(pd.DataFrame(history).set_index("時間"),
                              use_container_width=True, height=210)
            else:
                with st.spinner(f"載入 {sel_code} 分鐘走勢…"):
                    df_intra = fetch_intraday_chart(sel_code, sel_ex)
                if df_intra is not None and not df_intra.empty:
                    st.line_chart(df_intra.set_index("時間")[["收盤"]],
                                  use_container_width=True, height=210)
                    with st.expander("分鐘 K 線數據"):
                        st.dataframe(df_intra, use_container_width=True,
                                     hide_index=True, height=200)
                else:
                    st.caption("走勢資料暫時無法取得。開啟自動更新後將逐步累積即時走勢。")
    elif rt_codes:
        st.info("按「🔍 查詢」取得報價，或開啟「自動更新」持續監看。")
    else:
        st.info("請輸入股票代號，例如：2330,2317,0050")

    if st.session_state.rt_running:
        time.sleep(rt_sec)
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# Tab 3：選股掃描
# ══════════════════════════════════════════════════════════════════════════════
with tab_scan:
    st.subheader("🔍 技術面選股掃描")
    st.caption("支援自訂清單或一鍵掃描全市場上市 / 上櫃，多執行緒平行抓取")

    # ── Session state 初始化 ──────────────────────────────────────────────────
    for _k, _v in [("scan_running", False), ("scan_results", []),
                   ("scan_codes", ""), ("scan_mode", "自訂清單"),
                   ("scan_fetched_codes", [])]:
        if _k not in st.session_state:
            st.session_state[_k] = _v

    # ── 掃描範圍 ──────────────────────────────────────────────────────────────
    st.markdown("#### 掃描範圍")
    # 台灣前50成分股（台灣50 ETF 0050 成分，約略）
    TW50_CODES = (
        "2330,2317,2454,2382,2308,3711,2303,3034,2357,2379,"
        "2395,2881,2882,2886,2891,2892,5880,2884,2885,1301,"
        "1303,1326,6505,2002,1101,2207,2105,2912,2801,2880,"
        "4904,2412,3045,2301,3008,2474,6669,2376,5871,2327,"
        "2408,4938,2603,2615,2609,2354,2887,3037,2353,2345"
    )

    scope_col, _ = st.columns([3, 1])
    with scope_col:
        scan_scope = st.radio(
            "掃描範圍",
            ["自訂清單", "台灣前50", "全市場・上市（TWSE）", "全市場・上櫃（TPEx）", "全市場・上市＋上櫃"],
            index=0, horizontal=True, label_visibility="collapsed",
            key="scan_scope",
        )

    DEFAULT_CODES = (
        "2330,2317,2454,2382,2308,3711,2303,3034,2357,2379,"
        "2395,2881,2882,2886,2891,2892,5880,2884,2885,1301,"
        "1303,1326,6505,2002,1101,2207,2105,2912,2801,2880"
    )

    # 全市場模式用到的變數，先給預設值
    inc_twse, inc_tpex = False, False
    stock_type = "一般股票（排除 ETF）"
    type_map   = {"一般股票（排除 ETF）": "一般股票", "含 ETF": "含ETF", "全部": "全部"}
    scan_input = ""

    if scan_scope == "自訂清單":
        scan_input  = st.text_area(
            "股票代號（逗號或換行分隔）",
            value=st.session_state.get("scan_codes") or DEFAULT_CODES,
            height=90, placeholder="2330,2317,0050,3008…",
            key="scan_input_box",
        )
        scope_codes = [c.strip() for c in scan_input.replace("\n", ",").split(",") if c.strip()]
        scope_codes = list(dict.fromkeys(scope_codes))
        st.caption(f"共 {len(scope_codes)} 支")

    elif scan_scope == "台灣前50":
        scope_codes = [c.strip() for c in TW50_CODES.replace("\n", "").split(",") if c.strip()]
        scope_codes = list(dict.fromkeys(scope_codes))
        scan_input  = TW50_CODES
        st.info(f"台灣前50成分股（共 {len(scope_codes)} 支），約 **2–5 分鐘**完成掃描。")

    else:   # 全市場
        inc_twse   = scan_scope in ("全市場・上市（TWSE）", "全市場・上市＋上櫃")
        inc_tpex   = scan_scope in ("全市場・上櫃（TPEx）", "全市場・上市＋上櫃")
        stock_type = st.selectbox(
            "股票類型篩選",
            ["一般股票（排除 ETF）", "含 ETF", "全部"],
            index=0, key="scan_stock_type",
        )
        scope_codes = []   # 掃描時動態從交易所抓取
        st.info(
            "⚠️ 全市場掃描將即時從證交所 / 櫃買中心抓取所有股票代號，"
            "再逐一下載歷史 K 線。\n\n"
            "上市約 900 支、上櫃約 700 支。建議選「**2 個月**」加「**3 執行緒**」，"
            "約 **25–40 分鐘**完成。請確保網路穩定。"
        )

    st.divider()

    # ── 條件設定 + 進階參數 ───────────────────────────────────────────────────
    cond_col, param_col = st.columns([1, 1])

    with cond_col:
        st.markdown("**篩選條件**")
        use_c1 = st.checkbox("條件 1：MACD + KD 糾結向上", value=True, key="scan_c1")
        if use_c1:
            st.markdown(
                "<small style='color:#888'>① DIF > 0 &nbsp;② K > D（黃金交叉）"
                "<br>③ OSC 由負轉正 &nbsp;④ K &lt; 50 後向上</small>",
                unsafe_allow_html=True)

        use_c2 = st.checkbox("條件 2：上升軌道站上月線（MA20）＋成交量", value=True, key="scan_c2")
        if use_c2:
            min_vol = st.number_input("最低成交量（張）", min_value=0, value=1000,
                                      step=100, key="scan_min_vol")
            st.markdown(
                "<small style='color:#888'>"
                "① MA20 向上傾斜（今日 MA20 &gt; 5日前 MA20）<br>"
                "② 收盤站上 MA20<br>"
                "③ 成交量 ≥ 門檻值"
                "</small>",
                unsafe_allow_html=True)
        else:
            min_vol = 1000
        tol_pct = 3
        n_days  = 20

    with param_col:
        st.markdown("**進階參數**")
        scan_months  = st.slider("抓取月數（建議全市場選 2）", 2, 6, 3, key="scan_months")
        scan_workers = st.slider("平行執行緒數",              1, 8, 3, key="scan_workers")
        scan_match   = st.radio("結果顯示", ["只顯示符合", "全部顯示"],
                                index=0, horizontal=True, key="scan_match")

        # 預估時間
        if scan_scope in ("自訂清單", "台灣前50"):
            est_n = len(scope_codes) if scope_codes else 0
        else:
            est_n = 900 if inc_twse and not inc_tpex else (
                    700 if inc_tpex and not inc_twse else 1600)
        if est_n > 0:
            secs_per = scan_months * 0.5    # 每支股票約 0.5s × 月數
            est_min  = est_n * secs_per / scan_workers / 60
            st.markdown(
                f"<small style='color:#aaa'>預估時間：{est_n} 支 ÷ {scan_workers} 執行緒 "
                f"× {scan_months} 月 ≈ <b style='color:#e8a838'>{est_min:.0f} 分鐘</b></small>",
                unsafe_allow_html=True)

    st.divider()

    # ── 按鈕列 ────────────────────────────────────────────────────────────────
    b1, b2, b3, _ = st.columns([1, 1, 1, 4])
    with b1:
        scan_btn   = st.button("▶ 開始掃描", type="primary",
                               use_container_width=True, key="scan_start")
    with b2:
        scan_stop  = st.button("⏹ 停止",    use_container_width=True, key="scan_stop")
    with b3:
        scan_clear = st.button("🗑 清除",    use_container_width=True, key="scan_clear")

    if scan_stop:  st.session_state.scan_running = False
    if scan_clear:
        st.session_state.scan_results = []
        st.session_state.scan_running = False
        st.session_state.scan_fetched_codes = []

    # ── 掃描執行 ──────────────────────────────────────────────────────────────
    if scan_btn:
        if not use_c1 and not use_c2:
            st.warning("請至少啟用一個篩選條件")
        else:
            # 1. 取得代號清單
            if scan_scope in ("自訂清單", "台灣前50"):
                codes_to_scan = scope_codes
                if not codes_to_scan:
                    st.warning("請先輸入股票代號")
                    st.stop()
            else:
                with st.spinner("正在從交易所抓取所有股票代號…"):
                    codes_to_scan = fetch_all_stock_codes(
                        include_twse=inc_twse,
                        include_tpex=inc_tpex,
                        stock_type=type_map[stock_type],
                    )
                if not codes_to_scan:
                    st.error("無法取得股票代號，請稍後再試")
                    st.stop()
                st.session_state.scan_fetched_codes = codes_to_scan

            st.session_state.scan_running = True
            st.session_state.scan_results = []
            st.session_state.scan_codes   = scan_input

            total      = len(codes_to_scan)
            results_buf = []
            matched     = 0
            done_count  = 0
            stop_flag   = threading.Event()

            prog   = st.progress(0, text=f"掃描中：0 / {total}　符合：0")
            status = st.status(f"正在掃描 {total} 支股票（{scan_workers} 執行緒）…",
                               expanded=True)

            def _worker(code):
                if stop_flag.is_set():
                    return {"代號": code, "狀態": "⏹ 已停止", "整體符合": "─"}
                try:
                    return scan_stock(
                        code,
                        use_cond1=use_c1, use_cond2=use_c2,
                        months=scan_months, n_days=n_days,
                        tol=tol_pct / 100,
                        req_delay=0.35,
                        min_vol_lot=int(min_vol),
                    )
                except Exception as e:
                    return {"代號": code, "狀態": f"❌ {e}", "整體符合": "─"}

            with ThreadPoolExecutor(max_workers=scan_workers) as exe:
                futures = {exe.submit(_worker, c): c for c in codes_to_scan}
                for fut in as_completed(futures):
                    if not st.session_state.scan_running:
                        stop_flag.set()
                        status.write("⏹ 使用者停止掃描")
                        break
                    done_count += 1
                    r = fut.result()
                    results_buf.append(r)
                    if r.get("整體符合") == "✅ 符合":
                        matched += 1
                        status.write(f"✅ {r['代號']} 符合！（目前 {matched} 支）")
                    prog.progress(
                        done_count / total,
                        text=f"掃描中：{done_count} / {total}　符合：{matched}",
                    )

            # 依輸入順序排序結果
            code_order = {c: i for i, c in enumerate(codes_to_scan)}
            results_buf.sort(key=lambda r: code_order.get(r.get("代號", ""), 9999))

            st.session_state.scan_results  = results_buf
            st.session_state.scan_running  = False
            prog.progress(1.0, text=f"掃描完成：{done_count} 支，符合 {matched} 支")
            status.update(label=f"掃描完成：{done_count} 支，符合 {matched} 支",
                          state="complete")

    # ── 顯示結果 ──────────────────────────────────────────────────────────────
    results = st.session_state.scan_results
    if results:
        matched_list = [r for r in results if r.get("整體符合") == "✅ 符合"]

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("掃描股票數",  len(results))
        m2.metric("✅ 符合條件", len(matched_list))
        m3.metric("❌ 不符合",   len(results) - len(matched_list))
        hit_rate = len(matched_list) / len(results) * 100 if results else 0
        m4.metric("命中率", f"{hit_rate:.1f}%")

        st.divider()

        display = matched_list if scan_match == "只顯示符合" else results

        if display:
            # 符合的先、再不符，方便瀏覽
            display_sorted = (
                sorted(display, key=lambda r: 0 if r.get("整體符合") == "✅ 符合" else 1)
                if scan_match == "全部顯示" else display
            )
            st.markdown(render_scan_table(display_sorted, use_c1, use_c2),
                        unsafe_allow_html=True)

            df_dl = pd.DataFrame([{k: v for k, v in r.items() if not k.startswith("_")}
                                   for r in display_sorted])
            st.download_button(
                "⬇ 下載掃描結果 CSV",
                data=df_to_csv_bytes(df_dl),
                file_name=f"選股掃描_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
                key="scan_dl",
            )
        else:
            st.info("目前沒有符合條件的股票，可嘗試放寬篩選參數或選擇「全部顯示」。")
    else:
        if scan_scope in ("自訂清單", "台灣前50"):
            n_est = len(scope_codes) if scope_codes else 0
            hint_t = f"{n_est * scan_months * 0.5 / scan_workers / 60:.1f} 分鐘" if n_est else "─"
            hint_n = f"**{n_est} 支**（{scan_scope}）"
        else:
            hint_n = "全市場（上市＋上櫃約 1600 支）"
            hint_t = "25–40 分鐘（視執行緒數與月數而定）"
        st.info(
            f"設定條件後按「▶ 開始掃描」。\n\n"
            f"目前設定：{hint_n}，預計約 {hint_t}。\n\n"
            "**提示**：全市場掃描建議選「2 個月」＋「3 執行緒」以縮短時間。"
        )
