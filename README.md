# KnowledgeVideo

## Giao diện hiện tại: Next.js + Electron

Giao diện mới nằm trong `frontend/` và dùng lại toàn bộ phần xử lý Python trong `core/`. Sidebar gồm **Tạo video**, **Lịch sử video**, **Thư viện mẫu** và **Cài đặt**. Trong Tạo video, chọn **Ảnh / Clip**, sau đó chọn **Tự động / Thủ công**. Số bước thay đổi theo luồng; template, chuyển cảnh, phụ đề và xem trước được chọn trước khi tạo video.

Sau khi cài Python và FFmpeg theo phần yêu cầu bên dưới, cài frontend và chạy:

```powershell
cd frontend
npm install
npm run dev
```

Để chạy bản build tĩnh trong Electron:

```powershell
cd frontend
npm run build
npm start
```

Node.js và npm là yêu cầu bổ sung cho giao diện mới. Có thể đặt `KV_PYTHON` tới Python đã cài `requirements.txt`; mặc định Electron dùng `.venv/Scripts/python.exe` trong thư mục dự án. Xem [hướng dẫn frontend](frontend/README.md) để biết cấu trúc và lệnh kiểm tra.

## Tài liệu giao diện PySide6 cũ

Ứng dụng desktop (PySide6) tạo **video dọc 9:16 về kiến thức lịch sử** từ một chủ đề: AI gợi ý chủ đề, lập đề cương, viết kịch bản, chia cảnh, tự tìm ảnh tư liệu, đọc giọng tiếng Việt và render ra MP4.

Đây là bản thử nghiệm (prototype) cho luồng "Kiến thức" của dự án VIAI; chạy hoàn toàn trên máy, không cần database.

## Luồng tạo video

1. **Nội dung** – chọn loại nội dung (Kiến thức – Lịch sử), AI viết nội dung (Ollama, Gemini, hoặc Gemini qua cổng API bên thứ ba), độ dài video, giọng đọc, phong cách lời kể (kể chuyện, tư liệu, ngắn gọn, giảng giải), số ý chính (1–8 hoặc tự động) và **số cảnh** (*Bằng số ý chính*, *Ngắn tự động* ~8 giây/cảnh, hoặc 1–12 cảnh; AI chia lệch thì app tự gộp/tách cho đúng). Rồi chọn một trong ba cách bắt đầu:
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

### Chạy tự động

Ở bước 1 tích **Tự động chạy đến hết sau khi chọn chủ đề** và chọn **mẫu video**, **độ phân giải** (giọng đọc là ô ở trên; chuyển cảnh, phụ đề, nhạc nền lấy theo lần render gần nhất). Chọn chủ đề ở bước 2 rồi bấm **Chạy tự động đến hết**: app tự duyệt đề cương và kịch bản, chia cảnh, lấy ảnh (luồng ảnh) hoặc chọn video nguồn (luồng clip), rồi render. Cũng áp dụng khi bắt đầu từ nội dung có sẵn hoặc kịch bản JSON.

- Luồng clip không có link: tìm bằng từ khóa AI gợi ý, AI chấm mỗi video **0–10 theo độ hợp chủ đề** (cùng lần xem storyboard), tự chọn video đúng loại, dài không quá 30 phút, điểm cao nhất. Điểm cao nhất dưới **6** thì tìm lại bằng từ khóa tiếng Anh; vẫn thấp thì dừng để bạn chọn. Video nguồn ghép được ít cảnh (quá nửa) thì thử video điểm cao kế tiếp một lần.
- Cảnh báo về cảnh được ghi vào Nhật ký và hiện một lần khi video xong. Gặp lỗi thì dừng đúng bước đó; bấm lại bước đó để chạy tiếp. **Hủy** thì dừng hẳn chế độ tự động.

## Luồng video clip ("Tạo video clip")

Bước 1–3 giống luồng ảnh. Bước 4 **Cảnh & clip** dùng các shot của **một video nguồn** cho cả video (màu và chất hình đồng đều):

- Bước 1 của luồng clip có dải màu cam nhận diện và ô **Link video nguồn (tùy chọn)**: có link thì bước 4 dùng luôn video đó.
- **AI xem hình & chọn đoạn** (ô ở bước 1 và bước 4, dùng chung): *Như AI viết nội dung*, *Gemini*, *Gemini qua cổng API* hoặc *Ollama* (`KV_VISION_MODEL`, mặc định `gemma3`). Gemini nhận ảnh storyboard/lưới shot để phân loại và mô tả — nhanh và đúng hơn gemma3 nhưng tốn token (ghi trong Nhật ký).
- Các việc dài ở bước 4 (tìm video, chuẩn bị video nguồn, ghép lại) có nút **Hủy** trên thanh trạng thái: trang mở khóa ngay, việc đang chạy dừng ở nền.
- **Chọn video nguồn**: tìm video YouTube theo từ khóa chủ đề hoặc **dán link YouTube** video nguồn.
  - Khi tìm, app lấy storyboard (ảnh lưới nhỏ, không tải video) và dùng model xem ảnh phân loại: quay thật, tư liệu cũ, hoạt hình/3D, tranh vẽ, slide, người dẫn, kèm **điểm hợp chủ đề 0–10** (danh sách xếp theo điểm). Bộ lọc *Chỉ tư liệu thật* hoặc *Cho phép hoạt hình*.
- App tải bản **360p** của video nguồn để phân tích: tách shot (FFmpeg), AI mô tả từng shot, AI chọn **shot bắt đầu** hợp với lời đọc của từng cảnh. Mỗi cảnh là **một đoạn liền** của video nguồn, chạy từ shot đó đủ số giây của cảnh; các đoạn không chồng nhau (trùng thì dời sang đoạn trống gần nhất; video nguồn không đủ dài thì cảnh đó dùng ảnh thay). Từng cảnh có thể **chọn điểm bắt đầu khác** hoặc **dùng ảnh thay**.
- **Logo/watermark**: tự dò vùng chữ/logo đứng yên suốt video; khung dọc 9:16 được đặt tránh logo, logo còn trong khung thì làm mờ. Có thể **khoanh vùng logo** bằng tay hoặc chọn *Không có logo*.
- Khi render: chỉ tải **đúng đoạn** của từng cảnh ở chất lượng cao (tối đa 1080p), cắt 9:16, bỏ tiếng gốc (chỉ có giọng đọc theo kịch bản). Render xong thì xóa bản 360p.
- **Ghi nguồn**: tên video nguồn, kênh và link được lưu vào `render/credits.txt`; nút **Copy ghi nguồn** để dán vào caption khi đăng.

Bản 360p nằm trong `output/_clip_cache/` (giới hạn dung lượng chỉnh trong Cài đặt, tự xóa file cũ nhất; có nút dọn cache).

## Nguồn ảnh (tự động, theo thứ tự)

1. Wikimedia Commons theo từ khóa của cảnh (tiếng Việt, rồi tiếng Anh)
2. Wikipedia tiếng Việt theo từ khóa của cảnh
3. Openverse
4. Ảnh chung của chủ đề trên Wikipedia tiếng Việt (được gắn nhãn để kiểm tra lại)
5. Pollinations – ảnh minh họa AI miễn phí (có thể tắt)
6. Ảnh thay thế tự vẽ (để luôn render được)

Không cần API key cho các nguồn trên. Nút "Ảnh AI (Gemini)" chỉ dùng được với API key có bật billing.

> Video không chèn dòng nguồn ảnh lên khung hình. Ảnh Commons/Wikipedia/Openverse có giấy phép riêng; thông tin tác giả và giấy phép vẫn được lưu trong `state.json` để tra lại khi cần. Ảnh AI chỉ là minh họa, không phải tư liệu lịch sử thật.

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
- Luồng video clip: [Deno](https://deno.com/) để yt-dlp giải mã YouTube (`winget install DenoLand.Deno`; app tự tìm cả khi PATH chưa cập nhật)
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
| `KV_GATEWAY_API_KEY`, `KV_GATEWAY_BASE_URL`, `KV_GATEWAY_MODEL` | Gemini qua cổng API bên thứ ba (key gửi dạng `Authorization: Bearer`; địa chỉ định dạng Gemini, ví dụ `https://api.shopaikey.com/v1beta`) |
| `KV_VISION_MODEL` | Model Ollama xem ảnh cho luồng video clip (mặc định `gemma3`) |
| `KV_CLIP_CACHE_MB` | Giới hạn cache video nguồn 360p (MB, mặc định 2048) |

## Chạy

```powershell
.\.venv\Scripts\python.exe main.py
```

Sidebar có 5 mục:

- **Tạo video ảnh** – 5 bước ở trên; nút "Video mới" để bắt đầu lại. Khi render có nút **Hủy**; xong thì **Xuất video** (MP4 kèm phụ đề `.srt`, ảnh bìa `.jpg` và ghi nguồn `.credits.txt` nếu có, cùng tên, ra thư mục bạn chọn).
- **Tạo video clip** – luồng video clip ở trên.
- **Lịch sử video** – các video đã làm (nhãn Video ảnh / Video clip), mở lại để sửa cảnh, đổi mẫu hoặc render lại.
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
core/clips.py        Luồng video clip: tìm video nguồn, phân loại, tách shot, dò logo, ghép shot, cắt clip 9:16
ui/clip_page.py      Bước "Cảnh & clip"
assets/templates/    Khung SVG cho template tin tức
```

## Hạn chế đã biết

- Model nhỏ chạy local (`gemma3` 4B) hay bịa sự kiện lịch sử; Gemini chính xác hơn nhưng vẫn phải kiểm tra.
- Tìm ảnh tự động vẫn có cảnh ra ảnh lệch nội dung, nhất là chủ đề trừu tượng; nên xem lại từng cảnh.
- "Theo câu đọc" ước lượng điểm đổi ảnh theo độ dài chữ của từng cảnh trên mốc thời gian từng câu; ranh giới cảnh nằm giữa câu có thể lệch vài trăm mili giây.
- PDF dạng ảnh scan không đọc được (cần OCR).
- Video clip: `gemma3` phân loại video và nhận ra logo chưa chắc chắn (thử 8 tấm storyboard: đúng 6); mô tả shot có thể đọc sai chữ trên hình. Video nguồn về lịch sử Việt Nam thường có nhiều slide/tranh vẽ/3D, ít cảnh quay thật.
