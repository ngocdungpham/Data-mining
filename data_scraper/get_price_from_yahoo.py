import os
import time
import pandas as pd
import yfinance as yf


def is_valid_csv(file_path):
    """Kiem tra file gia co ton tai va co du lieu hop le hay khong."""
    if not os.path.isfile(file_path):
        return False

    try:
        if os.path.getsize(file_path) == 0:
            return False

        df = pd.read_csv(file_path)

        required_columns = [
            "Date", "Open", "High", "Low",
            "Close", "Adj Close", "Volume"
        ]

        # File phai co du cac cot can thiet va co du lieu
        if df.empty:
            return False

        if not all(col in df.columns for col in required_columns):
            return False

        # Phai co it nhat mot dong co du lieu gia
        if df["Date"].isna().all() or df["Close"].isna().all():
            return False

        return True

    except Exception:
        return False


def get_price(ticker, output_path):
    """Tai du lieu gia. Tra ve 1 neu thanh cong, 0 neu that bai."""

    for attempt in range(1, 4):
        try:
            print("Lan thu", attempt, "- dang tai:", ticker)

            data = yf.download(
                ticker,
                start="2020-01-01",
                end="2026-10-01",
                auto_adjust=False,
                progress=False,
                threads=False
            )

            if data.empty:
                print("Khong co du lieu:", ticker)

            else:
                # Chuyen tieu de nhieu cap thanh tieu de mot cap
                if isinstance(data.columns, pd.MultiIndex):
                    data.columns = data.columns.get_level_values(0)

                # Dua ngay giao dich thanh cot Date
                data.index.name = "Date"
                data = data.reset_index()

                # Dam bao cac cot co dung thu tu mong muon
                required_columns = [
                    "Date", "Open", "High", "Low",
                    "Close", "Adj Close", "Volume"
                ]

                if all(col in data.columns for col in required_columns):
                    data = data[required_columns]

                    # Luu CSV khong them chi muc thua
                    data.to_csv(output_path, index=False)

                    if is_valid_csv(output_path):
                        print("Da luu:", output_path)
                        return 1

                    print("File khong co du lieu hop le:", ticker)

                else:
                    print("Thieu cot du lieu can thiet:", ticker)
                    print("Cac cot hien co:", list(data.columns))

        except Exception as e:
            print("Loi khi tai", ticker, ":", e)

        # Cho truoc khi thu lai, neu chua phai lan cuoi
        if attempt < 3:
            time.sleep(1)

    print("Bo qua ma that bai:", ticker)
    return 0


def process_list(init):
    """Xu ly mot danh sach co ten list_<init>.csv."""

    list_file_path = "list_" + init + ".csv"
    list_path = os.path.join("lists", list_file_path)

    if not os.path.isfile(list_path):
        print("Khong tim thay danh sach:", list_path)
        return 0, 0

    list_df = pd.read_csv(list_path, encoding="utf-8")

    if "Stock_name" not in list_df.columns or "Mark" not in list_df.columns:
        print("Danh sach thieu cot Stock_name hoac Mark:", list_path)
        return 0, 0

    # Tao thu muc rieng cho tung list
    output_folder = os.path.join("yahoo", "list_" + init)
    os.makedirs(output_folder, exist_ok=True)

    success = 0
    failed = 0

    for index, row in list_df.iterrows():
        value = row["Stock_name"]

        if pd.isna(value) or not str(value).strip():
            print("Bo qua dong khong co ma co phieu:", index + 1)
            list_df.at[index, "Mark"] = 0
            list_df.to_csv(list_path, index=False)
            failed += 1
            continue

        ticker = str(value).strip()
        output_path = os.path.join(output_folder, ticker + ".csv")

        print(
            "\nDang xu ly:", ticker,
            "--", index + 1, "/", len(list_df)
        )

        # Chi bo qua neu file hop le va Mark da bang 1
        if (
            list_df.at[index, "Mark"] == 1
            and is_valid_csv(output_path)
        ):
            print("Da co du lieu hop le:", output_path)
            success += 1

        else:
            # File bi mat, khong hop le hoac Mark = 0: tai lai
            list_df.at[index, "Mark"] = 0
            list_df.to_csv(list_path, index=False)

            result = get_price(ticker, output_path)
            list_df.at[index, "Mark"] = result

            if result == 1:
                success += 1
            else:
                failed += 1

        # Luu trang thai sau moi ma
        list_df.to_csv(list_path, index=False)
        time.sleep(0.1)

    print("\nHoan tat list_" + init)
    print("Tong so ma:", len(list_df))
    print("Thanh cong:", success)
    print("That bai:", failed)

    return success, failed


if __name__ == "__main__":
    inits = input(
        "Nhap cac list can cao (vi du: a hoac abc): "
    ).strip().lower()

    # Loai bo ky tu lap neu nguoi dung nhap trung
    inits = "".join(dict.fromkeys(inits))

    total_success = 0
    total_failed = 0

    for init in inits:
        if not init.isalpha() or len(init) != 1:
            print("Bo qua ky tu khong hop le:", init)
            continue

        success, failed = process_list(init)
        total_success += success
        total_failed += failed

    print("\n===== TONG KET =====")
    print("Tong ma thanh cong:", total_success)
    print("Tong ma that bai:", total_failed)
