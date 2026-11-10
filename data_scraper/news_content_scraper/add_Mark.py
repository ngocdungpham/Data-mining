
import os
import time
from pathlib import Path

import pandas as pd


# ============================================================
# CAU HINH THU MUC
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

# Thu muc chua headline:
# headline_scraper/headlines/list_a/aapl.csv
HEADLINES_DIR = PROJECT_ROOT / "headline_scraper" / "headlines"

# Thu muc luu content:
# news_content_scraper/news_contents/list_a/aapl.csv
NEWS_CONTENTS_DIR = BASE_DIR / "news_contents"

OUTPUT_COLUMNS = ["Date", "Url", "Text", "Mark"]


# ============================================================
# CAC HAM HO TRO
# ============================================================

def read_csv_safely(file_path):
    """Doc CSV voi mot so encoding pho bien."""
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
        try:
            return pd.read_csv(file_path, encoding=encoding)
        except UnicodeDecodeError:
            continue

    raise ValueError(f"Khong doc duoc file: {file_path}")


def normalize_columns(df):
    """Chuan hoa ten cot headline."""
    rename_map = {}

    for col in df.columns:
        key = str(col).strip().lower()

        if key == "date":
            rename_map[col] = "Date"
        elif key == "headline":
            rename_map[col] = "Headline"
        elif key in ("url", "uri", "link"):
            rename_map[col] = "URL"

    return df.rename(columns=rename_map)


def atomic_save(df, output_file):
    """Ghi file tam, sau do thay the file chinh."""
    output_file.parent.mkdir(parents=True, exist_ok=True)

    temp_file = output_file.with_name(
        output_file.stem + ".tmp"
    )

    df.to_csv(temp_file, index=False, encoding="utf-8-sig")

    for attempt in range(5):
        try:
            os.replace(temp_file, output_file)
            return
        except PermissionError:
            if attempt == 4:
                raise

            print(f"File dang bi khoa, thu lai lan {attempt + 2}/5...")
            time.sleep(2)


def preserve_old_progress(new_df, output_file):
    """
    Neu file cu ton tai:
    - Giu lai Text va Mark theo Url.
    Neu file chua ton tai:
    - Su dung du lieu moi, Text rong, Mark=0.
    """
    if not output_file.exists():
        return new_df

    try:
        old_df = read_csv_safely(output_file)

        for col in OUTPUT_COLUMNS:
            if col not in old_df.columns:
                old_df[col] = "" if col != "Mark" else 0

        old_df = old_df[OUTPUT_COLUMNS].copy()

        old_df["Url"] = (
            old_df["Url"].astype("string").fillna("").str.strip()
        )
        old_df["Text"] = (
            old_df["Text"].astype("string").fillna("")
        )
        old_df["Mark"] = pd.to_numeric(
            old_df["Mark"], errors="coerce"
        ).fillna(0).astype(int)

        old_df = old_df.drop_duplicates(
            subset=["Url"], keep="first"
        )

        old_data = old_df.set_index("Url")

        for index, row in new_df.iterrows():
            url = str(row["Url"]).strip()

            if url in old_data.index:
                old_row = old_data.loc[url]

                if isinstance(old_row, pd.DataFrame):
                    old_row = old_row.iloc[0]

                new_df.at[index, "Text"] = str(old_row["Text"])
                new_df.at[index, "Mark"] = int(old_row["Mark"])

    except Exception as error:
        print(f"Canh bao: khong doc duoc file cu {output_file}: {error}")
        print("File se duoc khoi tao lai tu headline.")

    return new_df


# ============================================================
# XU LY TUNG LIST
# ============================================================

def process_list(list_folder):
    """
    Moi list co mot thu muc rieng trong news_contents.
    Vi du:
    headlines/list_a/aapl.csv
    -> news_contents/list_a/aapl.csv
    """

    headline_files = sorted(list_folder.glob("*.csv"))

    if not headline_files:
        print(f"{list_folder.name}: Khong co file CSV.")
        return 0, 0

    # Tao thu muc dau ra tuong ung
    output_folder = NEWS_CONTENTS_DIR / list_folder.name
    output_folder.mkdir(parents=True, exist_ok=True)

    ticker_count = 0
    total_urls = 0

    for file_path in headline_files:
        ticker = file_path.stem.strip().lower()

        try:
            df = normalize_columns(read_csv_safely(file_path))

            if not {"Date", "URL"}.issubset(df.columns):
                print(f"Bo qua {file_path}: thieu cot Date hoac URL.")
                continue

            # Tao du lieu dau ra
            new_df = pd.DataFrame({
                "Date": df["Date"].astype("string").fillna(""),
                "Url": df["URL"].astype("string").fillna("").str.strip()
            })

            # Loai URL rong
            new_df = new_df[new_df["Url"] != ""].copy()
            new_df = new_df[
                new_df["Url"].str.lower() != "nan"
            ].copy()

            # Loai URL trung lap trong cung ticker
            new_df = new_df.drop_duplicates(
                subset=["Url"], keep="first"
            ).reset_index(drop=True)

            # Khoi tao Text va Mark
            new_df["Text"] = ""
            new_df["Mark"] = 0

            new_df = new_df[OUTPUT_COLUMNS]

            # Duong dan luu theo tung list
            output_file = output_folder / f"{ticker}.csv"

            # Neu file cu ton tai thi giu tien do
            new_df = preserve_old_progress(new_df, output_file)

            new_df["Text"] = (
                new_df["Text"].astype("string").fillna("")
            )
            new_df["Mark"] = pd.to_numeric(
                new_df["Mark"], errors="coerce"
            ).fillna(0).astype(int)

            new_df = new_df[OUTPUT_COLUMNS]

            atomic_save(new_df, output_file)

            ticker_count += 1
            total_urls += len(new_df)

            success = int((new_df["Mark"] == 1).sum())
            pending = len(new_df) - success

            print(
                f"{list_folder.name}/{ticker}: "
                f"{len(new_df)} URL | "
                f"Da co content: {success} | "
                f"Can xu ly: {pending}"
            )

        except Exception as error:
            print(f"LOI ticker {ticker}: {error}")

    return ticker_count, total_urls


# ============================================================
# MAIN
# ============================================================

def main():
    print("========== INITIALIZE NEWS CONTENT FILES ==========")
    print("Nguon headlines:", HEADLINES_DIR)
    print("Thu muc ket qua:", NEWS_CONTENTS_DIR)

    if not HEADLINES_DIR.exists():
        print("Khong tim thay headline_scraper/headlines.")
        return

    list_folders = sorted(
        folder
        for folder in HEADLINES_DIR.glob("list_*")
        if folder.is_dir()
    )

    if not list_folders:
        print("Khong tim thay thu muc list_*.")
        return

    total_tickers = 0
    total_urls = 0

    for list_folder in list_folders:
        print(f"\n========== {list_folder.name} ==========")

        ticker_count, url_count = process_list(list_folder)

        total_tickers += ticker_count
        total_urls += url_count

    print("\n========== HOAN THANH ==========")
    print("Tong so ticker:", total_tickers)
    print("Tong so URL:", total_urls)
    print("Thu muc luu:", NEWS_CONTENTS_DIR)
    print("Du lieu duoc chia theo tung list.")
    print("File cu duoc giu lai neu da ton tai.")
    print("File moi co Text rong va Mark=0.")


if __name__ == "__main__":
    main()
