"""把 JSON 存储的数据迁移到 PostgreSQL。

用法:
  DATABASE_URL=postgresql://happyimage:happyimage-local-dev@localhost:5432/happyimage \
  python scripts/migrate_json_to_pg.py /path/to/original/data

表结构与 database_storage.py 一致：
  accounts (id, access_token, data)
  auth_keys (id, key_id, data)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import Column, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class AccountModel(Base):
    __tablename__ = "accounts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    access_token = Column(String(2048), unique=True, nullable=False, index=True)
    data = Column(Text, nullable=False)


class AuthKeyModel(Base):
    __tablename__ = "auth_keys"
    id = Column(Integer, primary_key=True, autoincrement=True)
    key_id = Column(String(255), unique=True, nullable=False, index=True)
    data = Column(Text, nullable=False)


def migrate(data_dir: Path, database_url: str) -> None:
    engine = create_engine(database_url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    # ── 迁移 accounts ──
    accounts_file = data_dir / "accounts.json"
    if accounts_file.exists():
        accounts: list[dict] = json.loads(accounts_file.read_text("utf-8"))
        if not isinstance(accounts, list):
            accounts = []
        session = Session()
        try:
            session.query(AccountModel).delete()
            count = 0
            for item in accounts:
                if not isinstance(item, dict):
                    continue
                access_token = str(item.get("access_token") or "").strip()
                if not access_token:
                    continue
                session.add(AccountModel(
                    access_token=access_token,
                    data=json.dumps(item, ensure_ascii=False),
                ))
                count += 1
            session.commit()
            print(f"✅ accounts: {count} 条")
        except Exception as e:
            session.rollback()
            print(f"❌ accounts 迁移失败: {e}")
            raise
        finally:
            session.close()
    else:
        print(f"⚠️  未找到 {accounts_file}")

    # ── 迁移 auth_keys ──
    auth_keys_file = data_dir / "auth_keys.json"
    if auth_keys_file.exists():
        auth_keys: list[dict] = json.loads(auth_keys_file.read_text("utf-8"))
        if not isinstance(auth_keys, list):
            auth_keys = []
        session = Session()
        try:
            session.query(AuthKeyModel).delete()
            count = 0
            for item in auth_keys:
                if not isinstance(item, dict):
                    continue
                key_id = str(item.get("id") or "").strip()
                if not key_id:
                    continue
                session.add(AuthKeyModel(
                    key_id=key_id,
                    data=json.dumps(item, ensure_ascii=False),
                ))
                count += 1
            session.commit()
            print(f"✅ auth_keys: {count} 条")
        except Exception as e:
            session.rollback()
            print(f"❌ auth_keys 迁移失败: {e}")
            raise
        finally:
            session.close()
    else:
        print(f"⚠️  未找到 {auth_keys_file}")

    print("\n🎉 迁移完成")


if __name__ == "__main__":
    database_url = sys.argv[1] if len(sys.argv) > 1 else None
    data_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else None

    if not database_url:
        import os
        database_url = os.getenv("DATABASE_URL", "")
    if not data_dir:
        data_dir = Path(__file__).resolve().parents[1] / "data"

    if not database_url:
        print("用法: DATABASE_URL=postgresql://... python scripts/migrate_json_to_pg.py [data_dir]")
        print("或:   python scripts/migrate_json_to_pg.py <DATABASE_URL> [data_dir]")
        sys.exit(1)

    migrate(Path(data_dir), database_url)
