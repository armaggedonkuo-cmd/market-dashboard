# -*- coding: utf-8 -*-
"""市場觀察面板 (Streamlit) — 台美股 + 持股 + 領先/情緒指標 + 經濟日曆"""
import io, re
import datetime as dt
import requests
import pandas as pd
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="市場觀察", page_icon="chart", layout="centered")

# ============ 設定 ============
SHEET_ID = "103uVFwc34ljwZxauN2ClRxW5rMSo_BAHL3dNDwCH6HA"
USE_SHEET = True   # True=從 Google 試算表自動讀持股；讀不到自動退回下面寫死的清單

TW_FALLBACK = [
    ("富邦金", "2881.TW", 45.088), ("南亞", "1303.TW", 13.0),
    ("台灣50", "0050.TW", 152.792), ("台積電", "2330.TW", 0.048),
    ("富邦采吉50", "006208.TW", 73.672),
]
US_FALLBACK = [("VOO", "VOO", 148.95), ("VT", "VT", 379.20), ("BND", "BND", 193.81)]

INDICES = [("加權", "^TWII"), ("費半", "^SOX"), ("S&P 500", "^GSPC"),
           ("Nasdaq", "^IXIC"), ("道瓊", "^DJI")]

# ============ 從試算表讀持股 ============
def _scell(r, j):
    return "" if (j is None or j >= len(r) or pd.isna(r[j])) else str(r[j]).strip()

def _scol(h, key):
    for j, c in enumerate(h):
        if key in str(c):
            return j
    return None

def _parse_tables(df):
    rows = [[("" if pd.isna(x) else str(x)).strip() for x in df.iloc[i].tolist()]
            for i in range(len(df))]
    tw, us = [], []
    hi = next((i for i, r in enumerate(rows) if any("代號" in c for c in r)), None)
    if hi is not None:
        h = rows[hi]; ni, ci, li = _scol(h, "名稱"), _scol(h, "代號"), _scol(h, "張數")
        for r in rows[hi + 1:]:
            code = _scell(r, ci)
            if re.fullmatch(r"\d{1,3}", code):
                code = code.zfill(4)
            if not re.fullmatch(r"\d{3,6}", code):
                break
            try:
                tw.append((_scell(r, ni), code + ".TW", float(_scell(r, li))))
            except Exception:
                break
    hi = next((i for i, r in enumerate(rows)
               if any("張數" in c for c in r) and not any("代號" in c for c in r)), None)
    if hi is not None:
        h = rows[hi]; ni, li = _scol(h, "名稱"), _scol(h, "張數")
        if ni is None:
            ni = 0
        for r in rows[hi + 1:]:
            tkr = _scell(r, ni)
            if not re.fullmatch(r"[A-Za-z.]{1,6}", tkr):
                break
            try:
                us.append((tkr.upper(), tkr.upper(), float(_scell(r, li))))
            except Exception:
                break
    return tw, us

@st.cache_data(ttl=600, show_spinner=False)
def holdings_from_sheet():
    urls = [
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv",
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv",
    ]
    diag = []
    for u in urls:
        try:
            r = requests.get(u, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            head = r.text[:140].replace("\n", " ")
            diag.append(f"[{u.split('/')[-1][:18]}] status={r.status_code} head={head!r}")
            df = pd.read_csv(io.StringIO(r.text), header=None, dtype=str)
            tw, us = _parse_tables(df)
            diag.append(f"  -> 解析 台股{len(tw)} 美股{len(us)}")
            if tw and us:
                return tw, us, ""
        except Exception as e:
            diag.append(f"  err={type(e).__name__}: {e}")
    raise ValueError(" || ".join(diag))

def load_holdings():
    if USE_SHEET:
        try:
            tw, us, _ = holdings_from_sheet()
            return tw, us, "試算表", ""
        except Exception as e:
            return TW_FALLBACK, US_FALLBACK, "內建清單", str(e)
    return TW_FALLBACK, US_FALLBACK, "內建清單", "USE_SHEET=False"

# ============ 報價 ============
@st.cache_data(ttl=600, show_spinner=False)
def get_quotes(symbols):
    out = {}
    data = yf.Tickers(" ".join(symbols))
    for s in symbols:
        price = prev = None
        try:
            fi = data.tickers[s].fast_info
            price = float(fi.last_price); prev = float(fi.previous_close)
        except Exception:
            try:
                h = yf.Ticker(s).history(period="5d")
                if len(h) >= 2:
                    price = float(h["Close"].iloc[-1]); prev = float(h["Close"].iloc[-2])
                elif len(h) == 1:
                    price = prev = float(h["Close"].iloc[-1])
            except Exception:
                pass
        out[s] = (price, prev)
    return out

@st.cache_data(ttl=900, show_spinner=False)
def get_fx_usdtwd():
    try:
        return get_quotes(["TWD=X"])["TWD=X"][0]
    except Exception:
        return None

@st.cache_data(ttl=1800, show_spinner=False)
def get_yield_curve():
    try:
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10,DGS2"
        df = pd.read_csv(io.StringIO(requests.get(url, timeout=15).text))
        df = df.replace(".", pd.NA).dropna()
        last = df.iloc[-1]
        return float(last["DGS10"]), float(last["DGS2"]), str(last.iloc[0])
    except Exception:
        return None, None, None

@st.cache_data(ttl=1800, show_spinner=False)
def get_fear_greed():
    """回傳 F&G 與 美股 put/call（CNN 取自 CBOE 5日 put/call）"""
    try:
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        headers = {
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://edition.cnn.com",
            "Referer": "https://edition.cnn.com/markets/fear-and-greed",
        }
        r = requests.get(url, headers=headers, timeout=15); r.raise_for_status()
        j = r.json(); d = j["fear_and_greed"]
        us_pc = None
        try:
            pcd = j.get("put_call_options", {})
            yv = float(pcd["data"][-1]["y"])
            if 0.2 <= yv <= 2.5:
                us_pc = yv
        except Exception:
            pass
        return {"score": round(d["score"]), "rating": d["rating"], "close": round(d["previous_close"]),
                "wk": round(d["previous_1_week"]), "mo": round(d["previous_1_month"]), "us_pc": us_pc}
    except Exception:
        return None

@st.cache_data(ttl=1800, show_spinner=False)
def get_taifex_pc():
    try:
        url = "https://www.taifex.com.tw/cht/3/pcRatioDown"
        raw = requests.get(url, timeout=15).content.decode("ms950", "ignore")
        rows = [l for l in raw.splitlines() if l and l[0].isdigit()]
        c = rows[0].split(",")
        return float(c[6]) / 100.0, float(c[3]) / 100.0, c[0]
    except Exception:
        return None, None, None

# ============ Put/Call 判讀 ============
def pc_sentiment(v, market):
    """回傳 (情緒標籤, css)。put/call 高=買權避險多=偏空；極端值反向。"""
    if v is None:
        return ("—", "mut")
    if market == "us":   # CBOE 全市場約 0.4–1.2
        if v >= 1.05:
            return ("偏空(避險濃)", "dn")
        if v <= 0.70:
            return ("偏多(樂觀)", "up")
        return ("中性", "mut")
    else:                # 台指期 未平倉比 約 1.0–1.5
        if v >= 1.30:
            return ("偏空(避險濃)", "dn")
        if v <= 1.00:
            return ("偏多(樂觀)", "up")
        return ("中性", "mut")

# ============ 經濟日曆（規則式，自動往後滾） ============
def gen_calendar(now):
    today = now.date(); out = []
    d = today
    while d.weekday() != 3:
        d += dt.timedelta(days=1)
    for k in range(6):
        out.append((f"{d + dt.timedelta(days=7*k)} 20:30", "us", "美國 初領失業金", "低", ""))
    for k in range(3):
        m = (today.month - 1 + k) % 12 + 1; y = today.year + (today.month - 1 + k) // 12
        out.append((f"{dt.date(y, m, 13)} 20:30", "us", "美國 CPI（約）", "高", "前值/預期見官方"))
        out.append((f"{dt.date(y, m, 14)} 20:30", "us", "美國 PPI（約）", "中", ""))
        out.append((f"{dt.date(y, m, 10)} 16:00", "tw", "台股 月營收截止", "中", ""))
    for ds in ["2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09", "2027-01-27", "2027-03-17"]:
        dd = dt.date.fromisoformat(ds) + dt.timedelta(days=1)
        out.append((f"{dd} 02:00", "us", "FOMC 利率決議+記者會", "高", ""))
    for ds in ["2026-09-17", "2026-12-17", "2027-03-18", "2027-06-17"]:
        out.append((f"{ds} 16:00", "tw", "台灣央行理監事會", "高", "季度"))
    nowstr = now.strftime("%Y-%m-%d %H:%M")
    return sorted([e for e in out if e[0] >= nowstr], key=lambda e: e[0])[:8]

# ============ 工具 ============
def fmt(n, d=0): return f"{n:,.{d}f}" if n is not None else "—"
def pct(n): return f"{n:+.2f}%" if n is not None else "—"

# ============ 抓資料 ============
TW_HOLDINGS, US_HOLDINGS, HSRC, HDBG = load_holdings()
all_syms = [s for _, s, _ in TW_HOLDINGS] + [s for _, s, _ in US_HOLDINGS] + [s for _, s in INDICES] + ["^VIX"]
quotes = get_quotes(all_syms)
fx = get_fx_usdtwd() or 31.5
y10, y2, ydate = get_yield_curve()
fg = get_fear_greed()
pc_oi, pc_vol, pc_date = get_taifex_pc()

# ============ 樣式 ============
st.markdown("""
<style>
.block-container{padding-top:2.5rem;padding-bottom:3rem;max-width:640px;}
.sec{font-size:13px;color:#6b7785;font-weight:700;letter-spacing:1px;margin:18px 0 6px;border-left:3px solid #2563eb;padding-left:8px;}
.card{background:#fff;border:1px solid #e2e6ec;border-radius:14px;padding:12px 14px;margin-bottom:8px;color:#1a2029;}
.up{color:#15883f;font-weight:700;} .dn{color:#d6342b;font-weight:700;} .mut{color:#6b7785;font-size:12px;}
.big{font-size:26px;font-weight:800;}
.hrow{display:flex;justify-content:space-between;align-items:center;padding:7px 2px;border-top:1px solid #eef0f3;font-size:14px;}
.hrow:first-child{border-top:none;}
.hrow .r{text-align:right;} .hrow .r .px{font-weight:700;} .hrow .r .pl{font-size:11px;}
.flag{font-size:11px;font-weight:700;padding:1px 5px;border-radius:4px;margin-right:5px;}
.fus{background:#e6effd;color:#2563eb;} .ftw{background:#e3f4ea;color:#15883f;}
.tag{display:inline-block;font-size:12px;font-weight:800;}
</style>
""", unsafe_allow_html=True)

now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
st.markdown(f"<div style='font-size:24px;font-weight:800;line-height:1.6;padding-top:4px'>市場觀察 "
            f"<span class='mut' style='font-weight:400'>{now:%Y/%m/%d %H:%M} 台北</span></div>",
            unsafe_allow_html=True)

# ============ 大盤 ============
st.markdown("<div class='sec'>大盤概覽</div>", unsafe_allow_html=True)
cols = st.columns(3)
for i, (name, sym) in enumerate(INDICES):
    price, prev = quotes.get(sym, (None, None))
    chg = (price - prev) / prev * 100 if price and prev else None
    with cols[i % 3]:
        st.metric(name, fmt(price, 2), pct(chg) if chg is not None else None)

# ============ 持股 ============
st.markdown(f"<div class='sec'>我的持股　<span class='mut' style='font-weight:400'>來源：{HSRC}</span></div>",
            unsafe_allow_html=True)
if HSRC == "內建清單" and HDBG:
    with st.expander("持股讀取除錯（點開看原因）"):
        st.code(HDBG)

def build_rows(holdings, is_tw):
    rows, tv, tt = [], 0.0, 0.0
    for name, sym, qty in holdings:
        price, prev = quotes.get(sym, (None, None))
        if price is None:
            rows.append((name, sym, qty, None, None, None, None)); continue
        mult = 1000 if is_tw else 1
        dpx = price - (prev or price); dpct = (dpx / prev * 100) if prev else 0.0
        v = qty * mult * price; t = qty * mult * dpx
        tv += v; tt += t
        rows.append((name, sym, qty, price, dpx, dpct, t))
    return rows, tv, tt

tw_rows, tw_val, tw_today = build_rows(TW_HOLDINGS, True)
us_rows, us_val, us_today = build_rows(US_HOLDINGS, False)
total = tw_val + us_val * fx; total_today = tw_today + us_today * fx
tp = (total_today / (total - total_today) * 100) if total - total_today else 0
cls = "up" if total_today >= 0 else "dn"
st.markdown(f"<div class='card'><div class='mut'>總市值（台幣）</div><div class='big'>NT$ {fmt(total)}</div>"
            f"<div>今日合計 <span class='{cls}'>{total_today:+,.0f}（{tp:+.2f}%）</span></div></div>",
            unsafe_allow_html=True)
c1, c2 = st.columns(2)
c1.metric(f"台股 ({len(TW_HOLDINGS)})", f"NT${fmt(tw_val)}",
          f"{tw_today:+,.0f} / {tw_today/(tw_val-tw_today)*100:+.2f}%" if tw_val - tw_today else None)
c2.metric("美股 (USD)", f"${fmt(us_val)}",
          f"{us_today:+,.0f} / {us_today/(us_val-us_today)*100:+.2f}%" if us_val - us_today else None)

def render_rows(rows, is_tw, head):
    unit = "張" if is_tw else "股"; cur = "" if is_tw else "$"
    html = f"<div class='mut' style='margin-top:6px'>{head}</div>"
    for name, sym, qty, price, dpx, dpct, t in rows:
        code = sym[:-3] if is_tw else sym
        if price is None:
            html += (f"<div class='hrow'><span>{name} <span class='mut'>{code} · {qty}{unit}</span></span>"
                     f"<span class='r mut'>—</span></div>"); continue
        c = "up" if dpx >= 0 else "dn"
        html += (f"<div class='hrow'><span>{name} <span class='mut'>{code} · {qty}{unit}</span></span>"
                 f"<span class='r'><span class='px'>{price:,.2f}</span> "
                 f"<span class='{c}'>{dpx:+.2f} / {dpct:+.2f}%</span>"
                 f"<div class='pl mut'>當日 <span class='{c}'>{cur}{t:+,.0f}</span></div></span></div>")
    return html

st.markdown("<div class='card'>" + render_rows(tw_rows, True, "台股")
            + render_rows(us_rows, False, "美股") + "</div>", unsafe_allow_html=True)

# ============ 情緒 / 領先 ============
st.markdown("<div class='sec'>情緒 / 領先指標</div>", unsafe_allow_html=True)
g1, g2 = st.columns(2)
with g1:
    if fg:
        rmap = {"extreme fear": "極度恐懼", "fear": "恐懼", "neutral": "中性",
                "greed": "貪婪", "extreme greed": "極度貪婪"}
        col = "#d6342b" if fg["score"] < 45 else ("#8a7d2a" if fg["score"] <= 55 else "#15883f")
        st.markdown(f"<div class='card'><div class='mut'>CNN Fear &amp; Greed</div>"
                    f"<div class='big' style='color:{col}'>{fg['score']}</div>"
                    f"<div style='color:{col};font-weight:700'>{rmap.get(fg['rating'], fg['rating'])}</div>"
                    f"<div class='mut'>前收 {fg['close']} · 一週 {fg['wk']} · 一月 {fg['mo']}</div></div>",
                    unsafe_allow_html=True)
    else:
        st.markdown("<div class='card mut'>Fear &amp; Greed 讀取失敗</div>", unsafe_allow_html=True)
with g2:
    vixp = quotes.get("^VIX", (None, None))[0]
    vtag = "平穩" if (vixp and vixp < 20) else ("中性" if (vixp and vixp < 28) else "升高")
    st.markdown(f"<div class='card'><div class='mut'>VIX 波動率</div><div class='big'>{fmt(vixp,2)}</div>"
                f"<div class='mut'>{vtag}</div></div>", unsafe_allow_html=True)

p1, p2 = st.columns(2)
with p1:
    if pc_oi:
        lab, c = pc_sentiment(pc_oi, "tw")
        st.markdown(f"<div class='card'><div class='mut'>台指期 Put/Call <span class='tag {c}'>{lab}</span></div>"
                    f"<div class='big'>{pc_oi:.2f}</div>"
                    f"<div class='mut'>未平倉比 · 成交量 {pc_vol:.2f}（{pc_date}）</div></div>",
                    unsafe_allow_html=True)
    else:
        st.markdown("<div class='card mut'>台指期 Put/Call 讀取失敗</div>", unsafe_allow_html=True)
with p2:
    us_pc = fg.get("us_pc") if fg else None
    if us_pc is not None:
        lab, c = pc_sentiment(us_pc, "us")
        st.markdown(f"<div class='card'><div class='mut'>美股 Put/Call <span class='tag {c}'>{lab}</span></div>"
                    f"<div class='big'>{us_pc:.2f}</div>"
                    f"<div class='mut'>CBOE 5日（CNN）</div></div>", unsafe_allow_html=True)
    else:
        st.markdown("<div class='card mut'>美股 Put/Call 讀取失敗</div>", unsafe_allow_html=True)

st.caption("Put/Call 判讀門檻 — 美股(CBOE)：≥1.05 偏空避險、≤0.70 偏多樂觀、之間中性；"
           "台指期(未平倉比)：≥1.30 偏空、≤1.00 偏多、之間中性。極端值常為反向訊號。")

if y10 and y2:
    spread = y10 - y2
    last_inv = dt.date(2024, 9, 5)
    months = (now.date().year - last_inv.year) * 12 + (now.date().month - last_inv.month)
    tag = "倒掛" if spread < 0 else "未倒掛"
    st.markdown(f"<div class='card'><div class='mut'>殖利率曲線 10Y-2Y（{ydate}）</div>"
                f"<div class='big'>{spread:+.2f}% <span class='mut' style='font-size:14px'>{tag}</span></div>"
                f"<div class='mut'>10Y {y10:.2f}% · 2Y {y2:.2f}%　|　最後倒掛 2024/9，距今約 {months} 個月</div></div>",
                unsafe_allow_html=True)

# ============ 經濟日曆 ============
st.markdown("<div class='sec'>經濟日曆（台北時間）</div>", unsafe_allow_html=True)
cal = "<div class='card'>"
for when, flag, name, imp, note in gen_calendar(now):
    fcls = "fus" if flag == "us" else "ftw"; flab = "美" if flag == "us" else "台"
    cal += (f"<div class='hrow'><span><span class='flag {fcls}'>{flab}</span>"
            f"<b>{when[5:]}</b> {name}</span>"
            f"<span class='mut'>{imp}{(' · ' + note) if note else ''}</span></div>")
cal += "</div>"
st.markdown(cal, unsafe_allow_html=True)

st.caption("資料：Yahoo Finance（延遲約15分）· FRED · CNN · TAIFEX。CPI/PPI 日期為約略，以官方為準。非投資建議。")
if st.button("重新整理"):
    st.cache_data.clear(); st.rerun()
