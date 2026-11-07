# QUY TRÌNH THU THẬP HEADLINES

## 1. Nguồn dữ liệu

- **Nguồn tin tức:** Alpaca News API
- **API Endpoint:** https://data.alpaca.markets/v1beta1/news
- **GitHub tham khảo:** https://github.com/Zdong104/FNSPID

## 2. Chuẩn bị

Tạo thư mục `headline_scraper` gồm:

```text
headline_scraper/
├── list/
├── headlines/
└── get_headlines.py
```

Trong đó:

- `list/`: Chứa danh sách mã cổ phiếu cần thu thập.
- `headlines/`: Lưu dữ liệu Headlines thu thập được.
- `get_headlines.py`: Chương trình thu thập tiêu đề bài báo.

## 3. Thu thập dữ liệu

### 3.1. Cài đặt thư viện

```bash
pip install pandas requests python-dotenv beautifulsoup4
```

### 3.2. Cấu hình API Key

Tạo file `.env` tại thư mục gốc dự án và khai báo:

```env
APCA_API_KEY_ID=YOUR_API_KEY
APCA_API_SECRET_KEY=YOUR_API_SECRET
```

### 3.3. Tiến hành thu thập

Chạy chương trình:

```bash
py get_headlines.py
```

Chương trình cho phép lựa chọn danh sách mã cổ phiếu cần thu thập.

## 4. Kết quả thu thập

Sau khi hoàn thành, dữ liệu được lưu dưới định dạng CSV, phân chia theo từng nhóm mã cổ phiếu.

Mỗi file chứa các trường:

- `Date`: Thời gian đăng bài.
- `Headline`: Tiêu đề bài báo.
- `URL`: Đường dẫn bài báo.

### 4.1. Thống kê kết quả

| Chỉ tiêu | Kết quả |
|---|---:|
| Số file ticker | 4.540 |
| Tổng số bài báo | 1.545.266 |
| Thiếu headline | 0 |
| Thiếu URL | 0 |
| URL trùng lặp | 0 |
| Thời gian dữ liệu | 17/04/2012 – 30/09/2026 |

### 4.2. Đánh giá

Quá trình thu thập hoàn thành 4.540 file ticker với tổng cộng 1.545.266 bản ghi Headlines.

Không ghi nhận tiêu đề hoặc URL bị thiếu và không phát hiện URL trùng lặp trong phạm vi kiểm tra của chương trình.
