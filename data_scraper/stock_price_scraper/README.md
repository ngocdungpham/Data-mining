# Stock Price Scraper

## 1. Nguồn dữ liệu

- **API:** [Yahoo Finance](https://finance.yahoo.com/)
- **GitHub gốc:** [Zdong104/FNSPID](https://github.com/Zdong104/FNSPID)

## 2. Chuẩn bị

Tạo thư mục `stock_price_scraper` gồm các thành phần sau:

- `list/`: Chứa danh sách mã cổ phiếu cần cào.
- `yahoo/`: Chứa dữ liệu giá cổ phiếu đã cào được.
- `add_Mark.py`: Khởi tạo trạng thái của các mã cổ phiếu bằng `Mark = 0`, chuẩn bị dữ liệu đầu vào. Code được giữ nguyên từ GitHub gốc.
- `get_price_from_yahoo.py`: Chương trình cào dữ liệu giá cổ phiếu, được cải tiến từ code của GitHub gốc.

## 3. Cào dữ liệu

### 3.1. Cài đặt thư viện

Cài đặt các thư viện cần thiết bằng lệnh:

```bash
pip install pandas yfinance numpy
```

### 3.2. Chạy chương trình

**Bước 1:** Chạy `add_Mark.py` để khởi tạo trạng thái của các mã cổ phiếu bằng `Mark = 0`.

```bash
python add_Mark.py
```

**Bước 2:** Chạy `get_price_from_yahoo.py` để cào dữ liệu giá cổ phiếu.

```bash
python get_price_from_yahoo.py
```

Nếu cào dữ liệu thành công, chương trình đánh dấu `Mark = 1` và lưu dữ liệu vào thư mục `yahoo/`.

### 3.3. Kết quả thu được

#### Thống kê dữ liệu

| Chỉ tiêu | Kết quả |
|---|---:|
| Số file CSV có dữ liệu ngày hợp lệ | 3,749 |
| Tổng số bản ghi giá cổ phiếu | 6,274,575 |
| Số file lỗi hoặc không hợp lệ | 0 |

#### Thống kê mã cổ phiếu

| Chỉ tiêu | Kết quả |
|---|---:|
| Tổng số mã trong danh sách | 4,540 |
| Số mã cào thành công | 3,749 |
| Số mã cần kiểm tra hoặc cào lại | 791 |

Danh sách các mã cần kiểm tra hoặc cào lại được lưu trong file `failed_tickers.csv`.

## 4. Đẩy dữ liệu lên Hugging Face

Dữ liệu giá cổ phiếu được tải lên Hugging Face tại:

[Hugging Face Dataset](https://huggingface.co/trthanh226789)

