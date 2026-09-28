from core.title_cards import HISTORY_TEMPLATES

CONTENT_TYPES = {
    "kien_thuc": {
        "label": "Kiến thức",
        "categories": {
            "lich_su": {
                "label": "Lịch sử",
                "guidance": (
                    "Video kiến thức lịch sử. Ưu tiên mốc thời gian, nhân vật, bối cảnh, diễn biến và ý nghĩa. "
                    "Chỉ nêu năm, tên người, địa danh, số liệu khi đó là thông tin lịch sử phổ biến và chắc chắn; "
                    "nếu các nguồn còn tranh cãi thì nói rõ là còn nhiều ý kiến, không khẳng định."
                ),
            },
        },
    },
}

# Suggested lengths; any whole number of seconds in MIN_DURATION..MAX_DURATION can be typed.
DURATIONS = (60, 90, 120, 180, 300)
MIN_DURATION, MAX_DURATION = 30, 300

VOICES = {
    "vi-VN-HoaiMyNeural": "Hoài My (nữ)",
    "vi-VN-NamMinhNeural": "Nam Minh (nam)",
}

NEWS_TEMPLATES = {
    "news": "Báo điện tử 9:16",
    "news-overview": "Toàn cảnh (2 dải xanh)",
    "review": "Review & tóm tắt",
    "minimal": "Tối giản",
    "banner-yellow": "Banner vàng đen",
    "banner-red": "Banner đỏ trắng",
    "banner-neon": "Banner neon",
}

# Each content type offers only its own templates; "tin_tuc" is kept for when the news type is added here.
TEMPLATES_BY_TYPE = {
    "kien_thuc": HISTORY_TEMPLATES,
    "tin_tuc": NEWS_TEMPLATES,
}

RESOLUTIONS = ("1080x1920", "720x1280")

# Narration style: label and the instruction added to the outline, script and length-adjust prompts.
STYLES = {
    "ke_chuyen": ("Kể chuyện hấp dẫn", "Kể như một câu chuyện có bối cảnh, nhân vật, tình huống và cao trào; "
                                       "câu văn giàu hình ảnh nhưng không thêm chi tiết không có thật."),
    "tu_lieu": ("Tư liệu trang trọng", "Giọng thuyết minh phim tài liệu: trang trọng, chính xác, mạch lạc; "
                                       "không cảm thán, không dùng từ lóng."),
    "ngan_gon": ("Ngắn gọn, nhịp nhanh", "Câu ngắn, nhịp nhanh kiểu video TikTok; mỗi câu một thông tin, "
                                         "đi thẳng vào điểm chính."),
    "giang_giai": ("Giảng giải dễ hiểu", "Như thầy cô giảng bài cho học sinh: giải thích nguyên nhân – diễn biến – "
                                         "kết quả, dùng so sánh gần gũi."),
}

# None = derived from the duration (outline_point_count).
POINT_COUNTS = (None, 1, 2, 3, 4, 5, 6, 7, 8)

# Number of scenes: "points" = one scene per main point (paragraph), "auto" = short scenes of about 8 s
# (scene_count), or a fixed number.
SCENE_CHOICES = {"points": "Bằng số ý chính", "auto": "Ngắn tự động (~8 giây/cảnh)",
                 **{count: f"{count} cảnh" for count in range(1, 13)}}

SCENE_TIMINGS = {
    "sentences": "Theo câu đọc",
    "even": "Chia đều",
}

SUBTITLE_STYLES = {
    "normal": "Thường",
    "highlight": "Highlight từng từ",
    "off": "Tắt phụ đề",
}

# "template" cycles the template's own set (title_cards.HISTORY_TRANSITIONS); "none" is a hard cut.
TRANSITIONS = {
    "template": "Theo template",
    "fade": "Mờ dần",
    "dissolve": "Hòa tan",
    "fadeblack": "Chớp đen",
    "smoothleft": "Lướt ngang",
    "hblur": "Nhòe ngang",
    "none": "Không chuyển cảnh (cắt thẳng)",
}

# Measured on Edge TTS vi-VN-HoaiMyNeural: 118 words -> 31s (~3.8 words/s); used to size prompts and estimates.
WORDS_PER_SECOND = 3.7


def outline_point_count(duration_seconds: int) -> int:
    return max(3, min(10, round(duration_seconds / 15)))


def style_instruction(style: str | None) -> str:
    return f"Phong cách lời kể: {STYLES[style][1]}" if style in STYLES else ""


def scene_count(duration_seconds: int) -> int:
    # About one picture every 8 s; the cap only matters for the longest (300 s) videos.
    return max(4, min(40, round(duration_seconds / 8)))


def resolve_scene_count(choice, duration_seconds: int, main_points: int) -> int:
    """Scenes to split the narration into, from the "Số cảnh" choice."""
    if isinstance(choice, int) and not isinstance(choice, bool):
        return max(1, choice)
    if choice == "auto":
        return scene_count(duration_seconds)
    return max(1, min(40, main_points))


def category_info(content_type: str, category: str) -> dict:
    return CONTENT_TYPES[content_type]["categories"][category]
