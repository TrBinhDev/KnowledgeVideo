# KnowledgeVideo

Ứng dụng desktop (PySide6) tạo **video dọc 9:16 về kiến thức lịch sử** từ một chủ đề: AI gợi ý chủ đề, lập đề cương, viết kịch bản, chia cảnh, tự tìm ảnh tư liệu, đọc giọng tiếng Việt và render ra MP4.

Đây là bản thử nghiệm (prototype) cho luồng "Kiến thức" của dự án VIAI; chạy hoàn toàn trên máy, không cần database.

## Luồng tạo video

1. **Bắt đầu** – chọn danh mục (Lịch sử), AI viết kịch bản (Ollama hoặc Gemini, chọn model), thời lượng; nhập từ khóa hoặc chủ đề.
2. **Chọn chủ đề** – AI gợi ý vài chủ đề, người dùng chọn hoặc sửa.
3. **Đề cương** – mỗi ý kèm số giây (`20s | nội dung`), tổng luôn bằng thời lượng đã chọn; duyệt/sửa được.
4. **Kịch bản** – viết theo số từ của từng đoạn; đo thời lượng bằng giọng đọc thật rồi tự chỉnh độ dài và tốc độ đọc để sai số trong khoảng ±3 giây.
5. **Cảnh & ảnh** – chia cảnh, mỗi cảnh tự tìm ảnh theo từ khóa riêng (tiếng Việt và tiếng Anh); đổi ảnh từng cảnh được.
6. **Render** – chọn giọng đọc, template lịch sử, nhạc nền; xuất MP4 kèm phụ đề SRT/VTT.

Mọi bước AI đều có duyệt/sửa: **AI có thể viết sai năm tháng, tên người, sự kiện — luôn kiểm tra kịch bản trước khi render.**

## Nguồn ảnh (tự động, theo thứ tự)

1. Wikimedia Commons theo từ khóa của cảnh (tiếng Việt, rồi tiếng Anh)
2. Wikipedia tiếng Việt theo từ khóa của cảnh
3. Openverse
4. Ảnh chung của chủ đề trên Wikipedia tiếng Việt (được gắn nhãn để kiểm tra lại)
5. Pollinations – ảnh minh họa AI miễn phí (có thể tắt)
6. Ảnh thay thế tự vẽ (để luôn render được)

Không cần API key cho các nguồn trên. Nút "Ảnh AI (Gemini)" chỉ dùng được với API key có bật billing.

> Ảnh Commons/Wikipedia/Openverse có giấy phép riêng (thường là CC BY-SA). Thông tin tác giả và giấy phép của từng ảnh được lưu trong `state.json`; khi đăng video công khai cần ghi công theo đúng giấy phép. Ảnh AI chỉ là minh họa, không phải tư liệu lịch sử thật.

## Template lịch sử

| Template | Phong cách |
|---|---|
| Cổ thư | Cuộn giấy da, con dấu năm, ảnh tông sepia |
| Hoàng triều | Dải đỏ son viền vàng kim |
| Tư liệu | Viền phim, năm cỡ lớn, ảnh đen trắng |

## Yêu cầu

- Windows, Python 3.12
- [FFmpeg](https://ffmpeg.org/) (`ffmpeg` và `ffprobe` có trong `PATH`)
- Internet (giọng đọc Edge TTS, tìm ảnh)
- Ít nhất một nguồn AI:
  - [Ollama](https://ollama.com/) chạy local (mặc định model `gemma3`: `ollama pull gemma3`), và/hoặc
  - Gemini API key

## Cài đặt

```powershell
git clone https://github.com/TrBinhDev/KnowledgeVideo.git
cd KnowledgeVideo
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Mở `.env` và điền các giá trị cần dùng (không commit file này):

| Biến | Ý nghĩa |
|---|---|
| `KV_GEMINI_API_KEY` | Key Gemini (để trống nếu chỉ dùng Ollama) |
| `KV_GEMINI_MODEL` | Model Gemini mặc định; trong app có thể chọn model khác và tự chuyển model khi quá tải |
| `KV_OLLAMA_URL`, `KV_OLLAMA_MODEL` | Địa chỉ và model Ollama |
| `KV_OUTPUT_DIR` | Thư mục lưu kết quả (mặc định `./output`) |
| `KV_HTTP_USER_AGENT` | User-Agent khi gọi Wikimedia (nên thêm thông tin liên hệ của bạn) |
| `KV_VIDEO_FONT` | Font TTF hỗ trợ tiếng Việt cho chữ trên video (mặc định Arial) |

## Chạy

```powershell
.\.venv\Scripts\python.exe main.py
```

Mỗi lần tạo video được lưu trong `output/<ngày_giờ>__<chủ-đề>/`:

- `state.json` – chủ đề, đề cương, kịch bản, cảnh, nguồn và giấy phép ảnh
- `assets/` – ảnh của từng cảnh
- `render/final.mp4`, `render/subtitles.srt`, `render/subtitles.vtt`

Log ở `output/logs/app.log`.

## Cấu trúc mã

```
main.py              Khởi động ứng dụng
ui/                  Giao diện PySide6 (6 bước, panel tiến độ + timeline)
core/ai/             Ollama, Gemini (danh sách model, tự chuyển model khi quá tải)
core/prompts.py      Prompt và JSON schema cho từng bước AI
core/steps.py        Gợi ý chủ đề, đề cương, kịch bản, canh thời lượng, chia cảnh
core/timing.py       Đo thời lượng giọng đọc thật, chỉnh tốc độ đọc
core/images.py       Tìm/tải ảnh, lọc bài/ảnh lạc đề, ảnh thay thế
core/title_cards.py  Thẻ tiêu đề cho template lịch sử (vẽ bằng Qt)
core/video_pipeline.py  TTS, phụ đề, ghép ảnh, FFmpeg, kiểm tra MP4
core/render.py       Chuẩn bị dữ liệu render
assets/templates/    Khung SVG cho template tin tức
```

## Hạn chế đã biết

- Model nhỏ chạy local (`gemma3` 4B) hay bịa sự kiện lịch sử; Gemini chính xác hơn nhưng vẫn phải kiểm tra.
- Tìm ảnh tự động vẫn có cảnh ra ảnh lệch nội dung, nhất là chủ đề trừu tượng; nên xem lại từng cảnh.
- Ảnh được chia đều theo thời lượng video, chưa khớp chính xác theo từng câu đọc.
