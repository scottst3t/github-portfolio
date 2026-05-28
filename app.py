"""
University of Bohol — Freedom Wall (demo backend)
Run: pip install -r requirements.txt
     python app.py
"""
import os
import random
import sqlite3
import uuid
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, render_template, request, jsonify, send_from_directory
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from PIL import Image, ImageDraw, ImageFont

load_dotenv()

app = Flask(__name__)
UPLOAD_DIR = os.path.join(app.static_folder, "uploads", "profiles")
POST_UPLOAD_DIR = os.path.join(app.static_folder, "uploads", "posts")
COMMENT_UPLOAD_DIR = os.path.join(app.static_folder, "uploads", "comments")

# Email config
MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "").replace(" ", "")
MAIL_FROM = os.getenv("MAIL_FROM", MAIL_USERNAME)

# In-memory store for pending verifications: {email: {code, expires, data}}
_pending_verifications = {}
VERIFY_CODE_TTL = 600  # 10 minutes

def send_verification_email(to_email, code):
    """Send a 6-digit verification code via Gmail SMTP."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Your VarsiVoice Verification Code"
    msg["From"] = f"VarsiVoice <{MAIL_FROM}>"
    msg["To"] = to_email

    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:2rem;background:#fff;border-radius:12px;">
      <h2 style="color:#7a1515;margin:0 0 0.5rem;">VarsiVoice</h2>
      <p style="color:#444;margin:0 0 1.5rem;">The official student publication of the University of Bohol</p>
      <hr style="border:none;border-top:1px solid #eee;margin:0 0 1.5rem;" />
      <p style="font-size:1rem;color:#222;">Your verification code is:</p>
      <div style="font-size:2.5rem;font-weight:700;letter-spacing:0.3em;color:#7a1515;text-align:center;padding:1rem;background:#fdf0f0;border-radius:8px;margin:1rem 0;">{code}</div>
      <p style="font-size:0.85rem;color:#888;">This code expires in 10 minutes. If you didn't request this, ignore this email.</p>
    </div>
    """
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(MAIL_USERNAME, MAIL_PASSWORD)
        server.sendmail(MAIL_FROM, to_email, msg.as_string())

SUBMISSION_UPLOAD_DIR = os.path.join(app.static_folder, "uploads", "submissions")
IMAGES_DIR = os.path.join(app.root_path, "images")
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
ALLOWED_DOC_EXTENSIONS = {"pdf", "doc", "docx", "odt", "txt"}
DB_PATH = os.path.join(app.root_path, "freedom_wall.db")

# Avatar color palette (matching avatar-color.js)
AVATAR_COLOR_PALETTE = [
    '#c0392b', '#e74c3c', '#8e44ad', '#9b59b6',
    '#2980b9', '#3498db', '#16a085', '#1abc9c',
    '#27ae60', '#2ecc71', '#d35400', '#e67e22',
    '#c0392b', '#7f8c8d', '#2c3e50', '#6d4c41',
    '#00838f', '#558b2f', '#6a1b9a', '#1565c0'
]


def select_random_color():
    """Select a random color from the avatar color palette."""
    return random.choice(AVATAR_COLOR_PALETTE)


def extract_initials(display_name):
    """
    Extract initials from display name.
    
    Rules:
    - Split by whitespace
    - Take first character of first two words
    - Convert to uppercase
    - Default to "U" if empty or invalid
    
    Examples:
    - "John Doe" → "JD"
    - "Alice" → "A"
    - "Mary Jane Watson" → "MJ"
    - "" → "U"
    """
    if not display_name or not display_name.strip():
        return "U"
    
    words = display_name.strip().split()
    if len(words) == 0:
        return "U"
    elif len(words) == 1:
        return words[0][0].upper()
    else:
        return (words[0][0] + words[1][0]).upper()


def generate_initial_avatar(user_id, display_name):
    """
    Generate an initial-based avatar image.
    
    Args:
        user_id: The user's ID
        display_name: The user's display name
    
    Returns:
        File path (relative URL) on success, None on failure
    
    Side effects:
        Creates image file in static/uploads/profiles/
        Logs errors if generation fails
    """
    try:
        # Extract initials
        initials = extract_initials(display_name)
        
        # Select random background color
        bg_color = select_random_color()
        
        # Image dimensions
        size = 200
        
        # Create image with colored background
        image = Image.new('RGB', (size, size), bg_color)
        draw = ImageDraw.Draw(image)
        
        # Load font - try multiple options for better consistency
        font = None
        font_size = 70 if len(initials) == 2 else 90  # Smaller for 2 chars, larger for 1
        
        # Try to load a sans-serif font
        font_options = [
            "arial.ttf",
            "Arial.ttf",
            "arialbd.ttf",  # Arial Bold
            "C:\\Windows\\Fonts\\arial.ttf",
            "C:\\Windows\\Fonts\\arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Linux
            "/System/Library/Fonts/Helvetica.ttc",  # macOS
        ]
        
        for font_path in font_options:
            try:
                font = ImageFont.truetype(font_path, font_size)
                break
            except:
                continue
        
        # Fallback to default font if none found
        if font is None:
            try:
                font = ImageFont.load_default()
            except:
                # Ultimate fallback - use a larger default
                font = ImageFont.load_default()
        
        # Calculate text position (centered both horizontally and vertically)
        bbox = draw.textbbox((0, 0), initials, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        # Center the text
        x = (size - text_width) / 2 - bbox[0]
        y = (size - text_height) / 2 - bbox[1]
        
        # Draw white text with slight offset for better centering
        draw.text((x, y), initials, fill='white', font=font)
        
        # Generate unique filename
        filename = f"user_{user_id}_{uuid.uuid4().hex}.png"
        
        # Ensure directory exists
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        
        # Save image
        filepath = os.path.join(UPLOAD_DIR, filename)
        image.save(filepath, 'PNG')
        
        # Return relative URL
        rel_path = os.path.relpath(filepath, app.root_path)
        return "/" + rel_path.replace(os.sep, "/")
        
    except Exception as e:
        # Log error and return None
        print(f"Error generating avatar for user {user_id}: {e}")
        return None







def get_default_profile_images():
    if not os.path.isdir(IMAGES_DIR):
        return []
    defaults = []
    for filename in sorted(os.listdir(IMAGES_DIR)):
        if allowed_file(filename):
            defaults.append(f"/images/{filename}")
    return defaults


def pick_default_profile_image():
    images = get_default_profile_images()
    if not images:
        return None
    return random.choice(images)


def allowed_file(filename):
    if "." not in filename:
        return False
    return filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def save_upload(file, directory):
    """Save an uploaded image file to *directory* and return its static URL."""
    safe_name = secure_filename(file.filename)
    ext = safe_name.rsplit(".", 1)[1].lower()
    filename = uuid.uuid4().hex + "." + ext
    os.makedirs(directory, exist_ok=True)
    file.save(os.path.join(directory, filename))
    # Build relative URL: strip app.static_folder prefix to get /static/…
    rel = os.path.relpath(os.path.join(directory, filename), app.root_path)
    return "/" + rel.replace(os.sep, "/")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def json_row(row):
    """Make DB row JSON-serializable."""
    if row is None:
        return None
    return dict(row)


def init_db():
    conn = get_conn()
    try:
        c = conn.cursor()
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              email TEXT NOT NULL UNIQUE,
              password_hash TEXT NOT NULL,
              display_name TEXT NOT NULL,
              photo_url TEXT,
              created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS posts (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER NULL,
              content TEXT NOT NULL,
              category TEXT NOT NULL DEFAULT 'Other',
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              updated_at TEXT NULL,
              FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS comments (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              post_id INTEGER NOT NULL,
              user_id INTEGER NULL,
              parent_id INTEGER NULL,
              content TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              updated_at TEXT NULL,
              FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE,
              FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
              FOREIGN KEY (parent_id) REFERENCES comments(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS likes (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              post_id INTEGER NOT NULL,
              user_token TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              UNIQUE (post_id, user_token),
              FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS submissions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              author_name TEXT NOT NULL,
              author_bio TEXT,
              title TEXT NOT NULL,
              category TEXT NOT NULL,
              content TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'Pending Review',
              created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS reactions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              target_type TEXT NOT NULL,
              target_id INTEGER NOT NULL,
              user_token TEXT NOT NULL,
              reaction_type TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              UNIQUE (target_type, target_id, user_token)
            );

            CREATE TABLE IF NOT EXISTS notifications (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              recipient_user_id INTEGER NOT NULL,
              actor_user_id INTEGER NULL,
              notif_type TEXT NOT NULL,
              post_id INTEGER NULL,
              comment_id INTEGER NULL,
              reaction_type TEXT NULL,
              is_read INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              FOREIGN KEY (recipient_user_id) REFERENCES users(id) ON DELETE CASCADE,
              FOREIGN KEY (actor_user_id) REFERENCES users(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS reports (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              reporter_user_id INTEGER NOT NULL,
              target_type TEXT NOT NULL,
              target_id INTEGER NOT NULL,
              reason TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              UNIQUE (reporter_user_id, target_type, target_id),
              FOREIGN KEY (reporter_user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS warnings (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER NOT NULL,
              admin_id INTEGER NOT NULL,
              target_type TEXT NOT NULL,
              target_id INTEGER NOT NULL,
              reason TEXT NOT NULL,
              message TEXT,
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
              FOREIGN KEY (admin_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )
        # Migrate existing likes to reactions (heart) — idempotent via INSERT OR IGNORE
        c.execute(
            """
            INSERT OR IGNORE INTO reactions (target_type, target_id, user_token, reaction_type)
            SELECT 'post', post_id, user_token, 'heart' FROM likes
            """
        )
        conn.commit()
        # Add updated_at to submissions if it doesn't exist yet (idempotent)
        for sql in [
            "ALTER TABLE posts ADD COLUMN image_url TEXT NULL",
            "ALTER TABLE comments ADD COLUMN image_url TEXT NULL",
            "ALTER TABLE notifications ADD COLUMN comment_content TEXT NULL",
            "ALTER TABLE submissions ADD COLUMN updated_at TEXT NULL",
            "ALTER TABLE posts ADD COLUMN is_anonymous INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'",
            "ALTER TABLE submissions ADD COLUMN document_url TEXT NULL",
            "ALTER TABLE submissions ADD COLUMN document_name TEXT NULL",
            "ALTER TABLE users ADD COLUMN user_id TEXT NULL",
            "ALTER TABLE submissions ADD COLUMN user_id INTEGER NULL",
        ]:
            try:
                conn.execute(sql)
            except Exception:
                pass
        conn.commit()
        
        # Generate user_id for existing users who don't have one
        try:
            users_without_id = conn.execute("SELECT id FROM users WHERE user_id IS NULL").fetchall()
            for row in users_without_id:
                user_id = f"USR-{row[0]:05d}"
                conn.execute("UPDATE users SET user_id = ? WHERE id = ?", (user_id, row[0]))
            conn.commit()
        except Exception:
            pass
    finally:
        conn.close()


# --- Pages ---


@app.route("/")
def home():
    return render_template("login.html")


@app.route("/wall")
def wall():
    return render_template("wall.html")


@app.route("/freedom-wall")
def freedom_wall():
    return render_template("freedom_wall.html")


@app.route("/api/fw-posts", methods=["GET"])
def list_fw_posts():
    search = (request.args.get("q") or "").strip()
    category = (request.args.get("category") or "").strip()
    sort = request.args.get("sort", "latest")

    order = "p.created_at DESC"
    if sort == "likes":
        order = "like_count DESC, p.created_at DESC"
    elif sort == "comments":
        order = "comment_count DESC, p.created_at DESC"

    where_clauses = ["p.is_anonymous = 1"]
    params = []
    if search:
        where_clauses.append("p.content LIKE ?")
        params.append("%" + search + "%")
    if category and category != "All":
        where_clauses.append("p.category = ?")
        params.append(category)

    where = "WHERE " + " AND ".join(where_clauses)

    conn = get_conn()
    try:
        rows = conn.execute(
            f"""
            SELECT p.id, p.content, p.category, p.created_at, p.updated_at, p.image_url,
              'Anonymous' AS author_name,
              NULL AS author_photo,
              (SELECT COUNT(*) FROM reactions r WHERE r.target_type='post' AND r.target_id = p.id) AS like_count,
              (SELECT COUNT(*) FROM comments cm WHERE cm.post_id = p.id) AS comment_count
            FROM posts p
            {where}
            ORDER BY {order}
            """,
            params,
        ).fetchall()
        return jsonify([json_row(r) for r in rows])
    finally:
        conn.close()


@app.route("/api/fw-posts", methods=["POST"])
def create_fw_post():
    data = request.form
    user_id = data.get("user_id")
    content = (data.get("content") or "").strip()
    category = (data.get("category") or "Other").strip() or "Other"
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return jsonify({"error": "Valid user_id is required."}), 400
    if len(content) > 1000:
        return jsonify({"error": "Post is too long (max 1000 characters)."}), 400

    image_url = None
    image_file = request.files.get("image")
    if image_file and image_file.filename:
        if not allowed_file(image_file.filename):
            return jsonify({"error": "Allowed image types: png, jpg, jpeg, gif, webp."}), 400
        image_file.seek(0, 2)
        size = image_file.tell()
        image_file.seek(0)
        if size > 5 * 1024 * 1024:
            return jsonify({"error": "Image must be under 5 MB."}), 400
        image_url = save_upload(image_file, POST_UPLOAD_DIR)

    if not content and not image_url:
        return jsonify({"error": "Please write something or attach an image."}), 400

    conn = get_conn()
    try:
        if not conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone():
            return jsonify({"error": "User not found."}), 404
        cur = conn.execute(
            "INSERT INTO posts (user_id, content, category, image_url, is_anonymous) VALUES (?, ?, ?, ?, 1)",
            (user_id, content, category, image_url),
        )
        pid = cur.lastrowid
        conn.commit()
        row = conn.execute(
            """
            SELECT p.id, p.content, p.category, p.created_at, p.updated_at, p.image_url,
              'Anonymous' AS author_name, NULL AS author_photo
            FROM posts p WHERE p.id = ?
            """,
            (pid,),
        ).fetchone()
        return jsonify(json_row(row)), 201
    finally:
        conn.close()


@app.route("/writers")
def writers():
    return render_template("writers.html")


@app.route("/profile/<int:user_id>")
def profile_page(user_id):
    return render_template("profile.html")


@app.route("/images/<path:filename>")
def user_image_file(filename):
    return send_from_directory(IMAGES_DIR, filename)


# --- API: Posts ---


@app.route("/api/posts", methods=["GET"])
def list_posts():
    sort = request.args.get("sort", "latest")
    search = (request.args.get("q") or "").strip()

    order = "p.created_at DESC"
    if sort == "likes":
        order = "like_count DESC, p.created_at DESC"
    elif sort == "comments":
        order = "comment_count DESC, p.created_at DESC"
    elif sort == "recent-comment":
        order = "(SELECT MAX(cm.created_at) FROM comments cm WHERE cm.post_id = p.id) DESC NULLS LAST, p.created_at DESC"

    category = (request.args.get("category") or "").strip()

    conn = get_conn()
    try:
        where_clauses = ["(p.is_anonymous = 0 OR p.is_anonymous IS NULL)"]
        params = []
        if search:
            where_clauses.append("p.content LIKE ?")
            params.append("%" + search + "%")
        if category and category != "All":
            where_clauses.append("p.category = ?")
            params.append(category)
        where = "WHERE " + " AND ".join(where_clauses)

        rows = conn.execute(
            f"""
            SELECT p.id, p.user_id, p.content, p.category, p.created_at,
              p.updated_at, p.image_url,
              COALESCE(u.display_name, 'Anonymous') AS author_name,
              u.photo_url AS author_photo,
              (SELECT COUNT(*) FROM reactions r WHERE r.target_type='post' AND r.target_id = p.id) AS like_count,
              (SELECT COUNT(*) FROM comments cm WHERE cm.post_id = p.id) AS comment_count
            FROM posts p
            LEFT JOIN users u ON u.id = p.user_id
            {where}
            ORDER BY {order}
            """,
            params,
        ).fetchall()
        return jsonify([json_row(r) for r in rows])
    finally:
        conn.close()


@app.route("/api/posts", methods=["POST"])
def create_post():
    data = request.form
    user_id = data.get("user_id")
    content = (data.get("content") or "").strip()
    category = (data.get("category") or "Other").strip() or "Other"
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return jsonify({"error": "Valid user_id is required."}), 400
    if len(content) > 1000:
        return jsonify({"error": "Post is too long (max 1000 characters)."}), 400

    image_url = None
    image_file = request.files.get("image")
    if image_file and image_file.filename:
        if not allowed_file(image_file.filename):
            return jsonify({"error": "Allowed image types: png, jpg, jpeg, gif, webp."}), 400
        image_file.seek(0, 2)
        size = image_file.tell()
        image_file.seek(0)
        if size > 5 * 1024 * 1024:
            return jsonify({"error": "Image must be under 5 MB."}), 400
        image_url = save_upload(image_file, POST_UPLOAD_DIR)

    if not content and not image_url:
        return jsonify({"error": "Please write something or attach an image."}), 400

    conn = get_conn()
    try:
        if not conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone():
            return jsonify({"error": "User not found."}), 404
        cur = conn.execute(
            "INSERT INTO posts (user_id, content, category, image_url) VALUES (?, ?, ?, ?)",
            (user_id, content, category, image_url),
        )
        pid = cur.lastrowid
        conn.commit()
        row = conn.execute(
            """
            SELECT p.id, p.user_id, p.content, p.category, p.created_at,
              p.updated_at, p.image_url,
              COALESCE(u.display_name, 'Anonymous') AS author_name,
              u.photo_url AS author_photo
            FROM posts p
            LEFT JOIN users u ON u.id = p.user_id
            WHERE p.id = ?
            """,
            (pid,),
        ).fetchone()
        return jsonify(json_row(row)), 201
    finally:
        conn.close()


@app.route("/api/posts/<int:post_id>", methods=["GET"])
def get_post_details(post_id):
    """Get full post details including comments and reactions for admin modal."""
    conn = get_conn()
    try:
        # Get post
        post = conn.execute(
            """
            SELECT p.id, p.user_id, p.content, p.category, p.created_at,
              p.updated_at, p.image_url, p.is_anonymous,
              COALESCE(u.display_name, 'Anonymous') AS author_name,
              u.photo_url AS author_photo
            FROM posts p
            LEFT JOIN users u ON u.id = p.user_id
            WHERE p.id = ?
            """,
            (post_id,),
        ).fetchone()
        if not post:
            return jsonify({"error": "Post not found."}), 404
        
        # Get comments
        comments = conn.execute(
            """
            SELECT cm.id, cm.post_id, cm.parent_id, cm.content, cm.created_at,
              cm.updated_at, cm.user_id, cm.image_url, u.photo_url AS author_photo,
              COALESCE(u.display_name, 'Anonymous') AS author_name
            FROM comments cm
            LEFT JOIN users u ON u.id = cm.user_id
            WHERE cm.post_id = ?
            ORDER BY cm.created_at ASC
            """,
            (post_id,),
        ).fetchall()
        
        # Get reaction counts for post
        post_reactions = conn.execute(
            """
            SELECT reaction_type, COUNT(*) AS cnt
            FROM reactions
            WHERE target_type = 'post' AND target_id = ?
            GROUP BY reaction_type
            """,
            (post_id,),
        ).fetchall()
        
        reaction_counts = {rt: 0 for rt in ALLOWED_REACTION_TYPES}
        for r in post_reactions:
            if r["reaction_type"] in reaction_counts:
                reaction_counts[r["reaction_type"]] = r["cnt"]
        
        return jsonify({
            "post": json_row(post),
            "comments": [json_row(c) for c in comments],
            "reactions": reaction_counts,
            "total_reactions": sum(reaction_counts.values())
        })
    finally:
        conn.close()


@app.route("/api/posts/<int:post_id>", methods=["PUT"])
def update_post(post_id):
    data = request.get_json(force=True, silent=True) or {}
    content = (data.get("content") or "").strip()
    category = (data.get("category") or "Other").strip() or "Other"
    user_id = data.get("user_id")

    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return jsonify({"error": "Valid user_id is required."}), 400
    if not content:
        return jsonify({"error": "Content is required."}), 400
    if len(content) > 1000:
        return jsonify({"error": "Post is too long (max 1000 characters)."}), 400

    conn = get_conn()
    try:
        row = conn.execute("SELECT user_id FROM posts WHERE id = ?", (post_id,)).fetchone()
        if not row:
            return jsonify({"error": "Post not found."}), 404
        if row["user_id"] != user_id:
            return jsonify({"error": "You can only edit your own posts."}), 403
        conn.execute(
            """
            UPDATE posts
            SET content = ?, category = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (content, category, post_id),
        )
        conn.commit()
        post = conn.execute(
            """
            SELECT p.id, p.user_id, p.content, p.category, p.created_at,
              p.updated_at, p.image_url,
              COALESCE(u.display_name, 'Anonymous') AS author_name,
              u.photo_url AS author_photo,
              (SELECT COUNT(*) FROM reactions r WHERE r.target_type='post' AND r.target_id = p.id) AS like_count,
              (SELECT COUNT(*) FROM comments cm WHERE cm.post_id = p.id) AS comment_count
            FROM posts p
            LEFT JOIN users u ON u.id = p.user_id
            WHERE p.id = ?
            """,
            (post_id,),
        ).fetchone()
        return jsonify({"post": json_row(post)})
    finally:
        conn.close()


@app.route("/api/posts/<int:post_id>", methods=["DELETE"])
def delete_post(post_id):
    data = request.get_json(force=True, silent=True) or {}
    user_id = data.get("user_id")
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return jsonify({"error": "Valid user_id is required."}), 400

    conn = get_conn()
    try:
        row = conn.execute("SELECT user_id, image_url FROM posts WHERE id = ?", (post_id,)).fetchone()
        if not row:
            return jsonify({"error": "Post not found."}), 404
        if row["user_id"] != user_id:
            return jsonify({"error": "You can only delete your own posts."}), 403
        image_url = row["image_url"]
        conn.execute(
            "DELETE FROM reactions WHERE target_type='post' AND target_id=?", (post_id,)
        )
        conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        conn.commit()
        if image_url:
            try:
                os.remove(os.path.join(app.root_path, image_url.lstrip("/")))
            except OSError:
                pass
        return jsonify({"ok": True})
    finally:
        conn.close()


# --- API: Auth + Accounts ---


@app.route("/api/auth/send-verification", methods=["POST"])
def send_verification():
    """Step 1: validate inputs, send 6-digit code to email."""
    data = request.get_json(force=True, silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    display_name = (data.get("display_name") or "").strip()

    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return jsonify({"error": "Please provide a valid email address."}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters."}), 400
    if not display_name:
        return jsonify({"error": "Display name is required."}), 400
    if len(display_name) > 120:
        return jsonify({"error": "Display name is too long."}), 400

    conn = get_conn()
    try:
        if conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
            return jsonify({"error": "This email is already registered."}), 409
    finally:
        conn.close()

    # Generate 6-digit code
    code = str(random.randint(100000, 999999))
    _pending_verifications[email] = {
        "code": code,
        "expires": time.time() + VERIFY_CODE_TTL,
        "password": password,
        "display_name": display_name,
    }

    try:
        send_verification_email(email, code)
    except Exception as e:
        return jsonify({"error": f"Could not send email: {str(e)}"}), 500

    return jsonify({"ok": True, "message": "Verification code sent."})


@app.route("/api/auth/verify-and-signup", methods=["POST"])
def verify_and_signup():
    """Step 2: verify code and create account."""
    data = request.get_json(force=True, silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()

    pending = _pending_verifications.get(email)
    if not pending:
        return jsonify({"error": "No verification pending for this email. Please sign up again."}), 400
    if time.time() > pending["expires"]:
        _pending_verifications.pop(email, None)
        return jsonify({"error": "Verification code expired. Please sign up again."}), 400
    if pending["code"] != code:
        return jsonify({"error": "Incorrect verification code."}), 400

    # Code is valid — create the account
    _pending_verifications.pop(email, None)
    password_hash = generate_password_hash(pending["password"])
    conn = get_conn()
    try:
        if conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
            return jsonify({"error": "This email is already registered."}), 409
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, display_name, photo_url) VALUES (?, ?, ?, ?)",
            (email, password_hash, pending["display_name"], None),
        )
        uid = cur.lastrowid
        user_id = f"USR-{uid:05d}"
        conn.execute("UPDATE users SET user_id = ? WHERE id = ?", (user_id, uid))
        
        # Generate initial avatar
        photo_url = generate_initial_avatar(uid, pending["display_name"])
        if photo_url:
            conn.execute("UPDATE users SET photo_url = ? WHERE id = ?", (photo_url, uid))
        
        conn.commit()
        user = conn.execute(
            "SELECT id, email, display_name, photo_url, created_at, role, user_id FROM users WHERE id = ?",
            (uid,),
        ).fetchone()
        return jsonify({"user": json_row(user)}), 201
    finally:
        conn.close()


@app.route("/api/auth/signup", methods=["POST"])
def signup():
    data = request.get_json(force=True, silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    display_name = (data.get("display_name") or "").strip()

    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return jsonify({"error": "Please provide a valid email address."}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters."}), 400
    if not display_name:
        return jsonify({"error": "Display name is required."}), 400
    if len(display_name) > 120:
        return jsonify({"error": "Display name is too long."}), 400

    password_hash = generate_password_hash(password)
    conn = get_conn()
    try:
        if conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
            return jsonify({"error": "This email is already registered."}), 409
        cur = conn.execute(
            """
            INSERT INTO users (email, password_hash, display_name, photo_url)
            VALUES (?, ?, ?, ?)
            """,
            (email, password_hash, display_name, None),
        )
        uid = cur.lastrowid
        
        # Generate user_id
        user_id = f"USR-{uid:05d}"
        conn.execute("UPDATE users SET user_id = ? WHERE id = ?", (user_id, uid))
        
        # Generate initial avatar
        photo_url = generate_initial_avatar(uid, display_name)
        if photo_url:
            conn.execute("UPDATE users SET photo_url = ? WHERE id = ?", (photo_url, uid))
        
        conn.commit()
        
        user = conn.execute(
            "SELECT id, email, display_name, photo_url, created_at, role, user_id FROM users WHERE id = ?",
            (uid,),
        ).fetchone()
        return jsonify({"user": json_row(user)}), 201
    finally:
        conn.close()


@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json(force=True, silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400

    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT id, email, password_hash, display_name, photo_url, created_at, role, user_id
            FROM users WHERE email = ?
            """,
            (email,),
        ).fetchone()
        if not row:
            return jsonify({"error": "This email has no account. Please sign up first."}), 404
        if not check_password_hash(row["password_hash"], password):
            return jsonify({"error": "Incorrect password."}), 401
        user = {
            "id": row["id"],
            "email": row["email"],
            "display_name": row["display_name"],
            "photo_url": row["photo_url"],
            "created_at": row["created_at"],
            "role": row["role"],
            "user_id": row["user_id"],
        }
        return jsonify({"user": user})
    finally:
        conn.close()


@app.route("/api/users/<int:user_id>/delete-account", methods=["DELETE"])
def delete_account(user_id):
    data = request.get_json(force=True, silent=True) or {}
    requesting_user_id = data.get("user_id")
    try:
        if int(requesting_user_id) != user_id:
            return jsonify({"error": "Unauthorized."}), 403
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid user_id."}), 400

    conn = get_conn()
    try:
        row = conn.execute("SELECT id, photo_url FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            return jsonify({"error": "User not found."}), 404
        
        photo_url = row["photo_url"]
        
        # Enable foreign keys
        conn.execute("PRAGMA foreign_keys=ON")
        
        # Collect all files to delete
        files_to_delete = []
        
        # User's profile photo
        if photo_url:
            files_to_delete.append(photo_url)
        
        # Get user's posts and their images
        post_rows = conn.execute("SELECT id, image_url FROM posts WHERE user_id = ?", (user_id,)).fetchall()
        post_ids = [p["id"] for p in post_rows]
        
        for post in post_rows:
            if post["image_url"]:
                files_to_delete.append(post["image_url"])
        
        # Get comments on user's posts (will be deleted when posts are deleted)
        if post_ids:
            placeholders = ",".join(["?"] * len(post_ids))
            comment_images = conn.execute(
                f"SELECT image_url FROM comments WHERE post_id IN ({placeholders}) AND image_url IS NOT NULL",
                post_ids
            ).fetchall()
            for comment in comment_images:
                files_to_delete.append(comment["image_url"])
        
        # Get user's comments on other posts
        user_comments = conn.execute(
            "SELECT id, image_url FROM comments WHERE user_id = ?",
            (user_id,)
        ).fetchall()
        for comment in user_comments:
            if comment["image_url"]:
                files_to_delete.append(comment["image_url"])
        
        # Delete user's reactions (using user_token pattern)
        user_token = f"user_{user_id}"
        conn.execute("DELETE FROM reactions WHERE user_token = ?", (user_token,))
        
        # Delete user's likes (using user_token pattern)
        conn.execute("DELETE FROM likes WHERE user_token = ?", (user_token,))
        
        # Delete comments on user's posts (before deleting posts)
        if post_ids:
            placeholders = ",".join(["?"] * len(post_ids))
            conn.execute(f"DELETE FROM comments WHERE post_id IN ({placeholders})", post_ids)
        
        # Delete reactions on user's posts
        if post_ids:
            placeholders = ",".join(["?"] * len(post_ids))
            conn.execute(f"DELETE FROM reactions WHERE target_type = 'post' AND target_id IN ({placeholders})", post_ids)
        
        # Delete likes on user's posts
        if post_ids:
            placeholders = ",".join(["?"] * len(post_ids))
            conn.execute(f"DELETE FROM likes WHERE post_id IN ({placeholders})", post_ids)
        
        # Delete user's posts
        conn.execute("DELETE FROM posts WHERE user_id = ?", (user_id,))
        
        # Delete user's comments on other posts
        conn.execute("DELETE FROM comments WHERE user_id = ?", (user_id,))
        
        # Delete user's submissions
        conn.execute("DELETE FROM submissions WHERE user_id = ?", (user_id,))
        
        # Delete the user account (notifications and reports will cascade)
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        
        conn.commit()
        
        # Clean up uploaded files
        for file_url in files_to_delete:
            try:
                file_path = os.path.join(app.root_path, file_url.lstrip("/"))
                if os.path.exists(file_path):
                    os.remove(file_path)
            except OSError as e:
                print(f"Error deleting file {file_url}: {e}")
        
        return jsonify({"ok": True})
    finally:
        conn.close()


@app.route("/api/users/<int:user_id>/profile", methods=["PUT"])
def update_profile(user_id):
    data = request.get_json(force=True, silent=True) or {}
    display_name_raw = data.get("display_name")
    photo_url_raw = data.get("photo_url")
    updates = {}

    if display_name_raw is not None:
        display_name = str(display_name_raw).strip()
        if not display_name:
            return jsonify({"error": "Display name is required."}), 400
        if len(display_name) > 120:
            return jsonify({"error": "Display name is too long."}), 400
        updates["display_name"] = display_name

    if photo_url_raw is not None:
        photo_url = str(photo_url_raw).strip()
        default_images = set(get_default_profile_images())
        if photo_url and photo_url not in default_images:
            return jsonify({"error": "Please choose a valid default profile image."}), 400
        updates["photo_url"] = photo_url

    if not updates:
        return jsonify({"error": "Nothing to update."}), 400

    conn = get_conn()
    try:
        if not conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone():
            return jsonify({"error": "User not found."}), 404
        set_clause = ", ".join([f"{key} = ?" for key in updates.keys()])
        params = list(updates.values()) + [user_id]
        conn.execute(f"UPDATE users SET {set_clause} WHERE id = ?", params)
        conn.commit()
        user = conn.execute(
            "SELECT id, email, display_name, photo_url, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        return jsonify({"user": json_row(user)})
    finally:
        conn.close()


@app.route("/api/profile/default-images", methods=["GET"])
def profile_default_images():
    return jsonify({"images": get_default_profile_images()})


@app.route("/api/users/<int:user_id>/profile-photo", methods=["POST"])
def upload_profile_photo(user_id):
    file = request.files.get("photo")
    if not file:
        return jsonify({"error": "Please choose an image file."}), 400
    if not file.filename:
        return jsonify({"error": "Please choose an image file."}), 400
    if not allowed_file(file.filename):
        return jsonify({"error": "Allowed image types: png, jpg, jpeg, gif, webp."}), 400

    safe_name = secure_filename(file.filename)
    ext = safe_name.rsplit(".", 1)[1].lower()
    saved_name = f"user_{user_id}_{uuid.uuid4().hex}.{ext}"

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    save_path = os.path.join(UPLOAD_DIR, saved_name)
    file.save(save_path)
    photo_url = f"/static/uploads/profiles/{saved_name}"

    conn = get_conn()
    try:
        if not conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone():
            return jsonify({"error": "User not found."}), 404
        conn.execute(
            "UPDATE users SET photo_url = ? WHERE id = ?",
            (photo_url, user_id),
        )
        conn.commit()
        user = conn.execute(
            "SELECT id, email, display_name, photo_url, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        return jsonify({"user": json_row(user)})
    finally:
        conn.close()


# --- API: Comments ---


@app.route("/api/posts/<int:post_id>/comments", methods=["GET"])
def list_comments(post_id):
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT cm.id, cm.post_id, cm.parent_id, cm.content, cm.created_at,
              cm.updated_at, cm.user_id, cm.image_url, u.photo_url AS author_photo,
              COALESCE(u.display_name, 'Anonymous') AS author_name
            FROM comments cm
            LEFT JOIN users u ON u.id = cm.user_id
            WHERE cm.post_id = ?
            ORDER BY cm.created_at ASC
            """,
            (post_id,),
        ).fetchall()
        return jsonify([json_row(r) for r in rows])
    finally:
        conn.close()


@app.route("/api/posts/<int:post_id>/comments", methods=["POST"])
def create_comment(post_id):
    data = request.form
    user_id = data.get("user_id")
    content = (data.get("content") or "").strip()
    parent_id = data.get("parent_id")
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return jsonify({"error": "Valid user_id is required."}), 400
    if parent_id is not None:
        try:
            parent_id = int(parent_id)
        except (TypeError, ValueError):
            parent_id = None

    image_url = None
    image_file = request.files.get("image")
    if image_file and image_file.filename:
        if not allowed_file(image_file.filename):
            return jsonify({"error": "Allowed image types: png, jpg, jpeg, gif, webp."}), 400
        image_file.seek(0, 2)
        size = image_file.tell()
        image_file.seek(0)
        if size > 5 * 1024 * 1024:
            return jsonify({"error": "Image must be under 5 MB."}), 400
        image_url = save_upload(image_file, COMMENT_UPLOAD_DIR)

    if not content and not image_url:
        return jsonify({"error": "Please write something or attach an image."}), 400

    conn = get_conn()
    try:
        if not conn.execute("SELECT id FROM posts WHERE id = ?", (post_id,)).fetchone():
            return jsonify({"error": "Post not found."}), 404
        if not conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone():
            return jsonify({"error": "User not found."}), 404
        if parent_id:
            pr = conn.execute(
                "SELECT id, parent_id FROM comments WHERE id = ? AND post_id = ?",
                (parent_id, post_id),
            ).fetchone()
            if not pr:
                return jsonify({"error": "Parent comment not found."}), 400
            if pr["parent_id"] is not None:
                return jsonify({"error": "Reply to a top-level comment only."}), 400

        cur = conn.execute(
            """
            INSERT INTO comments (post_id, user_id, parent_id, content, image_url)
            VALUES (?, ?, ?, ?, ?)
            """,
            (post_id, user_id, parent_id, content, image_url),
        )
        cid = cur.lastrowid
        conn.commit()

        # Notify post owner when someone comments
        post_owner = conn.execute("SELECT user_id FROM posts WHERE id = ?", (post_id,)).fetchone()
        if post_owner and post_owner["user_id"]:
            _create_notification(conn, post_owner["user_id"], user_id, "comment",
                                  post_id=post_id, comment_id=cid, comment_content=content)
        # Notify parent comment owner when someone replies
        if parent_id:
            parent_owner = conn.execute("SELECT user_id FROM comments WHERE id = ?", (parent_id,)).fetchone()
            if parent_owner and parent_owner["user_id"]:
                _create_notification(conn, parent_owner["user_id"], user_id, "reply",
                                      post_id=post_id, comment_id=cid, comment_content=content)
        conn.commit()
        row = conn.execute(
            """
            SELECT cm.id, cm.post_id, cm.parent_id, cm.content, cm.created_at,
              cm.updated_at, cm.user_id, cm.image_url, u.photo_url AS author_photo,
              COALESCE(u.display_name, 'Anonymous') AS author_name
            FROM comments cm
            LEFT JOIN users u ON u.id = cm.user_id
            WHERE cm.id = ?
            """,
            (cid,),
        ).fetchone()
        return jsonify(json_row(row)), 201
    finally:
        conn.close()


@app.route("/api/comments/<int:comment_id>", methods=["PUT"])
def update_comment(comment_id):
    data = request.get_json(force=True, silent=True) or {}
    content = (data.get("content") or "").strip()
    user_id = data.get("user_id")
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return jsonify({"error": "Valid user_id is required."}), 400
    if not content:
        return jsonify({"error": "Comment cannot be empty."}), 400

    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT user_id FROM comments WHERE id = ?", (comment_id,)
        ).fetchone()
        if not row:
            return jsonify({"error": "Comment not found."}), 404
        if row["user_id"] != user_id:
            return jsonify({"error": "You can only edit your own comments."}), 403
        conn.execute(
            """
            UPDATE comments
            SET content = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (content, comment_id),
        )
        conn.commit()
        comment = conn.execute(
            """
            SELECT cm.id, cm.post_id, cm.parent_id, cm.content, cm.created_at,
              cm.updated_at, cm.user_id, cm.image_url, u.photo_url AS author_photo,
              COALESCE(u.display_name, 'Anonymous') AS author_name
            FROM comments cm
            LEFT JOIN users u ON u.id = cm.user_id
            WHERE cm.id = ?
            """,
            (comment_id,),
        ).fetchone()
        return jsonify({"comment": json_row(comment)})
    finally:
        conn.close()


@app.route("/api/comments/<int:comment_id>", methods=["DELETE"])
def delete_comment(comment_id):
    data = request.get_json(force=True, silent=True) or {}
    user_id = data.get("user_id")
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return jsonify({"error": "Valid user_id is required."}), 400

    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT user_id, parent_id, image_url FROM comments WHERE id = ?", (comment_id,)
        ).fetchone()
        if not row:
            return jsonify({"error": "Comment not found."}), 404
        if row["user_id"] != user_id:
            return jsonify({"error": "You can only delete your own comments."}), 403
        image_url = row["image_url"]
        conn.execute(
            "DELETE FROM reactions WHERE target_type='comment' AND target_id=?", (comment_id,)
        )
        conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
        conn.commit()
        if image_url:
            try:
                os.remove(os.path.join(app.root_path, image_url.lstrip("/")))
            except OSError:
                pass
        return jsonify({"ok": True})
    finally:
        conn.close()


# --- API: Likes ---


ALLOWED_REACTION_TYPES = {"heart", "haha", "wow", "sad", "angry"}
ALLOWED_TARGET_TYPES = {"post", "comment"}


def _reaction_counts(conn, target_type, target_id):
    """Return counts dict, total, and a helper row list for a given target."""
    rows = conn.execute(
        """
        SELECT reaction_type, COUNT(*) AS cnt
        FROM reactions
        WHERE target_type = ? AND target_id = ?
        GROUP BY reaction_type
        """,
        (target_type, target_id),
    ).fetchall()
    counts = {rt: 0 for rt in ALLOWED_REACTION_TYPES}
    for r in rows:
        if r["reaction_type"] in counts:
            counts[r["reaction_type"]] = r["cnt"]
    total = sum(counts.values())
    return counts, total


def _create_notification(conn, recipient_user_id, actor_user_id, notif_type,
                          post_id=None, comment_id=None, reaction_type=None, comment_content=None):
    """Insert a notification, skipping if actor == recipient or duplicate within 1 min."""
    if not recipient_user_id or recipient_user_id == actor_user_id:
        return
    # Deduplicate: skip if same notif already exists in the last 60 seconds
    existing = conn.execute(
        """
        SELECT id FROM notifications
        WHERE recipient_user_id = ? AND actor_user_id = ? AND notif_type = ?
          AND post_id IS ? AND comment_id IS ? AND reaction_type IS ?
          AND created_at >= datetime('now', '-60 seconds')
        LIMIT 1
        """,
        (recipient_user_id, actor_user_id, notif_type, post_id, comment_id, reaction_type),
    ).fetchone()
    if existing:
        return
    conn.execute(
        """
        INSERT INTO notifications
          (recipient_user_id, actor_user_id, notif_type, post_id, comment_id, reaction_type, comment_content)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (recipient_user_id, actor_user_id, notif_type, post_id, comment_id, reaction_type, comment_content),
    )


# --- API: Reactions ---


@app.route("/api/reactions", methods=["GET"])
def get_reactions():
    target_type = (request.args.get("target_type") or "").strip()
    target_id_raw = request.args.get("target_id", "")
    token = (request.args.get("token") or "").strip()

    if target_type not in ALLOWED_TARGET_TYPES:
        return jsonify({"error": "target_type must be 'post' or 'comment'"}), 400

    try:
        target_id = int(target_id_raw)
    except (TypeError, ValueError):
        return jsonify({"error": "target_id must be an integer"}), 400

    conn = get_conn()
    try:
        counts, total = _reaction_counts(conn, target_type, target_id)
        user_reaction = None
        if token:
            row = conn.execute(
                """
                SELECT reaction_type FROM reactions
                WHERE target_type = ? AND target_id = ? AND user_token = ?
                LIMIT 1
                """,
                (target_type, target_id, token),
            ).fetchone()
            if row:
                user_reaction = row["reaction_type"]
        return jsonify({"counts": counts, "total": total, "user_reaction": user_reaction})
    finally:
        conn.close()


@app.route("/api/reactions", methods=["POST"])
def post_reaction():
    data = request.get_json(force=True, silent=True) or {}
    target_type = (data.get("target_type") or "").strip()
    target_id_raw = data.get("target_id")
    user_token = (data.get("user_token") or "").strip()
    reaction_type = (data.get("reaction_type") or "").strip()

    if target_type not in ALLOWED_TARGET_TYPES:
        return jsonify({"error": "target_type must be 'post' or 'comment'"}), 400
    if reaction_type not in ALLOWED_REACTION_TYPES:
        return jsonify({"error": f"reaction_type must be one of: {', '.join(sorted(ALLOWED_REACTION_TYPES))}"}), 400
    if not user_token:
        return jsonify({"error": "user_token is required"}), 400

    try:
        target_id = int(target_id_raw)
    except (TypeError, ValueError):
        return jsonify({"error": "target_id must be an integer"}), 400

    conn = get_conn()
    try:
        existing = conn.execute(
            """
            SELECT reaction_type FROM reactions
            WHERE target_type = ? AND target_id = ? AND user_token = ?
            LIMIT 1
            """,
            (target_type, target_id, user_token),
        ).fetchone()

        if existing is None:
            # No reaction yet — insert new
            conn.execute(
                """
                INSERT INTO reactions (target_type, target_id, user_token, reaction_type)
                VALUES (?, ?, ?, ?)
                """,
                (target_type, target_id, user_token, reaction_type),
            )
            # Notify the owner of the target
            actor_user_id = None
            try:
                actor_user_id = int(user_token.replace("user_", ""))
            except Exception:
                pass
            if target_type == "post":
                owner = conn.execute("SELECT user_id FROM posts WHERE id = ?", (target_id,)).fetchone()
                if owner and owner["user_id"] and actor_user_id:
                    _create_notification(conn, owner["user_id"], actor_user_id, "reaction",
                                          post_id=target_id, reaction_type=reaction_type)
            elif target_type == "comment":
                owner = conn.execute("SELECT user_id, post_id, content FROM comments WHERE id = ?", (target_id,)).fetchone()
                if owner and owner["user_id"] and actor_user_id:
                    _create_notification(conn, owner["user_id"], actor_user_id, "reaction",
                                          post_id=owner["post_id"], comment_id=target_id,
                                          reaction_type=reaction_type,
                                          comment_content=owner["content"])
        elif existing["reaction_type"] == reaction_type:
            # Same reaction — toggle off
            conn.execute(
                """
                DELETE FROM reactions
                WHERE target_type = ? AND target_id = ? AND user_token = ?
                """,
                (target_type, target_id, user_token),
            )
        else:
            # Different reaction — replace
            conn.execute(
                """
                DELETE FROM reactions
                WHERE target_type = ? AND target_id = ? AND user_token = ?
                """,
                (target_type, target_id, user_token),
            )
            conn.execute(
                """
                INSERT INTO reactions (target_type, target_id, user_token, reaction_type)
                VALUES (?, ?, ?, ?)
                """,
                (target_type, target_id, user_token, reaction_type),
            )

        conn.commit()

        counts, total = _reaction_counts(conn, target_type, target_id)
        user_reaction = None
        row = conn.execute(
            """
            SELECT reaction_type FROM reactions
            WHERE target_type = ? AND target_id = ? AND user_token = ?
            LIMIT 1
            """,
            (target_type, target_id, user_token),
        ).fetchone()
        if row:
            user_reaction = row["reaction_type"]

        return jsonify({"counts": counts, "total": total, "user_reaction": user_reaction})
    finally:
        conn.close()


@app.route("/api/posts/<int:post_id>/likes", methods=["GET"])
def get_like_state(post_id):
    token = (request.args.get("token") or "").strip()
    conn = get_conn()
    try:
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM likes WHERE post_id = ?", (post_id,)
        ).fetchone()["c"]
        liked = 0
        if token:
            liked = 1 if conn.execute(
                "SELECT 1 FROM likes WHERE post_id = ? AND user_token = ? LIMIT 1",
                (post_id, token),
            ).fetchone() else 0
        return jsonify({"count": total, "liked": bool(liked)})
    finally:
        conn.close()


@app.route("/api/posts/<int:post_id>/likes", methods=["POST"])
def toggle_like(post_id):
    data = request.get_json(force=True, silent=True) or {}
    token = (data.get("token") or "").strip()
    if not token:
        return jsonify({"error": "token required"}), 400
    conn = get_conn()
    try:
        if not conn.execute("SELECT id FROM posts WHERE id = ?", (post_id,)).fetchone():
            return jsonify({"error": "Post not found."}), 404
        existing = conn.execute(
            "SELECT id FROM likes WHERE post_id = ? AND user_token = ?",
            (post_id, token),
        ).fetchone()
        if existing:
            conn.execute(
                "DELETE FROM likes WHERE post_id = ? AND user_token = ?",
                (post_id, token),
            )
            liked = False
        else:
            conn.execute(
                "INSERT INTO likes (post_id, user_token) VALUES (?, ?)",
                (post_id, token),
            )
            liked = True
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM likes WHERE post_id = ?", (post_id,)
        ).fetchone()["c"]
        conn.commit()
        return jsonify({"count": count, "liked": liked})
    finally:
        conn.close()


# --- API: Submissions ---


@app.route("/api/submissions", methods=["GET"])
def list_submissions():
    ids_param = request.args.get("ids", "").strip()
    user_id_param = request.args.get("user_id", "").strip()
    # Public feed: return all submissions when no ids/user_id given
    if not ids_param and not user_id_param:
        conn = get_conn()
        try:
            rows = conn.execute(
                """
                SELECT id, author_name, author_bio, title, category,
                  status, created_at, updated_at
                FROM submissions
                ORDER BY created_at DESC
                LIMIT 50
                """
            ).fetchall()
            return jsonify([json_row(r) for r in rows])
        finally:
            conn.close()
    # Filter by user_id (owner's submissions only)
    if user_id_param and not ids_param:
        try:
            uid = int(user_id_param)
        except (TypeError, ValueError):
            return jsonify([])
        conn = get_conn()
        try:
            rows = conn.execute(
                """
                SELECT id, author_name, author_bio, title, category,
                  content, status, created_at, updated_at, document_url, document_name
                FROM submissions WHERE user_id = ?
                ORDER BY created_at DESC
                """,
                (uid,),
            ).fetchall()
            return jsonify([json_row(r) for r in rows])
        finally:
            conn.close()
    ids = [int(x) for x in ids_param.split(",") if x.strip().isdigit()]
    if not ids:
        return jsonify([])
    conn = get_conn()
    try:
        placeholders = ",".join(["?"] * len(ids))
        rows = conn.execute(
            f"""
            SELECT id, author_name, author_bio, title, category,
              content, status, created_at, updated_at, document_url, document_name
            FROM submissions WHERE id IN ({placeholders})
            ORDER BY created_at DESC
            """,
            ids,
        ).fetchall()
        return jsonify([json_row(r) for r in rows])
    finally:
        conn.close()


@app.route("/api/submissions/<int:submission_id>", methods=["PUT"])
def update_submission(submission_id):
    # Accept both JSON and multipart form data
    if request.content_type and 'multipart' in request.content_type:
        data = request.form
        title = (data.get("title") or "").strip()
        author_name = (data.get("author_name") or "").strip()
        category = (data.get("category") or "").strip() or "Campus Life"
        content = (data.get("content") or "").strip()
        author_bio = (data.get("author_bio") or "").strip() or None
        requesting_user_id = data.get("user_id")
    else:
        data = request.get_json(force=True, silent=True) or {}
        title = (data.get("title") or "").strip()
        author_name = (data.get("author_name") or "").strip()
        category = (data.get("category") or "").strip() or "Campus Life"
        content = (data.get("content") or "").strip()
        author_bio = (data.get("author_bio") or "").strip() or None
        requesting_user_id = data.get("user_id")

    if not title or not author_name:
        return jsonify({"error": "Title and author name are required."}), 400

    # Handle optional document upload
    document_url = None
    document_name = None
    doc_file = request.files.get("document")
    if doc_file and doc_file.filename:
        ext = doc_file.filename.rsplit(".", 1)[-1].lower() if "." in doc_file.filename else ""
        if ext not in ALLOWED_DOC_EXTENSIONS:
            return jsonify({"error": "Allowed document types: pdf, doc, docx, odt, txt."}), 400
        doc_file.seek(0, 2)
        size = doc_file.tell()
        doc_file.seek(0)
        if size > 20 * 1024 * 1024:
            return jsonify({"error": "Document must be under 20 MB."}), 400
        safe_name = secure_filename(doc_file.filename)
        stored_name = uuid.uuid4().hex + "." + ext
        os.makedirs(SUBMISSION_UPLOAD_DIR, exist_ok=True)
        doc_file.save(os.path.join(SUBMISSION_UPLOAD_DIR, stored_name))
        document_url = "/static/uploads/submissions/" + stored_name
        document_name = safe_name

    conn = get_conn()
    try:
        row = conn.execute("SELECT id, status, user_id, document_url FROM submissions WHERE id = ?", (submission_id,)).fetchone()
        if not row:
            return jsonify({"error": "Submission not found."}), 404
        if row["status"] != "Pending Review":
            return jsonify({"error": "Only pending submissions can be edited."}), 403
        # Ownership check: if submission has a user_id, only that user can edit
        if row["user_id"] is not None and requesting_user_id is not None:
            try:
                if int(requesting_user_id) != row["user_id"]:
                    return jsonify({"error": "You can only edit your own submissions."}), 403
            except (TypeError, ValueError):
                return jsonify({"error": "Invalid user_id."}), 400
        
        # If a new document is uploaded, delete the old one
        old_document_url = row["document_url"]
        if document_url and old_document_url:
            try:
                old_path = os.path.join(app.root_path, old_document_url.lstrip("/"))
                if os.path.exists(old_path):
                    os.remove(old_path)
            except OSError:
                pass
        
        # Update submission with new document info if provided
        if document_url:
            conn.execute(
                """
                UPDATE submissions
                SET title = ?, author_name = ?, author_bio = ?, category = ?,
                    content = ?, document_url = ?, document_name = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (title, author_name, author_bio, category, content, document_url, document_name, submission_id),
            )
        else:
            conn.execute(
                """
                UPDATE submissions
                SET title = ?, author_name = ?, author_bio = ?, category = ?,
                    content = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (title, author_name, author_bio, category, content, submission_id),
            )
        conn.commit()
        updated = conn.execute(
            """
            SELECT id, author_name, author_bio, title, category,
              content, status, created_at, updated_at, document_url, document_name
            FROM submissions WHERE id = ?
            """,
            (submission_id,),
        ).fetchone()
        return jsonify(json_row(updated))
    finally:
        conn.close()


@app.route("/api/users/<int:user_id>/public-profile", methods=["GET"])
def get_public_profile(user_id):
    category = (request.args.get("category") or "").strip()
    sort = request.args.get("sort", "latest")

    # Build order clause
    order = "p.created_at DESC"
    if sort == "likes":
        order = "like_count DESC, p.created_at DESC"
    elif sort == "comments":
        order = "comment_count DESC, p.created_at DESC"

    conn = get_conn()
    try:
        user = conn.execute(
            """
            SELECT id, display_name, photo_url, created_at
            FROM users WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
        if not user:
            return jsonify({"error": "User not found."}), 404

        # Build WHERE clause for posts
        where_clauses = ["p.user_id = ?", "(p.is_anonymous = 0 OR p.is_anonymous IS NULL)"]
        params = [user_id]
        
        if category and category != "All":
            where_clauses.append("p.category = ?")
            params.append(category)
        
        where = "WHERE " + " AND ".join(where_clauses)

        posts = conn.execute(
            f"""
            SELECT p.id, p.user_id, p.content, p.category, p.created_at,
              p.updated_at, p.image_url,
              COALESCE(u.display_name, 'Anonymous') AS author_name,
              u.photo_url AS author_photo,
              (SELECT COUNT(*) FROM reactions r WHERE r.target_type='post' AND r.target_id = p.id) AS like_count,
              (SELECT COUNT(*) FROM comments cm WHERE cm.post_id = p.id) AS comment_count
            FROM posts p
            LEFT JOIN users u ON u.id = p.user_id
            {where}
            ORDER BY {order}
            """,
            params,
        ).fetchall()
        return jsonify(
            {"user": json_row(user), "posts": [json_row(post) for post in posts]}
        )
    finally:
        conn.close()


@app.route("/api/submissions", methods=["POST"])
def create_submission():
    # Accept both JSON and multipart form
    if request.content_type and 'multipart' in request.content_type:
        data = request.form
        title = (data.get("title") or "").strip()
        author_name = (data.get("author_name") or "").strip()
        category = (data.get("category") or "").strip() or "Campus Life"
        content = (data.get("content") or "").strip()
        author_bio = (data.get("author_bio") or "").strip() or None
    else:
        data = request.get_json(force=True, silent=True) or {}
        title = (data.get("title") or "").strip()
        author_name = (data.get("author_name") or "").strip()
        category = (data.get("category") or "").strip() or "Campus Life"
        content = (data.get("content") or "").strip()
        author_bio = (data.get("author_bio") or "").strip() or None

    if not title or not author_name:
        return jsonify({"error": "Title and author name are required."}), 400
    if not content and not request.files.get("document"):
        return jsonify({"error": "Please provide content or upload a document."}), 400

    # Handle optional document upload
    document_url = None
    document_name = None
    doc_file = request.files.get("document")
    if doc_file and doc_file.filename:
        ext = doc_file.filename.rsplit(".", 1)[-1].lower() if "." in doc_file.filename else ""
        if ext not in ALLOWED_DOC_EXTENSIONS:
            return jsonify({"error": "Allowed document types: pdf, doc, docx, odt, txt."}), 400
        doc_file.seek(0, 2)
        size = doc_file.tell()
        doc_file.seek(0)
        if size > 20 * 1024 * 1024:
            return jsonify({"error": "Document must be under 20 MB."}), 400
        safe_name = secure_filename(doc_file.filename)
        stored_name = uuid.uuid4().hex + "." + ext
        os.makedirs(SUBMISSION_UPLOAD_DIR, exist_ok=True)
        doc_file.save(os.path.join(SUBMISSION_UPLOAD_DIR, stored_name))
        document_url = "/static/uploads/submissions/" + stored_name
        document_name = safe_name

    conn = get_conn()
    try:
        cur = conn.execute(
            """
            INSERT INTO submissions
              (author_name, author_bio, title, category, content, document_url, document_name, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (author_name, author_bio, title, category, content or "", document_url, document_name,
             data.get("user_id") or request.form.get("user_id") or None),
        )
        sid = cur.lastrowid
        conn.commit()
        row = conn.execute(
            """
            SELECT id, author_name, author_bio, title, category, content,
              status, created_at, document_url, document_name
            FROM submissions WHERE id = ?
            """,
            (sid,),
        ).fetchone()
        return jsonify(json_row(row)), 201
    finally:
        conn.close()


# --- API: Notifications ---

@app.route("/api/notifications", methods=["GET"])
def get_notifications():
    user_id_raw = request.args.get("user_id", "")
    try:
        user_id = int(user_id_raw)
    except (TypeError, ValueError):
        return jsonify({"error": "user_id required"}), 400

    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT n.id, n.notif_type, n.post_id, n.comment_id, n.reaction_type,
                   n.is_read, n.created_at, n.comment_content,
                   u.display_name AS actor_name, u.photo_url AS actor_photo,
                   p.content AS post_snippet
            FROM notifications n
            LEFT JOIN users u ON u.id = n.actor_user_id
            LEFT JOIN posts p ON p.id = n.post_id
            WHERE n.recipient_user_id = ?
            ORDER BY n.created_at DESC
            LIMIT 30
            """,
            (user_id,),
        ).fetchall()
        unread = conn.execute(
            "SELECT COUNT(*) AS c FROM notifications WHERE recipient_user_id = ? AND is_read = 0",
            (user_id,),
        ).fetchone()["c"]
        return jsonify({"notifications": [json_row(r) for r in rows], "unread": unread})
    finally:
        conn.close()


@app.route("/api/notifications/read", methods=["POST"])
def mark_notifications_read():
    data = request.get_json(force=True, silent=True) or {}
    user_id_raw = data.get("user_id")
    notif_id = data.get("notif_id")  # optional: mark single; if absent mark all
    try:
        user_id = int(user_id_raw)
    except (TypeError, ValueError):
        return jsonify({"error": "user_id required"}), 400

    conn = get_conn()
    try:
        if notif_id:
            conn.execute(
                "UPDATE notifications SET is_read = 1 WHERE id = ? AND recipient_user_id = ?",
                (notif_id, user_id),
            )
        else:
            conn.execute(
                "UPDATE notifications SET is_read = 1 WHERE recipient_user_id = ?",
                (user_id,),
            )
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


# --- API: Reports ---

ALLOWED_REPORT_REASONS = {
    "spam", "harassment", "inappropriate", "bullying", "other"
}
ALLOWED_REPORT_TARGETS = {"post", "comment"}


@app.route("/api/reports/check", methods=["GET"])
def check_report():
    reporter_user_id = request.args.get("reporter_user_id")
    target_type = (request.args.get("target_type") or "").strip()
    target_id_raw = request.args.get("target_id", "")
    try:
        reporter_user_id = int(reporter_user_id)
        target_id = int(target_id_raw)
    except (TypeError, ValueError):
        return jsonify({"reported": False})
    if target_type not in ALLOWED_REPORT_TARGETS:
        return jsonify({"reported": False})
    conn = get_conn()
    try:
        existing = conn.execute(
            "SELECT id FROM reports WHERE reporter_user_id = ? AND target_type = ? AND target_id = ?",
            (reporter_user_id, target_type, target_id),
        ).fetchone()
        return jsonify({"reported": existing is not None})
    finally:
        conn.close()


@app.route("/api/reports", methods=["POST"])
def create_report():
    data = request.get_json(force=True, silent=True) or {}
    reporter_user_id = data.get("reporter_user_id")
    target_type = (data.get("target_type") or "").strip()
    target_id_raw = data.get("target_id")
    reason = (data.get("reason") or "").strip()

    try:
        reporter_user_id = int(reporter_user_id)
    except (TypeError, ValueError):
        return jsonify({"error": "Valid reporter_user_id is required."}), 400
    if target_type not in ALLOWED_REPORT_TARGETS:
        return jsonify({"error": "target_type must be 'post' or 'comment'"}), 400
    if reason not in ALLOWED_REPORT_REASONS:
        return jsonify({"error": "Invalid reason."}), 400
    try:
        target_id = int(target_id_raw)
    except (TypeError, ValueError):
        return jsonify({"error": "target_id must be an integer"}), 400

    conn = get_conn()
    try:
        # Check if already reported
        existing = conn.execute(
            "SELECT id FROM reports WHERE reporter_user_id = ? AND target_type = ? AND target_id = ?",
            (reporter_user_id, target_type, target_id),
        ).fetchone()
        if existing:
            return jsonify({"error": "You have already reported this."}), 409
        conn.execute(
            "INSERT INTO reports (reporter_user_id, target_type, target_id, reason) VALUES (?, ?, ?, ?)",
            (reporter_user_id, target_type, target_id, reason),
        )
        conn.commit()
        return jsonify({"ok": True}), 201
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Admin Panel
# ---------------------------------------------------------------------------

ADMIN_ROLES = {"main_admin", "co_admin"}
MAIN_ADMIN_ROLE = "main_admin"


def get_requesting_user(user_id_raw):
    """Return (user_row, None) on success or (None, error_response_tuple) on failure."""
    try:
        user_id = int(user_id_raw)
    except (TypeError, ValueError):
        return None, (jsonify({"error": "Valid user_id is required."}), 400)
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id, role FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None, (jsonify({"error": "User not found."}), 404)
    return row, None


@app.route("/admin")
def admin_page():
    return render_template("admin.html")


# --- Submissions admin endpoints ---

@app.route("/api/admin/submissions", methods=["GET"])
def admin_list_submissions():
    user_row, err = get_requesting_user(request.args.get("user_id"))
    if err:
        return err
    if user_row["role"] not in ADMIN_ROLES:
        return jsonify({"error": "Admin access required."}), 403
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT id, title, author_name, category, status, created_at, updated_at, content
            FROM submissions
            ORDER BY created_at DESC
            """
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            # Strip HTML tags for plain-text preview
            import re
            plain = re.sub(r'<[^>]+>', '', d.get("content") or '')
            plain = re.sub(r'\s+', ' ', plain).strip()
            d["content_preview"] = plain[:200]
            d["content_full"] = d.get("content") or ''
            del d["content"]
            result.append(d)
        return jsonify(result)
    finally:
        conn.close()


@app.route("/api/admin/submissions/<int:submission_id>/status", methods=["PATCH"])
def admin_update_submission_status(submission_id):
    data = request.get_json(force=True, silent=True) or {}
    user_row, err = get_requesting_user(data.get("user_id"))
    if err:
        return err
    if user_row["role"] not in ADMIN_ROLES:
        return jsonify({"error": "Admin access required."}), 403
    status = (data.get("status") or "").strip()
    valid_statuses = {"Pending Review", "Approved", "Rejected"}
    if status not in valid_statuses:
        return jsonify({"error": "Invalid status."}), 400
    conn = get_conn()
    try:
        existing = conn.execute(
            "SELECT id FROM submissions WHERE id = ?", (submission_id,)
        ).fetchone()
        if not existing:
            return jsonify({"error": "Not found."}), 404
        conn.execute(
            "UPDATE submissions SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (status, submission_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id, title, author_name, category, status, created_at, updated_at, content FROM submissions WHERE id = ?",
            (submission_id,),
        ).fetchone()
        d = dict(row)
        import re
        plain = re.sub(r'<[^>]+>', '', d.get("content") or '')
        plain = re.sub(r'\s+', ' ', plain).strip()
        d["content_preview"] = plain[:200]
        d["content_full"] = d.get("content") or ''
        del d["content"]
        return jsonify(d)
    finally:
        conn.close()


# --- Reports admin endpoints ---

@app.route("/api/admin/reports", methods=["GET"])
def admin_list_reports():
    user_row, err = get_requesting_user(request.args.get("user_id"))
    if err:
        return err
    if user_row["role"] not in ADMIN_ROLES:
        return jsonify({"error": "Admin access required."}), 403
    
    # Get filter parameter
    reason_filter = (request.args.get("reason") or "").strip()
    
    conn = get_conn()
    try:
        # Build WHERE clause for filtering
        where_clauses = []
        params = []
        
        if reason_filter and reason_filter != "all":
            where_clauses.append("r.reason = ?")
            params.append(reason_filter)
        
        where_clause = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        
        rows = conn.execute(
            f"""
            SELECT r.id, r.target_type, r.target_id, r.reason, r.created_at,
                   u.display_name AS reporter_name, u.user_id AS reporter_user_id
            FROM reports r
            LEFT JOIN users u ON u.id = r.reporter_user_id
            {where_clause}
            ORDER BY r.created_at DESC
            """,
            params
        ).fetchall()
        # Group by (target_type, target_id)
        groups = {}
        order = []
        for r in rows:
            key = (r["target_type"], r["target_id"])
            if key not in groups:
                groups[key] = {
                    "target_type": r["target_type"],
                    "target_id": r["target_id"],
                    "target_content_preview": None,
                    "target_deleted": False,
                    "reports": [],
                    "primary_reason": r["reason"],  # Store the most common reason
                    "report_count": 0,
                }
                order.append(key)
            groups[key]["reports"].append({
                "id": r["id"],
                "reporter_name": r["reporter_name"],
                "reporter_user_id": r["reporter_user_id"],
                "reason": r["reason"],
                "created_at": r["created_at"],
            })
            groups[key]["report_count"] = len(groups[key]["reports"])
        
        # Determine primary reason for each group (most frequent reason)
        for key, group in groups.items():
            reason_counts = {}
            for report in group["reports"]:
                reason = report["reason"]
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
            # Find the most common reason
            if reason_counts:
                group["primary_reason"] = max(reason_counts.keys(), key=lambda k: reason_counts[k])
        
        # Fetch content previews
        for key, group in groups.items():
            target_type, target_id = key
            if target_type == "post":
                content_row = conn.execute(
                    "SELECT content FROM posts WHERE id = ?", (target_id,)
                ).fetchone()
            else:
                content_row = conn.execute(
                    "SELECT content FROM comments WHERE id = ?", (target_id,)
                ).fetchone()
            if content_row:
                import re
                plain = re.sub(r'<[^>]+>', '', content_row["content"] or '')
                plain = re.sub(r'\s+', ' ', plain).strip()
                group["target_content_preview"] = plain[:200]
                group["target_deleted"] = False
            else:
                group["target_content_preview"] = None
                group["target_deleted"] = True
        
        # Sort by report count (most reported first)
        sorted_groups = sorted([groups[k] for k in order], key=lambda g: g["report_count"], reverse=True)
        
        return jsonify(sorted_groups)
    finally:
        conn.close()


@app.route("/api/admin/reports/<int:report_id>", methods=["DELETE"])
def admin_dismiss_report(report_id):
    data = request.get_json(force=True, silent=True) or {}
    user_row, err = get_requesting_user(data.get("user_id"))
    if err:
        return err
    if user_row["role"] not in ADMIN_ROLES:
        return jsonify({"error": "Admin access required."}), 403
    conn = get_conn()
    try:
        existing = conn.execute(
            "SELECT id FROM reports WHERE id = ?", (report_id,)
        ).fetchone()
        if not existing:
            return jsonify({"error": "Not found."}), 404
        conn.execute("DELETE FROM reports WHERE id = ?", (report_id,))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@app.route("/api/admin/content", methods=["DELETE"])
def admin_delete_content():
    data = request.get_json(force=True, silent=True) or {}
    user_row, err = get_requesting_user(data.get("user_id"))
    if err:
        return err
    if user_row["role"] not in ADMIN_ROLES:
        return jsonify({"error": "Admin access required."}), 403
    target_type = (data.get("target_type") or "").strip()
    target_id_raw = data.get("target_id")
    if target_type not in {"post", "comment"}:
        return jsonify({"error": "target_type must be 'post' or 'comment'"}), 400
    try:
        target_id = int(target_id_raw)
    except (TypeError, ValueError):
        return jsonify({"error": "target_id must be an integer"}), 400
    conn = get_conn()
    try:
        if target_type == "post":
            conn.execute("DELETE FROM posts WHERE id = ?", (target_id,))
        else:
            conn.execute("DELETE FROM comments WHERE id = ?", (target_id,))
        conn.execute(
            "DELETE FROM reports WHERE target_type = ? AND target_id = ?",
            (target_type, target_id),
        )
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@app.route("/api/admin/warnings", methods=["POST"])
def admin_issue_warning():
    data = request.get_json(force=True, silent=True) or {}
    user_row, err = get_requesting_user(data.get("user_id"))
    if err:
        return err
    if user_row["role"] not in ADMIN_ROLES:
        return jsonify({"error": "Admin access required."}), 403
    
    target_type = (data.get("target_type") or "").strip()
    target_id_raw = data.get("target_id")
    reason = (data.get("reason") or "").strip()
    message = (data.get("message") or "").strip()
    
    if target_type not in {"post", "comment"}:
        return jsonify({"error": "target_type must be 'post' or 'comment'"}), 400
    try:
        target_id = int(target_id_raw)
    except (TypeError, ValueError):
        return jsonify({"error": "target_id must be an integer"}), 400
    
    if not reason:
        return jsonify({"error": "Reason is required"}), 400
    
    conn = get_conn()
    try:
        # Get the owner of the content
        if target_type == "post":
            owner_row = conn.execute("SELECT user_id FROM posts WHERE id = ?", (target_id,)).fetchone()
        else:
            owner_row = conn.execute("SELECT user_id FROM comments WHERE id = ?", (target_id,)).fetchone()
        
        if not owner_row or not owner_row["user_id"]:
            return jsonify({"error": "Content owner not found"}), 404
        
        content_owner_id = owner_row["user_id"]
        
        # Issue the warning
        conn.execute(
            """
            INSERT INTO warnings (user_id, admin_id, target_type, target_id, reason, message)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (content_owner_id, user_row["id"], target_type, target_id, reason, message)
        )
        
        # Create a notification for the user
        _create_notification(conn, content_owner_id, user_row["id"], "warning", 
                           post_id=target_id if target_type == "post" else None,
                           comment_id=target_id if target_type == "comment" else None)
        
        # Dismiss all reports for this content
        conn.execute(
            "DELETE FROM reports WHERE target_type = ? AND target_id = ?",
            (target_type, target_id)
        )
        
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


# --- User management admin endpoints ---

@app.route("/api/admin/users", methods=["GET"])
def admin_list_users():
    user_row, err = get_requesting_user(request.args.get("user_id"))
    if err:
        return err
    if user_row["role"] != MAIN_ADMIN_ROLE:
        return jsonify({"error": "Main admin access required."}), 403
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, display_name, email, role, created_at, user_id FROM users ORDER BY created_at ASC"
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()


@app.route("/api/admin/users/<int:target_user_id>/role", methods=["PATCH"])
def admin_update_user_role(target_user_id):
    data = request.get_json(force=True, silent=True) or {}
    user_row, err = get_requesting_user(data.get("user_id"))
    if err:
        return err
    if user_row["role"] != MAIN_ADMIN_ROLE:
        return jsonify({"error": "Main admin access required."}), 403
    if user_row["id"] == target_user_id:
        return jsonify({"error": "Cannot change your own role."}), 400
    role = (data.get("role") or "").strip()
    if role not in {"co_admin", "user"}:
        return jsonify({"error": "Invalid role."}), 400
    conn = get_conn()
    try:
        target = conn.execute(
            "SELECT id, display_name, email, role, created_at, user_id FROM users WHERE id = ?",
            (target_user_id,),
        ).fetchone()
        if not target:
            return jsonify({"error": "Not found."}), 404
        conn.execute(
            "UPDATE users SET role = ? WHERE id = ?", (role, target_user_id)
        )
        conn.commit()
        updated = conn.execute(
            "SELECT id, display_name, email, role, created_at, user_id FROM users WHERE id = ?",
            (target_user_id,),
        ).fetchone()
        return jsonify(dict(updated))
    finally:
        conn.close()


@app.route("/api/admin/transfer-ownership", methods=["POST"])
def admin_transfer_ownership():
    data = request.get_json(force=True, silent=True) or {}
    user_row, err = get_requesting_user(data.get("user_id"))
    if err:
        return err
    if user_row["role"] != MAIN_ADMIN_ROLE:
        return jsonify({"error": "Main admin access required."}), 403
    target_user_id_raw = data.get("target_user_id")
    try:
        target_user_id = int(target_user_id_raw)
    except (TypeError, ValueError):
        return jsonify({"error": "Valid target_user_id is required."}), 400
    if target_user_id == user_row["id"]:
        return jsonify({"error": "Cannot transfer ownership to yourself."}), 400
    conn = get_conn()
    try:
        target = conn.execute(
            "SELECT id FROM users WHERE id = ?", (target_user_id,)
        ).fetchone()
        if not target:
            return jsonify({"error": "Not found."}), 404
        conn.execute("BEGIN")
        conn.execute(
            "UPDATE users SET role = 'user' WHERE id = ?", (user_row["id"],)
        )
        conn.execute(
            "UPDATE users SET role = 'main_admin' WHERE id = ?", (target_user_id,)
        )
        conn.execute("COMMIT")
        return jsonify({"ok": True, "new_main_admin_id": target_user_id})
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
