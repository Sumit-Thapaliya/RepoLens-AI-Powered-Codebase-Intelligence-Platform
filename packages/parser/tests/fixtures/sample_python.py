# --- sample FastAPI-ish source used by the parser smoke test
import os
from datetime import datetime
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import Column, ForeignKey, Integer, String, DateTime
from sqlalchemy.orm import relationship, sessionmaker

app = FastAPI()
router = APIRouter()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    orders = relationship("Order", back_populates="user")


class AuthService:
    def __init__(self, db):
        self.db = db

    async def authenticate(self, email: str, password: str):
        user = self.db.query(User).filter(User.email == email).first()
        if not user or not verify_password(password, user.hashed_password):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        return create_access_token(user)


@app.post("/api/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db=Depends(get_db)):
    if payload.email is None:
        raise HTTPException(status_code=400)
    service = AuthService(db)
    token = await service.authenticate(payload.email, payload.password)
    return {"access_token": token}


@router.get("/api/users/{user_id}")
def get_user(user_id: int, db=Depends(get_db)):
    return db.query(User).get(user_id)
