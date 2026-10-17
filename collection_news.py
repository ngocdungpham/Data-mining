"""
collection_news.py - Cao TIN TUC theo quy trinh FNSPID (ban rut gon). Chi tao news.csv.


Quy trinh:
  Giai doan 1: trang tin cua tung ma -> headline + URL
  Giai doan 2: vao tung URL -> noi dung (bai ngan / tra phi thi de trong)

Ket qua trong thu muc output/ canh file nay:
  news.csv                 LUON duoc tao (neu khong cao duoc gi thi chi co dong tieu de)
  news_collection_log.txt  nhat ky chay + ly do dung (bang chung cho bao cao)
  debug_<ma>.png / .html   anh va ma nguon trang khi khong lay duoc headline

Ton trong robots.txt: tu dong doc Crawl-delay va giu khoang cach giua cac request.
"""
import importlib
import random
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib import robotparser

try:                                           
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def ensure(pkg, module=None):
    """Neu thieu thu vien thi tu cai vao dung Python dang chay."""
    try:
        importlib.import_module(module or pkg)
    except ImportError:
        print(f"Dang cai {pkg} (chi lan dau) ...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", pkg])


ensure("pandas")
ensure("selenium")

import pandas as pd                                              # noqa: E402
from selenium import webdriver                                   # noqa: E402
from selenium.webdriver.common.by import By                      # noqa: E402
from selenium.webdriver.chrome.options import Options            # noqa: E402
from selenium.webdriver.support.ui import WebDriverWait          # noqa: E402
from selenium.webdriver.support import expected_conditions as EC  # noqa: E402

# ============================== CAU HINH ==============================
TICKERS = ["AAPL", "MSFT"]          # thu it ma truoc
START_DATE = "2024-01-01"           # chi giu tin tu ngay nay (neu doc duoc ngay)
MAX_ARTICLES = 5                    # so bai toi da moi ma (tang len sau khi chay on)
MAX_MB = 500                        # tran dung luong tin   
HEADLESS = False                    # False: thay Chrome chay; True: chay an
SLEEP = (2, 4)                      # khoang cach toi thieu giua 2 request; tu tang theo Crawl-delay
WAIT_LINKS = 25                     # giay toi da cho danh sach tin hien ra (trang tai bang JavaScript)
MIN_CHARS = 300                     # noi dung ngan hon muc nay coi nhu khong lay duoc
BASE = "https://www.nasdaq.com"
NEWS_URL = BASE + "/market-activity/stocks/{t}/news-headlines"   # kiem tra lai tren trinh duyet
LINK_CSS = "a[href*='/market-activity/stocks#news']"  # cach nhan dien link bai viet
OUT = Path(__file__).parent / "output"
# ======================================================================

COLUMNS = ["Symbol", "Date", "Headline", "URL", "Text", "Source"]
LOG = []
LAST_REQ = [0.0]


def log(msg):
    print(msg)
    LOG.append(msg)


def polite_get(driver, url):
    """Mo URL, dam bao cach request truoc it nhat SLEEP giay (tinh tu luc request truoc)."""
    gap = random.uniform(*SLEEP) - (time.time() - LAST_REQ[0])
    if gap > 0:
        time.sleep(gap)
    LAST_REQ[0] = time.time()
    driver.get(url)


def make_driver():
    opts = Options()
    if HEADLESS:
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1280,900")
    opts.add_argument("--blink-settings=imagesEnabled=false")
    opts.page_load_strategy = "eager"
    try:
        driver = webdriver.Chrome(options=opts)
    except Exception as e:
        raise RuntimeError(f"Khong mo duoc Chrome (da cai Google Chrome chua?): {e}")
    driver.set_page_load_timeout(30)
    return driver


def get_headlines(driver, ticker):
    """Giai doan 1: tra ve list (headline, url)."""
    polite_get(driver, NEWS_URL.format(t=ticker.lower()))
    try:                                     # cho danh sach tin hien ra (noi dung tai bang JS)
        WebDriverWait(driver, WAIT_LINKS).until(EC.presence_of_element_located((By.CSS_SELECTOR, LINK_CSS)))
    except Exception:
        pass                                 # khong thay link: debug_page se ghi lai chi tiet
    for _ in range(3):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1)
    found, seen = [], set()
    for a in driver.find_elements(By.CSS_SELECTOR, LINK_CSS):
        href, title = a.get_attribute("href"), a.text.strip()
        if href and title and href not in seen:
            seen.add(href)
            found.append((title, href))
    return found[:MAX_ARTICLES]


def get_article(driver, url):
    """Giai doan 2: tra ve (ngay, noi_dung)."""
    polite_get(driver, url)
    paras = driver.find_elements(By.CSS_SELECTOR, "article p") or driver.find_elements(By.CSS_SELECTOR, "p")
    text = " ".join(p.text.strip() for p in paras if p.text.strip())
    date = ""
    for css, attr in [("meta[property='article:published_time']", "content"), ("time", "datetime")]:
        els = driver.find_elements(By.CSS_SELECTOR, css)
        if els and els[0].get_attribute(attr):
            date = els[0].get_attribute(attr)
            break
    return date, text


def debug_page(driver, t):
    """Luu anh, ma nguon va thong tin trang de biet vi sao khong lay duoc headline."""
    try:
        driver.save_screenshot(str(OUT / f"debug_{t}.png"))
        (OUT / f"debug_{t}.html").write_text(driver.page_source, encoding="utf-8")
        anchors = driver.find_elements(By.TAG_NAME, "a")
        links = [(a.text.strip(), a.get_attribute("href") or "") for a in anchors]
        log(f"  -> URL hien tai: {driver.current_url}")
        log(f"  -> Tieu de trang: {driver.title!r}")
        log(f"  -> Tong so link: {len(links)}; link khop '{LINK_CSS}': {sum('/market-activity/stocks#news' in h for _, h in links)}")
        long_links = [(x, h) for x, h in links if len(x) >= 30][:12]
        if long_links:
            log("  -> Mot so link co chu dai (de xem tin nam o dau):")
            for x, h in long_links:
                log(f"       {x[:60]} | {h[:90]}")
        log(f"  -> Da luu output/debug_{t}.png va output/debug_{t}.html")
    except Exception as e:
        log(f"  -> khong luu duoc thong tin debug: {e}")


def load_robots():
    """Doc robots.txt co gioi han thoi gian (robotparser.read() mac dinh khong co timeout)."""
    rp = robotparser.RobotFileParser()
    req = urllib.request.Request(BASE + "/robots.txt", headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            rp.parse(r.read().decode("utf-8", "replace").splitlines())
    except urllib.error.HTTPError as e:
        if e.code == 404:            # khong co robots.txt: coi nhu khong han che
            rp.parse([])
        else:
            raise
    return rp


def scrape(rows):
    """Cao tin, them dong vao `rows`. Neu loi giua chung thi rows van giu phan da cao duoc."""
    global SLEEP
    log("Dang kiem tra robots.txt (toi da 15 giay) ...")
    try:
        rp = load_robots()
        log("Da doc robots.txt.")
    except Exception as e:
        log(f"DUNG: khong doc duoc robots.txt ({e}).")
        log(f"Hay tu mo {BASE}/robots.txt trong trinh duyet de kiem tra; may co the dang bi Nasdaq tu choi ket noi.")
        return
    delay = rp.crawl_delay("*")
    if delay:
        SLEEP = (delay, delay + 5)
        log(f"robots.txt yeu cau Crawl-delay {delay}s: cac request cach nhau {SLEEP[0]}-{SLEEP[1]} giay.")
        log(f"Uoc tinh: moi bai mat ~{delay + 2}s, {len(TICKERS)} ma x {MAX_ARTICLES} bai ~ "
            f"{len(TICKERS) * (MAX_ARTICLES + 1) * (delay + 2) / 60:.0f} phut.")

    log("Dang mo Chrome ...")
    driver, size_bytes = make_driver(), 0
    try:
        for t in TICKERS:
            url = NEWS_URL.format(t=t.lower())
            if not rp.can_fetch("*", url):
                log(f"[{t}] robots.txt khong cho phep: {url}")
                continue
            log(f"[{t}] dang mo trang tin ...")
            try:
                heads = get_headlines(driver, t)
            except Exception as e:
                log(f"[{t}] loi lay headline: {e}")
                heads = []
            log(f"[{t}] {len(heads)} headline")
            if not heads:
                debug_page(driver, t)
            for i, (title, href) in enumerate(heads, 1):
                t0 = time.time()
                try:
                    date, text = get_article(driver, href)
                except Exception as e:
                    log(f"  loi bai {i}: {e}")
                    date, text = "", ""
                ok = len(text) >= MIN_CHARS
                log(f"  {i}/{len(heads)} ({time.time() - t0:.1f}s) "
                    f"{'co noi dung' if ok else 'bo qua noi dung'}: {title[:60]}")
                rows.append({"Symbol": t, "Date": date, "Headline": title,
                             "URL": href, "Text": text if ok else "", "Source": "NASDAQ"})
                size_bytes += len(title.encode()) + len(href.encode()) + (len(text.encode()) if ok else 0)
                if size_bytes >= MAX_MB * 1e6:
                    log(f"Da dat tran {MAX_MB} MB, dung cao.")
                    return
    finally:
        driver.quit()


def save(rows):
    df = pd.DataFrame(rows, columns=COLUMNS)
    if not df.empty:
        d = pd.to_datetime(df["Date"], errors="coerce", utc=True).dt.tz_localize(None)
        df["Date"] = d
        df = df[d.isna() | (d >= pd.Timestamp(START_DATE))].drop_duplicates(subset="URL")
    df.to_csv(OUT / "news.csv", index=False, encoding="utf-8")
    log(f"Da luu {len(df)} tin -> {OUT / 'news.csv'}")
    if len(df):
        log(f"Ty le co noi dung: {(df['Text'].fillna('') != '').mean():.3f}")
        log(f"Ty le co ngay: {df['Date'].notna().mean():.3f}")
    else:
        log("news.csv chi co dong tieu de (khong cao duoc tin nao). Xem ly do o cac dong log phia tren.")
    header = f"Chay luc {datetime.now():%Y-%m-%d %H:%M:%S} | ma: {TICKERS} | tu ngay: {START_DATE}\n"
    (OUT / "news_collection_log.txt").write_text(header + "\n".join(LOG), encoding="utf-8")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    rows = []
    try:
        scrape(rows)
    except KeyboardInterrupt:
        log("Da dung boi nguoi dung (Ctrl+C). Luu phan da cao duoc.")
    except Exception as e:
        log(f"DUNG do loi: {e}")
    finally:
        save(rows)
