"""
collection_content.py - PHAN 2: lay NOI DUNG bai bao (giai doan 2 cua quy trinh FNSPID).

  Vao : output/headlines.csv  (do collection_headlines.py tao ra)
  Ra  : output/content.csv  chi 4 cot: Date, Url, Text, Mark
          Mark = ket qua thu lay noi dung cua bai do:
            ok               lay duoc noi dung (cot Text co van ban)
            short            mo duoc trang nhung noi dung qua ngan (co the tra phi / tai bang JavaScript)
            robots           robots.txt khong cho phep (hoac khong doc duoc robots.txt)
            denied_403 ...   website tu choi (401/402/403/429)
            domain_skipped / domain_cap / not_html / error / http_xxx ...  cac ly do khac
            not_attempted    chua thu (chi xuat hien neu INCLUDE_NOT_ATTEMPTED = True)
        output/content_log.txt  nhat ky + thong ke theo trang thai / ten mien
        output/content_cache/content_results.csv  bo nho dem tung bai da thu (de chay tiep, khong phai ket qua nop)

Chi thu mot MAU NHO (FULLTEXT_SAMPLE bai, phan tang theo nguon tin), theo cac quy tac ton trong website:
  - doc robots.txt cua TUNG ten mien truoc khi mo bai (ke ca moi buoc chuyen huong)
  - giu khoang cach giua cac request den cung mot ten mien (toi thieu MIN_DOMAIN_GAP, hoac Crawl-delay neu lon hon)
  - tu nhan dien bang User-Agent trung thuc (khong gia lam trinh duyet)
  - bi tu choi (403/401/402/429, robots cam, trang tra phi) thi BO QUA, khong tim cach lach;
    2 lan bi tu choi lien tiep o mot ten mien thi bo han ten mien do trong lan chay nay
Ket qua giong bai bao: chi mot phan bai co noi dung (bai goc: khoang 25%).

CACH DUNG: mo file trong VS Code, bam Run (khong can API key). Tang FULLTEXT_SAMPLE tu tu va chay lai:
cac bai da thu o lan truoc duoc giu nguyen, chi thu them bai moi.
"""
import importlib
import random
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime
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
FULLTEXT_SAMPLE = 30            # tong so bai thu lay noi dung (tang dan: 30 -> 100 -> ...)
MAX_PER_DOMAIN = 10             # toi da bao nhieu bai tu moi ten mien trong mot lan chay
MIN_DOMAIN_GAP = 5              # giay toi thieu giua 2 request den cung ten mien
MIN_CHARS = 300                 # noi dung ngan hon muc nay coi la khong lay duoc (co the tra phi / tai bang JS)
SAVE_EVERY = 5                  # luu tien do sau moi N bai
INCLUDE_NOT_ATTEMPTED = False   # False: content.csv chi gom cac bai da thu; True: gom ca bai chua thu (Mark = not_attempted)
CONTACT = ""                    # (nen dien) email lien he, se nam trong User-Agent de website biet ai dang truy cap
UA_NAME = "FNSPID-course-project"
def find_out():
    """Thu muc output DUNG CHUNG: neu thu muc cha cua script da co 'output' thi dung no (script nam trong thu muc con),
    nguoc lai dung 'output' canh script."""
    here = Path(__file__).resolve().parent
    return here.parent / "output" if (here.parent / "output").is_dir() else here / "output"


OUT = find_out()
# ======================================================================

HEAD = OUT / "headlines.csv"
RES = OUT / "content_cache" / "content_results.csv"
UA = f"{UA_NAME}/1.0 (educational research" + (f"; contact: {CONTACT}" if CONTACT else "") + ")"
LOG = []


class StopRun(Exception):
    pass


def log(msg):
    print(msg)
    LOG.append(msg)


# ----------------------------- MANG (tach rieng de de kiem thu) -----------------------------
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(_NoRedirect)
ROBOTS = {}         # "scheme://host" -> (RobotFileParser hoac None, delay)
LAST_HIT = {}       # host -> thoi diem request cuoi
DOMAIN_COUNT = Counter()
DOMAIN_FAIL = Counter()


def http_robots(url):
    """Doc robots.txt (theo chuyen huong binh thuong)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", "replace")


def http_open(req):
    """Mo mot URL, KHONG tu theo chuyen huong (de kiem tra robots.txt o tung buoc)."""
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


# ----------------------------- TRICH XUAT NOI DUNG -----------------------------
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
    """Tra ve (html, status, host_cuoi). Kiem tra robots.txt o moi buoc chuyen huong, giu khoang cach theo ten mien."""
    host = urllib.parse.urlparse(url).netloc
    for _ in range(max_hops):
        host = urllib.parse.urlparse(url).netloc
        if DOMAIN_FAIL[host] >= 2:
            return None, "domain_skipped", host
        if DOMAIN_COUNT[host] >= MAX_PER_DOMAIN:
            return None, "domain_cap", host
        rp, delay = robots_for(url)
        if rp is None:                       # khong doc duoc robots.txt cua ten mien nay: bo ten mien, khong mo bai
            DOMAIN_FAIL[host] += 2
            return None, "robots", host
        if not rp.can_fetch(UA_NAME, url):   # robots.txt cam duong dan nay: bo bai nay (khong gui request nao)
            return None, "robots", host
        gap = max(delay, MIN_DOMAIN_GAP) - (time.time() - LAST_HIT.get(host, 0))
        if gap > 0:
            time.sleep(gap)
        LAST_HIT[host] = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
        try:
            with http_open(req) as r:
                if "html" not in (r.headers.get("Content-Type") or "").lower():
                    return None, "not_html", host
                raw = r.read(2_000_000)
                DOMAIN_COUNT[host] += 1
                return raw.decode(r.headers.get_content_charset() or "utf-8", "replace"), "ok", host
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                loc = e.headers.get("Location")
                if not loc:
                    return None, "redirect_error", host
                url = urllib.parse.urljoin(url, loc)
                continue
            if e.code in (401, 402, 403, 429):
                DOMAIN_FAIL[host] += 1
                return None, f"denied_{e.code}", host
            return None, f"http_{e.code}", host
        except Exception:
            return None, "error", host
    return None, "too_many_redirects", host


# ----------------------------- CHON MAU + CHAY -----------------------------
def pick_sample(rows, n):
    """Mau phan tang theo NGUON (Yahoo, Benzinga, ...), thu tu co dinh: n lon hon thi chi them bai moi o cuoi."""
    rnd = random.Random(42)
    groups = {}
    for i, r in enumerate(rows):
        groups.setdefault(r.get("Source", ""), []).append(i)   # khong co cot Source thi chi la 1 nhom (chon ngau nhien)
    for g in groups.values():
        rnd.shuffle(g)
    order = list(groups)
    rnd.shuffle(order)
    out = []
    while len(out) < n and any(groups.values()):
        for src in order:
            if groups[src] and len(out) < n:
                out.append(groups[src].pop())
    return out


def load_headlines():
    if not HEAD.exists():
        raise StopRun("Chua co output/headlines.csv. Hay chay collection_headlines.py (phan 1) truoc.")
    df = pd.read_csv(HEAD, keep_default_na=False, dtype=str, encoding="utf-8-sig")
    for c in ("Date", "Headline", "URL"):
        if c not in df.columns:
            raise StopRun(f"headlines.csv thieu cot {c}.")
    return df.to_dict("records")


def load_results():
    if not RES.exists():
        return {}
    df = pd.read_csv(RES, keep_default_na=False, dtype=str)
    return {r["URL"]: r for r in df.to_dict("records")}


def save_results(results):
    RES.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(list(results.values()), columns=["URL", "TextStatus", "Host", "Text"]).to_csv(
        RES, index=False, encoding="utf-8")


def run(rows, results):
    if FULLTEXT_SAMPLE <= 0:
        raise StopRun("FULLTEXT_SAMPLE = 0: khong lay noi dung.")
    idx = pick_sample(rows, min(FULLTEXT_SAMPLE, len(rows)))
    todo = [i for i in idx if rows[i]["URL"] not in results]
    n_src = len({rows[i].get("Source", "") for i in idx})
    log(f"Phan 2 (noi dung): {len(rows)} headline; mau {len(idx)} bai ({n_src} nhom nguon); da thu truoc do {len(idx) - len(todo)}, "
        f"con {len(todo)} bai can thu.")
    log(f"  User-Agent: {UA}")
    for n, i in enumerate(todo, 1):
        r = rows[i]
        html, status, host = polite_fetch(r["URL"])
        text = ""
        if status == "ok":
            text = extract_text(html)
            if len(text) < MIN_CHARS:
                status, text = "short", ""
        results[r["URL"]] = {"URL": r["URL"], "TextStatus": status, "Host": host, "Text": text}
        log(f"  [{n}/{len(todo)}] {status:16} {host[:40]} | {r['Headline'][:50]}")
        if n % SAVE_EVERY == 0:
            save_results(results)


def save(rows, results):
    save_results(results)
    df = pd.DataFrame(rows)
    df["Url"] = df["URL"]
    df["Text"] = df["URL"].map(lambda u: results.get(u, {}).get("Text", ""))
    df["Mark"] = df["URL"].map(lambda u: results.get(u, {}).get("TextStatus", "not_attempted"))
    df["Host"] = df["URL"].map(lambda u: results.get(u, {}).get("Host", ""))
    tried = df[df["Mark"] != "not_attempted"]
    out = df if INCLUDE_NOT_ATTEMPTED else tried
    out[["Date", "Url", "Text", "Mark"]].to_csv(OUT / "content.csv", index=False, encoding="utf-8-sig")
    mb = (OUT / "content.csv").stat().st_size / 1e6
    log(f"Da luu {len(out)} dong -> {OUT / 'content.csv'} ({mb:.2f} MB), cot: Date, Url, Text, Mark")
    if len(tried):
        log(f"Da thu {len(tried)} bai, lay duoc noi dung {(tried['Mark'] == 'ok').sum()} bai ({(tried['Mark'] == 'ok').mean():.0%}). "
            "Mark: " + ", ".join(f"{k}={v}" for k, v in Counter(tried['Mark']).items()))
        log("Theo ten mien (so bai thu / lay duoc): " + "; ".join(
            f"{h}={g.shape[0]}/{(g['Mark'] == 'ok').sum()}" for h, g in tried.groupby("Host")))
    header = f"Chay luc {datetime.now():%Y-%m-%d %H:%M:%S} | mau {FULLTEXT_SAMPLE} bai\n"
    (OUT / "content_log.txt").write_text(header + "\n".join(LOG), encoding="utf-8")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    log(f"Thu muc output: {OUT}")
    rows, results = [], {}
    try:
        rows = load_headlines()
        results = load_results()
        run(rows, results)
    except StopRun as e:
        log(f"DUNG: {e}")
    except KeyboardInterrupt:
        log("Da dung boi nguoi dung (Ctrl+C). Luu phan da lay duoc.")
    except Exception as e:
        log(f"DUNG do loi: {type(e).__name__}: {e}")
    finally:
        if rows:
            save(rows, results)
        else:
            (OUT / "content_log.txt").write_text("\n".join(LOG), encoding="utf-8")