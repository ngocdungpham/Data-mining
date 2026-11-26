# QUY TRÌNH THU THẬP NEWS CONTENT

## 1. Nguồn dữ liệu

- **Nguồn tin tức:** Alpaca News API
- **API Endpoint:** https://data.alpaca.markets/v1beta1/news
- **GitHub tham khảo:** https://github.com/Zdong104/FNSPID

News Content được thu thập dựa trên danh sách Headlines đã có. Chương trình sử dụng URL của từng bài báo để đối chiếu và lấy nội dung chi tiết thông qua Alpaca News API.

## 2. Chuẩn bị

Tạo thư mục `news_content_scraper` gồm:

```text
news_content_scraper/
├── news_contents/
└── get_content.py
```

Trong đó:

- `news_contents/`: Lưu nội dung bài báo sau khi thu thập, được phân chia theo từng nhóm mã cổ phiếu.
- `get_content.py`: Chương trình thu thập nội dung bài báo từ Alpaca News API.

Dữ liệu Headlines đầu vào được lấy từ thư mục `headline_scraper/headlines/`.

## 3. Thu thập dữ liệu

### 3.1. Cài đặt thư viện

```bash
pip install pandas requests python-dotenv beautifulsoup4
```

### 3.2. Cấu hình API Key

Sử dụng file `.env` tại thư mục gốc dự án với các thông tin:

```env
APCA_API_KEY_ID=YOUR_API_KEY
APCA_API_SECRET_KEY=YOUR_API_SECRET
```

### 3.3. Tiến hành thu thập

Chạy chương trình:

```bash
py get_content.py
```

Chương trình đọc dữ liệu Headlines đã thu thập, sử dụng URL để đối chiếu với dữ liệu từ Alpaca News API và lấy nội dung chi tiết của các bài báo.

Quá trình thu thập có hỗ trợ phân trang và thử lại khi gặp lỗi kết nối. Dữ liệu được lưu theo từng nhóm mã cổ phiếu để thuận tiện cho việc quản lý và tiếp tục xử lý.

## 4. Kết quả thu thập

Sau khi hoàn thành, dữ liệu được lưu dưới định dạng CSV và phân chia theo từng nhóm mã cổ phiếu.

Cấu trúc thư mục kết quả:

```text
news_contents/
├── list_a/
│   ├── A.csv
│   ├── AA.csv
│   └── ...
├── list_b/
│   └── ...
└── ...
```

Mỗi file chứa các trường:

- `Date`: Thời gian đăng bài.
- `Url`: Đường dẫn bài báo.
- `Text`: Nội dung chi tiết của bài báo.
- `Mark`: Trạng thái thu thập nội dung.

### 4.1. Thống kê kết quả

| Chỉ tiêu | Kết quả |
|---|---:|
| Số file ticker | 4.540 |
| Tổng số bài báo | 1.545.266 |
| Bài báo có nội dung | 894.217 |
| Bài báo thiếu nội dung | 651.049 |
| Tỷ lệ có nội dung | 57,87% |
| Tỷ lệ thiếu nội dung | 42,13% |

### 4.2. Đánh giá

Quá trình thu thập đã xử lý 4.540 file ticker với tổng cộng 1.545.266 bản ghi bài báo.

Trong đó, có 894.217 bài báo thu thập được nội dung chi tiết, chiếm 57,87%. Còn lại 651.049 bài báo chưa có nội dung, chiếm 42,13%.

Việc một số bài báo không có nội dung có thể xuất phát từ việc API không cung cấp trường nội dung cho bài báo tương ứng. Do đó, không phải tất cả Headlines đều có thể thu thập được phần nội dung chi tiết.

Dữ liệu News Content sau khi thu thập được lưu trữ riêng theo từng nhóm mã cổ phiếu, phục vụ cho các bước kiểm tra, làm sạch và xử lý dữ liệu tiếp theo.
