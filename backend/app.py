import os
from flask import send_from_directory
from flask import session
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from flask import Flask, jsonify, request
import sqlite3
from pathlib import Path

app = Flask(__name__)
app.json.ensure_ascii = False
app.config["SECRET_KEY"] = os.environ.get(
    "FLASK_SECRET_KEY",
    "local-development-only-key"
)

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


DB_PATH = Path(
    os.environ.get(
        "PICKIT_DB_PATH",
        str(Path(__file__).parent / "pickit.db")
    )
)

DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn



def init_db():
    with get_db() as conn:

        # 1. 회원 정보 테이블
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                nickname TEXT NOT NULL,
                department TEXT NOT NULL
            )
        """)

        # 2. 투표 정보 테이블
        conn.execute("""
            CREATE TABLE IF NOT EXISTS polls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                deadline TEXT NOT NULL,
                creator_id INTEGER,
                target_department TEXT,
                FOREIGN KEY (creator_id) REFERENCES users(id)
            )
        """)

        # 3. 투표 선택지 테이블
        conn.execute("""
            CREATE TABLE IF NOT EXISTS options (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                poll_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                votes INTEGER DEFAULT 0,
                FOREIGN KEY (poll_id) REFERENCES polls(id)
            )
        """)

        # 4. 기존 닉네임 기반 투표 기록
        # 이전 테스트 데이터 보존용
        conn.execute("""
            CREATE TABLE IF NOT EXISTS voters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                poll_id INTEGER NOT NULL,
                nickname TEXT NOT NULL,
                option_id INTEGER NOT NULL,
                UNIQUE(poll_id, nickname)
            )
        """)

        # 5. 기존 polls 테이블의 컬럼 확인
        columns = [
            row["name"]
            for row in conn.execute("PRAGMA table_info(polls)")
        ]

        # 기존 테이블에 생성자 컬럼이 없다면 추가
        if "creator_id" not in columns:
            conn.execute("""
                ALTER TABLE polls
                ADD COLUMN creator_id INTEGER
            """)

        # 기존 테이블에 학과 제한 컬럼이 없다면 추가
        if "target_department" not in columns:
            conn.execute("""
                ALTER TABLE polls
                ADD COLUMN target_department TEXT
            """)

        # 6. 회원 ID 기반 투표 기록 테이블
        conn.execute("""
            CREATE TABLE IF NOT EXISTS member_votes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                poll_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                option_id INTEGER NOT NULL,
                UNIQUE(poll_id, user_id),
                FOREIGN KEY (poll_id) REFERENCES polls(id),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (option_id) REFERENCES options(id)
            )
        """)


# 현재 로그인한 회원 정보 조회
def current_user():
    user_id = session.get("user_id")

    if user_id is None:
        return None

    with get_db() as conn:
        user = conn.execute(
            """SELECT id, username, nickname, department
               FROM users WHERE id = ?""",
            (user_id,)
        ).fetchone()

    return dict(user) if user else None


# 투표 접근 권한 확인
def can_access_poll(user, poll):
    target = poll["target_department"]

    return (
        target is None
        or target == user["department"]
    )


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "PICKIT"
    })


@app.route("/api/polls", methods=["POST"])
def create_poll():
    user = current_user()

    if user is None:
        return jsonify({"error": "로그인이 필요합니다."}), 401

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "올바른 JSON을 입력하세요."}), 400

    title = data.get("title")
    deadline = data.get("deadline")
    options = data.get("options")
    target = data.get("target_department")

    if not isinstance(title, str) or not title.strip():
        return jsonify({"error": "제목을 입력하세요."}), 400

    if not isinstance(options, list) or not 2 <= len(options) <= 10:
        return jsonify({"error": "선택지는 2~10개 필요합니다."}), 400

    if any(not isinstance(x, str) or not x.strip() for x in options):
        return jsonify({"error": "빈 선택지는 사용할 수 없습니다."}), 400

    if not isinstance(deadline, str):
        return jsonify({"error": "마감 시간을 입력하세요."}), 400

    if target is not None and target not in DEPARTMENTS:
        return jsonify({"error": "올바른 학과를 선택하세요."}), 400

    if target is not None and target != user["department"]:
        return jsonify({
            "error": "본인 학과의 투표만 생성할 수 있습니다."
        }), 403

    # 마감 시간은 한국 시간 기준
    from datetime import datetime, timezone, timedelta

    kst = timezone(timedelta(hours=9))

    try:
        end_time = datetime.fromisoformat(deadline)

        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=kst)

        if end_time <= datetime.now(kst):
            return jsonify({
                "error": "마감 시간은 미래여야 합니다."
            }), 400

    except ValueError:
        return jsonify({
            "error": "마감 시간 형식이 잘못되었습니다."
        }), 400

    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO polls
               (title, deadline, creator_id, target_department)
               VALUES (?, ?, ?, ?)""",
            (title.strip(), end_time.isoformat(), user["id"], target)
        )

        poll_id = cursor.lastrowid

        for option in options:
            conn.execute(
                "INSERT INTO options (poll_id, content) VALUES (?, ?)",
                (poll_id, option.strip())
            )

    return jsonify({
        "message": "투표가 생성되었습니다.",
        "poll_id": poll_id,
        "target_department": target
    }), 201



@app.route("/api/polls", methods=["GET"])
def get_polls():
    user = current_user()

    if user is None:
        return jsonify({"error": "로그인이 필요합니다."}), 401

    with get_db() as conn:
        polls = conn.execute(
            """SELECT *
               FROM polls
               WHERE target_department IS NULL
                  OR target_department = ?
               ORDER BY id DESC""",
            (user["department"],)
        ).fetchall()

    return jsonify([dict(poll) for poll in polls])





@app.route("/api/polls/<int:poll_id>/options", methods=["GET"])
def get_options(poll_id):
    user = current_user()

    if user is None:
        return jsonify({"error": "로그인이 필요합니다."}), 401

    with get_db() as conn:
        poll = conn.execute(
            "SELECT * FROM polls WHERE id = ?",
            (poll_id,)
        ).fetchone()

        if poll is None or not can_access_poll(user, poll):
            return jsonify({
                "error": "투표를 찾을 수 없습니다."
            }), 404

        options = conn.execute(
            "SELECT id, content FROM options WHERE poll_id = ?",
            (poll_id,)
        ).fetchall()

    return jsonify({
        "poll": dict(poll),
        "options": [dict(option) for option in options]
    })



# 투표 참여

@app.route("/api/polls/<int:poll_id>/vote", methods=["POST"])
def vote(poll_id):
    from datetime import datetime, timezone, timedelta

    user = current_user()

    if user is None:
        return jsonify({"error": "로그인이 필요합니다."}), 401

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "올바른 JSON을 입력하세요."}), 400

    option_id = data.get("option_id")

    if type(option_id) is not int:
        return jsonify({"error": "선택지를 선택하세요."}), 400

    with get_db() as conn:
        poll = conn.execute(
            "SELECT * FROM polls WHERE id = ?",
            (poll_id,)
        ).fetchone()

        if poll is None or not can_access_poll(user, poll):
            return jsonify({
                "error": "투표를 찾을 수 없습니다."
            }), 404

        kst = timezone(timedelta(hours=9))

        try:
            deadline = datetime.fromisoformat(poll["deadline"])

            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=kst)
        except ValueError:
            return jsonify({
                "error": "마감 시간 형식이 잘못되었습니다."
            }), 400

        if datetime.now(kst) >= deadline:
            return jsonify({
                "error": "이미 마감된 투표입니다."
            }), 400

        option = conn.execute(
            "SELECT id FROM options WHERE id = ? AND poll_id = ?",
            (option_id, poll_id)
        ).fetchone()

        if option is None:
            return jsonify({
                "error": "올바른 선택지가 아닙니다."
            }), 400

        try:
            conn.execute(
                """INSERT INTO member_votes
                   (poll_id, user_id, option_id)
                   VALUES (?, ?, ?)""",
                (poll_id, user["id"], option_id)
            )
        except sqlite3.IntegrityError:
            return jsonify({
                "error": "이미 참여한 투표입니다."
            }), 409

        conn.execute(
            "UPDATE options SET votes = votes + 1 WHERE id = ?",
            (option_id,)
        )

    return jsonify({
        "message": "투표가 완료되었습니다."
    }), 201



# 투표 결과 조회

@app.route("/api/polls/<int:poll_id>/results", methods=["GET"])
def get_results(poll_id):
    user = current_user()

    if user is None:
        return jsonify({"error": "로그인이 필요합니다."}), 401

    with get_db() as conn:
        poll = conn.execute(
            "SELECT * FROM polls WHERE id = ?",
            (poll_id,)
        ).fetchone()

        if poll is None or not can_access_poll(user, poll):
            return jsonify({
                "error": "투표를 찾을 수 없습니다."
            }), 404

        options = conn.execute(
            "SELECT id, content, votes FROM options WHERE poll_id = ?",
            (poll_id,)
        ).fetchall()

    total_votes = sum(option["votes"] for option in options)
    results = []

    for option in options:
        percentage = (
            round(option["votes"] / total_votes * 100, 1)
            if total_votes > 0 else 0
        )

        results.append({
            "id": option["id"],
            "content": option["content"],
            "votes": option["votes"],
            "percentage": percentage
        })

    return jsonify({
        "title": poll["title"],
        "total_votes": total_votes,
        "results": results
    })


# 회원가입 시 선택 가능한 학과
DEPARTMENTS = [
    "컴퓨터공학과",
    "경영학과",
    "디자인학과",
    "전자공학과"
]


# 회원가입

# 회원가입 API
@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json(silent=True)

    # JSON 입력 확인
    if not isinstance(data, dict):
        return jsonify({
            "error": "올바른 JSON을 입력하세요."
        }), 400

    # 회원가입 정보 가져오기
    username = data.get("username")
    password = data.get("password")
    nickname = data.get("nickname")
    department = data.get("department")

    # 입력값 자료형 확인
    if not all(isinstance(x, str) for x in
               [username, password, nickname, department]):
        return jsonify({
            "error": "모든 항목을 입력하세요."
        }), 400

    # 불필요한 공백 제거
    username = username.strip()
    nickname = nickname.strip()

    # 학번 검사 (숫자 7자리)
    if not (len(username) == 7 and
            username.isascii() and username.isdigit()):
        return jsonify({
            "error": "학번은 숫자 7자리로 입력하세요."
        }), 400

    # 비밀번호 검사
    if len(password) < 8:
        return jsonify({
            "error": "비밀번호는 8자 이상이어야 합니다."
        }), 400

    # 닉네임 검사
    if not (1 <= len(nickname) <= 20):
        return jsonify({
            "error": "닉네임은 1~20자로 입력하세요."
        }), 400

    # 학과 검사
    if department not in DEPARTMENTS:
        return jsonify({
            "error": "올바른 학과를 선택하세요."
        }), 400

    # 비밀번호 해시 처리
    password_hash = generate_password_hash(password)

    # 회원 정보 데이터베이스 저장
    try:
        with get_db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO users
                (username, password_hash, nickname, department)
                VALUES (?, ?, ?, ?)
                """,
                (username, password_hash, nickname, department)
            )

            user_id = cursor.lastrowid

    # 이미 가입된 학번인 경우
    except sqlite3.IntegrityError:
        return jsonify({
            "error": "이미 가입된 학번입니다."
        }), 409

    # 회원가입 성공
    return jsonify({
        "message": "회원가입이 완료되었습니다.",
        "user_id": user_id
    }), 201



# 로그인
@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "올바른 JSON을 입력하세요."}), 400

    username = data.get("username")
    password = data.get("password")

    if not isinstance(username, str) or \
            not isinstance(password, str):
        return jsonify({"error": "아이디와 비밀번호를 입력하세요."}), 400

    with get_db() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (username.strip(),)
        ).fetchone()

    if user is None or not check_password_hash(
        user["password_hash"], password
    ):
        return jsonify({
            "error": "아이디 또는 비밀번호가 올바르지 않습니다."
        }), 401

    session.clear()
    session["user_id"] = user["id"]

    return jsonify({
        "message": "로그인 성공",
        "nickname": user["nickname"],
        "department": user["department"]
    })


# 내 정보 확인
@app.route("/api/me", methods=["GET"])
def get_my_info():
    user_id = session.get("user_id")

    if user_id is None:
        return jsonify({
            "error": "로그인이 필요합니다."
        }), 401

    with get_db() as conn:
        user = conn.execute(
            """SELECT id, username, nickname, department
               FROM users WHERE id = ?""",
            (user_id,)
        ).fetchone()

    if user is None:
        session.clear()
        return jsonify({
            "error": "회원 정보를 찾을 수 없습니다."
        }), 401

    return jsonify(dict(user))


# 로그아웃
@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()

    return jsonify({
        "message": "로그아웃되었습니다."
    })


# 메인 웹페이지
@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


# CSS 제공
@app.route("/style.css")
def style():
    return send_from_directory(FRONTEND_DIR, "style.css")


# JavaScript 제공
@app.route("/script.js")
def script():
    return send_from_directory(FRONTEND_DIR, "script.js")


init_db()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)



