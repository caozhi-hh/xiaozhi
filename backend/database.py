"""
数据库配置 — 连接 SQLite 并管理会话

SQLAlchemy 是 Python 最常用的 ORM（对象关系映射）：
  你不写 SQL 语句，而是用 Python 类操作数据库。
  比如创建用户：User(username="小明")
  而不是：INSERT INTO users (username) VALUES ("小明")
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# SQLite 数据库文件会自动创建在 backend/ 目录下
engine = create_engine("sqlite:///./xiaozhi.db", connect_args={"check_same_thread": False})

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
