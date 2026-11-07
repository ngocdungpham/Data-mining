
import os
import re
import json
import time
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter

import requests
import pandas as pd
from dotenv import load_dotenv


# ============================================================
# CAU HINH
# ============================================================

# Thu muc goc FNSPID_GiaCoPhieu
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

# Doc API Key tu file .env
load_dotenv(PROJECT_ROOT / ".env")

API_KEY = os.getenv("APCA_API_KEY_ID")
API_SECRET = os.getenv("APCA_API_SECRET_KEY")

API_URL = "https://data.alpaca.markets/v1beta1/news"

# Thoi gian: 2020 den het thang 9/2026
START_DATE = "2020-01-01T00:00:00Z"
END_DATE = "2026-10-01T00:00:00Z"

LIMIT = 50

# Danh sach ticker lay tu stock_price_scraper
LIST_DIR = PROJECT_ROOT / "stock_price_scraper" / "lists"

# Thu muc luu ket qua va tien do
OUTPUT_DIR = BASE_DIR / "headlines"
PROGRESS_DIR = BASE_DIR / "progress"

MAX_RETRIES = 3
REQUEST_TIMEOUT = 30


# ============================================================
# API
# ============================================================

def make_headers():

    if not API_KEY or not API_SECRET:
        raise ValueError(
            "Khong tim thay API Key trong file .env"
        )

    return {
        "APCA-API-KEY-ID": API_KEY,
        "APCA-API-SECRET-KEY": API_SECRET
    }


def format_date(created_at):

    if not created_at:
        return ""

    try:
        dt = datetime.fromisoformat(
            str(created_at).replace("Z", "+00:00")
        )

        return dt.astimezone(timezone.utc).strftime(
            "%b %d, %Y"
        ).upper()

    except ValueError:
        return str(created_at)


def request_page(session, headers, params):

    for attempt in range(1, MAX_RETRIES + 1):

        try:
            response = session.get(
                API_URL,
                headers=headers,
                params=params,
                timeout=REQUEST_TIMEOUT
            )

            if response.status_code == 200:
                return response.json()

            if response.status_code in (429, 500, 502, 503, 504):

                if attempt < MAX_RETRIES:
                    wait_time = 2 ** attempt

                    print(
                        f"API loi {response.status_code}. "
                        f"Thu lai sau {wait_time}s..."
                    )

                    time.sleep(wait_time)
                    continue

            raise RuntimeError(
                f"HTTP {response.status_code}: {response.text}"
            )

        except requests.exceptions.RequestException as error:

            if attempt == MAX_RETRIES:
                raise RuntimeError(str(error))

            time.sleep(2 ** attempt)

    raise RuntimeError("Khong the ket noi Alpaca API.")


# ============================================================
# DOC DANH SACH TICKER
# ============================================================

def read_tickers(list_file):

    df = pd.read_csv(list_file)

    if df.empty:
        return []

    columns = {
        str(col).strip().lower(): col
        for col in df.columns
    }

    ticker_column = None

    for name in ["stock_name", "symbol", "ticker"]:

        if name in columns:
            ticker_column = columns[name]
            break

    if ticker_column is None:
        ticker_column = df.columns[0]

    tickers = (
        df[ticker_column]
        .dropna()
        .astype(str)
        .str.strip()
        .str.upper()
    )

    return list(dict.fromkeys(
        ticker for ticker in tickers
        if ticker and ticker.lower() != "nan"
    ))


def get_list_files(letters):

    files = []

    for letter in letters:

        list_file = LIST_DIR / f"list_{letter}.csv"

        if list_file.exists():
            files.append((letter, list_file))

        else:
            print(f"Khong tim thay {list_file.name}")

    return files


# ============================================================
# CHECKPOINT
# ============================================================

def load_checkpoint(checkpoint_file):

    if not checkpoint_file.exists():
        return {
            "next_page_token": None,
            "page_number": 0
        }

    try:
        with open(checkpoint_file, "r", encoding="utf-8") as f:
            return json.load(f)

    except (json.JSONDecodeError, OSError):

        return {
            "next_page_token": None,
            "page_number": 0
        }


def save_checkpoint(checkpoint_file, next_token, page_number):

    checkpoint_file.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    data = {
        "next_page_token": next_token,
        "page_number": page_number,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }

    temp_file = checkpoint_file.with_suffix(".tmp")

    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    temp_file.replace(checkpoint_file)


# ============================================================
# LUU DU LIEU
# ============================================================

def append_page_to_csv(news, output_file):

    rows = []

    for article in news:

        headline = article.get("headline", "")
        url = article.get("url", "")
        created_at = article.get("created_at", "")

        if not headline or not url:
            continue

        rows.append({
            "Date": format_date(created_at),
            "Headline": headline.strip(),
            "URL": url.strip()
        })

    columns = ["Date", "Headline", "URL"]

    new_df = pd.DataFrame(rows, columns=columns)

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    if output_file.exists():

        old_df = pd.read_csv(output_file)

        combined = pd.concat(
            [old_df, new_df],
            ignore_index=True
        )

    else:
        combined = new_df

    # Loai bai trung theo URL
    combined = combined.drop_duplicates(
        subset=["URL"],
        keep="first"
    )

    combined = combined.reset_index(drop=True)

    # Ghi file tam truoc khi thay the CSV chinh
    temp_file = output_file.with_suffix(".tmp")

    combined.to_csv(
        temp_file,
        index=False,
        encoding="utf-8-sig"
    )

    temp_file.replace(output_file)

    return len(combined)


# ============================================================
# CAO MOT TICKER
# ============================================================

def get_headlines(symbol, output_file, checkpoint_file):

    headers = make_headers()
    session = requests.Session()

    checkpoint = load_checkpoint(checkpoint_file)

    page_number = checkpoint["page_number"]
    next_token = checkpoint["next_page_token"]

    params = {
        "symbols": symbol,
        "start": START_DATE,
        "end": END_DATE,
        "limit": LIMIT,
        "sort": "asc",
        "include_content": "false"
    }

    if next_token:

        params["page_token"] = next_token

        print(
            f"Tiep tuc {symbol} tu trang {page_number + 1}"
        )

    else:

        page_number = 0

        print(f"Bat dau cao {symbol}")

    try:

        seen_tokens = set()

        while True:

            data = request_page(
                session,
                headers,
                params
            )

            news = data.get("news", [])

            page_number += 1

            total_saved = append_page_to_csv(
                news,
                output_file
            )

            print(
                f"Trang {page_number}: {len(news)} bai bao "
                f"| Tong da luu: {total_saved}"
            )

            next_token = data.get("next_page_token")

            # Luu checkpoint sau khi CSV da duoc ghi
            save_checkpoint(
                checkpoint_file,
                next_token,
                page_number
            )

            if not next_token:
                break

            if next_token in seen_tokens:
                raise RuntimeError(
                    "next_page_token bi lap."
                )

            seen_tokens.add(next_token)

            params["page_token"] = next_token

    finally:

        session.close()

    # Danh dau ticker da hoan thanh
    done_file = checkpoint_file.with_suffix(".done")

    done_file.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    done_file.touch()

    if checkpoint_file.exists():
        checkpoint_file.unlink()


# ============================================================
# THONG KE
# ============================================================

def print_summary(symbol, output_file):

    if not output_file.exists():
        return

    df = pd.read_csv(output_file)

    print(f"\n========== KET QUA {symbol} ==========")

    print("Tong so headline:", len(df))

    if not df.empty:

        years = pd.to_datetime(
            df["Date"],
            format="%b %d, %Y",
            errors="coerce"
        ).dt.year

        counts = Counter(
            years.dropna().astype(int)
        )

        print("\nSo bai theo nam:")

        for year in sorted(counts):
            print(f"{year}: {counts[year]}")

    print("\nDa luu:", output_file)


# ============================================================
# CHUONG TRINH CHINH
# ============================================================

def main():

    make_headers()

    print("========== ALPACA HEADLINE SCRAPER ==========")

    print("Thoi gian:", START_DATE, "->", END_DATE)

    print("Thu muc danh sach:", LIST_DIR)

    if not LIST_DIR.exists():

        print("Khong tim thay thu muc lists.")
        return

    letters = input(
        "\nNhap list can cao (vi du: a hoac abcdef): "
    ).strip().lower()

    # Nhan abcdef thanh tung list rieng
    letters = "".join(
        dict.fromkeys(re.findall(r"[a-z]", letters))
    )

    if not letters:

        print("Danh sach nhap khong hop le.")
        return

    list_files = get_list_files(letters)

    if not list_files:

        print("Khong co list nao hop le.")
        return

    for letter, list_file in list_files:

        print(
            f"\n\n========== LIST {letter.upper()} =========="
        )

        tickers = read_tickers(list_file)

        print("Tong so ticker:", len(tickers))

        # Moi list co thu muc rieng
        list_output_dir = OUTPUT_DIR / f"list_{letter}"

        list_progress_dir = PROGRESS_DIR / f"list_{letter}"

        success = 0
        skipped = 0
        failed = 0

        for index, ticker in enumerate(tickers, start=1):

            output_file = (
                list_output_dir / f"{ticker.lower()}.csv"
            )

            checkpoint_file = (
                list_progress_dir / f"{ticker.lower()}.json"
            )

            done_file = checkpoint_file.with_suffix(".done")

            print(
                f"\n[{index}/{len(tickers)}] Ticker: {ticker}"
            )

            # Bo qua ticker da hoan thanh
            if done_file.exists() and output_file.exists():

                print("Da hoan thanh, bo qua.")

                skipped += 1
                continue

            try:

                get_headlines(
                    ticker,
                    output_file,
                    checkpoint_file
                )

                print_summary(
                    ticker,
                    output_file
                )

                success += 1

            except KeyboardInterrupt:

                print("\nDa dung chuong trinh.")

                print(
                    "Du lieu da luu van duoc giu lai. "
                    "Chay lai va nhap list cu de tiep tuc."
                )

                return

            except Exception as error:

                print(
                    f"LOI ticker {ticker}: {error}"
                )

                failed += 1

        print(
            f"\n========== TONG KET LIST {letter.upper()} =========="
        )

        print("Thanh cong:", success)
        print("Da bo qua:", skipped)
        print("That bai:", failed)

    print("\nHOAN THANH CAC LIST DUOC CHON!")


if __name__ == "__main__":
    main()
