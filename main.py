from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from fastapi import Query

from mini_llm.llm_client import call_llm, call_sql_llm
from mini_llm.db_schema import SCHEMA_TEXT


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    session_id: int
    user_id: int


class SQLRequest(BaseModel):
    message: str


class ApproveUnknownRequest(BaseModel):
    unknown_id: int
    intent_id: int | None = None  # nếu None -> dùng predicted_intent_id


def is_safe_sql(sql: str):
    forbidden = ["insert", "update", "delete", "drop", "alter"]
    return not any(word in sql.lower() for word in forbidden)


# =======================
# Database
# =======================
DATABASE_URL = "mysql+pymysql://root:oyiywCYcRXgEFQwGRccBWelkPthPjNHC@nozomi.proxy.rlwy.net:53106/railway"
engine = create_engine(
    DATABASE_URL, pool_pre_ping=True, pool_recycle=3600, pool_size=5, max_overflow=10
)


# test
print(DATABASE_URL)


@app.post("/chat_nl2sql")
def chat_nl2sql(req: ChatRequest):

    user_id = req.user_id
    question = req.message
    session_id = req.session_id

    # ===== CHECK SESSION =====
    if not validate_session(user_id, session_id):
        return {"reply": "Session không hợp lệ."}

    # ===== GET EMPLOYEE =====
    employee_id = get_employee_id(user_id)
    if not employee_id:
        return {"reply": "Không tìm thấy nhân viên."}

    q_low = question.lower()

    # ===== PROMPT SQL =====
    prompt_sql = f"""
Bạn là chuyên    gia MySQL 8.
Nhiệm vụ: Chuyển câu hỏi tiếng Việt thành một câu lệnh SELECT hợp lệ.

========================
QUY ĐỊNH BẮT BUỘC
========================
- Chỉ dùng SELECT.
- Không dùng INSERT, UPDATE, DELETE, DROP.
- Không dùng markdown.
- Không giải thích.
- Không thêm văn bản ngoài SQL.
- Mọi truy vấn bắt buộc có: employee_id = {employee_id}

========================
QUY ƯỚC NGHIỆP VỤ
========================
- Nếu hỏi về "lương" → dùng bảng payroll.
- Nếu hỏi về "nghỉ", "nghỉ phép" → dùng bảng leave_requests.
- Nếu hỏi về "đi làm", "chấm công" → dùng bảng attendances.
- Nếu có từ "trung bình" → phải dùng AVG()
- Nếu có từ "tổng" → dùng SUM()

- Với attendances:
  - cột ngày là date
  - giờ vào là check_in_time
  - giờ ra là check_out_time
  - "về sớm" nghĩa là check_out_time < '17:30:00'
  - "đi trễ" nghĩa là check_in_time > '08:30:00'

- Với payroll:
  - cột lương tổng là total_salary
  - cột lương cơ bản là salary_base
  - cột khấu trừ là deductions

- leave_requests KHÔNG có cột year/month.
  Nếu cần year/month thì dùng:
  YEAR(start_date) và MONTH(start_date)
========================
QUY TẮC THỜI GIAN (RẤT QUAN TRỌNG)
========================

1) Nếu hỏi "mới nhất", "gần nhất":
   → ORDER BY theo cột thời gian DESC LIMIT 1

2) Nếu hỏi "N tháng gần nhất" (chỉ áp dụng cho payroll):
   → KHÔNG dùng IN (subquery có LIMIT).
   → Phải dùng derived table / subquery trong FROM.

   Ví dụ SUM 2 tháng gần nhất:
   SELECT SUM(total_salary) FROM (
       SELECT total_salary
       FROM payroll
       WHERE employee_id = {employee_id}
       ORDER BY year DESC, month DESC
       LIMIT 2
   ) t

   Ví dụ AVG 2 tháng gần nhất:
   SELECT AVG(total_salary) FROM (
       SELECT total_salary
       FROM payroll
       WHERE employee_id = {employee_id}
       ORDER BY year DESC, month DESC
       LIMIT 2
   ) t

3) Nếu hỏi "N ngày gần nhất" (attendances):
  → BẮT BUỘC dùng subquery:
    SELECT COUNT(*) FROM (
       SELECT date
       FROM attendances
       WHERE employee_id = {employee_id}
       ORDER BY date DESC
       LIMIT N
    ) t

4) Nếu hỏi "tháng trước":
- payroll:
    month = MONTH(DATE_SUB(CURRENT_DATE, INTERVAL 1 MONTH))
    AND year = YEAR(DATE_SUB(CURRENT_DATE, INTERVAL 1 MONTH))
- attendances:
    MONTH(date) = MONTH(DATE_SUB(CURRENT_DATE, INTERVAL 1 MONTH))
    AND YEAR(date) = YEAR(DATE_SUB(CURRENT_DATE, INTERVAL 1 MONTH))

5) Nếu hỏi "năm trước":
- attendances: YEAR(date) = YEAR(CURRENT_DATE) - 1
- leave_requests: YEAR(start_date) = YEAR(CURRENT_DATE) - 1
- payroll: year = YEAR(CURRENT_DATE) - 1

6) Nếu có cụm "tháng này" và truy vấn attendances,
BẮT BUỘC phải có đúng 2 điều kiện sau trong WHERE:

MONTH(date) = MONTH(CURRENT_DATE)
AND YEAR(date) = YEAR(CURRENT_DATE)

Thiếu 1 trong 2 điều kiện là SQL sai.

7) TUYỆT ĐỐI KHÔNG:
- Không dùng MAX(year) + MAX(month)
- Không dùng MAX(month) đơn lẻ
- Không dùng MONTH(CURRENT_DATE) - 1
- Không dùng BETWEEN DATE_SUB(CURRENT_DATE, INTERVAL 1 MONTH) AND CURRENT_DATE để thay cho "tháng này"
- Không dùng rolling window cho "tháng trước" kiểu: work_date >= DATE_SUB(CURRENT_DATE, INTERVAL 1 MONTH)

========================
SCHEMA
========================
{SCHEMA_TEXT}

========================
CÂU HỎI
========================
{question}

Chỉ trả về SQL thuần.
"""

    # ===== CALL LLM (SQL) =====
    generated_sql = call_sql_llm(prompt_sql).strip()

    # ===== CLEAN MARKDOWN =====
    generated_sql = generated_sql.replace("```sql", "").replace("```", "").strip()
    generated_sql = generated_sql.rstrip(";").strip()

    def violates_count_limit(sql: str) -> bool:
        s = sql.lower()
        return "count(" in s and "limit" in s and "from (" not in s

    def violates_prev_month(sql: str) -> bool:
        s = sql.lower()
        # sai phổ biến: dùng rolling window thay vì calendar month
        return ("date >=" in s and "date_sub(current_date" in s) or (
            "between date_sub(current_date" in s and "current_date" in s
    )


    def violates_limit_in_subquery(sql: str) -> bool:
        s = " ".join(sql.lower().split())
        return " in (" in s and " limit " in s

    # ===== RETRY 1: fix COUNT + LIMIT (N ngày gần nhất) =====
    if (
        "ngày gần nhất" in q_low
        or "5 ngày" in q_low
        or "7 ngày" in q_low
        or "10 ngày" in q_low
    ) and violates_count_limit(generated_sql):
        fix_prompt = f"""
SQL bạn vừa tạo bị sai logic: dùng COUNT() cùng cấp với LIMIT.
Để trả lời "N ngày gần nhất" trong attendance, BẮT BUỘC dùng subquery rồi COUNT bên ngoài.

Hãy viết lại SQL đúng (MySQL 8) theo mẫu:

SELECT COUNT(*) FROM (
  SELECT date
  FROM attendances
  WHERE employee_id = {employee_id}
  ORDER BY date DESC
  LIMIT 5
) t

Câu hỏi: {question}
Chỉ trả về SQL thuần.
"""
        generated_sql = call_sql_llm(fix_prompt).strip()
        generated_sql = (
            generated_sql.replace("```sql", "")
            .replace("```", "")
            .strip()
            .rstrip(";")
            .strip()
        )

    if "nghỉ" in q_low and "from attendances" in generated_sql.lower():
        fix_prompt = f"""
Câu hỏi nói về NGHỈ PHÉP nên phải dùng bảng leave_requests, không dùng attendance.
Hãy viết lại SQL để tính số NGÀY NGHỈ trong 3 tháng gần nhất.

Gợi ý:
SELECT COALESCE(SUM(DATEDIFF(end_date, start_date) + 1),0)
FROM leave_requests
WHERE employee_id = {employee_id}
AND status = 'approved'
AND start_date >= DATE_SUB(CURRENT_DATE, INTERVAL 3 MONTH)

Câu hỏi: {question}
Chỉ trả về SQL thuần.
"""
        generated_sql = call_sql_llm(fix_prompt).strip()

    # ===== RETRY 2: fix "tháng trước" rolling window =====
    if "tháng trước" in q_low and violates_prev_month(generated_sql):
        fix_prompt = f"""
SQL bạn vừa tạo đang hiểu sai "tháng trước" thành "30 ngày gần đây".
Hãy viết lại đúng "tháng trước" theo calendar month.

Nếu là attendances thì dùng:
MONTH(date) = MONTH(DATE_SUB(CURRENT_DATE, INTERVAL 1 MONTH))
AND YEAR(date) = YEAR(DATE_SUB(CURRENT_DATE, INTERVAL 1 MONTH))

Câu hỏi: {question}
Bắt buộc có employee_id = {employee_id}.
Chỉ trả về SQL thuần.
"""
        generated_sql = call_sql_llm(fix_prompt).strip()
        generated_sql = (
            generated_sql.replace("```sql", "")
            .replace("```", "")
            .strip()
            .rstrip(";")
            .strip()
        )

    print("DEBUG SQL:", generated_sql)

    # ===== RETRY: leave_requests bị dùng year/month sai =====

    sql_low = generated_sql.lower()
    if "from leave_requests" in sql_low and (
        "select year" in sql_low or "select month" in sql_low
    ):
        fix_prompt = f"""
Bảng leave_requests KHÔNG có cột year/month.
Nếu cần year/month thì phải dùng YEAR(start_date) và MONTH(start_date).

Hãy viết lại SQL đúng theo MySQL 8.
Ví dụ đúng (nếu câu hỏi là "tháng nào nghỉ nhiều nhất"):

SELECT
  YEAR(start_date) AS year,
  MONTH(start_date) AS month,
  SUM(DATEDIFF(end_date, start_date) + 1) AS total_days_off
FROM leave_requests
WHERE employee_id = {employee_id}
  AND status = 'approved'
GROUP BY YEAR(start_date), MONTH(start_date)
ORDER BY total_days_off DESC
LIMIT 1

Câu hỏi: {question}
BẮT BUỘC có employee_id = {employee_id}.
Chỉ trả về SQL thuần.
"""
        generated_sql = call_sql_llm(fix_prompt).strip()
        generated_sql = (
            generated_sql.replace("```sql", "")
            .replace("```", "")
            .strip()
            .rstrip(";")
            .strip()
        )
    print("DEBUG SQL FIX LEAVE_YEAR_MONTH:", generated_sql)

        # ===== RETRY: fix LIMIT bên trong IN (...) cho N tháng gần nhất =====
    if (
        ("tháng gần nhất" in q_low or "tháng gần đây" in q_low or "gần nhất" in q_low)
        and ("tổng" in q_low or "trung bình" in q_low or "avg" in q_low)
        and violates_limit_in_subquery(generated_sql)
    ):
        fix_prompt = f"""
SQL bạn vừa tạo không chạy được trên MySQL hiện tại vì dùng LIMIT bên trong IN (subquery).

YÊU CẦU SỬA:
- Không dùng: IN (SELECT ... ORDER BY ... LIMIT N)
- Phải dùng subquery trong FROM (derived table)

Ví dụ đúng nếu hỏi TỔNG 2 tháng gần nhất:
SELECT SUM(total_salary) FROM (
    SELECT total_salary
    FROM payroll
    WHERE employee_id = {employee_id}
    ORDER BY year DESC, month DESC
    LIMIT 2
) t

Ví dụ đúng nếu hỏi TRUNG BÌNH 2 tháng gần nhất:
SELECT AVG(total_salary) FROM (
    SELECT total_salary
    FROM payroll
    WHERE employee_id = {employee_id}
    ORDER BY year DESC, month DESC
    LIMIT 2
) t

Câu hỏi: {question}
BẮT BUỘC có employee_id = {employee_id}.
Chỉ trả về SQL thuần.
"""
        generated_sql = call_sql_llm(fix_prompt).strip()
        generated_sql = (
            generated_sql.replace("```sql", "")
            .replace("```", "")
            .strip()
            .rstrip(";")
            .strip()
        )

    print("DEBUG SQL AFTER LIMIT_IN_FIX:", generated_sql)

    # ===== BASIC VALIDATION =====
    if not generated_sql.lower().startswith("select"):
        return {"reply": "SQL không hợp lệ."}

    if any(x in generated_sql.lower() for x in ["insert", "update", "delete", "drop"]):
        return {"reply": "SQL không an toàn."}

    if f"employee_id = {employee_id}" not in generated_sql:
        return {"reply": "Thiếu employee_id."}

    # ===== EXECUTE SQL =====
    # ===== EXECUTE SQL =====
    try:
        with engine.connect() as conn:
            result = conn.execute(text(generated_sql))
            rows = result.fetchall()

    except Exception as e:
        print("SQL ERROR:", str(e))  # log cho dev xem

        return {
            "reply": "Xin lỗi, hệ thống đang gặp sự cố khi truy vấn dữ liệu. Bạn vui lòng thử lại sau hoặc liên hệ HR."
        }

    # ===== FORMAT RESULT FOR LLM =====
    if rows and len(rows) == 1 and len(rows[0]) == 1:
        value = rows[0][0]
    else:
        value = rows

    print("DEBUG VALUE:", value)

    # ===== PROMPT ANSWER =====
    prompt_answer = f"""
Bạn là chatbot HR nội bộ.

QUY TẮC BẮT BUỘC:
- PHẢI sử dụng chính xác giá trị trong "Kết quả SQL".
- Không được tự suy luận.
- Không được dùng kiến thức lịch.
- Không được thay đổi con số.
- Nếu kết quả SQL là 5 thì phải trả lời là 5.

Câu hỏi:
{question}

Kết quả SQL:
{value}

Yêu cầu:
- Trả lời đúng trọng tâm.
- Không chào lại, không giới thiệu bản thân.
- Nếu kết quả là số, trả lời trực tiếp bằng câu hoàn chỉnh.
- Nếu không có dữ liệu, nói rõ là không có dữ liệu.

Chỉ trả lời nội dung.
"""

    try:
        llm_response = call_llm(prompt_answer)

        if not llm_response:
            final_answer = "Tôi đã tìm được dữ liệu nhưng không thể tạo câu trả lời."
        else:
            final_answer = llm_response.strip()

    except Exception as e:
        print("LLM ERROR:", str(e))
        final_answer = f"Kết quả là: {value}"

    # ===== SAVE HISTORY =====
    save_chat_history(
        engine=engine,
        user_id=user_id,
        session_id=session_id,
        message=question,
        bot_response=final_answer,
        intent="nl2sql",
    )

    return {"generated_sql": generated_sql, "reply": final_answer}


@app.post("/chat/session")
def create_chat_session(user_id: int = Query(...)):
    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                INSERT INTO chat_sessions (user_id, started_at)
                VALUES (:uid, NOW())
            """
            ),
            {"uid": user_id},
        )
        sid = result.lastrowid
    return {"session_id": int(sid)}


# =======================
# DB helpers
# =======================
def get_employee_id(user_id: int):
    """
    Compatibility mode:
    tạm thời map user_id của ứng dụng = employees.id
    để giữ nguyên flow hiện tại khi DB mới chưa có bảng users riêng.
    """
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id FROM employees WHERE user_id = :uid"),
            {"uid": user_id},
        ).fetchone()
    return row[0] if row else None

def save_chat_history(engine, user_id, session_id, message, bot_response, intent=None):
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO chat_history (
                        user_id, session_id, message, bot_response, intent, created_at
                    )
                    VALUES (
                        :user_id, :session_id, :message, :bot_response, :intent, NOW()
                    )
                    """
                ),
                {
                    "user_id": user_id,
                    "session_id": session_id,
                    "message": message,
                    "bot_response": bot_response,
                    "intent": intent,
                },
            )
    except Exception as e:
        print("WARN save_chat_history skipped:", str(e))

def validate_session(user_id: int, session_id: int):
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT 1 
                FROM chat_sessions
                WHERE session_id = :sid
                  AND user_id = :uid
            """
            ),
            {"sid": session_id, "uid": user_id},
        ).fetchone()
    return bool(row)


def get_salary(employee_id: int, time_ctx: dict | None):
    if not time_ctx:
        time_ctx = {"type": "latest"}

    t_type = time_ctx.get("type")
    t_value = time_ctx.get("value")

    with engine.connect() as conn:

        # 1) Lương mới nhất (mặc định)
        if t_type == "latest":
            sql = """
                SELECT base_salary + bonus - deduction
                FROM salary
                WHERE employee_id = :eid
                ORDER BY year DESC, month DESC
                LIMIT 1
            """
            params = {"eid": employee_id}

        # 2) Lương tháng hiện tại
        elif t_value == "current_month":
            sql = """
                SELECT base_salary + bonus - deduction
                FROM salary
                WHERE employee_id = :eid
                  AND month = MONTH(CURRENT_DATE)
                  AND year = YEAR(CURRENT_DATE)
            """
            params = {"eid": employee_id}

        # 3) Lương tháng trước (calendar month)
        elif t_value == "previous_month":
            sql = """
                SELECT base_salary + bonus - deduction
                FROM salary
                WHERE employee_id = :eid
                  AND month = MONTH(DATE_SUB(CURRENT_DATE, INTERVAL 1 MONTH))
                  AND year  = YEAR(DATE_SUB(CURRENT_DATE, INTERVAL 1 MONTH))
            """
            params = {"eid": employee_id}

        # 4) Lương theo tháng cụ thể
        elif t_type == "month" and time_ctx.get("month"):
            sql = """
                SELECT base_salary + bonus - deduction
                FROM salary
                WHERE employee_id = :eid
                  AND month = :month
                  AND year = :year
            """
            params = {
                "eid": employee_id,
                "month": time_ctx["month"],
                "year": time_ctx.get("year"),
            }

        else:
            return None

        row = conn.execute(text(sql), params).fetchone()
        return row[0] if row else None


def get_attendance_days(employee_id: int, time_ctx: dict | None):
    """
    Schema attendance:
      attendance_id, employee_id, work_date, check_in, check_out

    Quy ước:
      - Có record trong ngày => tính là 1 ngày đi làm
      - COUNT DISTINCT work_date để tránh trùng
    """
    if not time_ctx:
        time_ctx = {"type": "relative", "value": "current_month"}

    t_type = time_ctx.get("type")
    t_value = time_ctx.get("value")

    with engine.connect() as conn:

        # 1) Tháng này
        if t_value == "current_month":
            sql = """
                SELECT COUNT(DISTINCT work_date)
                FROM attendance
                WHERE employee_id = :eid
                  AND MONTH(work_date) = MONTH(CURRENT_DATE)
                  AND YEAR(work_date) = YEAR(CURRENT_DATE)
            """
            params = {"eid": employee_id}

        # 2) Tháng trước
        elif t_value == "previous_month":
            sql = """
                SELECT COUNT(DISTINCT work_date)
                FROM attendance
                WHERE employee_id = :eid
                  AND MONTH(work_date) = MONTH(DATE_SUB(CURRENT_DATE, INTERVAL 1 MONTH))
                  AND YEAR(work_date) = YEAR(DATE_SUB(CURRENT_DATE, INTERVAL 1 MONTH))
            """
            params = {"eid": employee_id}

        # 3) Tháng cụ thể
        elif t_type == "month" and time_ctx.get("month"):
            sql = """
                SELECT COUNT(DISTINCT work_date)
                FROM attendance
                WHERE employee_id = :eid
                  AND MONTH(work_date) = :m
                  AND YEAR(work_date) = :y
            """
            params = {
                "eid": employee_id,
                "m": time_ctx["month"],
                "y": time_ctx.get("year"),
            }

        # 4) latest -> hiểu là tháng này
        elif t_type == "latest":
            sql = """
                SELECT COUNT(DISTINCT work_date)
                FROM attendance
                WHERE employee_id = :eid
                  AND MONTH(work_date) = MONTH(CURRENT_DATE)
                  AND YEAR(work_date) = YEAR(CURRENT_DATE)
            """
            params = {"eid": employee_id}

        else:
            return None

        row = conn.execute(text(sql), params).fetchone()
        return int(row[0]) if row and row[0] is not None else 0


def get_late_early(employee_id: int, time_ctx: dict | None):
    if not time_ctx:
        time_ctx = {"value": "current_month"}

    t_value = time_ctx.get("value")
    t_type = time_ctx.get("type")

    with engine.connect() as conn:

        if t_value == "current_month":
            time_cond = """
              MONTH(work_date) = MONTH(CURRENT_DATE)
              AND YEAR(work_date) = YEAR(CURRENT_DATE)
            """
            params = {"eid": employee_id}

        elif t_value == "previous_month":
            time_cond = """
              MONTH(work_date) = MONTH(DATE_SUB(CURRENT_DATE, INTERVAL 1 MONTH))
              AND YEAR(work_date) = YEAR(DATE_SUB(CURRENT_DATE, INTERVAL 1 MONTH))
            """
            params = {"eid": employee_id}

        elif t_type == "month" and time_ctx.get("month"):
            time_cond = "MONTH(work_date) = :m AND YEAR(work_date) = :y"
            params = {
                "eid": employee_id,
                "m": time_ctx["month"],
                "y": time_ctx.get("year"),
            }
        else:
            return {"late_days": 0, "early_days": 0}

        sql = f"""
            SELECT
              COUNT(DISTINCT CASE WHEN check_in > '08:30:00' THEN work_date END) AS late_days,
              COUNT(DISTINCT CASE WHEN check_out < '17:30:00' THEN work_date END) AS early_days
            FROM attendance
            WHERE employee_id = :eid
              AND {time_cond}
        """

        row = conn.execute(text(sql), params).fetchone()

        return {
            "late_days": int(row[0]) if row and row[0] else 0,
            "early_days": int(row[1]) if row and row[1] else 0,
        }


def get_remaining_leave(employee_id: int):
    TOTAL = 12
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT SUM(DATEDIFF(end_date, start_date) + 1)
                FROM leave_requests
                WHERE employee_id = :eid
                  AND status = 'approved'
            """
            ),
            {"eid": employee_id},
        ).fetchone()

    used = row[0] if row and row[0] else 0
    return TOTAL - used


# =======================
# Health
# =======================
@app.get("/")
def home():
    return {"status": "HRM Mini-LLM Chatbot running"}


@app.get("/chat/sessions")
def get_chat_sessions(user_id: int = Query(...), limit: int = Query(10)):
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    cs.session_id,
                    cs.started_at,
                    -- tin nhắn đầu tiên trong session làm title
                    (
                        SELECT ch1.message
                        FROM chat_history ch1
                        WHERE ch1.session_id = cs.session_id
                        ORDER BY ch1.created_at ASC
                        LIMIT 1
                    ) AS title,
                    -- tin nhắn cuối cùng để preview
                    (
                        SELECT ch2.message
                        FROM chat_history ch2
                        WHERE ch2.session_id = cs.session_id
                        ORDER BY ch2.created_at DESC
                        LIMIT 1
                    ) AS last_message,
                    (
                        SELECT ch3.created_at
                        FROM chat_history ch3
                        WHERE ch3.session_id = cs.session_id
                        ORDER BY ch3.created_at DESC
                        LIMIT 1
                    ) AS last_at
                FROM chat_sessions cs
                WHERE cs.user_id = :uid
                ORDER BY COALESCE(last_at, cs.started_at) DESC
                LIMIT :limit
            """
            ),
            {"uid": user_id, "limit": limit},
        ).fetchall()

    result = []
    for r in rows:
        session_id, started_at, title, last_message, last_at = r
        # giữ key created_at cho frontend (bạn đang dùng)
        display_time = last_at or started_at
        result.append(
            {
                "session_id": session_id,
                "created_at": (
                    display_time.strftime("%d/%m %H:%M") if display_time else ""
                ),
                "title": title or f"Session #{session_id}",
                "last_message": last_message or "",
            }
        )
    return result


@app.delete("/chat/session/{session_id}")
def delete_chat_session(session_id: int, user_id: int = Query(...)):
    """
    Xóa 1 session của user + toàn bộ chat_history thuộc session đó.
    """
    with engine.begin() as conn:
        # đảm bảo session thuộc user (tránh xóa nhầm user khác)
        owner = conn.execute(
            text(
                "SELECT 1 FROM chat_sessions WHERE session_id = :sid AND user_id = :uid"
            ),
            {"sid": session_id, "uid": user_id},
        ).fetchone()

        if not owner:
            return {
                "ok": False,
                "message": "Session không tồn tại hoặc không thuộc user.",
            }

        # xóa lịch sử trước
        conn.execute(
            text("DELETE FROM chat_history WHERE session_id = :sid"),
            {"sid": session_id},
        )

        # rồi xóa session
        conn.execute(
            text("DELETE FROM chat_sessions WHERE session_id = :sid"),
            {"sid": session_id},
        )

    return {"ok": True}


@app.get("/chat/history/{session_id}")
def get_chat_history_by_session(session_id: int):
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT message, bot_response, created_at
                FROM chat_history
                WHERE session_id = :sid
                ORDER BY created_at DESC
                LIMIT 10
            """
            ),
            {"sid": session_id},
        ).fetchall()

    messages = []
    for r in reversed(rows):
        messages.append(
            {
                "id": len(messages) + 1,
                "text": r[0],
                "sender": "user",
                "time": r[2].strftime("%H:%M"),
            }
        )
        messages.append(
            {
                "id": len(messages) + 1,
                "text": r[1],
                "sender": "bot",
                "time": r[2].strftime("%H:%M"),
            }
        )

    return messages


# =======================
# Chat API
# =======================
@app.post("/chat")
def chat(req: ChatRequest):
    user_id = req.user_id
    message = req.message
    session_id = req.session_id
    text_norm = normalize_text(message)

    employee_id = get_employee_id(user_id)
    if not employee_id:
        return {"reply": "Không tìm thấy thông tin nhân viên."}

    time_ctxs = extract_times(text_norm)

    if not time_ctxs:
        time_ctxs = [{"type": "relative", "value": "current_month"}]

    # =======================
    # GOM DỮ LIỆU TRƯỚC
    # =======================
    salary_contexts = []
    attendance_contexts = []
    late_early_contexts = []

    for time_ctx in time_ctxs:
        salary = get_salary(employee_id, time_ctx)
        salary_contexts.append({"time_ctx": time_ctx, "salary": salary})

        days = get_attendance_days(employee_id, time_ctx)
        attendance_contexts.append({"time_ctx": time_ctx, "days": days})

        late_early = get_late_early(employee_id, time_ctx)
        print("DEBUG time_ctx =", time_ctx)
        print("DEBUG late_early =", late_early)

        late_early_contexts.append(
            {
                "time_ctx": time_ctx,
                "late_days": late_early["late_days"],
                "early_days": late_early["early_days"],
            }
        )

    leave_days = get_remaining_leave(employee_id)
    used_leave_days = 12 - leave_days

    user_ctx = {
        "salary_contexts": salary_contexts,
        "attendance_contexts": attendance_contexts,
        "leave_days": leave_days,
        "used_leave_days": used_leave_days,
        "late_early_contexts": late_early_contexts,
    }

    reply = hr_chatbot(question=text_norm, user_ctx=user_ctx)

    # LƯU CHAT HISTORY
    save_chat_history(
        engine=engine,
        user_id=user_id,
        session_id=session_id,
        message=message,
        bot_response=reply,
        intent=None,
    )

    return {"reply": reply}
