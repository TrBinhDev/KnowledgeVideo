# KnowledgeVideo

Ứng dụng desktop (PySide6) tạo **video dọc 9:16 về kiến thức lịch sử** từ một chủ đề: AI gợi ý chủ đề, lập đề cương, viết kịch bản, chia cảnh, tự tìm ảnh tư liệu, đọc giọng tiếng Việt và render ra MP4.

Đây là bản thử nghiệm (prototype) cho luồng "Kiến thức" của dự án VIAI; chạy hoàn toàn trên máy, không cần database.

## Luồng tạo video

1. **Nội dung** – chọn loại nội dung (Kiến thức – Lịch sử), AI viết nội dung (Ollama hoặc Gemini, chọn model), độ dài video, giọng đọc, phong cách lời kể (kể chuyện, tư liệu, ngắn gọn, giảng giải), số ý chính. Rồi chọn một trong ba cách bắt đầu:
   - **Nhập từ khóa** – AI gợi ý chủ đề (bước 2).
   - **Nhập nội dung trực tiếp** – dán hoặc tải file `.txt`, `.docx`, `.pdf` (tối đa 10MB, dùng 15.000 ký tự đầu). *AI tóm tắt*: đề cương và lời đọc chỉ dùng dữ kiện trong tài liệu. *Dùng nguyên văn*: nội dung chính là lời đọc (dòng đầu ngắn là tiêu đề, câu đầu là hook), app chỉ chỉnh tốc độ đọc.
   - **Nhập kịch bản JSON** – dán kịch bản viết sẵn (ví dụ từ Claude/ChatGPT): `title`, `hook`, `paragraphs`; tùy chọn `outline` và `scenes` (lời đọc + từ khóa ảnh mỗi cảnh, có thì bỏ qua bước AI chia cảnh).
2. **Chủ đề** – AI gợi ý vài chủ đề kèm mô tả ngắn, người dùng chọn, sửa hoặc tự nhập.
3. **Kịch bản** – đề cương mỗi ý kèm mốc thời gian (`[0-15s]`), tổng luôn bằng độ dài đã chọn; sau khi xác nhận, AI viết lời đọc theo số từ của từng ý, đo bằng giọng đọc thật rồi tự chỉnh độ dài và tốc độ đọc để sai số trong khoảng ±3 giây. Cả hai đều sửa được.
4. **Cảnh & ảnh** – chia cảnh, mỗi cảnh tự tìm ảnh theo từ khóa riêng (tiếng Việt và tiếng Anh); đổi ảnh từng cảnh được.
5. **Mẫu & Render** – chọn template lịch sử (có ảnh mẫu), kiểu chuyển cảnh, giọng đọc, nhạc nền; xem trước template và chuyển cảnh bằng ảnh thật của video; xuất MP4 kèm phụ đề SRT/VTT.
   - **Nhịp ảnh**: *Theo câu đọc* (mỗi ảnh xuất hiện đúng lúc giọng đọc nói tới cảnh đó) hoặc *Chia đều*.
   - **Phụ đề**: *Thường*, *Highlight từng từ* (từ đang đọc đổi màu, kiểu TikTok, theo mốc thời gian từng từ của Edge TTS) hoặc *Tắt*.

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

Chuyển cảnh: "Theo template" dùng bộ riêng của từng template (Cổ thư: hòa tan, chớp đen; Hoàng triều: lướt ngang, mờ dần; Tư liệu: chớp đen, nhòe ngang), hoặc chọn một kiểu cố định, hoặc cắt thẳng.

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

Sidebar có 4 mục:

- **Tạo video** – 5 bước ở trên; nút "Video mới" để bắt đầu lại. Khi render có nút **Hủy**; xong thì **Xuất video** (MP4 kèm phụ đề `.srt` và ảnh bìa `.jpg` cùng tên ra thư mục bạn chọn).
- **Lịch sử video** – các video đã làm, mở lại để sửa ảnh, đổi mẫu hoặc render lại.
- **Mẫu video** – xem trước từng template với chuyển cảnh và chuyển động Ken Burns (dùng ảnh của video gần nhất, chưa có thì dùng ảnh minh họa tự vẽ); "Dùng mẫu này" áp dụng cho video đang làm.
- **Cài đặt** – sửa các giá trị trong `.env` ngay trong app, có hiệu lực không cần mở lại.

Mỗi lần tạo video được lưu trong `output/<ngày_giờ>__<chủ-đề>/`:

- `state.json` – chủ đề, đề cương, kịch bản, cảnh, nguồn và giấy phép ảnh, lựa chọn render
- `assets/` – ảnh của từng cảnh
- `render/final.mp4`, `render/thumbnail.jpg` (ảnh bìa), `render/subtitles.srt`, `render/subtitles.vtt`
- `preview/` – ảnh mẫu và clip xem trước (có thể xóa, sẽ tự tạo lại)

Log ở `output/logs/app.log`.

## Cấu trúc mã

```
main.py              Khởi động ứng dụng
ui/                  Giao diện PySide6: sidebar, 5 bước dạng card, panel tiến độ render
ui/widgets.py        Card, thanh bước, lưới lựa chọn dạng card, panel tiến độ
ui/icons.py          Bộ icon nét mảnh (SVG vẽ riêng)
ui/history_page.py   Lịch sử video
ui/templates_page.py Mẫu video
ui/settings_page.py  Cài đặt (.env)
core/ai/             Ollama, Gemini (danh sách model, tự chuyển model khi quá tải)
core/prompts.py      Prompt và JSON schema cho từng bước AI
core/steps.py        Gợi ý chủ đề, đề cương, kịch bản, canh thời lượng, chia cảnh
core/timing.py       Đo thời lượng giọng đọc thật, chỉnh tốc độ đọc
core/images.py       Tìm/tải ảnh, lọc bài/ảnh lạc đề, ảnh thay thế
core/title_cards.py  Thẻ tiêu đề cho template lịch sử (vẽ bằng Qt)
core/video_pipeline.py  TTS, phụ đề, ghép ảnh, FFmpeg, kiểm tra MP4
core/render.py       Chuẩn bị dữ liệu render
core/preview.py      Ảnh mẫu template và clip xem trước chuyển cảnh (dùng chung bộ lọc với render)
core/samples.py      Ảnh minh họa tự vẽ cho trang Mẫu video khi chưa có video nào
core/sources.py      Đọc tài liệu txt/docx/pdf, tách nội dung nguyên văn thành tiêu đề/hook/thân bài
assets/templates/    Khung SVG cho template tin tức
```

## Hạn chế đã biết

- Model nhỏ chạy local (`gemma3` 4B) hay bịa sự kiện lịch sử; Gemini chính xác hơn nhưng vẫn phải kiểm tra.
- Tìm ảnh tự động vẫn có cảnh ra ảnh lệch nội dung, nhất là chủ đề trừu tượng; nên xem lại từng cảnh.
- "Theo câu đọc" ước lượng điểm đổi ảnh theo độ dài chữ của từng cảnh trên mốc thời gian từng câu; ranh giới cảnh nằm giữa câu có thể lệch vài trăm mili giây.
- PDF dạng ảnh scan không đọc được (cần OCR).
