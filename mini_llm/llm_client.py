import os
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

_client = Groq(
    api_key=os.getenv("GROQ_API_KEY")
)


def _chat_once(prompt: str, temperature: float = 0) -> str:
    resp = _client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=temperature,
    )
    return resp.choices[0].message.content.strip()


def call_llm(prompt: str) -> str:
    """
    Dùng cho trả lời HR chatbot bằng tiếng Việt.
    """
    full_prompt = f"""
Bạn là chatbot HR nội bộ tại Việt Nam.
BẮT BUỘC trả lời bằng tiếng Việt.
Không chèn markdown nếu không cần.
Không dùng tiếng Anh trong câu trả lời cho người dùng.

{prompt}
""".strip()

    return _chat_once(full_prompt, temperature=0)


def call_sql_llm(prompt: str) -> str:
    """
    Dùng riêng cho NL2SQL / SQL sửa lỗi.
    Không ép tiếng Việt, không thêm lời giải thích.
    """
    full_prompt = f"""
Bạn là chuyên gia tạo SQL MySQL 8.

QUY ĐỊNH BẮT BUỘC:
- Chỉ trả về đúng nội dung cần sinh ra.
- Nếu được yêu cầu sinh SQL thì chỉ trả về SQL thuần.
- Không dùng markdown.
- Không thêm giải thích.
- Không thêm tiền tố, hậu tố, tiêu đề hay chú thích.

{prompt}
""".strip()

    return _chat_once(full_prompt, temperature=0)