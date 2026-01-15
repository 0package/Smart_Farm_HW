import sqlite3
import logging

# 로깅 설정 (오류 추적용)
logging.basicConfig(level=logging.INFO)

def get_db_connection():
    """안전한 DB 연결 및 WAL 모드 설정"""
    try:
        # timeout을 설정하여 다른 프로세스가 사용 중일 때 기다리게 함
        conn = sqlite3.connect("farm.db", check_same_thread=False, timeout=10)
        # WAL 모드 활성화 (읽기/쓰기 충돌 방지 핵심)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn
    except sqlite3.Error as e:
        logging.error(f"DB Connection Error: {e}")
        return None

def execute_query(query, params=(), commit=False):
    """안전하게 쿼리를 실행하고 결과를 반환하는 함수"""
    conn = get_db_connection()
    if not conn:
        return None
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        if commit:
            conn.commit()
            return True
        return cursor.fetchall()  # 조회 시 데이터 반환
    except sqlite3.Error as e:
        logging.error(f"Query Error: {e}")
        return None
    finally:
        conn.close()