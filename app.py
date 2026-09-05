
import streamlit as st
import pandas as pd
import feedparser
import yfinance as yf
from urllib.parse import quote_plus
from datetime import datetime, timezone, timedelta
import re

st.set_page_config(
    page_title="材料株ニュース監視",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
/* Mobile-first layout */
.block-container {padding-top: 1rem; padding-bottom: 2rem; max-width: 1100px;}
h1 {font-size: clamp(1.55rem, 7vw, 2.4rem) !important;}
h2 {font-size: clamp(1.25rem, 5.5vw, 1.8rem) !important;}
h3 {font-size: clamp(1.05rem, 4.8vw, 1.45rem) !important;}
[data-testid="stMetric"] {border: 1px solid rgba(128,128,128,.22); padding: .7rem; border-radius: .8rem;}
[data-testid="stDataFrame"] {font-size: .9rem;}
a {word-break: break-word;}
@media (max-width: 640px) {
  .block-container {padding-left: .75rem; padding-right: .75rem;}
  [data-testid="column"] {min-width: 0 !important;}
  div[data-testid="stHorizontalBlock"] {gap: .45rem;}
  .stButton button {width: 100%;}
}
</style>
""", unsafe_allow_html=True)

THEMES = {
    "レアアース": {
        "keywords": [
            "レアアース", "希土類", "南鳥島", "レアアース泥", "重要鉱物",
            "JAMSTEC", "採泥", "揚泥", "深海資源", "中国 輸出規制"
        ],
        "stocks": {
            "6330.T": {"name":"東洋エンジニアリング","direct":["南鳥島","レアアース泥","JAMSTEC","採泥","揚泥","深海資源"]},
            "6269.T": {"name":"三井海洋開発","direct":["海洋資源","深海","海底"]},
            "5724.T": {"name":"アサカ理研","direct":["レアアース","希土類","リサイクル"]},
            "4082.T": {"name":"第一稀元素化学工業","direct":["希土類","レアアース"]},
            "5713.T": {"name":"住友金属鉱山","direct":["重要鉱物","非鉄","レアアース"]},
        },
    },
    "半導体": {
        "keywords": [
            "半導体", "AI半導体", "HBM", "EUV", "Rapidus", "TSMC", "NVIDIA",
            "メモリ", "半導体製造装置", "先端パッケージ", "輸出規制 半導体"
        ],
        "stocks": {
            "8035.T": {"name":"東京エレクトロン","direct":["半導体製造装置","EUV","TSMC"]},
            "6857.T": {"name":"アドバンテスト","direct":["半導体テスト","AI半導体","NVIDIA"]},
            "6146.T": {"name":"ディスコ","direct":["半導体製造装置","研削","切断"]},
            "6920.T": {"name":"レーザーテック","direct":["EUV","マスク","半導体"]},
            "7735.T": {"name":"SCREENホールディングス","direct":["洗浄装置","半導体製造装置"]},
            "285A.T": {"name":"キオクシアホールディングス","direct":["NAND","メモリ","半導体"]},
            "6526.T": {"name":"ソシオネクスト","direct":["SoC","AI半導体","先端半導体"]},
        },
    },
    "宇宙": {
        "keywords": [
            "宇宙", "衛星", "ロケット", "H3", "JAXA", "宇宙戦略基金",
            "月面", "SpaceX", "防衛衛星", "小型衛星", "宇宙輸送"
        ],
        "stocks": {
            "7011.T": {"name":"三菱重工業","direct":["H3","ロケット","JAXA","宇宙輸送"]},
            "7013.T": {"name":"IHI","direct":["ロケット","宇宙","衛星"]},
            "9348.T": {"name":"ispace","direct":["月面","月着陸","月資源"]},
            "5595.T": {"name":"QPS研究所","direct":["SAR衛星","小型衛星","衛星"]},
            "290A.T": {"name":"Synspective","direct":["SAR衛星","小型衛星","衛星"]},
        },
    },
}

POSITIVE = ["採択","受注","契約","成功","開始","増額","支援","投資","補助","実証","量産","増産","供給","承認","提携","開発"]
NEGATIVE = ["延期","中止","失敗","下方修正","赤字","損失","事故","不具合","規制強化","減産","撤退","訴訟","停止"]

def google_news_rss(query, max_items=20):
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=ja&gl=JP&ceid=JP:ja"
    feed = feedparser.parse(url)
    out = []
    for e in feed.entries[:max_items]:
        published = getattr(e, "published", "")
        out.append({
            "title": e.title,
            "link": e.link,
            "published": published,
            "source": getattr(getattr(e, "source", None), "title", "") if hasattr(e, "source") else "",
        })
    return out

def sentiment(title):
    p = sum(1 for k in POSITIVE if k in title)
    n = sum(1 for k in NEGATIVE if k in title)
    if p > n:
        return "🟢 プラス"
    if n > p:
        return "🔴 マイナス"
    return "⚪ 中立"

def score_news(title, theme):
    score = 1
    strong = ["受注","採択","契約","成功","政府","経済産業省","内閣府","JAMSTEC","JAXA","量産","実証","輸出規制"]
    score += min(2, sum(1 for k in strong if k in title))
    direct_hits = 0
    for ticker, meta in THEMES[theme]["stocks"].items():
        direct_hits += sum(1 for k in meta["direct"] if k in title)
    if direct_hits:
        score += 1
    if any(k in title for k in ["大型","数千億","国家","国策","世界初","商業化"]):
        score += 1
    return min(score, 5)

def related_stocks(title, theme):
    results = []
    for ticker, meta in THEMES[theme]["stocks"].items():
        hits = [k for k in meta["direct"] if k in title]
        if hits:
            rel = 5 if len(hits) >= 2 else 4
        elif any(k in title for k in THEMES[theme]["keywords"]):
            rel = 2
        else:
            continue
        results.append((ticker, meta["name"], rel))
    return sorted(results, key=lambda x: -x[2])[:5]

@st.cache_data(ttl=300)
def quote_table(tickers):
    rows = []
    for ticker, name in tickers:
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="5d", interval="1d")
            if hist.empty:
                continue
            last = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else last
            change = (last / prev - 1) * 100 if prev else 0
            vol = int(hist["Volume"].iloc[-1]) if "Volume" in hist else 0
            rows.append({"コード":ticker.replace(".T",""),"銘柄":name,"株価":round(last,1),"前日比%":round(change,2),"出来高":vol})
        except Exception:
            pass
    return pd.DataFrame(rows)

st.title("📡 材料株ニュース監視ダッシュボード")
st.caption("レアアース・半導体・宇宙のニュースを収集し、重要度・方向性・関連銘柄をまとめて確認します。")

theme = st.radio(
    "テーマ",
    list(THEMES.keys()),
    horizontal=True,
    label_visibility="collapsed"
)

with st.expander("🔧 絞り込み", expanded=False):
    c_filter1, c_filter2 = st.columns(2)
    with c_filter1:
        period = st.selectbox("検索範囲", ["直近24時間", "直近3日", "直近7日"], index=1)
    with c_filter2:
        min_score = st.slider("最低重要度", 1, 5, 2)
    st.caption("ニュース取得: Google News RSS / 株価: Yahoo Finance経由(yfinance)")
    st.warning("自動判定は投資判断ではありません。正式IR・一次情報を必ず確認してください。")

days_map = {"直近24時間":1, "直近3日":3, "直近7日":7}
query = "(" + " OR ".join(THEMES[theme]["keywords"][:8]) + f") when:{days_map[period]}d"

try:
    articles = google_news_rss(query, 50)
except Exception:
    articles = []

news_rows = []
for a in articles:
    s = score_news(a["title"], theme)
    if s < min_score:
        continue
    stocks = related_stocks(a["title"], theme)
    news_rows.append({
        **a,
        "score": s,
        "sentiment": sentiment(a["title"]),
        "stocks": stocks
    })

c1, c2, c3 = st.columns(3)
c1.metric("取得ニュース", len(news_rows))
c2.metric("★4以上", sum(1 for n in news_rows if n["score"] >= 4))
c3.metric("プラス判定", sum(1 for n in news_rows if n["sentiment"].startswith("🟢")))

st.subheader(f"{theme}ニュース")

if not news_rows:
    st.info("条件に合うニュースが取得できませんでした。ネット接続、検索範囲、重要度条件を確認してください。")
else:
    for n in news_rows[:25]:
        stars = "★" * n["score"] + "☆" * (5-n["score"])
        with st.container(border=True):
            st.markdown(f"### [{n['title']}]({n['link']})")
            st.write(f"**重要度:** {stars}　 **判定:** {n['sentiment']}")
            if n["published"]:
                st.caption(f"{n['published']}  {n['source']}")
            if n["stocks"]:
                labels = [f"{code.replace('.T','')} {name}（関連度 {'★'*rel}{'☆'*(5-rel)}）" for code,name,rel in n["stocks"]]
                st.write("**関連銘柄:** " + " / ".join(labels))
            else:
                st.write("**関連銘柄:** テーマ全体への材料")

st.subheader("監視銘柄の株価")
tickers = [(ticker, meta["name"]) for ticker, meta in THEMES[theme]["stocks"].items()]
df = quote_table(tickers)
if not df.empty:
    st.dataframe(df, use_container_width=True, hide_index=True, height=min(420, 40 + 36*len(df)))
else:
    st.info("株価データを取得できませんでした。")

st.subheader("材料を読むときの優先順位")
st.markdown("""
1. **企業の正式IR・受注・採択** → 最優先  
2. **政府・省庁・JAMSTEC/JAXA等の一次情報**  
3. **大手報道機関の速報**  
4. テーマ連想・解説記事  
5. SNS・掲示板  

「ニュースが大きい」ことと「その会社の利益が増える」ことは別です。  
特に国策テーマは、**具体的な受注額・契約相手・利益寄与時期**を確認してください。
""")
