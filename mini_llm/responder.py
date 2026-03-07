from mini_llm.llm_client import call_llm


def salary_responder(data, question: str):
    """
    data = {
        "salary_contexts": [
            {
                "salary": int | None,
                "time_ctx": dict
            }
        ]
    }
    """

    salary_contexts = data.get("salary_contexts", [])

    # ===== 1. KHÔNG CÓ DỮ LIỆU GÌ =====
    valid_items = [
        item for item in salary_contexts
        if item.get("salary") is not None
    ]

    if not valid_items:
        return (
            "Hiện tại chưa có dữ liệu lương cho các khoảng thời gian bạn hỏi. "
            "Bạn vui lòng kiểm tra lại hoặc liên hệ phòng nhân sự."
        )

    # ===== 2. BUILD NỘI DUNG CỨNG (KHÔNG ĐỂ LLM SUY ĐOÁN) =====
    salary_lines = []

    for item in valid_items:
        salary = item["salary"]
        time_ctx = item["time_ctx"]

        if time_ctx.get("value") == "current_month":
            label = "tháng này"
        elif time_ctx.get("value") == "previous_month":
            label = "tháng trước"
        elif time_ctx.get("type") == "month":
            label = f"tháng {time_ctx.get('month')}"
        else:
            label = "gần nhất"

        salary_lines.append(f"- Lương {label}: {salary:,.0f} VNĐ")

    salary_text = "\n".join(salary_lines)

    # ===== 3. GỌI LLM CHỈ ĐỂ DIỄN ĐẠT =====
    prompt = f"""
Bạn là chatbot nhân sự (HR) nội bộ tại Việt Nam.

QUY ĐỊNH:
- Chỉ trả lời bằng tiếng Việt.
- Chỉ dùng đúng dữ liệu được cung cấp.
- Không suy đoán, không thêm thông tin.
- Trả lời gọn gàng, rõ ràng, chuyên nghiệp.

DỮ LIỆU LƯƠNG:
{salary_text}

CÂU HỎI CỦA NHÂN VIÊN:
"{question}"

Hãy trả lời trực tiếp dựa trên dữ liệu trên.
"""

    return call_llm(prompt)


def leave_responder(data, question: str):
    remaining = data.get("leave_days")
    used = data.get("used_leave_days")

    if remaining is None:
        return "Hiện tại chưa xác định được thông tin ngày phép."

    prompt = f"""
Bạn là chatbot HR nội bộ.

QUY ĐỊNH:
- Chỉ trả lời về ngày phép.
- Không suy đoán.
- Chỉ dùng dữ liệu được cung cấp.

DỮ LIỆU:
- Số ngày phép đã dùng: {used}
- Số ngày phép còn lại: {remaining}

CÂU HỎI:
"{question}"

Hãy trả lời phù hợp với câu hỏi.
"""

    return call_llm(prompt)


def unknown_responder():
    return (
        "Nội dung này hiện chưa có trong dữ liệu hệ thống. "
        "Bạn vui lòng liên hệ phòng nhân sự để được hỗ trợ."
    )
