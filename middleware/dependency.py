from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import text
import jwt
import os
from db import engine

security = HTTPBearer()

SECRET_KEY = os.getenv("JWT_KEY")
JWT_ISSUER = os.getenv("JWT_ISSUER")
ALGORITHM = "HS256"

if not SECRET_KEY or not JWT_ISSUER:
    raise RuntimeError("Thiếu JWT_KEY hoặc JWT_ISSUER trong môi trường")

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    token = credentials.credentials

    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            issuer=JWT_ISSUER,
            audience=JWT_ISSUER,
        )

        email = payload.get("sub")
        if not email:
            email = payload.get(
                "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name"
            )

        if not email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token không có email",
            )

        with engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT id, user_id, full_name, email, role
                    FROM employees
                    WHERE email = :email
                    LIMIT 1
                """),
                {"email": email},
            ).fetchone()

        if not row:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Không tìm thấy nhân viên từ token",
            )

        return {
            "employee_id": row[0],
            "user_id": row[1] if row[1] is not None else row[0],
            "full_name": row[2],
            "email": row[3],
            "role": row[4],
        }

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token đã hết hạn",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token không hợp lệ",
        )