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

DURATIONS = (60, 90, 120, 180)

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

# Measured on Edge TTS vi-VN-HoaiMyNeural: 118 words -> 31s (~3.8 words/s); used to size prompts and estimates.
WORDS_PER_SECOND = 3.7


def outline_point_count(duration_seconds: int) -> int:
    return max(3, min(10, round(duration_seconds / 15)))


def scene_count(duration_seconds: int) -> int:
    return max(4, min(12, round(duration_seconds / 8)))


def category_info(content_type: str, category: str) -> dict:
    return CONTENT_TYPES[content_type]["categories"][category]
