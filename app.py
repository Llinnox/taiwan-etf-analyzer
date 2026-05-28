"""
台灣ETF智慧選股與投資組合分析系統
Flask 後端主程式
"""

from flask import Flask, jsonify, request, render_template
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import json
import pickle
import os
import time
from datetime import datetime, timedelta
import scipy.optimize as sco

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

# curl_cffi 可模擬真實瀏覽器 TLS 指紋，避免 Yahoo Finance 封鎖雲端伺服器 IP
try:
    from curl_cffi import requests as curl_requests
    CURL_CFFI_AVAILABLE = True
except ImportError:
    CURL_CFFI_AVAILABLE = False

app = Flask(__name__)

# ========== 全域設定 ==========
CACHE_DIR      = os.path.join("data", "cache")
ETF_LIST_CACHE = os.path.join("data", "etf_list_cache.json")
ETF_NAME_CSV   = os.path.join("data", "etf_name_list.csv")    # 舊版 CSV（名稱對照用）
ETF_LIST_V2    = os.path.join("data", "etf_list_v2.csv")      # 新版完整分類清單（333檔）
ERROR_LOG      = os.path.join("data", "error_log.txt")
RISK_FREE      = 0.015   # 台灣無風險利率（約1.5%年化）
BENCHMARK      = "0050.TW"

# 啟動時建立必要目錄
for _d in [CACHE_DIR, "data"]:
    os.makedirs(_d, exist_ok=True)

# ========== 分類關鍵字（對照新版6大類，僅作為 API 補充標的的備援分類）==========
# CSV 內的標的直接使用 CSV 的「類別」欄位，不走關鍵字分類
CATEGORY_KEYWORDS = {
    "市值型":  ["指數", "加權", "市值", "50", "500", "MSCI", "NASDAQ", "摩台",
                "富櫃", "中型", "藍籌", "寶滬深"],
    "高股息":  ["高股息", "股息", "高息", "配息", "填息", "股利", "入息", "優息"],
    "主題型":  ["科技", "半導體", "ESG", "AI", "5G", "永續", "電動車", "生技",
                "不動產", "綠能", "金融", "電信", "網路", "晶圓", "航太",
                "航運", "品牌", "創新", "支付", "太空", "儲能", "越南", "印度"],
    "債券型":  ["債", "公債", "投資級", "非投等", "國債", "信用"],
    "槓桿型":  ["正2", "反1", "正一", "反一", "L ", "R ", "正2倍"],
    "期貨型":  ["期元大", "期街口", "期貨", "黃金", "石油", "白銀", "銅", "黃豆",
                "美元指"],
}

# 備援清單（直接從新版 CSV 精選，所有類別齊全）
FALLBACK_ETF_LIST = [
    {"code": "0050.TW",   "name": "元大台灣50",       "category": "市值型", "exchange": "上市"},
    {"code": "006208.TW", "name": "富邦台50",          "category": "市值型", "exchange": "上市"},
    {"code": "00646.TW",  "name": "元大S&P500",        "category": "市值型", "exchange": "上市"},
    {"code": "00662.TW",  "name": "富邦NASDAQ",        "category": "市值型", "exchange": "上市"},
    {"code": "0056.TW",   "name": "元大高股息",         "category": "高股息", "exchange": "上市"},
    {"code": "00878.TW",  "name": "國泰永續高股息",     "category": "高股息", "exchange": "上市"},
    {"code": "00713.TW",  "name": "元大台灣高息低波",   "category": "高股息", "exchange": "上市"},
    {"code": "00919.TW",  "name": "群益台灣精選高息",   "category": "高股息", "exchange": "上市"},
    {"code": "00900.TW",  "name": "富邦特選高股息30",   "category": "高股息", "exchange": "上市"},
    {"code": "00830.TW",  "name": "國泰費城半導體",     "category": "主題型", "exchange": "上市"},
    {"code": "00881.TW",  "name": "國泰台灣科技龍頭",   "category": "主題型", "exchange": "上市"},
    {"code": "00850.TW",  "name": "元大臺灣ESG永續",    "category": "主題型", "exchange": "上市"},
    {"code": "00762.TW",  "name": "元大全球AI",         "category": "主題型", "exchange": "上市"},
    {"code": "00679B.TWO","name": "元大美債20年",        "category": "債券型", "exchange": "上櫃"},
    {"code": "00720B.TWO","name": "元大投資級公司債",    "category": "債券型", "exchange": "上櫃"},
    {"code": "00687B.TWO","name": "國泰20年美債",        "category": "債券型", "exchange": "上櫃"},
    {"code": "00631L.TW", "name": "元大台灣50正2",      "category": "槓桿型", "exchange": "上市"},
    {"code": "00632R.TW", "name": "元大台灣50反1",      "category": "槓桿型", "exchange": "上市"},
    {"code": "00635U.TW", "name": "期元大S&P黃金",      "category": "期貨型", "exchange": "上市"},
    {"code": "00642U.TW", "name": "期元大S&P石油",      "category": "期貨型", "exchange": "上市"},
]


# ─────────────────────────────────────
# 工具函式
# ─────────────────────────────────────

def log_error(msg: str):
    """將錯誤訊息寫入 error_log.txt"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(ERROR_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


def classify_etf(name: str) -> str:
    """
    根據ETF名稱關鍵字備援分類（僅用於 CSV 以外的新上市標的）
    主要分類來源為 etf_list_v2.csv 的「類別」欄位
    """
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in name for kw in keywords):
            return category
    return "其他"


# ─────────────────────────────────────
# ETF 清單管理
# ─────────────────────────────────────

def load_csv_etf_list() -> list:
    """
    從新版分類 CSV（etf_list_v2.csv）載入 333 檔台股 ETF
    欄位：類別, 市場別, 證券代號, 證券簡稱, 類別說明
    市場別「上市」→ .TW，「上櫃」→ .TWO
    第1、2行為標題說明，第3行起為資料
    """
    if not os.path.exists(ETF_LIST_V2):
        return []
    try:
        # skiprows=2：跳過第1行（總覽說明）和第2行（分類統計），從第3行的欄位標題讀起
        df = pd.read_csv(ETF_LIST_V2, dtype=str, encoding="utf-8-sig", skiprows=2)
        df.columns = [c.strip() for c in df.columns]
        df = df.dropna(subset=["證券代號", "證券簡稱"])

        # CSV 類別名稱對應（期貨型 → 期貨型，其餘直接使用）
        cat_map = {
            "市值型": "市值型",
            "高股息": "高股息",
            "主題型": "主題型",
            "債券型": "債券型",
            "槓桿型": "槓桿型",
            "期貨型": "期貨型",
        }

        result = []
        for _, row in df.iterrows():
            code     = str(row["證券代號"]).strip()
            name     = str(row["證券簡稱"]).strip()
            market   = str(row.get("市場別", "上市")).strip()
            cat_raw  = str(row.get("類別", "其他")).strip()
            category = cat_map.get(cat_raw, "其他")

            if not code or not name or code == "nan":
                continue

            suffix = ".TW" if market == "上市" else ".TWO"
            result.append({
                "code":     f"{code}{suffix}",
                "name":     name,
                "category": category,
                "exchange": market,
            })
        return result
    except Exception as e:
        log_error(f"etf_list_v2.csv 讀取失敗: {e}")
        return []


def get_etf_list() -> list:
    """
    合併三個來源的台灣ETF清單：
    1. 本地 CSV（台灣上市ETF清單.csv）— 221 筆上市 ETF，最完整
    2. 台灣證交所 OpenAPI — 補充 CSV 沒有的新上市標的
    3. 櫃買中心網頁 — 上櫃 ETF (.TWO)
    去重後合併，CSV 的名稱優先（較正確），以 JSON 快取每日更新
    """
    # 檢查當日快取
    if os.path.exists(ETF_LIST_CACHE):
        try:
            with open(ETF_LIST_CACHE, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if cached.get("date") == datetime.now().strftime("%Y-%m-%d"):
                return cached["data"]
        except Exception:
            pass

    # ── 來源 1：本地 CSV（最完整，優先載入）──
    etf_list = load_csv_etf_list()
    seen = {e["code"] for e in etf_list}

    # ── 來源 2：台灣證交所 OpenAPI（補充 CSV 遺漏的新標的）──
    try:
        resp = requests.get(
            "https://openapi.twse.com.tw/v1/ETF/domestic",
            timeout=15,
            headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"}
        )
        resp.raise_for_status()
        for item in resp.json():
            code = (item.get("公司代號") or item.get("SecuritiesCompanyCode") or "").strip()
            name = (item.get("公司簡稱") or item.get("CompanyName") or "").strip()
            full_code = f"{code}.TW"
            if code and len(code) >= 4 and full_code not in seen:
                etf_list.append({
                    "code":     full_code,
                    "name":     name or code,
                    "category": classify_etf(name),
                    "exchange": "上市",
                    "index":    "",
                })
                seen.add(full_code)
    except Exception as e:
        log_error(f"TWSE API 抓取失敗: {e}")

    # ── 來源 3：櫃買中心網頁（上櫃 .TWO）──
    if BS4_AVAILABLE:
        try:
            resp = requests.get(
                "https://www.tpex.org.tw/web/ETF/list/",
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for table in soup.find_all("table"):
                for row in table.find_all("tr")[1:]:
                    cols = row.find_all("td")
                    if len(cols) >= 2:
                        code = cols[0].get_text(strip=True)
                        name = cols[1].get_text(strip=True)
                        full_code = f"{code}.TWO"
                        if code and code[:4].isdigit() and full_code not in seen:
                            etf_list.append({
                                "code":     full_code,
                                "name":     name or code,
                                "category": classify_etf(name),
                                "exchange": "上櫃",
                                "index":    "",
                            })
                            seen.add(full_code)
        except Exception as e:
            log_error(f"TPEx 爬取失敗: {e}")

    # 三個來源都失敗時啟用備援
    if not etf_list:
        log_error("所有ETF清單來源均失敗，啟用備援清單")
        etf_list = FALLBACK_ETF_LIST

    # 寫入當日快取
    try:
        with open(ETF_LIST_CACHE, "w", encoding="utf-8") as f:
            json.dump(
                {"date": datetime.now().strftime("%Y-%m-%d"), "data": etf_list},
                f, ensure_ascii=False, indent=2
            )
    except Exception as e:
        log_error(f"ETF清單快取寫入失敗: {e}")

    return etf_list


# ─────────────────────────────────────
# 歷史價格抓取與快取
# 策略：
#   .TW  → 台灣證交所 (TWSE) 官方 API  ▶  yfinance 備援
#   .TWO → 櫃買中心 (TPEX) 官方 API   ▶  yfinance 備援
#   其他 → yfinance（如基準指數）
# ─────────────────────────────────────

# 給 yfinance / requests 使用的瀏覽器模擬 header
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}


def _months_in_range(start: datetime, end: datetime) -> list:
    """產生 (year, month) 清單，涵蓋 start 到 end 之間每個月"""
    months = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append((y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return months


def _fetch_twse_month(symbol: str, year: int, month: int) -> pd.Series:
    """
    從台灣證交所 STOCK_DAY API 抓取單月日收盤價
    回傳 index=日期(Timestamp), values=收盤價 的 Series
    優先使用 curl_cffi 繞過防爬蟲機制
    """
    fetch = curl_requests.get if CURL_CFFI_AVAILABLE else requests.get
    kwargs = {"impersonate": "chrome110"} if CURL_CFFI_AVAILABLE else {"headers": _HEADERS}
    resp = fetch(
        "https://www.twse.com.tw/exchangeReport/STOCK_DAY",
        params={"response": "json", "date": f"{year}{month:02d}01", "stockNo": symbol},
        timeout=12,
        **kwargs,
    )
    data = resp.json()
    if data.get("stat") != "OK" or not data.get("data"):
        return pd.Series(dtype=float)

    df = pd.DataFrame(data["data"], columns=data["fields"])

    # 民國年 → 西元年（e.g. "113/04/01" → Timestamp(2024,4,1)）
    def roc_to_ts(s):
        p = s.split("/")
        return pd.Timestamp(int(p[0]) + 1911, int(p[1]), int(p[2]))

    df["_date"]  = df["日期"].apply(roc_to_ts)
    df["_close"] = pd.to_numeric(df["收盤價"].str.replace(",", ""), errors="coerce")
    return df.set_index("_date")["_close"].dropna()


def _fetch_tpex_month(symbol: str, year: int, month: int) -> pd.Series:
    """
    從櫃買中心 st43 API 抓取單月日收盤價（上櫃 ETF）
    優先使用 curl_cffi 繞過防爬蟲機制
    """
    fetch = curl_requests.get if CURL_CFFI_AVAILABLE else requests.get
    kwargs = {"impersonate": "chrome110"} if CURL_CFFI_AVAILABLE else {"headers": _HEADERS}
    resp = fetch(
        "https://www.tpex.org.tw/web/stock/aftertrading/daily_trading_info/st43_result.php",
        params={"l": "zh-tw", "d": f"{year}/{month:02d}", "s": f"{symbol},asc,0"},
        timeout=12,
        **kwargs,
    )
    data = resp.json()
    rows = data.get("aaData") or data.get("data") or []
    if not rows:
        return pd.Series(dtype=float)

    records = []
    for row in rows:
        try:
            # 欄位順序：日期, 成交股數, 成交金額, 開盤, 最高, 最低, 收盤, 漲跌, 筆數
            date_str = row[0]   # e.g. "113/04/01"
            close_str = row[6]  # 收盤價
            p = date_str.split("/")
            ts    = pd.Timestamp(int(p[0]) + 1911, int(p[1]), int(p[2]))
            close = float(close_str.replace(",", ""))
            records.append((ts, close))
        except Exception:
            continue

    if not records:
        return pd.Series(dtype=float)
    idx, vals = zip(*records)
    return pd.Series(vals, index=idx, dtype=float)


def _price_from_official_api(symbol: str, exchange: str, period_days: int):
    """
    透過 TWSE / TPEX 官方 API 取得完整歷史收盤價
    exchange: 'TW' | 'TWO'
    """
    end   = datetime.now()
    start = end - timedelta(days=period_days + 10)
    months = _months_in_range(start, end)
    fetch_fn = _fetch_twse_month if exchange == "TW" else _fetch_tpex_month

    parts = []
    for y, m in months:
        try:
            s = fetch_fn(symbol, y, m)
            if not s.empty:
                parts.append(s)
            time.sleep(0.15)   # 避免被官方 API 限流（縮短以防 Render 請求超時）
        except Exception as e:
            log_error(f"{symbol} 官方API {y}/{m}: {e}")

    if not parts:
        return None

    series = pd.concat(parts).sort_index()
    cutoff = pd.Timestamp(start.date())
    series = series[series.index >= cutoff].dropna()
    return series if len(series) >= 20 else None


def _price_from_yfinance(ticker: str, period_days: int):
    """
    直接呼叫 Yahoo Finance Chart API v8，使用 curl_cffi 模擬 Chrome TLS 指紋。
    完全繞過 yfinance 的 session 機制（yfinance session 與 curl_cffi 相容性有問題）。
    curl_cffi 不可用時回退至標準 requests。
    """
    # 決定 range 字串
    if period_days <= 90:
        range_str = "3mo"
    elif period_days <= 180:
        range_str = "6mo"
    elif period_days <= 365:
        range_str = "1y"
    else:
        range_str = "5y"

    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"interval": "1d", "range": range_str}

    for attempt in range(2):
        try:
            if CURL_CFFI_AVAILABLE:
                resp = curl_requests.get(
                    url, params=params, impersonate="chrome110", timeout=20
                )
            else:
                resp = requests.get(url, params=params, headers=_HEADERS, timeout=20)

            data = resp.json()
            result_list = data.get("chart", {}).get("result")
            if not result_list:
                err = data.get("chart", {}).get("error")
                log_error(f"{ticker} Yahoo Chart API 無資料: {err}")
                time.sleep(2)
                continue

            result = result_list[0]
            timestamps = result.get("timestamp", [])

            # 優先使用還原後收盤價（adjclose），退而使用原始收盤價
            adj_list = result.get("indicators", {}).get("adjclose", [])
            if adj_list and adj_list[0].get("adjclose"):
                closes = adj_list[0]["adjclose"]
            else:
                closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])

            if not timestamps or not closes:
                time.sleep(2)
                continue

            # UTC Unix timestamp → 台灣日期（移除時區資訊）
            dates = (
                pd.to_datetime(timestamps, unit="s")
                  .tz_localize("UTC")
                  .tz_convert("Asia/Taipei")
                  .tz_localize(None)
            )
            series = pd.Series(closes, index=dates, dtype=float, name=ticker).dropna()

            cutoff = datetime.now() - timedelta(days=period_days)
            series = series[series.index >= cutoff]

            return series if len(series) >= 20 else None

        except Exception as e:
            log_error(f"{ticker} Yahoo Chart API attempt {attempt+1}: {e}")
            time.sleep(2)

    return None


def get_price_data(ticker: str, period_days: int = 365):
    """
    統一入口：依交易所選擇資料源
      .TW  → TWSE 官方 API → yfinance 備援
      .TWO → TPEX 官方 API → yfinance 備援
      其他 → yfinance
    pickle 快取有效期 23 小時
    """
    safe_name  = ticker.replace(".", "_").replace("^", "IDX_")
    cache_path = os.path.join(CACHE_DIR, f"{safe_name}_{period_days}.pkl")

    # 讀取 pickle 快取
    if os.path.exists(cache_path):
        mtime = datetime.fromtimestamp(os.path.getmtime(cache_path))
        if datetime.now() - mtime < timedelta(hours=23):
            try:
                with open(cache_path, "rb") as f:
                    return pickle.load(f)
            except Exception:
                pass

    close = None

    if ticker.endswith(".TW"):
        symbol = ticker[:-3]
        close  = _price_from_official_api(symbol, "TW", period_days)
        if close is None:
            log_error(f"{ticker}: TWSE API 失敗，改用 yfinance 備援")
            close = _price_from_yfinance(ticker, period_days)

    elif ticker.endswith(".TWO"):
        symbol = ticker[:-4]
        close  = _price_from_official_api(symbol, "TWO", period_days)
        if close is None:
            log_error(f"{ticker}: TPEX API 失敗，改用 yfinance 備援")
            close = _price_from_yfinance(ticker, period_days)

    else:
        # 基準指數或其他（^TWII 等）
        close = _price_from_yfinance(ticker, period_days)

    if close is not None:
        close.name = ticker
        with open(cache_path, "wb") as f:
            pickle.dump(close, f)
    else:
        log_error(f"{ticker}: 所有資料源均失敗")

    return close


# ─────────────────────────────────────
# 風險報酬指標計算
# ─────────────────────────────────────

def calc_metrics(price: pd.Series) -> dict:
    """
    計算單檔ETF的標準風險報酬指標：
    - 年化報酬率（Annual Return）
    - 年化波動率（Annual Volatility）
    - 夏普比率（Sharpe Ratio）
    - 最大回撤（Maximum Drawdown, MDD）
    """
    daily_ret = price.pct_change().dropna()
    if len(daily_ret) < 10:
        return {"annual_return": 0, "annual_vol": 0, "sharpe": 0, "mdd": 0}

    annual_ret = float((1 + daily_ret.mean()) ** 252 - 1)
    annual_vol = float(daily_ret.std() * np.sqrt(252))
    sharpe     = float((annual_ret - RISK_FREE) / annual_vol) if annual_vol > 0 else 0.0

    # 計算最大回撤：(當前累積值 - 歷史最高) / 歷史最高
    cumul      = (1 + daily_ret).cumprod()
    drawdown   = (cumul - cumul.cummax()) / cumul.cummax()
    mdd        = float(drawdown.min())

    return {
        "annual_return": round(annual_ret, 4),
        "annual_vol":    round(annual_vol, 4),
        "sharpe":        round(sharpe, 4),
        "mdd":           round(mdd, 4),
    }


# ─────────────────────────────────────
# 資產配置最佳化函式
# ─────────────────────────────────────

def max_sharpe_optimize(returns_df: pd.DataFrame) -> np.ndarray:
    """
    均值-變異數最佳化：最大化夏普比率
    - 使用 scipy.optimize.minimize（SLSQP 方法）
    - 限制條件：權重總和 = 1，各權重 ∈ [0, 1]（不允許放空）
    - 若最佳化失敗則回傳均等權重
    """
    n          = returns_df.shape[1]
    mean_ret   = returns_df.mean() * 252          # 年化平均報酬率
    cov_matrix = returns_df.cov() * 252           # 年化共變異數矩陣

    def neg_sharpe(w):
        """目標函數：負夏普比率（最小化 = 最大化夏普）"""
        port_ret = float(np.dot(w, mean_ret))
        port_vol = float(np.sqrt(w @ cov_matrix.values @ w))
        if port_vol < 1e-10:
            return 0.0
        return -(port_ret - RISK_FREE) / port_vol

    constraints = {"type": "eq", "fun": lambda w: np.sum(w) - 1}
    bounds      = [(0.0, 1.0)] * n
    init_w      = np.array([1.0 / n] * n)

    result = sco.minimize(
        neg_sharpe,
        x0=init_w,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"ftol": 1e-9, "maxiter": 1000},
    )

    return result.x if result.success else init_w


def min_variance_optimize(returns_df: pd.DataFrame) -> np.ndarray:
    """
    最小變異數最佳化：最小化投資組合年化波動率
    - 目標函數：portfolio_vol = sqrt(w' * Σ * w)
    - 限制條件：權重總和 = 1，各權重 ∈ [0, 1]（不允許放空）
    - 若最佳化失敗則回傳均等權重
    """
    n          = returns_df.shape[1]
    cov_matrix = returns_df.cov() * 252           # 年化共變異數矩陣

    def portfolio_vol(w):
        """目標函數：投資組合年化波動率"""
        return float(np.sqrt(w @ cov_matrix.values @ w))

    constraints = {"type": "eq", "fun": lambda w: np.sum(w) - 1}
    bounds      = [(0.0, 1.0)] * n
    init_w      = np.array([1.0 / n] * n)

    result = sco.minimize(
        portfolio_vol,
        x0=init_w,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"ftol": 1e-9, "maxiter": 1000},
    )

    return result.x if result.success else init_w


def get_market_cap(ticker: str) -> float | None:
    """
    取得ETF的資產規模（AUM）作為市值加權依據
    使用 yfinance info['totalAssets']（ETF 的總資產淨值）
    加入指數退避重試（最多3次），避免 Yahoo Finance 429 限流
    失敗時回傳 None
    """
    # 優先使用 curl_cffi 避免雲端 IP 被 Yahoo Finance 封鎖
    if CURL_CFFI_AVAILABLE:
        session = curl_requests.Session(impersonate="chrome110")
    else:
        session = requests.Session()
        session.headers.update(_HEADERS)

    for attempt in range(3):
        try:
            if attempt > 0:
                wait = 2 ** attempt + 1   # 3s, 5s
                log_error(f"{ticker} AUM 第{attempt+1}次重試，等待 {wait}s")
                time.sleep(wait)
            else:
                time.sleep(0.5)           # 首次請求加基礎間隔

            info = yf.Ticker(ticker, session=session).info
            aum  = info.get("totalAssets") or info.get("totalNav") or None
            return float(aum) if aum and aum > 0 else None

        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "Too Many Requests" in err_str:
                log_error(f"{ticker} AUM 429限流 (attempt {attempt+1}): {e}")
                continue
            log_error(f"{ticker} AUM查詢失敗: {e}")
            return None

    log_error(f"{ticker} AUM 重試3次均失敗，回傳 None")
    return None


def market_cap_weighted(tickers: list) -> np.ndarray:
    """
    市值加權：以各ETF的AUM（資產規模）計算比例
    - 請求間加入 0.5s 間隔，避免觸發 Yahoo Finance 429 限流
    - 無法取得AUM的標的以所有有效AUM的平均值替代，確保所有標的均有權重
    - 若全部標的均查無AUM則回退為均等權重
    """
    caps = []
    for t in tickers:
        caps.append(get_market_cap(t))
        time.sleep(0.5)

    # 有效市值的平均，作為缺失值替代
    valid_caps = [c for c in caps if c is not None]
    fallback   = float(np.mean(valid_caps)) if valid_caps else 1.0
    caps       = [c if c is not None else fallback for c in caps]

    total = sum(caps)
    return np.array([c / total for c in caps])


# ─────────────────────────────────────
# Flask API 路由
# ─────────────────────────────────────

@app.route("/api/etf_name_map")
def api_etf_name_map():
    """
    GET /api/etf_name_map
    讀取本地 CSV（台灣上市ETF清單.csv），回傳 {證券代號: 證券簡稱} 對照表
    前端用於輸入代碼時即時轉換成中文名稱
    """
    try:
        df = pd.read_csv(ETF_NAME_CSV, dtype=str, encoding="utf-8-sig")
        # 欄位：上市日期, 證券代號, 證券簡稱, 發行人, 標的指數
        df["證券代號"] = df["證券代號"].str.strip()
        df["證券簡稱"] = df["證券簡稱"].str.strip()
        name_map = dict(zip(df["證券代號"], df["證券簡稱"]))
        return jsonify({"success": True, "data": name_map})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/")
def index():
    """首頁：回傳 HTML 主頁面"""
    return render_template("index.html")


@app.route("/api/etf_list")
def api_etf_list():
    """
    GET /api/etf_list
    回傳台灣全市場ETF清單（含分類與交易所資訊）
    """
    try:
        data = get_etf_list()
        return jsonify({"success": True, "data": data, "count": len(data)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/performance")
def api_performance():
    """
    GET /api/performance?tickers=0050.TW,0056.TW&period=1Y
    回傳各ETF的累積報酬率走勢與風險指標
    自動附加基準指數資料
    """
    tickers_str = request.args.get("tickers", "")
    period      = request.args.get("period", "1Y")
    period_map  = {"3M": 90, "6M": 180, "1Y": 365, "3Y": 1095}
    period_days = period_map.get(period, 365)

    tickers = [t.strip() for t in tickers_str.split(",") if t.strip()]
    if not tickers:
        return jsonify({"success": False, "error": "請提供 tickers 參數"}), 400

    # 加入基準（去重保序）
    all_tickers = list(dict.fromkeys(tickers + [BENCHMARK]))
    result = {}

    for ticker in all_tickers:
        price = get_price_data(ticker, period_days)
        if price is None:
            continue

        metrics   = calc_metrics(price)
        daily_ret = price.pct_change().dropna()
        cumul     = (1 + daily_ret).cumprod() - 1  # 累積報酬率

        result[ticker] = {
            **metrics,
            "dates":              [str(d)[:10] for d in cumul.index],
            "cumulative_returns": [round(float(v), 6) for v in cumul],
        }

    return jsonify({"success": True, "data": result, "benchmark": BENCHMARK})


@app.route("/api/correlation")
def api_correlation():
    """
    GET /api/correlation?tickers=0050.TW,0056.TW&period=1Y
    回傳ETF間的相關係數矩陣（基於日報酬率）
    """
    tickers_str = request.args.get("tickers", "")
    period      = request.args.get("period", "1Y")
    period_map  = {"3M": 90, "6M": 180, "1Y": 365, "3Y": 1095}
    period_days = period_map.get(period, 365)

    tickers = [t.strip() for t in tickers_str.split(",") if t.strip()]
    if len(tickers) < 2:
        return jsonify({"success": False, "error": "至少需要2檔ETF"}), 400

    # 抓取各ETF價格
    prices = {}
    for t in tickers:
        p = get_price_data(t, period_days)
        if p is not None:
            prices[t] = p

    if len(prices) < 2:
        return jsonify({"success": False, "error": "有效資料不足（可能下市或資料不足）"}), 400

    # 對齊日期，計算相關性矩陣
    df   = pd.DataFrame(prices).dropna()
    corr = df.pct_change().dropna().corr()

    return jsonify({
        "success": True,
        "tickers": corr.columns.tolist(),
        "matrix":  [[round(float(v), 4) for v in row] for row in corr.values],
    })


@app.route("/api/portfolio", methods=["POST"])
def api_portfolio():
    """
    POST /api/portfolio
    Body: {"tickers": [...], "method": "equal"|"market_cap"|"max_sharpe"|"min_variance", "period": "1Y"}

    接收選定ETF清單，計算投資組合配置並回傳：
    - 各ETF權重
    - 投資組合整體指標
    - 累積報酬率走勢（含日期）
    - 各ETF個別指標
    """
    body        = request.get_json(force=True)
    tickers     = body.get("tickers", [])
    method      = body.get("method", "equal")
    period      = body.get("period", "1Y")
    period_map  = {"3M": 90, "6M": 180, "1Y": 365, "3Y": 1095}
    period_days = period_map.get(period, 365)

    if not tickers:
        return jsonify({"success": False, "error": "請提供ETF清單"}), 400

    # 抓取價格資料
    prices = {}
    for t in tickers:
        p = get_price_data(t, period_days)
        if p is not None:
            prices[t] = p

    if len(prices) < 2:
        return jsonify({"success": False, "error": "有效ETF不足（至少需要2檔）"}), 400

    # 對齊日期並計算日報酬率矩陣
    prices_df   = pd.DataFrame(prices).dropna()
    returns_df  = prices_df.pct_change().dropna()
    valid_tkrs  = prices_df.columns.tolist()
    n           = len(valid_tkrs)

    # 依選擇的方法計算最佳權重
    if method == "max_sharpe" and n >= 2:
        weights = max_sharpe_optimize(returns_df)
    elif method == "min_variance" and n >= 2:
        weights = min_variance_optimize(returns_df)
    elif method == "market_cap":
        weights = market_cap_weighted(valid_tkrs)
    else:
        weights = np.array([1.0 / n] * n)  # 均等權重（預設）

    # 計算投資組合每日報酬率
    port_ret      = returns_df.values @ weights
    port_cumul    = (1 + port_ret).cumprod() - 1

    # 投資組合整體指標
    annual_ret = float((1 + port_ret.mean()) ** 252 - 1)
    annual_vol = float(port_ret.std() * np.sqrt(252))
    sharpe     = float((annual_ret - RISK_FREE) / annual_vol) if annual_vol > 0 else 0.0
    cumul_g    = pd.Series((1 + port_ret).cumprod())
    mdd        = float(((cumul_g - cumul_g.cummax()) / cumul_g.cummax()).min())

    # 各ETF個別指標
    etf_details = []
    for i, t in enumerate(valid_tkrs):
        m = calc_metrics(prices_df[t])
        etf_details.append({
            "ticker": t,
            "weight": round(float(weights[i]), 4),
            **m,
        })

    dates = [str(d)[:10] for d in prices_df.index]

    return jsonify({
        "success":    True,
        "tickers":    valid_tkrs,
        "weights":    {t: round(float(w), 4) for t, w in zip(valid_tkrs, weights)},
        "portfolio_metrics": {
            "annual_return": round(annual_ret, 4),
            "annual_vol":    round(annual_vol, 4),
            "sharpe":        round(sharpe, 4),
            "mdd":           round(mdd, 4),
        },
        "portfolio_cumulative": [round(float(v), 6) for v in port_cumul],
        "dates":       dates,
        "etf_details": etf_details,
        "method":      method,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV") != "production"
    print("=" * 50)
    print("  台灣ETF智慧選股與投資組合分析系統")
    print(f"  http://0.0.0.0:{port}")
    print("=" * 50)
    app.run(debug=debug, host="0.0.0.0", port=port)