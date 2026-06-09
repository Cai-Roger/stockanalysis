"""
台灣股市（上市 + 上櫃）每日資料抓取 + Streamlit 網頁介面  v3.0
=======================================================
抓取項目（上市 TWSE + 上櫃 TPEx）：
  1. 個股每日收盤資料
  2. 大盤指數（加權 / 櫃買）
  3. 三大法人買賣超
  4. 融資融券餘額

進階功能：
  5. 技術指標計算（MA5/10/20、RSI14、MACD、KD）
  6. 多日資料合併（依股票代號合併歷史 CSV）
  7. 自動排程（每個交易日收盤後 14:45 自動執行）

資料來源：
  上市  https://openapi.twse.com.tw
  上櫃  https://www.tpex.org.tw/openapi/v1

執行方式：
  streamlit run app.py                         # 啟動網頁介面
"""

import sys
import time
import json
import logging
import requests
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta, date as date_cls


# ─── 設定區 ─────────────────────────────────────────────────────────────────

OUTPUT_DIR      = Path("stock_data")   # CSV 輸出目錄
LOG_FILE        = OUTPUT_DIR / "fetch.log"
REQUEST_DELAY   = 1.5                  # 每次 API 請求間隔（秒）
REQUEST_TIMEOUT = 30                   # 請求逾時秒數
MAX_RETRY       = 3                    # 失敗重試次數
SCHEDULE_TIME   = "14:45"             # 自動排程執行時間（收盤後）

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

BASE_URL    = "https://www.twse.com.tw"
OPENAPI_URL = "https://openapi.twse.com.tw/v1"

# 櫃買中心
TPEX_BASE_URL    = "https://www.tpex.org.tw"
TPEX_OPENAPI_URL = "https://www.tpex.org.tw/openapi/v1"

ENDPOINTS = {
    # ── 上市 (TWSE) ──
    "stock_all":          f"{OPENAPI_URL}/exchangeReport/STOCK_DAY_ALL",
    "taiex_index":        f"{BASE_URL}/exchangeReport/MI_INDEX",
    "institutional":      f"{BASE_URL}/fund/T86",
    "margin":             f"{BASE_URL}/exchangeReport/MI_MARGN",
    "stock_day":          f"{BASE_URL}/exchangeReport/STOCK_DAY",
    # ── 上櫃 (TPEx) ──
    "tpex_stock_all":     f"{TPEX_OPENAPI_URL}/tpex_mainboard_daily_close_quotes",
    "tpex_index":         f"{TPEX_OPENAPI_URL}/tpex_mainboard_index_daily_close_quotes",
    "tpex_institutional": f"{TPEX_BASE_URL}/web/stock/3insti/daily_trade/3itrade_hedge_result.php",
    "tpex_margin":        f"{TPEX_BASE_URL}/web/stock/margin_trading/margin_balance/margin_bal_result.php",
}

# 台股收盤日（週六週日不抓）
WEEKDAYS = {0, 1, 2, 3, 4}   # Mon–Fri


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


# ─── 工具函式 ────────────────────────────────────────────────────────────────

def fetch_json(url: str, params: dict = None, retry: int = MAX_RETRY) -> dict | None:
    """發送 GET 請求並回傳 JSON，失敗時自動重試。"""
    for attempt in range(1, retry + 1):
        try:
            resp = requests.get(
                url, params=params, headers=HEADERS,
                timeout=REQUEST_TIMEOUT, stream=False
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return {"data": data, "stat": "OK"}
            if data.get("stat") == "OK":
                return data
            stat_msg = data.get("stat", "未知")
            if "沒有符合條件" in stat_msg or "很抱歉" in stat_msg:
                logger.warning("無資料：%s（可能非交易日，或資料尚未發布—通常 18:00 後才完整）",
                               stat_msg)
            else:
                logger.warning("無資料回應：%s", stat_msg)
            return None
        except requests.exceptions.ChunkedEncodingError:
            logger.warning("[傳輸錯誤] ChunkedEncoding 連線中斷（第 %d 次），重試中…", attempt)
        except requests.exceptions.HTTPError as e:
            logger.warning("[HTTP 錯誤] %s（第 %d 次）", e, attempt)
        except requests.exceptions.ConnectionError:
            logger.warning("[連線錯誤] 無法連線（第 %d 次）", attempt)
        except requests.exceptions.ReadTimeout:
            logger.warning("[逾時] 讀取逾時（第 %d 次）", attempt)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("[解析錯誤] %s（第 %d 次）", e, attempt)
        if attempt < retry:
            time.sleep(3)
    return None


def save_csv(df: pd.DataFrame, filename: str) -> Path:
    """儲存 DataFrame 為 UTF-8-BOM CSV（Excel 可直接開啟）。"""
    df = fix_duplicate_columns(df)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / filename
    df.to_csv(path, index=False, encoding="utf-8-sig")
    logger.info("已存檔：%s  (%d 筆)", path, len(df))
    return path


def is_trading_day(date_str: str) -> bool:
    """簡易判斷是否為交易日（排除週六日，國定假日需另行維護）。"""
    dt = datetime.strptime(date_str, "%Y%m%d")
    return dt.weekday() in WEEKDAYS


def to_roc_date(date_str: str) -> str:
    """將西元日期 YYYYMMDD 轉換為民國日期 YYY/MM/DD（TPEx 傳統 API 需要）。"""
    dt = datetime.strptime(date_str, "%Y%m%d")
    roc_year = dt.year - 1911
    return f"{roc_year}/{dt.month:02d}/{dt.day:02d}"


def fetch_json_tpex(url: str, params: dict = None, retry: int = MAX_RETRY) -> dict | None:
    """
    處理 TPEx API 三種回傳格式：
      1. OpenAPI → list
      2. 傳統 API 舊格式 → {'aaData': [...]}
      3. 傳統 API 新格式 → {'tables': [{'title':..., 'data':..., 'fields'/'field':...}]}
    統一回傳 {'aaData': [...], 'fields': [...], 'stat': 'OK'}。
    """
    if params is None:
        params = {}
    params.setdefault("_", int(time.time() * 1000))

    for attempt in range(1, retry + 1):
        try:
            resp = requests.get(
                url, params=params, headers=HEADERS,
                timeout=REQUEST_TIMEOUT, stream=False
            )
            resp.raise_for_status()

            if not resp.text.strip():
                logger.warning("TPEx 回傳空內容，資料可能尚未發布")
                return None

            data = resp.json()

            # ── 格式 1：OpenAPI 直接回傳 list ──
            if isinstance(data, list):
                return {"aaData": data, "fields": [], "stat": "OK"}

            # ── 格式 2：舊版 {'aaData': [...]} ──
            if "aaData" in data:
                if not data["aaData"]:
                    logger.warning("TPEx aaData 為空，可能非交易日或資料尚未發布")
                    return None
                data.setdefault("fields", [])
                data["stat"] = "OK"
                return data

            # ── 格式 3：新版 {'tables': [{...}]} ──
            if "tables" in data and isinstance(data["tables"], list) and data["tables"]:
                table = data["tables"][0]
                rows   = table.get("data",   table.get("aaData", []))
                fields = table.get("fields", table.get("field",  []))
                if not rows:
                    logger.warning("TPEx tables[0].data 為空，可能非交易日或資料尚未發布")
                    return None
                return {"aaData": rows, "fields": fields, "stat": "OK"}

            logger.warning("TPEx 未知回傳格式：%s", str(data)[:120])
            return None

        except requests.exceptions.ChunkedEncodingError:
            logger.warning("[TPEx 傳輸錯誤] ChunkedEncoding 中斷（第 %d 次），重試中…", attempt)
        except requests.exceptions.HTTPError as e:
            logger.warning("[TPEx HTTP 錯誤] %s（第 %d 次）", e, attempt)
        except requests.exceptions.ConnectionError:
            logger.warning("[TPEx 連線錯誤] 無法連線（第 %d 次）", attempt)
        except requests.exceptions.ReadTimeout:
            logger.warning("[TPEx 逾時] 讀取逾時（第 %d 次）", attempt)
        except (json.JSONDecodeError, ValueError):
            text_preview = resp.text[:80] if resp.text else "(空)"
            logger.warning("[TPEx 解析錯誤] 非 JSON，內容：%s（第 %d 次）", text_preview, attempt)
            return None
        if attempt < retry:
            time.sleep(3)
    return None


def safe_insert(df: pd.DataFrame, pos: int, col: str, value) -> pd.DataFrame:
    """在 DataFrame 插入欄位；若欄位已存在則直接覆寫值，避免 ValueError。"""
    if col in df.columns:
        df[col] = value
    else:
        df.insert(pos, col, value)
    return df


def clean_number(series: pd.Series) -> pd.Series:
    """將含逗號、+/- 的字串轉為數值。"""
    return (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("+", "", regex=False)
        .str.strip()
        .replace("--", np.nan)
        .replace("", np.nan)
        .pipe(pd.to_numeric, errors="coerce")
    )


def fix_duplicate_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    移除 DataFrame 中重複的欄位，保留第一個出現的。
    （PyArrow 與部分 CSV 讀取不允許重複欄名）
    """
    seen: set[str] = set()
    keep = []
    for i, col in enumerate(df.columns):
        if col not in seen:
            seen.add(col)
            keep.append(i)
    return df.iloc[:, keep]


# ─── 各類資料抓取 ────────────────────────────────────────────────────────────

def fetch_stock_all(date_str: str) -> pd.DataFrame | None:
    """抓取全部上市個股當日收盤資料。"""
    logger.info("[1/4] 抓取個股每日收盤資料  date=%s", date_str)

    today = datetime.today().strftime("%Y%m%d")

    if date_str == today:
        # 今日資料使用 OpenAPI（單次請求取得全部）
        data = fetch_json(ENDPOINTS["stock_all"])
        if not data:
            return None
        rows = data.get("data", [])
        if not rows:
            return None
        df = pd.DataFrame(rows)
        # TWSE OpenAPI 英文欄位 → 繁體中文（完整對照）
        rename_map = {
            "Code":                 "股票代號",
            "Name":                 "股票名稱",
            "TradeVolume":          "成交量(股)",
            "TradeValue":           "成交金額(元)",
            "OpeningPrice":         "開盤價",
            "HighestPrice":         "最高價",
            "LowestPrice":          "最低價",
            "ClosingPrice":         "收盤價",
            "Change":               "漲跌",
            "Transaction":          "成交筆數",
            "LastBestBidPrice":     "最後買進價",
            "LastBestBidVolume":    "最後買進量(張)",
            "LastBestAskPrice":     "最後賣出價",
            "LastBestAskVolume":    "最後賣出量(張)",
            "PriceEarningRatio":    "本益比",
            "YieldRatio":           "殖利率(%)",
            "BookToMarketRatio":    "股價淨值比",
            "UpperLimitPrice":      "漲停價",
            "LowerLimitPrice":      "跌停價",
        }
        df.rename(columns=rename_map, inplace=True)
    else:
        # 歷史資料：使用傳統 MI_INDEX 批次報表
        url = f"{BASE_URL}/exchangeReport/MI_INDEX"
        params = {"response": "json", "date": date_str, "type": "ALLBUT0999"}
        data = fetch_json(url, params)
        if not data:
            logger.warning("歷史個股批次資料無法取得，請改用 --range 逐日抓取")
            return None
        fields = data.get("fields9", data.get("fields", []))
        rows   = data.get("data9",   data.get("data",   []))
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=fields)

    df.insert(0, "日期", date_str)
    return df


def fetch_taiex(date_str: str) -> pd.DataFrame | None:
    """抓取加權指數各類指數當日行情。"""
    logger.info("[2/4] 抓取加權指數  date=%s", date_str)

    # type=IND 取分類指數，type=MS 取大盤統計；兩個都試
    for idx_type in ("IND", "MS", "ALLBUT0999"):
        params = {"response": "json", "date": date_str, "type": idx_type}
        data = fetch_json(ENDPOINTS["taiex_index"], params)
        if data:
            # 找有效 fields/data 鍵（TWSE 有時用 fields0/data0 等）
            for suffix in ("", "0", "1", "2"):
                fields = data.get(f"fields{suffix}", [])
                rows   = data.get(f"data{suffix}",   [])
                if rows:
                    df = pd.DataFrame(rows, columns=fields if fields else None)
                    df.insert(0, "日期", date_str)
                    logger.info("加權指數抓取成功 type=%s, %d 筆", idx_type, len(df))
                    return df
        time.sleep(0.5)

    logger.warning("加權指數無資料（所有 type 均失敗），可能非交易日或資料尚未發布")
    return None


def fetch_institutional(date_str: str) -> pd.DataFrame | None:
    """抓取三大法人買賣超（外資、投信、自營商）。"""
    logger.info("[3/4] 抓取三大法人買賣超  date=%s", date_str)
    params = {"response": "json", "date": date_str, "selectType": "ALL"}
    data = fetch_json(ENDPOINTS["institutional"], params)
    if not data:
        return None
    fields = data.get("fields", [])
    rows   = data.get("data",   [])
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=fields)
    df.insert(0, "日期", date_str)
    return df


def fetch_margin(date_str: str) -> pd.DataFrame | None:
    """抓取融資融券餘額。"""
    logger.info("[4/4] 抓取融資融券  date=%s", date_str)
    params = {"response": "json", "date": date_str, "selectType": "ALL"}
    data = fetch_json(ENDPOINTS["margin"], params)
    if not data:
        return None

    # TWSE MI_MARGN 依日期回傳 fields3/data3 或 fields4/data4 或 fields/data
    fields, rows = [], []
    for suffix in ("3", "4", ""):
        fields = data.get(f"fields{suffix}", [])
        rows   = data.get(f"data{suffix}",   [])
        if rows:
            break

    if not rows:
        logger.warning("融資融券無資料，可能非交易日或資料尚未發布")
        return None

    df = pd.DataFrame(rows, columns=fields if fields else None)
    df.insert(0, "日期", date_str)
    return df


def fetch_single_stock_month(stock_no: str, date_str: str) -> pd.DataFrame | None:
    """
    抓取單支股票的月成交資料（TWSE 以月為單位回傳）。
    date_str 為該月任一日期，YYYYMMDD。
    """
    params = {"response": "json", "date": date_str, "stockNo": stock_no}
    data = fetch_json(ENDPOINTS["stock_day"], params)
    if not data:
        return None
    fields = data.get("fields", [])
    rows   = data.get("data",   [])
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=fields)
    df.insert(0, "股票代號", stock_no)
    return df


# ─── 上櫃 (TPEx) 資料抓取 ───────────────────────────────────────────────────

def fetch_tpex_stock_all(date_str: str) -> pd.DataFrame | None:
    """抓取全部上櫃個股當日收盤資料。"""
    logger.info("[TPEx 1/4] 抓取上櫃個股收盤  date=%s", date_str)
    today = datetime.today().strftime("%Y%m%d")

    if date_str == today:
        # 今日：使用 TPEx OpenAPI（無需日期參數）
        data = fetch_json_tpex(ENDPOINTS["tpex_stock_all"])
        if not data:
            return None
        rows = data.get("aaData", [])
        if not rows:
            return None
        df = pd.DataFrame(rows)
        # TPEx OpenAPI 英文欄位 → 繁體中文（完整對照）
        rename_map = {
            "SecuritiesCompanyCode":  "股票代號",
            "CompanyName":            "股票名稱",
            "Open":                   "開盤價",
            "High":                   "最高價",
            "Low":                    "最低價",
            "Close":                  "收盤價",
            "Change":                 "漲跌",
            "ChangePercent":          "漲跌幅(%)",
            "Average":                "均價",
            "TradeVolume":            "成交量(股)",
            "TradingShares":          "成交股數",
            "TradeValue":             "成交金額(元)",
            "TransactionAmount":      "成交金額(元)",
            "TransactionCount":       "成交筆數",
            "TransactionNumber":      "成交筆數",
            "LatestBidPrice":         "最後買進價",
            "LatestBidVolume":        "最後買進量(張)",
            "LatestAskPrice":         "最後賣出價",
            "LatesAskPrice":          "最後賣出價",
            "LatestAskVolume":        "最後賣出量(張)",
            "Capitals":               "市值(元)",
            "MarketCapitalization":   "市值(元)",
            "IssuedShares":           "發行股數",
            "NextReference":          "次日參考價",
            "NextLimitUp":            "次日漲停價",
            "NextLimitDown":          "次日跌停價",
            "PERatio":                "本益比",
            "DividendYield":          "殖利率(%)",
            "PBRatio":                "股價淨值比",
        }
        df.rename(columns=rename_map, inplace=True)
    else:
        # 歷史：TPEx 傳統 API（民國日期格式）
        roc_date = to_roc_date(date_str)
        params = {"l": "zh-tw", "d": roc_date, "se": "EW"}
        data = fetch_json_tpex(ENDPOINTS["tpex_stock_all"].replace(
            TPEX_OPENAPI_URL,
            f"{TPEX_BASE_URL}/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php"
        ).split("?")[0], params)
        # 若 OpenAPI 沒有歷史，改用傳統端點
        url = (
            f"{TPEX_BASE_URL}/web/stock/aftertrading/otc_quotes_no1430/"
            "stk_wn1430_result.php"
        )
        data = fetch_json_tpex(url, {"l": "zh-tw", "d": roc_date, "se": "EW"})
        if not data:
            return None
        rows = data.get("aaData", [])
        if not rows:
            return None
        # 傳統 API 欄位順序
        cols = ["股票代號", "股票名稱", "收盤價", "漲跌", "開盤價",
                "最高價", "最低價", "成交量(股)", "成交金額", "成交筆數",
                "本益比", "殖利率(%)", "股價淨值比"]
        df = pd.DataFrame(rows, columns=cols[:len(rows[0])] if rows else cols)

    safe_insert(df, 0, "日期", date_str)
    safe_insert(df, 1, "市場", "上櫃")
    return df


def fetch_tpex_index(date_str: str) -> pd.DataFrame | None:
    """抓取櫃買指數當日行情（今日與歷史共用同一傳統 API）。"""
    logger.info("[TPEx 2/4] 抓取櫃買指數  date=%s", date_str)
    roc_date = to_roc_date(date_str)
    url = f"{TPEX_BASE_URL}/web/stock/aftertrading/daily_trading_index/st41_result.php"
    data = fetch_json_tpex(url, {"l": "zh-tw", "d": roc_date})
    if not data:
        return None
    rows   = data.get("aaData", [])
    fields = data.get("fields", [])
    if not rows:
        return None
    # 優先使用 API 回傳的欄位名；若沒有，用預設
    if not fields:
        fields = ["指數名稱", "收盤指數", "漲跌", "漲跌幅(%)", "成交量(千股)", "成交金額(千元)"]
    n = len(rows[0]) if rows else len(fields)
    df = pd.DataFrame(rows, columns=fields[:n])
    safe_insert(df, 0, "日期", date_str)
    return df


def fetch_tpex_institutional(date_str: str) -> pd.DataFrame | None:
    """抓取上櫃三大法人買賣超。"""
    logger.info("[TPEx 3/4] 抓取上櫃三大法人  date=%s", date_str)
    roc_date = to_roc_date(date_str)

    url = f"{TPEX_BASE_URL}/web/stock/3insti/daily_trade/3itrade_hedge_result.php"
    data = fetch_json_tpex(url, {"l": "zh-tw", "se": "EW", "t": "D", "d": roc_date})

    if not data:
        return None
    rows   = data.get("aaData", [])
    fields = data.get("fields", [])
    if not rows:
        return None
    # 預設欄位（API 沒提供時使用）
    if not fields:
        fields = ["股票代號", "股票名稱",
                  "外資買進", "外資賣出", "外資買賣超",
                  "投信買進", "投信賣出", "投信買賣超",
                  "自營商買進", "自營商賣出", "自營商買賣超",
                  "三大法人買賣超"]
    n = len(rows[0]) if rows else len(fields)
    df = pd.DataFrame(rows, columns=fields[:n])
    safe_insert(df, 0, "日期", date_str)
    safe_insert(df, 1, "市場", "上櫃")
    return df


def fetch_tpex_margin(date_str: str) -> pd.DataFrame | None:
    """抓取上櫃融資融券餘額。"""
    logger.info("[TPEx 4/4] 抓取上櫃融資融券  date=%s", date_str)
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
                  "融券買進", "融券賣出", "融券現券償還", "融券餘額", "融券限額",
                  "資券互抵"]
    n = len(rows[0]) if rows else len(fields)
    df = pd.DataFrame(rows, columns=fields[:n])
    safe_insert(df, 0, "日期", date_str)
    safe_insert(df, 1, "市場", "上櫃")
    return df


# ─── 5. 技術指標計算 ─────────────────────────────────────────────────────────

def calc_ma(series: pd.Series, window: int) -> pd.Series:
    """移動平均線。"""
    return series.rolling(window=window, min_periods=1).mean().round(2)


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """RSI（相對強弱指數）。"""
    delta = series.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).round(2)


def calc_macd(series: pd.Series,
              fast: int = 12, slow: int = 26, signal: int = 9
              ) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD（指數平滑異同移動平均線）。回傳 (DIF, MACD, OSC)。"""
    ema_fast   = series.ewm(span=fast,   adjust=False).mean()
    ema_slow   = series.ewm(span=slow,   adjust=False).mean()
    dif        = (ema_fast - ema_slow).round(4)
    macd_line  = dif.ewm(span=signal, adjust=False).mean().round(4)
    osc        = (dif - macd_line).round(4)
    return dif, macd_line, osc


def calc_kd(high: pd.Series, low: pd.Series, close: pd.Series,
            period: int = 9) -> tuple[pd.Series, pd.Series]:
    """KD 隨機指標（Stochastic Oscillator）。回傳 (K, D)。"""
    lowest_low   = low.rolling(window=period, min_periods=1).min()
    highest_high = high.rolling(window=period, min_periods=1).max()
    denom = (highest_high - lowest_low).replace(0, np.nan)
    rsv   = ((close - lowest_low) / denom * 100).fillna(50)
    k     = rsv.ewm(com=2, adjust=False).mean().round(2)
    d     = k.ewm(com=2, adjust=False).mean().round(2)
    return k, d


def add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    計算技術指標並加入 DataFrame。
    輸入 df 須包含欄位：收盤價、最高價、最低價。
    """
    # 統一欄位名稱（相容不同 API 回傳格式）
    col_map = {}
    for col in df.columns:
        if "收盤" in col:
            col_map[col] = "收盤價"
        elif "最高" in col:
            col_map[col] = "最高價"
        elif "最低" in col:
            col_map[col] = "最低價"
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


def compute_ta_for_stock(stock_no: str):
    """
    讀取指定股票的歷史 CSV，計算技術指標並回存。
    先嘗試讀取合併檔，否則合併後再計算。
    """
    merged_path = OUTPUT_DIR / f"merged_{stock_no}.csv"
    if not merged_path.exists():
        logger.info("找不到合併檔，先執行合併...")
        merge_stock_data(stock_no)

    if not merged_path.exists():
        logger.error("無法取得 %s 的歷史資料", stock_no)
        return

    df = pd.read_csv(merged_path, encoding="utf-8-sig")
    # 依日期排序
    date_col = [c for c in df.columns if "日期" in c]
    if date_col:
        df = df.sort_values(date_col[0]).reset_index(drop=True)

    df = add_technical_indicators(df)
    out = OUTPUT_DIR / f"ta_{stock_no}.csv"
    save_csv(df, f"ta_{stock_no}.csv")
    logger.info("技術指標已存至 %s", out)


# ─── 6. 多日資料合併 ─────────────────────────────────────────────────────────

def merge_stock_data(stock_no: str) -> pd.DataFrame | None:
    """
    將 OUTPUT_DIR 下所有 stock_all_YYYYMMDD.csv 中
    屬於 stock_no 的列合併為一支股票的歷史 DataFrame，
    並儲存為 merged_{stock_no}.csv。
    """
    # 同時搜尋中文檔名與舊版英文檔名
    csv_files = sorted(
        list(OUTPUT_DIR.glob("上市個股_*.csv")) +
        list(OUTPUT_DIR.glob("上櫃個股_*.csv")) +
        list(OUTPUT_DIR.glob("stock_all_*.csv")) +
        list(OUTPUT_DIR.glob("twse_stock_*.csv")) +
        list(OUTPUT_DIR.glob("tpex_stock_*.csv"))
    )
    if not csv_files:
        logger.warning("找不到任何 stock_all_*.csv，請先執行資料抓取")
        return None

    frames = []
    for f in csv_files:
        try:
            tmp = pd.read_csv(f, encoding="utf-8-sig", dtype=str)
            # 找股票代號欄
            code_col = next(
                (c for c in tmp.columns if "代號" in c or c == "Code"), None
            )
            if code_col is None:
                continue
            subset = tmp[tmp[code_col] == stock_no]
            if not subset.empty:
                frames.append(subset)
        except Exception as e:
            logger.warning("讀取 %s 失敗：%s", f, e)

    if not frames:
        logger.warning("在現有 CSV 中找不到股票代號 %s", stock_no)
        return None

    df = pd.concat(frames, ignore_index=True).drop_duplicates()
    save_csv(df, f"merged_{stock_no}.csv")
    return df


def merge_all_days(data_type: str = "twse_institutional"):
    """
    合併所有日期的同類型資料。
    data_type 對應 CSV 前綴：
      twse_stock / twse_index / twse_institutional / twse_margin
      tpex_stock / tpex_index / tpex_institutional / tpex_margin
    也相容舊版前綴（institutional / margin / taiex / stock_all）。
    """
    # 前綴對照（中文檔名 + 舊版英文相容）
    prefix_map = {
        "twse_stock":          "上市個股_",
        "twse_index":          "加權指數_",
        "twse_institutional":  "上市三大法人_",
        "twse_margin":         "上市融資融券_",
        "tpex_stock":          "上櫃個股_",
        "tpex_index":          "櫃買指數_",
        "tpex_institutional":  "上櫃三大法人_",
        "tpex_margin":         "上櫃融資融券_",
        # 相容舊版英文前綴
        "institutional":       "上市三大法人_",
        "margin":              "上市融資融券_",
        "taiex":               "加權指數_",
        "stock_all":           "上市個股_",
    }
    prefix = prefix_map.get(data_type, data_type + "_")
    csv_files = sorted(OUTPUT_DIR.glob(f"{prefix}*.csv"))
    if not csv_files:
        logger.warning("找不到 %s*.csv 檔案", prefix)
        return None

    frames = [pd.read_csv(f, encoding="utf-8-sig", dtype=str) for f in csv_files]
    df = pd.concat(frames, ignore_index=True).drop_duplicates()
    out_name = f"merged_all_{data_type}.csv"
    save_csv(df, out_name)
    return df


# ─── 7. 自動排程 ─────────────────────────────────────────────────────────────

def run_daily(date_str: str | None = None):
    """抓取單日所有資料的主流程（上市 TWSE + 上櫃 TPEx）。"""
    if date_str is None:
        date_str = datetime.today().strftime("%Y%m%d")

    if not is_trading_day(date_str):
        logger.info("日期 %s 為假日，跳過抓取", date_str)
        return

    logger.info("═" * 50)
    logger.info("開始抓取  date=%s  (上市 + 上櫃)", date_str)
    logger.info("═" * 50)

    results = {}

    # ── 上市 (TWSE) ──────────────────────────────
    logger.info("── 上市 (TWSE) ──")

    df = fetch_stock_all(date_str)
    if df is not None:
        save_csv(df, f"上市個股_{date_str}.csv")
        results["上市個股"] = len(df)
    time.sleep(REQUEST_DELAY)

    df = fetch_taiex(date_str)
    if df is not None:
        save_csv(df, f"加權指數_{date_str}.csv")
        results["加權指數"] = len(df)
    time.sleep(REQUEST_DELAY)

    df = fetch_institutional(date_str)
    if df is not None:
        save_csv(df, f"上市三大法人_{date_str}.csv")
        results["上市法人"] = len(df)
    time.sleep(REQUEST_DELAY)

    df = fetch_margin(date_str)
    if df is not None:
        save_csv(df, f"上市融資融券_{date_str}.csv")
        results["上市融資券"] = len(df)
    time.sleep(REQUEST_DELAY)

    # ── 上櫃 (TPEx) ──────────────────────────────
    logger.info("── 上櫃 (TPEx) ──")

    df = fetch_tpex_stock_all(date_str)
    if df is not None:
        save_csv(df, f"上櫃個股_{date_str}.csv")
        results["上櫃個股"] = len(df)
    time.sleep(REQUEST_DELAY)

    df = fetch_tpex_index(date_str)
    if df is not None:
        save_csv(df, f"櫃買指數_{date_str}.csv")
        results["櫃買指數"] = len(df)
    time.sleep(REQUEST_DELAY)

    df = fetch_tpex_institutional(date_str)
    if df is not None:
        save_csv(df, f"上櫃三大法人_{date_str}.csv")
        results["上櫃法人"] = len(df)
    time.sleep(REQUEST_DELAY)

    df = fetch_tpex_margin(date_str)
    if df is not None:
        save_csv(df, f"上櫃融資融券_{date_str}.csv")
        results["上櫃融資券"] = len(df)

    logger.info("─" * 50)
    if results:
        for name, count in results.items():
            logger.info("✓ %-12s %5d 筆", name, count)
    else:
        logger.warning("所有項目均無資料，請確認是否為交易日")
    logger.info("─" * 50)


def run_range(start: str, end: str):
    """批次抓取指定日期區間的資料。"""
    try:
        start_dt = datetime.strptime(start, "%Y%m%d")
        end_dt   = datetime.strptime(end,   "%Y%m%d")
    except ValueError:
        logger.error("日期格式錯誤，請使用 YYYYMMDD")
        return

    current = start_dt
    total, skipped = 0, 0
    while current <= end_dt:
        date_str = current.strftime("%Y%m%d")
        if is_trading_day(date_str):
            run_daily(date_str)
            total += 1
            time.sleep(REQUEST_DELAY)
        else:
            skipped += 1
        current += timedelta(days=1)

    logger.info("批次完成：共抓取 %d 個交易日，跳過 %d 天", total, skipped)


def start_scheduler():
    """啟動每日定時排程（需安裝 schedule 套件）。"""
    try:
        import schedule
    except ImportError:
        logger.error("請先安裝排程套件：pip install schedule")
        sys.exit(1)

    def job():
        date_str = datetime.today().strftime("%Y%m%d")
        logger.info("排程觸發  time=%s  date=%s", datetime.now().strftime("%H:%M"), date_str)
        run_daily(date_str)

    schedule.every().monday.at(SCHEDULE_TIME).do(job)
    schedule.every().tuesday.at(SCHEDULE_TIME).do(job)
    schedule.every().wednesday.at(SCHEDULE_TIME).do(job)
    schedule.every().thursday.at(SCHEDULE_TIME).do(job)
    schedule.every().friday.at(SCHEDULE_TIME).do(job)

    logger.info("排程啟動：每個交易日 %s 自動抓取資料", SCHEDULE_TIME)
    logger.info("按 Ctrl+C 停止排程")

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        logger.info("排程已停止")


# ─── Streamlit 網頁介面 ───────────────────────────────────────────────────────

import io
import streamlit as st

# ─── 頁面設定 ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="台股每日資料",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

try:
    setup_logging()
except Exception:
    # Streamlit Cloud 檔案系統為唯讀，只啟用 stdout 日誌
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

# ─── 工具函式 ────────────────────────────────────────────────────────────────

def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    """DataFrame → UTF-8 BOM CSV bytes（Excel 可直接開啟）。"""
    buf = io.BytesIO()
    df.to_csv(buf, index=False, encoding="utf-8-sig")
    return buf.getvalue()


def dedup_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    PyArrow（Streamlit 底層）不允許重複欄位名。
    將重複欄位加上 _2、_3… 後綴以避免 ValueError。
    """
    seen: dict[str, int] = {}
    new_cols = []
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


def show_table(df: pd.DataFrame, label: str, filename: str):
    """顯示資料表格 + 下載按鈕。"""
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
    st.title("📈 台股每日資料")
    st.divider()

    # 日期選擇
    today = date_cls.today()
    selected_date = st.date_input(
        "選擇日期",
        value=today,
        min_value=date_cls(2010, 1, 1),
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
            df = fix_duplicate_columns(df)
            # 同時存 CSV 到本地（Streamlit Cloud 可能唯讀，忽略錯誤）
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
