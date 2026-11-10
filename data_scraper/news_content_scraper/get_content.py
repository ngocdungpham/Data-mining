
import os
import re
import time
import uuid
import warnings
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pandas as pd
import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from dotenv import load_dotenv


# ============================================================
# CAU HINH
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

load_dotenv(PROJECT_ROOT / ".env")

API_KEY = os.getenv("APCA_API_KEY_ID")
API_SECRET = os.getenv("APCA_API_SECRET_KEY")

API_URL = "https://data.alpaca.markets/v1beta1/news"

START_DATE = "2020-01-01T00:00:00Z"
END_DATE = "2026-10-01T00:00:00Z"

LIMIT = 50
REQUEST_TIMEOUT = 40
MAX_RETRIES = 4
DELAY_SECONDS = 0.5
MIN_TEXT_LENGTH = 40

# Luu CSV sau moi 20 URL khop voi API.
SAVE_EVERY_MATCHES = 20

NEWS_CONTENTS_DIR = BASE_DIR / "news_contents"

OUTPUT_COLUMNS = ["Date", "Url", "Text", "Mark"]

# XMLParsedAsHTMLWarning chi la canh bao khi BeautifulSoup
# gap tai lieu XML nhung duoc phan tich bang HTML parser.
warnings.filterwarnings(
    "ignore",
    category=XMLParsedAsHTMLWarning
)


# ============================================================
# KHOI TAO API
# ============================================================

def make_headers():

    if not API_KEY or not API_SECRET:
        raise ValueError(
            "Khong tim thay APCA_API_KEY_ID hoac APCA_API_SECRET_KEY "
            "trong file .env tai thu muc goc project."
        )

    return {
        "APCA-API-KEY-ID": API_KEY,
        "APCA-API-SECRET-KEY": API_SECRET
    }


def request_page(session, params):

    for attempt in range(1, MAX_RETRIES + 1):

        try:
            response = session.get(
                API_URL,
                params=params,
                timeout=REQUEST_TIMEOUT
            )

            if response.status_code == 200:
                return response.json()

            if response.status_code in (429, 500, 502, 503, 504):

                if attempt < MAX_RETRIES:

                    # Uu tien Retry-After neu API cung cap.
                    retry_after = response.headers.get("Retry-After")

                    try:
                        wait = float(retry_after)
                    except (TypeError, ValueError):
                        wait = 2 ** attempt

                    print(
                        f"API HTTP {response.status_code}; "
                        f"thu lai sau {wait:.1f}s "
                        f"({attempt}/{MAX_RETRIES})"
                    )

                    time.sleep(wait)
                    continue

            raise RuntimeError(
                f"Alpaca HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )

        except requests.exceptions.RequestException as error:

            if attempt == MAX_RETRIES:
                raise RuntimeError(
                    f"Loi ket noi Alpaca: {error}"
                )

            wait = 2 ** attempt

            print(
                f"Loi ket noi, thu lai sau {wait}s "
                f"({attempt}/{MAX_RETRIES})..."
            )

            time.sleep(wait)

    raise RuntimeError("Khong the ket noi Alpaca API.")


# ============================================================
# DOC / LUU CSV
# ============================================================

def read_csv_safely(file_path):

    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin1"):

        try:
            return pd.read_csv(
                file_path,
                encoding=encoding
            )

        except UnicodeDecodeError:
            continue

    raise ValueError(f"Khong doc duoc file: {file_path}")


def atomic_save(df, output_file):

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    # Tao ten file tam rieng de tranh trung ten khi luu.
    temp_file = output_file.with_name(
        f".{output_file.stem}.{uuid.uuid4().hex}.tmp"
    )

    try:

        df.to_csv(
            temp_file,
            index=False,
            encoding="utf-8-sig"
        )

        # Thu lai neu Windows tam thoi khoa file.
        for attempt in range(1, 6):

            try:
                os.replace(
                    temp_file,
                    output_file
                )

                return

            except PermissionError:

                if attempt == 5:
                    raise

                print(
                    f"File dang bi khoa: {output_file.name}. "
                    f"Thu lai sau 2 giay ({attempt}/5)..."
                )

                time.sleep(2)

    finally:

        if temp_file.exists():

            try:
                temp_file.unlink()

            except OSError:
                pass


def normalize_output(df):

    rename = {}

    for col in df.columns:

        key = str(col).strip().lower()

        if key == "date":
            rename[col] = "Date"

        elif key in ("url", "uri", "link"):
            rename[col] = "Url"

        elif key == "text":
            rename[col] = "Text"

        elif key == "mark":
            rename[col] = "Mark"

    df = df.rename(columns=rename)

    for col in OUTPUT_COLUMNS:

        if col not in df.columns:
            df[col] = "" if col in (
                "Date", "Url", "Text"
            ) else 0

    df = df[OUTPUT_COLUMNS].copy()

    df["Date"] = (
        df["Date"]
        .astype("string")
        .fillna("")
    )

    df["Url"] = (
        df["Url"]
        .astype("string")
        .fillna("")
        .str.strip()
    )

    # Sua Pandas4Warning khi fillna tren cot co dtype float.
    df["Text"] = (
        df["Text"]
        .astype("string")
        .fillna("")
    )

    df["Mark"] = pd.to_numeric(
        df["Mark"],
        errors="coerce"
    ).fillna(0)

    # Chi chap nhan Mark = 0 hoac Mark = 1.
    df["Mark"] = (
        df["Mark"] == 1
    ).astype(int)

    # Mark=1 nhung Text khong dat nguong thi phai thu lai.
    invalid_success = (
        (df["Mark"] == 1)
        & (df["Text"].str.len() < MIN_TEXT_LENGTH)
    )

    df.loc[invalid_success, "Mark"] = 0

    return df


# ============================================================
# LAM SACH NOI DUNG
# ============================================================

def clean_article_content(raw_content):

    if raw_content is None:
        return ""

    raw_content = str(raw_content).strip()

    if not raw_content:
        return ""

    # Chi phan tich HTML khi nhan dien duoc the HTML pho bien.
    html_pattern = (
        r"<\s*(html|body|p|div|article|section|br|"
        r"span|script|style|noscript)\b"
    )

    if re.search(html_pattern, raw_content, flags=re.IGNORECASE):

        soup = BeautifulSoup(
            raw_content,
            "html.parser"
        )

        for tag in soup([
            "script",
            "style",
            "noscript",
            "svg"
        ]):
            tag.decompose()

        text = soup.get_text(
            "\n",
            strip=True
        )

    else:
        text = raw_content

    text = text.replace("\xa0", " ")

    text = re.sub(
        r"[ \t]+",
        " ",
        text
    )

    text = re.sub(
        r"\n[ \t]*\n[ \t]*\n+",
        "\n\n",
        text
    )

    return text.strip()


def normalize_url(url):

    """Chuan hoa URL de doi chieu URL trong CSV va URL tu Alpaca."""

    if not url:
        return ""

    try:

        parts = urlsplit(
            str(url).strip()
        )

        host = parts.netloc.lower()
        path = parts.path.rstrip("/")

        # Bo query va fragment de tranh khac nhau do tracking.
        return urlunsplit((
            parts.scheme.lower(),
            host,
            path,
            "",
            ""
        ))

    except Exception:
        return str(url).strip().rstrip("/")


# ============================================================
# LAY CONTENT TU ALPACA THEO TICKER
# ============================================================

def fetch_ticker_news(session, ticker):

    params = {
        "symbols": ticker,
        "start": START_DATE,
        "end": END_DATE,
        "limit": LIMIT,
        "sort": "asc",
        "include_content": "true"
    }

    page_token = None
    page_number = 0
    seen_tokens = set()

    while True:

        if page_token:
            params["page_token"] = page_token

        else:
            params.pop("page_token", None)

        data = request_page(
            session,
            params
        )

        articles = data.get("news", [])

        if not isinstance(articles, list):
            raise RuntimeError(
                "Du lieu news tu Alpaca khong dung dinh dang."
            )

        page_number += 1

        print(
            f"  Alpaca page {page_number}: "
            f"{len(articles)} bai"
        )

        for article in articles:
            yield article

        next_token = data.get("next_page_token")

        if not next_token:
            break

        if next_token in seen_tokens:
            raise RuntimeError(
                "Alpaca next_page_token bi lap."
            )

        seen_tokens.add(next_token)
        page_token = next_token

        time.sleep(DELAY_SECONDS)


# ============================================================
# XU LY MOT TICKER
# ============================================================

def process_ticker(csv_file, session):

    df = normalize_output(
        read_csv_safely(csv_file)
    )

    # Loai URL trung nhung khong xoa cac dong URL rong.
    duplicate_mask = (
        df["Url"].ne("")
        & df["Url"].duplicated(keep="first")
    )

    df = df.loc[
        ~duplicate_mask
    ].reset_index(drop=True)

    ticker = csv_file.stem.upper()
    total = len(df)

    already_success = int(
        (
            (df["Mark"] == 1)
            & (df["Text"].str.len() >= MIN_TEXT_LENGTH)
        ).sum()
    )

    print(f"\n========== TICKER {ticker} ==========")
    print("Tong bai trong CSV:", total)
    print("Da co noi dung tu truoc:", already_success)

    # Khong can goi API neu ticker khong co bai hoac da hoan thanh.
    if total == 0:

        print("File khong co bai bao. Bo qua.")

        return {
            "total": 0,
            "matched": 0,
            "new_success": 0,
            "success_total": 0,
            "pending": 0,
            "skipped": True
        }

    if already_success == total:

        print("Tat ca bai da co content hop le. Bo qua API.")

        return {
            "total": total,
            "matched": 0,
            "new_success": 0,
            "success_total": already_success,
            "pending": 0,
            "skipped": True
        }

    url_to_rows = {}

    for index, url in enumerate(df["Url"]):

        key = normalize_url(url)

        if key:
            url_to_rows.setdefault(
                key,
                []
            ).append(index)

    matched_urls = set()

    newly_success = 0
    content_missing = 0

    matches_since_save = 0
    dirty = False

    print("Can thu lay them:", total - already_success)
    print("Bat dau lay content tu Alpaca API...")

    try:

        for article in fetch_ticker_news(
            session,
            ticker
        ):

            article_url = normalize_url(
                article.get("url", "")
            )

            if (
                not article_url
                or article_url not in url_to_rows
            ):
                continue

            # Khong dem trung URL neu API tra lai bai bao nhieu lan.
            if article_url in matched_urls:
                continue

            matched_urls.add(article_url)
            matches_since_save += 1

            content = clean_article_content(
                article.get("content", "")
            )

            for index in url_to_rows[article_url]:

                current_text = str(
                    df.at[index, "Text"]
                ).strip()

                current_mark = int(
                    df.at[index, "Mark"]
                )

                # Khong ghi de bai da thanh cong.
                if (
                    current_mark == 1
                    and len(current_text) >= MIN_TEXT_LENGTH
                ):
                    continue

                if len(content) >= MIN_TEXT_LENGTH:

                    df.at[index, "Text"] = content
                    df.at[index, "Mark"] = 1

                    newly_success += 1
                    dirty = True

                    print(
                        f"  Co content: dong {index + 1}/{total} "
                        f"({len(content):,} ky tu)"
                    )

                else:

                    # De Mark=0 de co the thu lai o lan sau.
                    content_missing += 1

            # Luu theo lo de tranh ghi lai ca CSV sau moi URL.
            if matches_since_save >= SAVE_EVERY_MATCHES:

                if dirty:

                    atomic_save(
                        df,
                        csv_file
                    )

                    dirty = False

                matches_since_save = 0

    except KeyboardInterrupt:

        # Ctrl+C: luu ngay tien do dang co.
        if dirty:

            atomic_save(
                df,
                csv_file
            )

        print(
            "\nDa dung theo yeu cau. Tien do da duoc luu."
        )

        raise

    except Exception:

        # Neu API loi giua ticker, luu content da lay duoc.
        if dirty:

            atomic_save(
                df,
                csv_file
            )

        raise

    # Luu lan cuoi khi ticker hoan tat.
    if dirty:

        atomic_save(
            df,
            csv_file
        )

    success_total = int(
        (
            (df["Mark"] == 1)
            & (df["Text"].str.len() >= MIN_TEXT_LENGTH)
        ).sum()
    )

    pending_total = total - success_total
    matched = len(matched_urls)

    print(f"\n========== KET QUA {ticker} ==========")
    print("Tong bai trong CSV:", total)
    print("So URL khop voi Alpaca:", matched)
    print("So bai moi lay duoc content:", newly_success)
    print("Tong bai co content hop le:", success_total)
    print("Chua co content hop le:", pending_total)

    print(
        "So bai API khop URL nhung khong co content dat nguong:",
        content_missing
    )

    print("Da luu:", csv_file)

    return {
        "total": total,
        "matched": matched,
        "new_success": newly_success,
        "success_total": success_total,
        "pending": pending_total,
        "skipped": False
    }


# ============================================================
# CHON FILE THEO LIST
# ============================================================

def get_files_for_selection(selection):

    if selection == "all":

        files = []

        for folder in sorted(
            NEWS_CONTENTS_DIR.glob("list_*")
        ):

            if folder.is_dir():
                files.extend(
                    folder.glob("*.csv")
                )

        return sorted(files)

    # Vi du: a -> list_a; ab -> list_a va list_b.
    letters = "".join(
        dict.fromkeys(
            re.findall(r"[a-z]", selection)
        )
    )

    if not letters:
        return []

    files = []

    for letter in letters:

        folder = NEWS_CONTENTS_DIR / f"list_{letter}"

        if folder.exists() and folder.is_dir():

            files.extend(
                folder.glob("*.csv")
            )

    return sorted(files)


# ============================================================
# MAIN
# ============================================================

def main():

    print("========== ALPACA NEWS CONTENT SCRAPER ==========")

    print(
        "Thoi gian:",
        START_DATE,
        "->",
        END_DATE
    )

    print(
        "Thu muc ket qua:",
        NEWS_CONTENTS_DIR
    )

    if not API_KEY or not API_SECRET:

        print("Thieu API key trong file .env.")
        return

    if not NEWS_CONTENTS_DIR.exists():

        print(
            "Khong tim thay news_contents. "
            "Hay chay add_Mark.py truoc."
        )

        return

    selection = input(
        "\nNhap list can xu ly (a, ab, abc hoac all): "
    ).strip().lower()

    files = get_files_for_selection(selection)

    if not files:

        print("Khong tim thay file ticker phu hop.")
        return

    print(
        "So ticker se xu ly:",
        len(files)
    )

    session = requests.Session()

    session.headers.update(
        make_headers()
    )

    grand_total = 0
    grand_matched = 0
    grand_new_success = 0
    grand_success = 0
    grand_pending = 0

    completed_files = 0
    failed_files = []

    try:

        for file_index, csv_file in enumerate(
            files,
            start=1
        ):

            print(
                f"\n########## "
                f"[{file_index}/{len(files)}] "
                f"{csv_file.parent.name}/{csv_file.name} "
                f"##########"
            )

            try:

                result = process_ticker(
                    csv_file,
                    session
                )

                grand_total += result["total"]
                grand_matched += result["matched"]
                grand_new_success += result["new_success"]
                grand_success += result["success_total"]
                grand_pending += result["pending"]

                completed_files += 1

            except KeyboardInterrupt:

                print("\nDa dung chuong trinh.")
                break

            except Exception as error:

                failed_files.append(
                    csv_file.name
                )

                print(
                    f"LOI ticker {csv_file.stem}: {error}"
                )

            # Nghi ngan giua cac ticker de giam tan suat request.
            if file_index < len(files):
                time.sleep(DELAY_SECONDS)

    finally:

        session.close()

    print(
        "\n========== TONG KET CAC FILE DA HOAN THANH =========="
    )

    print("File da hoan thanh:", completed_files)
    print("Tong bai trong cac file da hoan thanh:", grand_total)
    print("URL khop voi Alpaca:", grand_matched)
    print("Bai moi lay duoc content:", grand_new_success)
    print("Bai co content:", grand_success)
    print("Bai chua co content:", grand_pending)

    print("Ticker gap loi:", len(failed_files))

    if failed_files:

        print("Danh sach ticker loi:")

        for ticker in failed_files:
            print("-", ticker)


if __name__ == "__main__":
    main()
