"""
collection_headlines.py - PHAN 1: cao HEADLINE qua API Finnhub (giai doan 1 cua quy trinh FNSPID).

  Vao : danh sach ma co phieu (tickers.txt hoac TICKERS trong file) + khoang ngay
  Ra  : output/headlines.csv  chi 3 cot: Date, Headline, URL  (doi bang OUTPUT_COLUMNS ben duoi)
        output/headlines_log.txt  (nhat ky chay)
        output/finnhub_parts/<MA>.csv  (bo nho dem, moi ma 1 file, giu day du Symbol/Summary/Source de chay tiep neu bi ngat)

Phan 2 (collection_content.py) doc headlines.csv va lay NOI DUNG bai.

CACH DUNG: mo file trong VS Code, bam Run. Nhap Finnhub API key khi duoc hoi
(hoac dat bien moi truong FINNHUB_API_KEY, hoac file finnhub_key.txt canh file nay). Dung dua key len GitHub.
Chi can pandas (tu cai neu thieu).
"""
import importlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

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
# Nguon danh sach ma (uu tien tu tren xuong):
#   1. file tickers.txt canh script (moi dong mot ma, dong bat dau bang # la ghi chu)
#   2. cac file list_<chu>.csv cua repo FNSPID (cot Stock_name) neu LIST_LETTERS khac rong,
#      tim trong thu muc lists_original / lists canh script hoac o thu muc cha
#   3. TICKERS ben duoi (danh sach du phong)
           # vi du "a" hoac "abc": lay ma tu list_a.csv, list_b.csv, list_c.csv. De trong = khong dung
MAX_TICKERS = 0                 # 0 = lay het; so khac 0 = chi lay N ma dau tien cua danh sach
START_DATE = "2020-10-28"       # lay tin tu ngay nay ...
END_DATE = "2026-09-30"         # ... den het ngay nay
MAX_MB = 1028                    # tran dung luong cua cac cot trong OUTPUT_COLUMNS
# Cot ghi vao headlines.csv. Chi 3 cot theo yeu cau; muon them thi bo sung "Symbol", "Summary", "Source"
# (khong can cao lai vi thu muc finnhub_parts da luu day du).
OUTPUT_COLUMNS = ["Date", "Headline", "URL"]
WINDOW_DAYS = 7                 # chia khoang ngay thanh cac cua so nho
SPLIT_AT = 200                  # cua so tra ve tu ngan tin tro len thi chia doi de tranh bi cat bot (phong doan)
CALL_GAP = 1.1                  # giay giua 2 lan goi API Finnhub
EMPTY_STOP = 6                  # gap bay nhieu cua so lien tiep khong co tin thi coi la het lich su cua goi
API = "https://finnhub.io/api/v1/company-news"
def find_out():
    """Thu muc output DUNG CHUNG: neu thu muc cha cua script da co 'output' thi dung no (script nam trong thu muc con),
    nguoc lai dung 'output' canh script."""
    here = Path(__file__).resolve().parent
    return here.parent / "output" if (here.parent / "output").is_dir() else here / "output"


OUT = find_out()
KEY_FILE = Path(__file__).parent / "finnhub_key.txt"
PARTS = OUT / "finnhub_parts"
# ======================================================================

COLUMNS = ["Symbol", "Date", "Headline", "URL", "Summary", "Source"]
LOG = []
USED_TICKERS = []


class StopRun(Exception):
    pass


def log(msg):
    print(msg)
    LOG.append(msg)


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



def tickers_from_repo_lists():
    """Đọc ticker từ tất cả file list_*.csv trong lists_headline."""
    here = Path(__file__).resolve().parent

    # Code nằm trong headline_scraper,
    # danh sách nằm trong D:\Data-mining\lists_headline
    folders = [
        here.parent / "lists_headline",
    ]

    files = []
    for folder in folders:
        if folder.is_dir():
            files = sorted(folder.glob("list_*.csv"))
            if files:
                break

    if not files:
        raise StopRun(
            f"Không tìm thấy file list_*.csv trong: {folders[0]}"
        )

    raw = []

    for f in files:
        try:
            df = pd.read_csv(f, on_bad_lines="skip")
            df.columns = df.columns.str.strip().str.lower()

            col = "stock_name" if "stock_name" in df.columns else df.columns[0]
            raw.extend(
                df[col].dropna().astype(str).str.strip().tolist()
            )

        except Exception as e:
            log(f"Lỗi đọc {f.name}: {e}")

    tickers = []
    seen = set()

    for ticker in raw:
        ticker = ticker.upper()

        if re.fullmatch(r"[A-Z]{1,5}([.-][A-Z])?", ticker):
            if ticker not in seen:
                seen.add(ticker)
                tickers.append(ticker)

    log(f"Đã đọc {len(files)} file CSV trong {folders[0]}")
    log(f"Tổng số ticker hợp lệ: {len(tickers)}")

    return tickers


def load_tickers():
    tickers = tickers_from_repo_lists()

    if not tickers:
        raise StopRun(
            "Không có ticker hợp lệ trong lists_headline."
        )

    log(f"Danh sách ticker từ CSV: {len(tickers)} mã")
    return tickers[:MAX_TICKERS] if MAX_TICKERS else tickers



def row_size(r):
    return sum(len(str(r.get(k, "")).encode()) for k in OUTPUT_COLUMNS)


def fetch_window(symbol, start, end, key):
    """Lay tin cua mot cua so ngay; neu tra ve qua nhieu (co the bi cat bot) thi chia doi va lay lai."""
    items = get_news(symbol, start, end, key)
    time.sleep(CALL_GAP)
    if len(items) >= SPLIT_AT and end > start:
        mid = start + (end - start) // 2
        log(f"    cua so {start}..{end} tra ve {len(items)} tin (>= {SPLIT_AT}), chia doi de tranh bi cat bot")
        return fetch_window(symbol, start, mid, key) + fetch_window(symbol, mid + timedelta(days=1), end, key)
    return items


def collect(rows):
    tickers = load_tickers()
    USED_TICKERS[:] = tickers
    PARTS.mkdir(parents=True, exist_ok=True)
    start_limit, end_limit = date.fromisoformat(START_DATE), date.fromisoformat(END_DATE)
    n_windows = ((end_limit - start_limit).days + 1) // WINDOW_DAYS + 1
    log(f"Phan 1 (headline): {len(tickers)} ma, {START_DATE} -> {END_DATE}, tran {MAX_MB} MB.")
    log(f"  Neu goi API co du lich su: toi da ~{len(tickers) * n_windows} lan goi (~{len(tickers) * n_windows * CALL_GAP / 3600:.1f} gio).")
    log("  Luu y: nhieu nguon mo ta goi mien phi chi cho lich su tin khoang 1 nam tinh tu hom nay;")
    log("  dong 'tin cu nhat lay duoc' o tung ma se cho biet goi cua ban lui duoc xa den dau.")
    size, key = 0, None
    for t in tickers:
        part = PARTS / f"{t}.csv"
        if part.exists():                    # chay tiep: ma nay da xong o lan truoc
            df = pd.read_csv(part, keep_default_na=False, dtype=str).reindex(columns=COLUMNS, fill_value="")
            recs = df.to_dict("records")
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
                     "Headline": head, "URL": url, "Summary": (it.get("summary") or "").strip(),
                     "Source": it.get("source") or "Finnhub"}
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
        log(f"[{t}] xong: {len(rows_t)} tin; tin cu nhat lay duoc: {oldest.date() if oldest else 'khong co'}")


def save(rows):
    df = pd.DataFrame(rows, columns=COLUMNS)           # day du cac cot (de thong ke)
    out = df[OUTPUT_COLUMNS]                           # chi ghi cac cot yeu cau
    if "Symbol" not in OUTPUT_COLUMNS:
        n0 = len(out)
        out = out.drop_duplicates()
        if n0 != len(out):
            log(f"Bo {n0 - len(out)} dong trung (cung mot bai xuat hien o nhieu ma; do khong co cot Symbol).")
    out.to_csv(OUT / "headlines.csv", index=False, encoding="utf-8-sig")   # -sig: Excel doc dung ky tu dac biet
    mb = (OUT / "headlines.csv").stat().st_size / 1e6
    log(f"Da luu {len(out)} headline -> {OUT / 'headlines.csv'} ({mb:.2f} MB), cot: {', '.join(OUTPUT_COLUMNS)}")
    if len(df):
        log(f"Khoang ngay: {df['Date'].min()} -> {df['Date'].max()}")
        log("So tin theo ma (truoc khi bo trung): " + ", ".join(f"{k}={v}" for k, v in df.groupby('Symbol').size().items()))
        log("So tin theo nguon: " + ", ".join(f"{k}={v}" for k, v in Counter(df['Source']).most_common(10)))
        log("Buoc tiep theo: chay collection_content.py (phan 2) de lay noi dung bai.")
    else:
        log("Khong lay duoc tin nao. Xem ly do o cac dong log phia tren.")
    header = f"Chay luc {datetime.now():%Y-%m-%d %H:%M:%S} | {len(USED_TICKERS)} ma | {START_DATE} -> {END_DATE}\n"
    (OUT / "headlines_log.txt").write_text(header + "\n".join(LOG), encoding="utf-8")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    log(f"Thu muc output: {OUT}")
    rows = []
    try:
        collect(rows)
    except StopRun as e:
        log(f"DUNG: {e}")
    except KeyboardInterrupt:
        log("Da dung boi nguoi dung (Ctrl+C). Luu phan da lay duoc.")
    except Exception as e:
        log(f"DUNG do loi: {type(e).__name__}: {e}")
    finally:
        save(rows)