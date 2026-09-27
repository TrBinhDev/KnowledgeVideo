def _object(**properties) -> dict:
    return {"type": "object", "properties": properties, "required": list(properties)}


_TEXT = {"type": "string"}

TOPICS_SCHEMA = _object(topics={"type": "array", "items": _object(title=_TEXT, angle=_TEXT)})
OUTLINE_SCHEMA = _object(title=_TEXT, points={"type": "array", "items": _object(text=_TEXT, seconds={"type": "integer"})})
SCRIPT_SCHEMA = _object(title=_TEXT, hook=_TEXT, paragraphs={"type": "array", "items": _TEXT})
ADJUST_SCHEMA = _object(paragraphs={"type": "array", "items": _TEXT})
SCENES_SCHEMA = _object(
    subject_vi=_TEXT, subject_en=_TEXT,
    scenes={"type": "array", "items": _object(text=_TEXT, image_query_vi=_TEXT, image_query_en=_TEXT, image_prompt=_TEXT)},
)

_COMMON_RULES = """QUY TẮC CHUNG:
- Viết tiếng Việt tự nhiên, phù hợp đọc bằng giọng nói (TTS).
- Không bịa số liệu, trích dẫn hay nguồn. Thông tin không chắc chắn thì diễn đạt khái quát.
- Không xuất suy nghĩ hay chain-of-thought.
- Chỉ trả về JSON thuần túy đúng schema được yêu cầu, không bọc markdown."""


def suggest_topics(guidance: str, user_input: str, count: int) -> tuple[str, str]:
    system = f"""Bạn là biên tập viên nội dung video ngắn dạng dọc (Shorts/Reels/TikTok).
{guidance}
{_COMMON_RULES}
Schema:
{{"topics": [{{"title": "Tên chủ đề cụ thể, dưới 90 ký tự", "angle": "1 câu nêu góc kể chuyện hấp dẫn"}}]}}"""
    user = f"""Người dùng nhập từ khóa hoặc ý tưởng sau:
\"\"\"{user_input}\"\"\"

Hãy gợi ý đúng {count} chủ đề video cụ thể, khác nhau, bám sát ý người dùng."""
    return system, user


def outline(guidance: str, topic: str, duration_seconds: int, point_count: int) -> tuple[str, str]:
    system = f"""Bạn là biên kịch video kiến thức ngắn.
{guidance}
{_COMMON_RULES}
- "seconds" là số giây dành cho ý đó khi đọc thành lời; tổng "seconds" của mọi ý phải đúng bằng thời lượng video.
Schema:
{{"title": "Tiêu đề video, dưới 90 ký tự", "points": [{{"text": "Nội dung ý", "seconds": 20}}]}}"""
    user = f"""Chủ đề: {topic}
Thời lượng video: đúng {duration_seconds} giây.

Lập đề cương gồm đúng {point_count} ý theo trình tự kể chuyện (mở vấn đề → diễn biến → kết/ý nghĩa).
Mỗi ý là 1 câu ngắn nêu nội dung chính sẽ nói, kèm số giây; ý quan trọng được nhiều giây hơn.
Tổng số giây của {point_count} ý phải bằng {duration_seconds}."""
    return system, user


def script(guidance: str, topic: str, title: str, points: list[dict], hook_words: int,
           paragraph_words: list[int]) -> tuple[str, str]:
    system = f"""Bạn là biên kịch video kiến thức ngắn cho nền tảng video dọc.
{guidance}
{_COMMON_RULES}
- Hook là 1 câu mở đầu nêu thẳng điều thú vị nhất của chủ đề; không mở bằng "Bạn có biết", "Hãy cùng khám phá".
- Không viết chỉ dẫn hình ảnh/cảnh quay/hiệu ứng trong hook hoặc các đoạn.
- "paragraphs" có đúng một đoạn cho mỗi ý của đề cương, đúng thứ tự; không lặp lại hook.
- ĐỘ DÀI LÀ BẮT BUỘC: mỗi đoạn phải đạt số từ yêu cầu (sai lệch tối đa 10%), vì video phải khớp thời lượng.
Schema:
{{"title": "Tiêu đề video", "hook": "Câu mở đầu", "paragraphs": ["Đoạn 1", "Đoạn 2"]}}"""
    numbered = "\n".join(f"{index}. {point['text']} → viết khoảng {words} từ"
                         for index, (point, words) in enumerate(zip(points, paragraph_words), 1))
    user = f"""Chủ đề: {topic}
Tiêu đề dự kiến: {title}
Hook: khoảng {hook_words} từ.

Đề cương đã được duyệt (mỗi ý thành 1 đoạn, kèm số từ cần viết):
{numbered}

Tổng cộng khoảng {hook_words + sum(paragraph_words)} từ. Viết kịch bản lời đọc hoàn chỉnh bám sát đề cương."""
    return system, user


def adjust_length(guidance: str, paragraphs: list[str], targets: list[int]) -> tuple[str, str]:
    system = f"""Bạn là biên tập viên lời đọc video.
{guidance}
{_COMMON_RULES}
- Viết lại từng đoạn cho đạt đúng số từ mục tiêu (sai lệch tối đa 10%), giữ nguyên ý chính và thứ tự đoạn.
- Khi cần dài hơn: chỉ thêm giải thích bối cảnh, nguyên nhân, ý nghĩa; KHÔNG thêm năm, số liệu, tên người hay sự kiện mới.
- Khi cần ngắn hơn: bỏ chi tiết phụ, giữ dữ kiện chính.
- Trả về đúng {len(paragraphs)} đoạn.
Schema:
{{"paragraphs": ["Đoạn 1", "Đoạn 2"]}}"""
    listed = "\n".join(f"{index}. [hiện {len(text.split())} từ → cần {target} từ] {text}"
                       for index, (text, target) in enumerate(zip(paragraphs, targets), 1))
    user = f"""Các đoạn lời đọc cần chỉnh độ dài:
{listed}"""
    return system, user


def scenes(title: str, topic: str, narration: str, scene_count: int) -> tuple[str, str]:
    system = f"""Bạn là đạo diễn hình ảnh cho video kiến thức lịch sử dạng dọc.
{_COMMON_RULES}
- "subject_vi" / "subject_en": tên riêng ngắn gọn (1-4 từ) của đối tượng chính trong video, tiếng Việt và tiếng Anh,
  ví dụ "Bạch Đằng" / "Bach Dang", "Nguyễn Phú Trọng" / "Nguyen Phu Trong". Không dùng cả câu chủ đề.
- "text": đoạn lời đọc thuộc cảnh đó, cắt theo thứ tự từ lời đọc gốc, không viết lại.
- "image_query_vi" và "image_query_en": 2-4 từ khóa tìm ảnh tư liệu cho ĐÚNG nội dung cảnh đó, tiếng Việt và tiếng Anh.
  Từ khóa phải là thứ NHÌN THẤY ĐƯỢC: tên người, địa danh, công trình, hiện vật, trận đánh, sự vật cụ thể
  (ví dụ "cọc Bạch Đằng", "Trần Hưng Đạo", "sông Bạch Đằng"). CẤM từ trừu tượng như chiến lược, chiến thắng,
  tinh thần, ý nghĩa, strategic, victory, patriotism. Nếu cảnh chỉ nói ý trừu tượng, dùng người/địa danh/sự vật
  chính của video.
- "image_prompt": mô tả tiếng Anh cho AI vẽ tranh minh họa lịch sử của cảnh, không chứa chữ trong ảnh.
Schema:
{{"subject_vi": "...", "subject_en": "...",
  "scenes": [{{"text": "...", "image_query_vi": "...", "image_query_en": "...", "image_prompt": "..."}}]}}"""
    user = f"""Chủ đề: {topic}
Tiêu đề: {title}

Lời đọc:
\"\"\"{narration}\"\"\"

Chia lời đọc thành đúng {scene_count} cảnh liên tiếp, mỗi cảnh ứng với 1 hình ảnh."""
    return system, user
