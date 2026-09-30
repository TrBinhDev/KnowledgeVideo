# KnowledgeVideo Desktop

Giao diện Next.js + Electron nằm trọn trong thư mục này. Electron mở bản Next.js đã xuất tĩnh và giao tiếp với `backend.py` qua JSON lines. `backend.py` gọi trực tiếp các hàm trong `../core`, nên video và dự án cũ trong `output/` vẫn dùng được.

## Chạy

Cài Python theo `../requirements.txt`, FFmpeg/FFprobe và các công cụ clip được mô tả ở README gốc. Sau đó:

```powershell
cd frontend
npm install
npm run dev
```

`npm run dev` build giao diện rồi mở Electron. Sau khi sửa mã, chạy lại lệnh này để thấy thay đổi trong cửa sổ desktop. `npm run dev:web` chạy Next.js có cập nhật trực tiếp trong trình duyệt, nhưng các thao tác tạo video cần Electron. Có thể đặt biến môi trường `KV_PYTHON` nếu Python cần dùng không nằm ở `../.venv/Scripts/python.exe`.

```powershell
npm run typecheck
npm run build
npm start
```

`npm start` mở bản tĩnh trong `out/`, vì vậy hãy chạy `npm run build` sau mỗi lần sửa giao diện.

## Bốn luồng

| Chất liệu | Cách làm | Các bước |
| --- | --- | --- |
| Ảnh | Tự động | Nội dung → Diện mạo → Tạo video |
| Clip | Tự động | Nội dung → Video nguồn → Diện mạo → Tạo video |
| Ảnh | Thủ công | Nội dung → Chủ đề → Kịch bản → Cảnh & ảnh → Diện mạo → Tạo video |
| Clip | Thủ công | Nội dung → Chủ đề → Kịch bản → Cảnh & clip → Diện mạo → Tạo video |

Các mục Lịch sử, Thư viện mẫu và Cài đặt dùng cùng dữ liệu và chức năng của ứng dụng Python. Nội dung (AI, giọng, thời lượng, số ý/cảnh), diện mạo (template, chuyển cảnh, phụ đề, nhạc và độ phân giải) được chọn ở bước tương ứng. Phần cuối chỉ tổng kết các lựa chọn và tạo video.

## Cấu trúc

- `app/`: giao diện và CSS.
- `electron/main.cjs`: cửa sổ desktop, giao thức tải file, quản lý Python.
- `electron/preload.cjs`: API IPC giới hạn cho giao diện.
- `backend.py`: cầu nối tới `core/`, chạy một tác vụ dài tại một thời điểm và hỗ trợ hủy.

Electron yêu cầu nội dung web chạy trong cửa sổ ứng dụng. Mở `localhost` bằng trình duyệt thường chỉ hiển thị giao diện; các lệnh tạo video cần Electron và Python bridge.
