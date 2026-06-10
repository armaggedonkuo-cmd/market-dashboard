# -*- coding: utf-8 -*-
"""
市場觀察面板 (Streamlit)
台美股市 + 持股淨值 + 領先/情緒指標 + 經濟日曆
資料源（皆免費、伺服器端抓取）：
  - 報價/指數/匯率：Yahoo Finance (yfinance)  ~延遲15分
  - 殖利率：FRED (DGS10/DGS2)
  - Fear & Greed：CNN
  - 台指期 Put/Call：TAIFEX
"""
import io
import datetime as dt
import requests
import pandas as pd
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="市場觀察", page_icon="chart", layout="centered")

# ============ 你的持股（要改就改這裡）============
# 台股：(顯示名, Yahoo代號, 張數)   1張=1000股
TW_HOLDINGS = [
    ("富邦金",        "2881.TW",  45.088),
    ("南亞",          "1303.TW",  13.0),
    ("台灣50",        "0050.TW",  152.792),
    ("台積電",        "2330.TW",  0.048),
    ("富邦采吉50",    "006208.TW", 73.672),
]
# 美股：(顯示名, Yahoo代號, 股數)
US_HOLDINGS = [
    ("VOO", "VOO", 148.95),
    ("VT",  "VT",  379.20),
    ("BND", "BND", 193.81),
]
# 大盤指數
INDICES = [
    ("加權",   "^TWII"),
    ("費半",   "^SOX"),
    ("S&P 500", "^GSPC"),
    ("Nasdaq", "^IXIC"),
    ("道瓊",   "^DJI"),
]

# ============ 資料抓取 ============
@st.cache_data(ttl=600, show_spinner=False)
def get_quotes(symbols):
    out = {}
    data = yf.Tickers(" ".join(symbols))
    for s in symbols:
        price = prev = None
        try:
            fi = data.tickers[s].fast_info
            price = float(fi.last_price)
            prev = float(fi.previous_close)
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
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        d = r.json()["fear_and_greed"]
        return {
            "score": round(d["score"]), "rating": d["rating"],
            "close": round(d["previous_close"]), "wk": round(d["previous_1_week"]),
            "mo": round(d["previous_1_month"]), "asof": d["timestamp"][:10],
        }
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

# ============ 工具 ============
def fmt(n, d=0):
    return f"{n:,.{d}f}" if n is not None else "—"

def pct(n):
    return f"{n:+.2f}%" if n is not None else "—"

# ============ 抓資料 ============
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
.hrow .r{text-align:right;}
.hrow .r .px{font-weight:700;}
.hrow .r .pl{font-size:11px;}
.flag{font-size:11px;font-weight:700;padding:1px 5px;border-radius:4px;margin-right:5px;}
.fus{background:#e6effd;color:#2563eb;} .ftw{background:#e3f4ea;color:#15883f;}
</style>
""", unsafe_allow_html=True)

now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
st.markdown(
    f"<div style='font-size:24px;font-weight:800;line-height:1.6;padding-top:4px'>市場觀察 "
    f"<span class='mut' style='font-weight:400'>{now:%Y/%m/%d %H:%M} 台北</span></div>",
    unsafe_allow_html=True)

# ============ 大盤 ============
st.markdown("<div class='sec'>大盤概覽</div>", unsafe_allow_html=True)
cols = st.columns(3)
disp = INDICES + [("VIX", "^VIX")]
for i, (name, sym) in enumerate(disp):
    price, prev = quotes.get(sym, (None, None))
    chg = (price - prev) / prev * 100 if price and prev else None
    with cols[i % 3]:
        st.metric(name, fmt(price, 2), pct(chg) if chg is not None else None)

# ============ 持股 ============
st.markdown("<div class='sec'>我的持股</div>", unsafe_allow_html=True)

def build_rows(holdings, is_tw):
    rows, tv, tt = [], 0.0, 0.0
    for name, sym, qty in holdings:
        price, prev = quotes.get(sym, (None, None))
        if price is None:
            rows.append((name, sym, qty, None, None, None, None)); continue
        mult = 1000 if is_tw else 1
        dpx = price - (prev or price)
        dpct = (dpx / prev * 100) if prev else 0.0
        v = qty * mult * price
        t = qty * mult * dpx
        tv += v; tt += t
        rows.append((name, sym, qty, price, dpx, dpct, t))
    return rows, tv, tt

tw_rows, tw_val, tw_today = build_rows(TW_HOLDINGS, True)
us_rows, us_val, us_today = build_rows(US_HOLDINGS, False)

total = tw_val + us_val * fx
total_today = tw_today + us_today * fx
tp = (total_today / (total - total_today) * 100) if total - total_today else 0
cls = "up" if total_today >= 0 else "dn"
st.markdown(
    f"<div class='card'><div class='mut'>總市值（台幣）</div><div class='big'>NT$ {fmt(total)}</div>"
    f"<div>今日合計 <span class='{cls}'>{total_today:+,.0f}（{tp:+.2f}%）</span></div></div>",
    unsafe_allow_html=True)

c1, c2 = st.columns(2)
c1.metric(f"台股 ({len(TW_HOLDINGS)})", f"NT${fmt(tw_val)}",
          f"{tw_today:+,.0f} / {tw_today/(tw_val-tw_today)*100:+.2f}%" if tw_val-tw_today else None)
c2.metric("美股 (USD)", f"${fmt(us_val)}",
          f"{us_today:+,.0f} / {us_today/(us_val-us_today)*100:+.2f}%" if us_val-us_today else None)

def render_rows(rows, is_tw, head):
    unit = "張" if is_tw else "股"
    cur = "" if is_tw else "$"
    html = f"<div class='mut' style='margin-top:6px'>{head}</div>"
    for name, sym, qty, price, dpx, dpct, t in rows:
        code = sym[:-3] if is_tw else sym
        if price is None:
            html += (f"<div class='hrow'><span>{name} <span class='mut'>{code} · {qty}{unit}</span></span>"
                     f"<span class='r mut'>—</span></div>")
            continue
        c = "up" if dpx >= 0 else "dn"
        pls = f"{cur}{t:+,.0f}"
        html += (
            f"<div class='hrow'><span>{name} <span class='mut'>{code} · {qty}{unit}</span></span>"
            f"<span class='r'>"
            f"<span class='px'>{price:,.2f}</span> "
            f"<span class='{c}'>{dpx:+.2f} / {dpct:+.2f}%</span>"
            f"<div class='pl mut'>當日 <span class='{c}'>{pls}</span></div>"
            f"</span></div>")
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
        st.markdown(
            f"<div class='card'><div class='mut'>CNN Fear &amp; Greed</div>"
            f"<div class='big' style='color:{col}'>{fg['score']}</div>"
            f"<div style='color:{col};font-weight:700'>{rmap.get(fg['rating'], fg['rating'])}</div>"
            f"<div class='mut'>前收 {fg['close']} · 一週 {fg['wk']} · 一月 {fg['mo']}</div></div>",
            unsafe_allow_html=True)
    else:
        st.markdown("<div class='card mut'>Fear &amp; Greed 讀取失敗</div>", unsafe_allow_html=True)
with g2:
    vixp = quotes.get("^VIX", (None, None))[0]
    pcs = f"未平倉 {pc_oi:.2f} · 成交量 {pc_vol:.2f}" if pc_oi else "讀取失敗"
    st.markdown(
        f"<div class='card'><div class='mut'>VIX</div><div class='big'>{fmt(vixp,2)}</div>"
        f"<div class='mut' style='margin-top:6px'>台指期 Put/Call</div><div style='font-weight:700'>{pcs}</div></div>",
        unsafe_allow_html=True)

# 殖利率曲線
if y10 and y2:
    spread = y10 - y2
    last_inv = dt.date(2024, 9, 5)
    months = (now.date().year - last_inv.year) * 12 + (now.date().month - last_inv.month)
    tag = "倒掛" if spread < 0 else "未倒掛"
    st.markdown(
        f"<div class='card'><div class='mut'>殖利率曲線 10Y-2Y（{ydate}）</div>"
        f"<div class='big'>{spread:+.2f}% <span class='mut' style='font-size:14px'>{tag}</span></div>"
        f"<div class='mut'>10Y {y10:.2f}% · 2Y {y2:.2f}%　|　最後倒掛 2024/9，距今約 {months} 個月</div></div>",
        unsafe_allow_html=True)

# ============ 經濟日曆 ============
st.markdown("<div class='sec'>經濟日曆（台北時間）</div>", unsafe_allow_html=True)
EVENTS = [
    ("2026-06-10 20:30", "us", "美國 CPI", "高", "預期 +3.2% / 前值 +3.4%"),
    ("2026-06-11 20:30", "us", "PPI、初領失業金", "中", ""),
    ("2026-06-16 20:30", "us", "零售銷售", "中", ""),
    ("2026-06-18 02:00", "us", "FOMC 利率決議+記者會", "高", "6/16-17 會議"),
    ("2026-06-18 16:00", "tw", "台灣央行理監事會", "高", "季度"),
    ("2026-07-10 16:00", "tw", "台股 6月營收截止", "中", ""),
]
nowstr = now.strftime("%Y-%m-%d %H:%M")
upcoming = [e for e in EVENTS if e[0] >= nowstr][:6]
cal = "<div class='card'>"
for when, flag, name, imp, note in (upcoming or EVENTS[:4]):
    fcls = "fus" if flag == "us" else "ftw"
    flab = "美" if flag == "us" else "台"
    cal += (f"<div class='hrow'><span><span class='flag {fcls}'>{flab}</span>"
            f"<b>{when[5:]}</b> {name}</span>"
            f"<span class='mut'>{imp}{(' · ' + note) if note else ''}</span></div>")
cal += "</div>"
st.markdown(cal, unsafe_allow_html=True)

st.caption("資料：Yahoo Finance（延遲約15分）· FRED · CNN · TAIFEX。僅供參考，非投資建議。")
if st.button("重新整理"):
    st.cache_data.clear()
    st.rerun()
