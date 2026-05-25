"""
数据库配置 — 连接 SQLite 并管理会话
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# HF Spaces 用 /data 持久化目录，本地用当前目录
DB_PATH = os.environ.get("DATABASE_URL", "sqlite:///./xiaozhi.db")
engine = create_engine(DB_PATH, connect_args={"check_same_thread": False})

# Session 是"一次数据库对话"——每次操作数据库时创建一个，用完关掉
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    """所有数据库模型的基类"""
    pass


def get_db():
    """依赖注入：每个请求自动获取一个数据库会话，请求结束自动关闭"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
