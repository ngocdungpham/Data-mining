"""
collection_news_api.py - Mo phong quy trinh cao tin 2 giai doan cua FNSPID, dung API Finnhub cho giai doan 1.

  Giai doan 1 (API Finnhub): ma co phieu -> tieu de + URL + tom tat + ngay + nguon
  Giai doan 2 (mo URL bai):  lay NOI DUNG bai cho mot MAU NHO, theo cac quy tac ton trong website:
      - doc robots.txt cua TUNG ten mien truoc khi mo bai (ke ca moi buoc chuyen huong)
      - giu khoang cach giua cac request den cung mot ten mien (toi thieu MIN_DOMAIN_GAP, hoac Crawl-delay neu lon hon)
      - tu nhan dien minh bang User-Agent trung thuc (khong gia lam trinh duyet)
      - bi tu choi (403/401/402/429, robots cam, trang tra phi) thi BO QUA, khong tim cach lach;
        2 lan bi tu choi lien tiep o mot ten mien thi bo han ten mien do
  Ket qua giong bai bao: chi mot phan bai co noi dung (bai goc: khoang 25%).

CACH DUNG: mo file trong VS Code, bam Run. Nhap Finnhub API key khi duoc hoi
(hoac dat bien moi truong FINNHUB_API_KEY, hoac file finnhub_key.txt canh file nay). Dung dua key len GitHub.

Ket qua trong output/:
  news_finnhub.csv       cot: Symbol, Date, Headline, URL, Text, Summary, Source, TextStatus
  news_finnhub_log.txt   nhat ky chay + thong ke theo trang thai / ten mien
"""
import importlib
import json
import os
import random
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib import robotparser

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def ensure(pkg, module=None):
    try:
        importlib.import_module(module or pkg)
    except ImportError:
        print(f"Dang cai {pkg} (chi lan dau) ...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", pkg])


ensure("pandas")
import pandas as pd  # noqa: E402

# ============================== CAU HINH ==============================
# Danh sach mac dinh: 50 ma von hoa lon do MINH CHON (khong phai danh sach cua bai bao).
# Muon dung danh sach khac (vi du ca S&P 500): tao file tickers.txt canh script, moi dong mot ma.
TICKERS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "JPM", "LLY",
           "V", "UNH", "XOM", "MA", "COST", "HD", "PG", "JNJ", "NFLX", "ABBV",
           "WMT", "BAC", "CRM", "ORCL", "CVX", "KO", "MRK", "AMD", "PEP", "TMO",
           "ADBE", "ACN", "LIN", "MCD", "CSCO", "ABT", "WFC", "GE", "IBM", "DIS",
           "QCOM", "TXN", "CAT", "INTU", "VZ", "AMGN", "PFE", "NOW", "UBER", "GS"]
START_DATE = "2025-10-28"       # lay tin tu ngay nay ...
END_DATE = "2026-09-30"         # ... den het ngay nay
MAX_MB = 500                    # tran dung luong (tong tieu de + URL + tom tat + noi dung)
WINDOW_DAYS = 7                 # chia khoang ngay thanh cac cua so nho
SPLIT_AT = 200                  # cua so tra ve tu ngan nay tin tro len thi chia doi de tranh bi cat bot (phong doan)
CALL_GAP = 1.1                  # giay giua 2 lan goi API Finnhub
EMPTY_STOP = 6                  # gap bay nhieu cua so lien tiep khong co tin thi coi la het lich su cua goi
API = "https://finnhub.io/api/v1/company-news"

FULLTEXT_SAMPLE = 30            # so bai thu lay noi dung (giai doan 2). Dat 0 de tat
MAX_PER_DOMAIN = 10             # toi da bao nhieu bai tu moi ten mien
MIN_DOMAIN_GAP = 5              # giay toi thieu giua 2 request den cung ten mien
MIN_CHARS = 300                 # noi dung ngan hon muc nay coi la khong lay duoc (co the tra phi / tai bang JS)
CONTACT = ""                    # (nen dien) email lien he, se nam trong User-Agent de website biet ai dang truy cap
UA_NAME = "FNSPID-course-project"
OUT = Path(__file__).parent / "output"
KEY_FILE = Path(__file__).parent / "finnhub_key.txt"
PARTS = OUT / "finnhub_parts"       # moi ma luu 1 file de co the chay tiep neu bi ngat
# ======================================================================

UA = f"{UA_NAME}/1.0 (educational research" + (f"; contact: {CONTACT}" if CONTACT else "") + ")"
COLUMNS = ["Symbol", "Date", "Headline", "URL", "Text", "Summary", "Source", "TextStatus"]
LOG = []


class StopRun(Exception):
    pass


def log(msg):
    print(msg)
    LOG.append(msg)


# ----------------------------- GIAI DOAN 1: API -----------------------------
def get_key():
    key = os.environ.get("FINNHUB_API_KEY", "").strip()
    if not key and KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
    if not key:
        import getpass
        key = getpass.getpass("Nhap Finnhub API key (se khong hien ra khi go): ").strip()
    if not key:
        raise StopRun("Khong co API key.")
    return key


def fetch_json(url):
    """Goi API, tu thu lai khi bi gioi han toc do (429). Khong bao gio in token ra man hinh."""
    for _ in range(3):
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                log("  bi gioi han toc do (429), doi 65 giay roi thu lai ...")
                time.sleep(65)
                continue
            if e.code in (401, 403):
                raise StopRun(f"API tu choi (HTTP {e.code}): key sai, het han, hoac goi mien phi khong cho phep yeu cau nay.")
            raise StopRun(f"Loi HTTP {e.code} tu API.")
        except urllib.error.URLError as e:
            raise StopRun(f"Khong ket noi duoc toi API: {e.reason}")
    raise StopRun("Van bi gioi han toc do sau 3 lan thu.")


def get_news(symbol, start, end, key):
    q = urllib.parse.urlencode({"symbol": symbol, "from": start.isoformat(), "to": end.isoformat(), "token": key})
    data = fetch_json(f"{API}?{q}")
    if not isinstance(data, list):
        raise StopRun(f"API tra ve dinh dang la: {str(data)[:120]}")
    return data


def load_tickers():
    f = Path(__file__).parent / "tickers.txt"
    if f.exists():
        t = [x.strip().upper() for x in f.read_text(encoding="utf-8").splitlines() if x.strip() and not x.startswith("#")]
        if t:
            return t
    return TICKERS


def row_size(r):
    return sum(len(str(r[k]).encode()) for k in ("Headline", "URL", "Summary", "Text"))


def fetch_window(symbol, start, end, key):
    """Lay tin cua mot cua so ngay; neu tra ve qua nhieu (co the bi cat bot) thi chia doi va lay lai."""
    items = get_news(symbol, start, end, key)
    time.sleep(CALL_GAP)
    if len(items) >= SPLIT_AT and end > start:
        mid = start + (end - start) // 2
        log(f"    cua so {start}..{end} tra ve {len(items)} tin (>= {SPLIT_AT}), chia doi de tranh bi cat bot")
        return fetch_window(symbol, start, mid, key) + fetch_window(symbol, mid + timedelta(days=1), end, key)
    return items


def stage1(rows):
    tickers = load_tickers()
    PARTS.mkdir(parents=True, exist_ok=True)
    start_limit, end_limit = date.fromisoformat(START_DATE), date.fromisoformat(END_DATE)
    n_windows = ((end_limit - start_limit).days + 1) // WINDOW_DAYS + 1
    log(f"Giai doan 1: {len(tickers)} ma, {START_DATE} -> {END_DATE}, tran {MAX_MB} MB.")
    log(f"  Neu goi API co du lich su: toi da ~{len(tickers) * n_windows} lan goi (~{len(tickers) * n_windows * CALL_GAP / 3600:.1f} gio).")
    log("  Luu y: nhieu nguon mo ta goi mien phi chi cho lich su tin khoang 1 nam tinh tu hom nay;")
    log("  dong 'tin cu nhat lay duoc' o tung ma se cho biet goi cua ban lui duoc xa den dau.")
    size, key = 0, None
    for t in tickers:
        part = PARTS / f"{t}.csv"
        if part.exists():                    # chay tiep: ma nay da xong o lan truoc
            recs = pd.read_csv(part, keep_default_na=False, dtype=str).to_dict("records")
            rows.extend(recs)
            size += sum(row_size(r) for r in recs)
            log(f"[{t}] bo qua: da co {len(recs)} tin trong {part.name} (tong {size / 1e6:.1f} MB)")
            if size >= MAX_MB * 1e6:
                log(f"Da dat tran {MAX_MB} MB, dung.")
                return
            continue
        if key is None:
            key = get_key()
        rows_t, seen = [], set()
        end, empty_run, oldest = end_limit, 0, None
        log(f"[{t}] bat dau (lui dan tu {end} ve {START_DATE})")
        while end >= start_limit:
            start = max(end - timedelta(days=WINDOW_DAYS - 1), start_limit)
            items = fetch_window(t, start, end, key)
            added = 0
            for it in items:
                url = (it.get("url") or "").strip()
                head = (it.get("headline") or "").strip()
                if not url or not head or url in seen:
                    continue
                ts = it.get("datetime")
                d = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None
                if d and not (start_limit <= d.date() <= end_limit):
                    continue
                seen.add(url)
                r = {"Symbol": t, "Date": d.strftime("%Y-%m-%d %H:%M:%S") if d else "",
                     "Headline": head, "URL": url, "Text": "", "Summary": (it.get("summary") or "").strip(),
                     "Source": it.get("source") or "Finnhub", "TextStatus": "not_attempted"}
                rows_t.append(r)
                rows.append(r)
                size += row_size(r)
                added += 1
                if d and (oldest is None or d < oldest):
                    oldest = d
            log(f"  [{t}] {start}..{end}: {len(items)} tin tu API, them {added} (tong {size / 1e6:.1f} MB)")
            if size >= MAX_MB * 1e6:
                log(f"Da dat tran {MAX_MB} MB giua chung ma {t}, dung (ma nay chua hoan tat nen chua danh dau xong).")
                return
            empty_run = empty_run + 1 if not items else 0
            if empty_run >= EMPTY_STOP:
                log(f"  [{t}] {EMPTY_STOP} cua so lien tiep khong co tin: nhieu kha nang goi hien tai khong co lich su xa hon.")
                break
            end = start - timedelta(days=1)
        pd.DataFrame(rows_t, columns=COLUMNS).to_csv(part, index=False, encoding="utf-8")
        log(f"[{t}] xong giai doan 1: {len(rows_t)} tin; tin cu nhat lay duoc: {oldest.date() if oldest else 'khong co'}")


# ----------------------------- GIAI DOAN 2: NOI DUNG BAI -----------------------------
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(_NoRedirect)
ROBOTS = {}         # "scheme://host" -> (RobotFileParser hoac None, delay)
LAST_HIT = {}       # host -> thoi diem request cuoi
DOMAIN_COUNT = Counter()
DOMAIN_FAIL = Counter()


def http_robots(url):
    """Doc robots.txt (theo chuyen huong binh thuong). Tach rieng de de kiem thu."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", "replace")


def http_open(req):
    """Mo mot URL, KHONG tu theo chuyen huong (de kiem tra robots.txt o tung buoc). Tach rieng de de kiem thu."""
    return OPENER.open(req, timeout=20)


def robots_for(url):
    p = urllib.parse.urlparse(url)
    origin = f"{p.scheme}://{p.netloc}"
    if origin in ROBOTS:
        return ROBOTS[origin]
    rp = robotparser.RobotFileParser()
    try:
        rp.parse(http_robots(origin + "/robots.txt").splitlines())
        delay = rp.crawl_delay(UA_NAME) or rp.crawl_delay("*") or 0
        res = (rp, delay)
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            rp.parse([])
            res = (rp, 0)
        elif e.code in (401, 403):
            rp.parse(["User-agent: *", "Disallow: /"])
            res = (rp, 0)
        else:
            res = (None, 0)          # khong doc duoc: than trong, coi nhu khong duoc phep
    except Exception:
        res = (None, 0)
    ROBOTS[origin] = res
    return res


class TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "header", "footer", "nav", "aside", "form"}

    def __init__(self):
        super().__init__()
        self.skip, self.in_art, self.in_p = 0, 0, False
        self.cur, self.art, self.other = [], [], []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag == "article":
            self.in_art += 1
        elif tag == "p":
            self.in_p, self.cur = True, []

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag == "article":
            self.in_art = max(0, self.in_art - 1)
        elif tag == "p" and self.in_p:
            txt = " ".join("".join(self.cur).split())
            if len(txt) >= 40:
                (self.art if self.in_art else self.other).append(txt)
            self.in_p = False

    def handle_data(self, data):
        if self.in_p and not self.skip:
            self.cur.append(data)


def extract_text(html):
    p = TextExtractor()
    try:
        p.feed(html)
    except Exception:
        pass
    return "\n".join(p.art or p.other)


def polite_fetch(url, max_hops=5):
    """Tra ve (html, status). Kiem tra robots.txt o moi buoc chuyen huong, giu khoang cach theo ten mien."""
    for _ in range(max_hops):
        host = urllib.parse.urlparse(url).netloc
        if DOMAIN_FAIL[host] >= 2:
            return None, "domain_skipped"
        if DOMAIN_COUNT[host] >= MAX_PER_DOMAIN:
            return None, "domain_cap"
        rp, delay = robots_for(url)
        if rp is None or not rp.can_fetch(UA_NAME, url):
            DOMAIN_FAIL[host] += 1
            return None, "robots"
        gap = max(delay, MIN_DOMAIN_GAP) - (time.time() - LAST_HIT.get(host, 0))
        if gap > 0:
            time.sleep(gap)
        LAST_HIT[host] = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
        try:
            with http_open(req) as r:
                if "html" not in (r.headers.get("Content-Type") or "").lower():
                    return None, "not_html"
                raw = r.read(2_000_000)
                DOMAIN_COUNT[host] += 1
                return raw.decode(r.headers.get_content_charset() or "utf-8", "replace"), "ok"
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                loc = e.headers.get("Location")
                if not loc:
                    return None, "redirect_error"
                url = urllib.parse.urljoin(url, loc)
                continue
            if e.code in (401, 402, 403, 429):
                DOMAIN_FAIL[host] += 1
                return None, f"denied_{e.code}"
            return None, f"http_{e.code}"
        except Exception:
            return None, "error"
    return None, "too_many_redirects"


def stage2(rows):
    if FULLTEXT_SAMPLE <= 0 or not rows:
        return
    idx = random.Random(42).sample(range(len(rows)), min(FULLTEXT_SAMPLE, len(rows)))
    log(f"Giai doan 2: thu lay noi dung {len(idx)} bai (mau ngau nhien, co dinh seed). User-Agent: {UA}")
    for n, i in enumerate(idx, 1):
        r = rows[i]
        html, status = polite_fetch(r["URL"])
        if status == "ok":
            text = extract_text(html)
            if len(text) >= MIN_CHARS:
                r["Text"] = text
            else:
                status = "short"
        r["TextStatus"] = status
        host = urllib.parse.urlparse(r["URL"]).netloc
        log(f"  [{n}/{len(idx)}] {status:16} {host[:40]} | {r['Headline'][:50]}")


# ----------------------------- LUU KET QUA -----------------------------
def save(rows):
    df = pd.DataFrame(rows, columns=COLUMNS)
    df.to_csv(OUT / "news_finnhub.csv", index=False, encoding="utf-8")
    mb = (OUT / "news_finnhub.csv").stat().st_size / 1e6
    log(f"Da luu {len(df)} tin -> {OUT / 'news_finnhub.csv'} ({mb:.2f} MB)")
    if len(df):
        log(f"Khoang ngay: {df['Date'].min()} -> {df['Date'].max()}")
        log(f"Ty le co tom tat: {(df['Summary'] != '').mean():.3f}; do dai tom tat trung binh: {df['Summary'].str.len().mean():.0f} ky tu")
        log("So tin theo ma: " + ", ".join(f"{k}={v}" for k, v in df.groupby('Symbol').size().items()))
        tried = df[df["TextStatus"] != "not_attempted"]
        if len(tried):
            log(f"Giai doan 2: thu {len(tried)} bai, lay duoc noi dung {(tried['TextStatus'] == 'ok').sum()} bai "
                f"({(tried['TextStatus'] == 'ok').mean():.0%}). Trang thai: " +
                ", ".join(f"{k}={v}" for k, v in Counter(tried['TextStatus']).items()))
            log("Theo ten mien (so bai thu / lay duoc): " + "; ".join(
                f"{h}={g.shape[0]}/{(g['TextStatus'] == 'ok').sum()}"
                for h, g in tried.assign(host=tried['URL'].map(lambda u: urllib.parse.urlparse(u).netloc)).groupby('host')))
    else:
        log("Khong lay duoc tin nao. Xem ly do o cac dong log phia tren.")
    header = f"Chay luc {datetime.now():%Y-%m-%d %H:%M:%S} | ma: {TICKERS} | tu ngay: {START_DATE}\n"
    (OUT / "news_finnhub_log.txt").write_text(header + "\n".join(LOG), encoding="utf-8")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    rows = []
    try:
        stage1(rows)
        stage2(rows)
    except StopRun as e:
        log(f"DUNG: {e}")
    except KeyboardInterrupt:
        log("Da dung boi nguoi dung (Ctrl+C). Luu phan da lay duoc.")
    except Exception as e:
        log(f"DUNG do loi: {type(e).__name__}: {e}")
    finally:
        save(rows)
