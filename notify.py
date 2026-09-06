
import os
import json
import hashlib
from pathlib import Path
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import feedparser

THEMES = {
    "レアアース": {
        "keywords": [
            "レアアース", "希土類", "南鳥島", "レアアース泥",
            "重要鉱物", "JAMSTEC", "採泥", "揚泥"
        ],
        "stocks": {
            "6330": ("東洋エンジニアリング", ["南鳥島","レアアース泥","JAMSTEC","採泥","揚泥","深海資源"]),
            "6269": ("三井海洋開発", ["海洋資源","深海","海底"]),
            "5724": ("アサカ理研", ["レアアース","希土類","リサイクル"]),
            "4082": ("第一稀元素化学工業", ["希土類","レアアース"]),
            "5713": ("住友金属鉱山", ["重要鉱物","非鉄","レアアース"]),
        },
    },
    "半導体": {
        "keywords": [
            "半導体", "AI半導体", "HBM", "EUV",
            "Rapidus", "TSMC", "NVIDIA", "半導体製造装置"
        ],
        "stocks": {
            "8035": ("東京エレクトロン", ["半導体製造装置","EUV","TSMC"]),
            "6857": ("アドバンテスト", ["半導体テスト","AI半導体","NVIDIA"]),
            "6146": ("ディスコ", ["半導体製造装置","研削","切断"]),
            "6920": ("レーザーテック", ["EUV","マスク","半導体"]),
            "7735": ("SCREENホールディングス", ["洗浄装置","半導体製造装置"]),
            "285A": ("キオクシアホールディングス", ["NAND","メモリ","半導体"]),
            "6526": ("ソシオネクスト", ["SoC","AI半導体","先端半導体"]),
        },
    },
    "宇宙": {
        "keywords": [
            "宇宙", "衛星", "ロケット", "H3",
            "JAXA", "宇宙戦略基金", "月面", "SpaceX"
        ],
        "stocks": {
            "7011": ("三菱重工業", ["H3","ロケット","JAXA","宇宙輸送"]),
            "7013": ("IHI", ["ロケット","宇宙","衛星"]),
            "9348": ("ispace", ["月面","月着陸","月資源"]),
            "5595": ("QPS研究所", ["SAR衛星","小型衛星","衛星"]),
            "290A": ("Synspective", ["SAR衛星","小型衛星","衛星"]),
        },
    },
}

POSITIVE = ["採択","受注","契約","成功","開始","増額","支援","投資","補助","実証","量産","増産","供給","承認","提携","開発"]
NEGATIVE = ["延期","中止","失敗","下方修正","赤字","損失","事故","不具合","規制強化","減産","撤退","訴訟","停止"]
STRONG = ["受注","採択","契約","成功","政府","経済産業省","内閣府","JAMSTEC","JAXA","量産","実証","輸出規制"]
VERY_STRONG = ["大型","数千億","国家","国策","世界初","商業化"]

STATE_PATH = Path(".notification_state.json")
MAX_STATE = 500

def google_news_rss(query, max_items=40):
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=ja&gl=JP&ceid=JP:ja"
    feed = feedparser.parse(url)
    rows = []
    for e in feed.entries[:max_items]:
        source = ""
        try:
            source = e.source.title
        except Exception:
            pass
        rows.append({
            "title": e.title,
            "link": e.link,
            "published": getattr(e, "published", ""),
            "source": source,
        })
    return rows

def score_news(title, theme):
    score = 1
    score += min(2, sum(1 for k in STRONG if k in title))
    direct_hits = 0
    for _, (_, terms) in THEMES[theme]["stocks"].items():
        direct_hits += sum(1 for k in terms if k in title)
    if direct_hits:
        score += 1
    if any(k in title for k in VERY_STRONG):
        score += 1
    return min(score, 5)

def direction(title):
    p = sum(1 for k in POSITIVE if k in title)
    n = sum(1 for k in NEGATIVE if k in title)
    if p > n:
        return "🟢 プラス材料"
    if n > p:
        return "🔴 マイナス材料"
    return "⚪ 中立"

def related_stocks(title, theme):
    rows = []
    for code, (name, terms) in THEMES[theme]["stocks"].items():
        hits = [k for k in terms if k in title]
        if hits:
            rel = 5 if len(hits) >= 2 else 4
            rows.append((code, name, rel))
    return sorted(rows, key=lambda x: -x[2])[:5]

def parse_published(text):
    if not text:
        return None
    try:
        dt = parsedate_to_datetime(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None

def load_state():
    if not STATE_PATH.exists():
        return []
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []

def save_state(items):
    STATE_PATH.write_text(
        json.dumps(items[-MAX_STATE:], ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

def article_id(theme, title, link):
    return hashlib.sha256(f"{theme}|{title}|{link}".encode("utf-8")).hexdigest()

def telegram_send(text):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urlencode({
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "false",
    }).encode("utf-8")
    req = Request(url, data=payload, method="POST")
    with urlopen(req, timeout=20) as response:
        if response.status != 200:
            raise RuntimeError(response.read().decode("utf-8"))

def main():
    min_score = int(os.environ.get("NOTIFY_MIN_SCORE", "4"))
    lookback_minutes = int(os.environ.get("LOOKBACK_MINUTES", "20"))
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=lookback_minutes)

    sent_ids = load_state()
    sent_set = set(sent_ids)
    newly_sent = []

    for theme, cfg in THEMES.items():
        query = "(" + " OR ".join(cfg["keywords"]) + ") when:1d"
        for article in google_news_rss(query):
            published = parse_published(article["published"])
            if published and published < cutoff:
                continue

            score = score_news(article["title"], theme)
            if score < min_score:
                continue

            aid = article_id(theme, article["title"], article["link"])
            if aid in sent_set:
                continue

            stocks = related_stocks(article["title"], theme)
            stock_text = " / ".join(
                f"{code} {name}（関連度 {'★'*rel}{'☆'*(5-rel)}）"
                for code, name, rel in stocks
            ) or "テーマ全体"

            stars = "★" * score + "☆" * (5-score)
            message = (
                "🚨 強い材料を検知\n\n"
                f"【{theme}】{stars}\n"
                f"{direction(article['title'])}\n\n"
                f"{article['title']}\n\n"
                f"関連銘柄: {stock_text}\n"
                f"出所: {article['source'] or 'Google News'}\n"
                f"{article['link']}"
            )
            telegram_send(message)
            newly_sent.append(aid)
            sent_set.add(aid)

    if newly_sent:
        save_state(sent_ids + newly_sent)
        print(f"sent {len(newly_sent)} alert(s)")
    else:
        print("no new strong material")

if __name__ == "__main__":
    main()
