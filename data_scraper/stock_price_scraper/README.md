1. Nguồn
	api: https://finance.yahoo.com/?utm_source=chatgpt.com
	github: github.com/Zdong104/FNSPID
	
2.Chuẩn bị
	Tạo thư mục stock_price_scraper gồm:
	   + thư mục list (mã cổ phiếu cần cào)
	   + thư mục yahoo (dữ liệu cào được)
	   + add_Mark.py (khởi tạo trạng thái của mã cần cào là 0, chuẩn bị dữ liệu đầu vào). Code lấy y nguyên từ github
	   + get_price_from_yahoo.py (chương trình cào dữ liệu). Cải tiến từ code trong github. 

3.Cào
	+ cài thư viện pandas, yfinance và numpy (thường cài tự động cùng pandas)
	+ chạy add_Mark.py để khởi tạo Mark của các mã = 0.
	+ chạy get_price_from_yahoo.py để cào dữ liệu. Nếu cào được dữ liệu sẽ đánh Mark = 1 và dữ liệu sẽ được lưu vào thư mục yahoo.
	+ Cào xong thu được 

===== KẾT QUẢ =====
Số file CSV có dữ liệu ngày hợp lệ: 3,749
Tổng số bản ghi giá cổ phiếu: 6,274,575
Số file lỗi hoặc không hợp lệ: 0

===== THỐNG KÊ MÃ CỔ PHIẾU =====
Tổng số mã trong danh sách: 4,540
Số mã cào thành công: 3,749
Số mã cần kiểm tra/cào lại: 791
Danh sách mã cần kiểm tra/cào lại đã lưu vào failed_tickers.csv

4.Đẩy dữ liệu lên hugging face.

https://huggingface.co/trthanh226789

