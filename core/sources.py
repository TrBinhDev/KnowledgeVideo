"""Source documents the user supplies (txt, docx, pdf) turned into plain text for the prompts or the narration."""
import re
from pathlib import Path

MAX_FILE_BYTES = 10 * 1024 * 1024
# Enough for a long article; longer sources are cut so prompts stay within what local models handle well.
MAX_SOURCE_CHARS = 15000
SUFFIXES = (".txt", ".md", ".docx", ".pdf")


class SourceError(Exception):
    pass


def _clean(text: str) -> str:
    lines = [" ".join(line.split()) for line in text.replace("\r", "\n").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _page_text(page) -> str:
    # The default mode splits Vietnamese words at every stacked diacritic ("Tr\nậ\nn"); layout mode keeps them whole.
    try:
        return page.extract_text(extraction_mode="layout") or ""
    except Exception:  # layout mode is newer and stricter; fall back to the default extraction
        return page.extract_text() or ""


def read_document(path: Path) -> str:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in SUFFIXES:
        raise SourceError("Chỉ đọc được file .txt, .md, .docx hoặc .pdf.")
    if not path.is_file():
        raise SourceError("Không tìm thấy file.")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise SourceError("File lớn hơn 10MB.")
    if suffix in (".txt", ".md"):
        raw = path.read_bytes()
        for encoding in ("utf-8-sig", "utf-16", "cp1258"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise SourceError("Không nhận ra bảng mã của file văn bản; hãy lưu lại dạng UTF-8.")
    elif suffix == ".docx":
        import docx

        try:
            document = docx.Document(str(path))
        except Exception as error:  # python-docx raises several unrelated types for damaged files
            raise SourceError("Không đọc được file Word (.docx).") from error
        # Blank line between Word paragraphs, so "use as written" keeps them as separate paragraphs.
        text = "\n\n".join(paragraph.text for paragraph in document.paragraphs)
    else:
        from pypdf import PdfReader

        try:
            reader = PdfReader(str(path))
            encrypted = reader.is_encrypted
            text = "" if encrypted else "\n\n".join(_page_text(page) for page in reader.pages)
        except Exception as error:  # pypdf raises many unrelated types for damaged files
            raise SourceError("Không đọc được file PDF.") from error
        if encrypted:
            raise SourceError("File PDF có mật khẩu.")
    text = _clean(text)
    if len(text) < 20:
        raise SourceError("File gần như không có chữ. PDF dạng ảnh scan cần OCR, ứng dụng chưa hỗ trợ.")
    return text


def limit(text: str) -> tuple[str, bool]:
    """Source text cut to MAX_SOURCE_CHARS at a paragraph or sentence end; the flag tells whether it was cut."""
    if len(text) <= MAX_SOURCE_CHARS:
        return text, False
    cut = text[:MAX_SOURCE_CHARS]
    end = max(cut.rfind("\n\n"), cut.rfind(". "))
    return (cut[:end + 1] if end > MAX_SOURCE_CHARS // 2 else cut).strip(), True


def title_line(text: str) -> str:
    """A leading heading (short first line without end punctuation), else ""."""
    lines = [line.strip() for line in _clean(text).split("\n") if line.strip()]
    if len(lines) > 1 and len(lines[0]) <= 120 and not re.search(r"[.!?…:;,]$", lines[0]):
        return lines[0]
    return ""


def split_narration(text: str) -> dict:
    """Use the text word for word: a leading heading as the title, first sentence as the hook, the rest as body."""
    text = _clean(text)
    title = title_line(text)
    if title:
        text = text.split(title, 1)[1].strip()
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if not paragraphs:
        raise SourceError("Nội dung trống.")
    first = paragraphs[0]
    match = re.search(r"(?<=[.!?…])\s+", first)
    hook, rest = (first[:match.start()].strip(), first[match.end():].strip()) if match else (first, "")
    body = [rest] if rest else []
    body += paragraphs[1:]
    if not body:
        raise SourceError("Cần ít nhất 2 câu: câu đầu làm hook, phần còn lại làm thân bài.")
    return {"title": title, "hook": " ".join(hook.split()),
            "body": "\n\n".join(" ".join(part.split()) for part in body)}
