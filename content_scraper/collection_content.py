"""
collection_content.py - PHAN 2: lay NOI DUNG bai bao (ban toi uu toc do cho > 100.000 URL).

  Vao : output/headlines.csv                 (do collection_headlines.py tao ra: Date, Headline, URL)
        output/finnhub_parts/*.csv           (tuy chon: chi dung de biet NGUON tin cua tung URL, phuc vu cat tia)
  Ra  : output/content.csv  chi 4 cot: Date, Url, Text, Mark
          Mark: ok | short | robots | denied_403... | source_skipped | domain_skipped | domain_cap | not_html | error | http_xxx
        output/content_log.txt                 nhat ky + thong ke theo trang thai / ten mien / nguon
        output/content_cache/content_results.csv   bo nho dem, GHI NOI THEM tung bai (chay tiep duoc, khong phai ket qua nop)

TOI UU (khong nhanh hon gioi han lich su cua tung website):
  1. Chay DA LUONG (MAX_WORKERS): cac ten mien khac nhau duoc xu ly song song.
  2. Moi ten mien chi co 1 request tai mot thoi diem va cach nhau >= khoang cach cho phep (HOST_GAP / MIN_DOMAIN_GAP /
     Crawl-delay trong robots.txt, lay so lon nhat). Day la gioi han CUNG: tang MAX_WORKERS khong lam nhanh hon no.
  3. CAT TIA THEO NGUON: nguon tin nao thu PRUNE_AFTER bai dau ma khong bai nao lay duoc noi dung thi bo qua phan con lai
     (khong gui request nao), tiet kiem phan lon thoi gian.
  4. Xen ke cac nguon khi sap xep hang doi de giai doan thu nghiem cua moi nguon dien ra som.
  5. Cache ghi noi them (khong ghi de ca file moi lan), log tom tat theo tien do thay vi tung bai.
Quy tac ton trong website van nhu cu: doc robots.txt tung ten mien (ke ca moi buoc chuyen huong), User-Agent trung thuc,
bi tu choi thi bo qua (khong lach), 2 lan bi tu choi lien tiep o mot ten mien thi bo ten mien do.

CACH DUNG: bam Run (khong can API key). Nen chay thu FULLTEXT_SAMPLE = 300 truoc, doc thong ke theo nguon/ten mien
trong content_log.txt, roi dat FULLTEXT_SAMPLE = 0 (tat ca) va chay lai: cac bai da thu duoc giu nguyen.
"""
import csv
import importlib
import random
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
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
FULLTEXT_SAMPLE = 0
INCLUDE_NOT_ATTEMPTED = True
MAX_WORKERS = 32
MIN_DOMAIN_GAP = 5
HOST_GAP = {"finnhub.io": 1.1}
MAX_PER_DOMAIN = 0
PRUNE_AFTER = 0       
MIN_CHARS = 300
MAX_BYTES = 1_500_000
CONNECT_TIMEOUT = 15
SAVE_EVERY = 100
VERBOSE = True
PROGRESS_EVERY = 1000
RETRY_STATUSES = {
    "error",
    "http_500",
    "http_502",
    "http_503",
    "http_504",
}
CONTACT = ""
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
PROGRESS_FILE = OUT / "content_progress.csv"
UA = f"{UA_NAME}/1.0 (educational research" + (f"; contact: {CONTACT}" if CONTACT else "") + ")"
LOG = []
LOG_LOCK = threading.Lock()
STATE_LOCK = threading.Lock()
STOP = threading.Event()


class StopRun(Exception):
    pass


def log(msg):
    with LOG_LOCK:
        print(msg)
        LOG.append(msg)


# ----------------------------- MANG (tach rieng de de kiem thu) -----------------------------
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(_NoRedirect)
ROBOTS = {}              # "scheme://host" -> (RobotFileParser hoac None, delay)
ROBOTS_LOCKS = {}
HOST_LOCKS = {}          # moi ten mien 1 khoa: chi 1 request dang chay tai mot thoi diem
LAST_HIT = {}
DOMAIN_COUNT = Counter()
DOMAIN_FAIL = Counter()
SRC_STATS = {}           # nguon -> [so bai da thu (khong tinh loi tam thoi), so bai ok]


def http_robots(url):
    """Doc robots.txt (theo chuyen huong binh thuong)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=CONNECT_TIMEOUT) as r:
        return r.read().decode("utf-8", "replace")


def http_open(req):
    """Mo mot URL, KHONG tu theo chuyen huong (de kiem tra robots.txt o tung buoc)."""
    return OPENER.open(req, timeout=CONNECT_TIMEOUT)


def _lock_for(table, key):
    with STATE_LOCK:
        lk = table.get(key)
        if lk is None:
            lk = table[key] = threading.Lock()
    return lk


def robots_for(url):
    p = urllib.parse.urlparse(url)
    origin = f"{p.scheme}://{p.netloc}"
    with _lock_for(ROBOTS_LOCKS, origin):          # chi 1 luong doc robots.txt cua mot ten mien
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
    """Tra ve (html, status, host_cuoi). An toan khi chay da luong:
    moi ten mien co 1 khoa -> chi 1 request/ten mien tai mot thoi diem va cach nhau >= khoang cach cho phep."""
    host = urllib.parse.urlparse(url).netloc
    for _ in range(max_hops):
        if STOP.is_set():
            return None, "stopped", host
        host = urllib.parse.urlparse(url).netloc
        with STATE_LOCK:
            fails, cnt = DOMAIN_FAIL[host], DOMAIN_COUNT[host]
        if fails >= 2:
            return None, "domain_skipped", host
        if MAX_PER_DOMAIN > 0 and cnt >= MAX_PER_DOMAIN:
            return None, "domain_cap", host
        rp, delay = robots_for(url)
        if rp is None:                       # khong doc duoc robots.txt cua ten mien nay: bo ten mien, khong mo bai
            with STATE_LOCK:
                DOMAIN_FAIL[host] += 2
            return None, "robots", host
        if not rp.can_fetch(UA_NAME, url):   # robots.txt cam duong dan nay: bo bai nay (khong gui request nao)
            return None, "robots", host
        need = max(delay, HOST_GAP.get(host, MIN_DOMAIN_GAP))
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
        redirect_to = None
        with _lock_for(HOST_LOCKS, host):
            wait = need - (time.time() - LAST_HIT.get(host, 0))
            if wait > 0:
                time.sleep(wait)
            LAST_HIT[host] = time.time()
            try:
                with http_open(req) as r:
                    if "html" not in (r.headers.get("Content-Type") or "").lower():
                        return None, "not_html", host
                    raw = r.read(MAX_BYTES)
                    html = raw.decode(r.headers.get_content_charset() or "utf-8", "replace")
            except urllib.error.HTTPError as e:
                code, loc = e.code, e.headers.get("Location")
                e.close()
                if code in (301, 302, 303, 307, 308):
                    if not loc:
                        return None, "redirect_error", host
                    redirect_to = urllib.parse.urljoin(url, loc)
                elif code in (401, 402, 403, 429):
                    with STATE_LOCK:
                        DOMAIN_FAIL[host] += 1
                    return None, f"denied_{code}", host
                else:
                    return None, f"http_{code}", host
            except Exception:
                return None, "error", host
        if redirect_to:                      # theo chuyen huong ben ngoai khoa (de ten mien dich duoc kiem tra robots rieng)
            url = redirect_to
            continue
        with STATE_LOCK:
            DOMAIN_COUNT[host] += 1
        return html, "ok", host
    return None, "too_many_redirects", host


# ----------------------------- CACHE GHI NOI THEM -----------------------------
class Cache:
    FIELDS = ["URL", "TextStatus", "Host", "Text"]

    def __init__(self, path):
        self.path, self.lock, self.n = path, threading.Lock(), 0
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists() or path.stat().st_size == 0
        if not new:                                   # neu lan truoc bi ngat giua dong thi xuong dong truoc khi ghi tiep
            with open(path, "rb") as f:
                f.seek(-1, 2)
                need_nl = f.read(1) not in (b"\n", b"\r")
        self.f = open(path, "a", newline="", encoding="utf-8")
        if not new and need_nl:
            self.f.write("\n")
        self.w = csv.DictWriter(self.f, fieldnames=self.FIELDS)
        if new:
            self.w.writeheader()

    def add(self, rec):
        with self.lock:
            self.w.writerow({k: rec.get(k, "") for k in self.FIELDS})
            self.n += 1
            if self.n % SAVE_EVERY == 0:
                self.f.flush()

    def close(self):
        with self.lock:
            self.f.flush()
            self.f.close()


def load_results():
    if not RES.exists():
        return {}
    df = pd.read_csv(RES, keep_default_na=False, dtype=str, on_bad_lines="skip")
    df = df.drop_duplicates("URL", keep="last")      # neu mot URL duoc thu lai thi lay ket qua moi nhat
    return {r["URL"]: r for r in df.to_dict("records")}


# ----------------------------- DOC DU LIEU + CHON THU TU -----------------------------
def load_headlines():
    if not HEAD.exists():
        raise StopRun("Chua co output/headlines.csv. Hay chay collection_headlines.py (phan 1) truoc.")
    df = pd.read_csv(HEAD, keep_default_na=False, dtype=str, encoding="utf-8-sig")
    for c in ("Date", "Headline", "URL"):
        if c not in df.columns:
            raise StopRun(f"headlines.csv thieu cot {c}.")
    return df.to_dict("records")


def load_source_map():
    """URL -> nguon tin (Yahoo, Benzinga...), doc tu bo nho dem cua phan 1. Khong co thi tra ve {} (khi do khong cat tia theo nguon)."""
    m, parts = {}, OUT / "finnhub_parts"
    if parts.is_dir():
        for f in parts.glob("*.csv"):
            try:
                df = pd.read_csv(f, usecols=["URL", "Source"], keep_default_na=False, dtype=str)
            except Exception:
                continue
            m.update(zip(df["URL"], df["Source"]))
    return m


def pick_sample(rows, n):
    """Xen ke cac NGUON (round-robin) theo thu tu co dinh: nguon nao cung duoc thu som va deu."""
    rnd = random.Random(42)
    groups = {}
    for i, r in enumerate(rows):
        groups.setdefault(r.get("Source", ""), []).append(i)
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


def source_pruned(src):
    if PRUNE_AFTER <= 0 or not src:
        return False
    with STATE_LOCK:
        st = SRC_STATS.get(src)
    return bool(st) and st[0] >= PRUNE_AFTER and st[1] == 0


def note_result(src, status):
    if not src or status in ("error", "stopped") or status.startswith("http_5"):
        return                                   # loi tam thoi khong tinh vao cat tia
    with STATE_LOCK:
        st = SRC_STATS.setdefault(src, [0, 0])
        st[0] += 1
        st[1] += status == "ok"


def save_progress(rows, results, current_run=0):
    """
    Lưu thống kê tổng thể vào content_progress.csv.
    current_run: số URL đã xử lý trong lần chạy hiện tại.
    """

    # Đếm URL duy nhất
    total_urls = len(set(r["URL"] for r in rows))

    # Chỉ tính URL có kết quả không thuộc nhóm cần thử lại
    completed_statuses = [
        url for url, rec in results.items()
        if rec.get("TextStatus") not in RETRY_STATUSES
    ]

    completed = len(set(completed_statuses))

    # Đếm số URL lấy nội dung thành công
    successful = len(set(
        url for url, rec in results.items()
        if rec.get("TextStatus") == "ok"
    ))

    # Số URL còn lại
    remaining = max(0, total_urls - completed)

    percent = completed / total_urls * 100 if total_urls else 0

    data = {
        "Updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Total_URL": total_urls,
        "Processed_URL": completed,
        "Successful_URL": successful,
        "Remaining_URL": remaining,
        "Current_Run": current_run,
        "Completion_Percent": round(percent, 2),
    }

    # Ghi file tạm trước, sau đó thay file chính
    temp_file = PROGRESS_FILE.with_suffix(".tmp")

    pd.DataFrame([data]).to_csv(
        temp_file,
        index=False,
        encoding="utf-8-sig"
    )

    temp_file.replace(PROGRESS_FILE)

    log(
        f"TIEN DO TONG: {completed:,}/{total_urls:,} URL "
        f"({percent:.2f}%) | "
        f"Thanh cong: {successful:,} | "
        f"Con lai: {remaining:,}"
    )

# ----------------------------- CHAY -----------------------------
def run(rows, results):
    smap = load_source_map()
    for r in rows:
        r["Source"] = smap.get(r["URL"], "")
    n_known = sum(1 for r in rows if r["Source"])
    log(f"Phan 2 (noi dung): {len(rows)} headline; biet nguon cua {n_known}; "
        f"{'cat tia theo nguon: bat' if (PRUNE_AFTER > 0 and n_known) else 'cat tia theo nguon: tat (khong co nguon)'}.")

    idx = pick_sample(rows, len(rows) if FULLTEXT_SAMPLE <= 0 else min(FULLTEXT_SAMPLE, len(rows)))
    todo, seen = [], set()
    for i in idx:
        u = rows[i]["URL"]
        if u in seen:
            continue
        seen.add(u)
        st = results.get(u, {}).get("TextStatus")
        if st is None or st in RETRY_STATUSES:
            todo.append(i)
    log(f"  Muc tieu {len(seen)} URL; da co trong cache {len(seen) - len(todo)}; can xu ly {len(todo)}; "
        f"{MAX_WORKERS} luong; User-Agent: {UA}")
    if not todo:
        return

    cache = Cache(RES)

    def process(i):
        r = rows[i]
        url, src = r["URL"], r["Source"]
        if STOP.is_set():
            return None
        if source_pruned(src):
            return {"URL": url, "TextStatus": "source_skipped", "Host": "", "Text": ""}
        try:
            html, status, host = polite_fetch(url)
            if status == "stopped":
                return None
            text = ""
            if status == "ok":
                text = extract_text(html)
                if len(text) < MIN_CHARS:
                    status, text = "short", ""
        except Exception as e:
            html, status, host, text = None, "error", "", ""
            log(f"  Loi khi xu ly {url[:80]}: {str(e)[:100]}")
        note_result(src, status)
        return {"URL": url, "TextStatus": status, "Host": host, "Text": text}

    t0, done, counts = time.time(), 0, Counter()
    ex = ThreadPoolExecutor(max_workers=max(1, MAX_WORKERS))
    futures = [ex.submit(process, i) for i in todo]
    try:
        for fut in as_completed(futures):
            rec = fut.result()
            if rec is None:
                continue
            results[rec["URL"]] = rec
            cache.add(rec)
            counts[rec["TextStatus"]] += 1
            done += 1
            print(
                f"\rDa xu ly: {done:,}/{len(todo):,} URL | "
                f"Lay thanh cong: {counts['ok']:,} | "
                f"Tien do: {done / len(todo) * 100:.2f}%",
                end="",
                flush=True
            )
            if done % PROGRESS_EVERY == 0 or done == len(todo):
                 print()
                 el = max(time.time() - t0, 1e-6)
                 rate = done / el * 60
                 remaining_time = (
                 (len(todo) - done) / (done / el) / 3600
                 if done > 0 else 0
                 )
        log(
        f"\n========== TIEN DO LAN CHAY ==========\n"
        f"Da xu ly: {done:,}/{len(todo):,} URL\n"
        f"Thanh cong: {counts['ok']:,}\n"
        f"Bi chan robots: {counts['robots']:,}\n"
        f"Bi tu choi: {sum(v for k, v in counts.items() if k.startswith('denied')):,}\n"
        f"Noi dung ngan: {counts['short']:,}\n"
        f"Bi bo qua: {counts['source_skipped'] + counts['domain_skipped']:,}\n"
        f"Toc do: {rate:.1f} URL/phut\n"
        f"Thoi gian con lai uoc tinh: {remaining_time:.2f} gio\n"
        f"======================================"
        )
        save_progress(rows, results, done)
    except KeyboardInterrupt:
        STOP.set()
        for f in futures:
            f.cancel()
        log("Da nhan Ctrl+C: dung cac luong, luu phan da lay duoc ...")
        raise
    finally:
        ex.shutdown(wait=True)
        cache.close()
    log("Hoan tat phan 2. Trang thai cua lan chay nay: " + ", ".join(f"{k}={v}" for k, v in counts.most_common()))
    with STATE_LOCK:
        pr = {s: v for s, v in SRC_STATS.items() if v[0] >= PRUNE_AFTER > 0 and v[1] == 0}
    if pr:
        log("Nguon bi cat tia (khong bai nao lay duoc noi dung): " + ", ".join(f"{s}({v[0]} bai thu)" for s, v in pr.items()))


# ----------------------------- LUU KET QUA -----------------------------
def save(rows, results):
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
        skipped = {"source_skipped", "domain_skipped", "domain_cap"}
        log(f"Tong cong {len(tried)} bai da xu ly, lay duoc noi dung {(tried['Mark'] == 'ok').sum()} bai ({(tried['Mark'] == 'ok').mean():.1%} tren so bai da xu ly).")
        log("Mark: " + ", ".join(f"{k}={v}" for k, v in Counter(tried['Mark']).most_common()))

        def table(key, top=None):
            g = tried[tried[key] != ""].groupby(key)["Mark"].agg(
                tong="count", thu=lambda s: int((~s.isin(skipped)).sum()), ok=lambda s: int((s == "ok").sum()))
            g = g.sort_values("tong", ascending=False)
            g = g.head(top) if top else g
            return "; ".join(f"{h}={r.tong}/{r.thu}/{r.ok}" for h, r in g.iterrows())

        log("Theo ten mien (tong / da thu that / ok), 15 ten mien nhieu bai nhat: " + table("Host", 15))
        if tried["Source"].ne("").any():
            log("Theo nguon tin (tong / da thu that / ok): " + table("Source"))
    header = f"Chay luc {datetime.now():%Y-%m-%d %H:%M:%S} | FULLTEXT_SAMPLE={FULLTEXT_SAMPLE} | workers={MAX_WORKERS}\n"
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
                save_progress(rows, results)
        else:
            (OUT / "content_log.txt").write_text("\n".join(LOG), encoding="utf-8")
