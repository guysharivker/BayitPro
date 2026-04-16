from dataclasses import dataclass
from datetime import datetime, timedelta

import bcrypt
from jose import JWTError, jwt

from app.config import JWT_ALGORITHM, JWT_EXPIRE_MINUTES, JWT_SECRET_KEY


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


@dataclass(frozen=True)
class TokenPayload:
    user_id: int
    company_id: int | None


def create_access_token(user_id: int, company_id: int | None = None) -> str:
    expire = datetime.utcnow() + timedelta(minutes=JWT_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": str(user_id), "company_id": company_id, "exp": expire},
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )


def decode_token(token: str) -> TokenPayload:
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return TokenPayload(
            user_id=int(payload["sub"]),
            company_id=int(payload["company_id"]) if payload.get("company_id") is not None else None,
        )
    except (JWTError, KeyError, ValueError) as exc:
        raise ValueError("Invalid token") from exc
