"""
===================================================================
  CONTENT PLATFORM  —  app.py  (v5.0)
  Automated Comment Moderation System for Local News Blogs
===================================================================
  NEW IN THIS VERSION
  • Naïve-Bayes multilingual comment classifier (replaces RF)
  • Adult/porn URL detection via keyword + domain pattern matching
  • Profanity filter covering 20+ languages
  • Member → Admin upgrade flow (password-verified, username must be "admin")
  • Article comment-review panel per article owner
  • Approved comments can be re-rejected by the article owner / admin
  • Photos & videos upload support
  • Forgot-password flow (token-based, no external email required for dev)
  • Change password + update profile + profile picture upload
  • Article categories: tech, travel, medicine, business, sport, lifestyle, general
  • External-platform webhook integration stubs (Disqus, WordPress, etc.)
  • Welcome message on login with user's surname
  • Rejected comment counter (stored but not shown publicly)
  • Rate limiting on comment submission (max 5 per minute per user)
===================================================================
"""

from flask import Flask, request, jsonify, session, url_for, send_from_directory
from flask_cors import CORS
import sqlite3, hashlib, re, os, json, math
from datetime import datetime, timedelta
from functools import wraps
import warnings, uuid, secrets, string, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from werkzeug.utils import secure_filename
from urllib.parse import urlparse
from collections import defaultdict
import time

warnings.filterwarnings('ignore')

# ── optional heavy deps – degrade gracefully ──────────────────────
try:
    from langdetect import detect, DetectorFactory
    DetectorFactory.seed = 0
    LANGDETECT_OK = True
except ImportError:
    LANGDETECT_OK = False

try:
    import requests as req_lib
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False

try:
    from bs4 import BeautifulSoup
    BS4_OK = True
except ImportError:
    BS4_OK = False

try:
    import bleach, markdown
    MARKDOWN_OK = True
except ImportError:
    MARKDOWN_OK = False

try:
    from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
    ITSDANGEROUS_OK = True
except ImportError:
    ITSDANGEROUS_OK = False

# ══════════════════════════════════════════════════════════════════
#  FLASK APP SETUP
# ══════════════════════════════════════════════════════════════════
app = Flask(__name__)
app.secret_key           = 'cp-secret-change-me-in-production-2024'
app.config.update(
    SECRET_KEY                = 'cp-secret-change-me-in-production-2024',
    SECURITY_PASSWORD_SALT    = 'cp-salt-2024',
    SESSION_COOKIE_SAMESITE   = 'Lax',
    SESSION_COOKIE_SECURE     = False,
    SESSION_COOKIE_HTTPONLY   = True,
    SESSION_COOKIE_PATH       = '/',
    UPLOAD_FOLDER             = 'uploads',
    MAX_CONTENT_LENGTH        = 64 * 1024 * 1024,   # 64 MB
    ALLOWED_IMAGE_EXT         = {'png','jpg','jpeg','gif','webp'},
    ALLOWED_VIDEO_EXT         = {'mp4','webm','mov','avi'},
    MAIL_SERVER               = 'smtp.gmail.com',
    MAIL_PORT                 = 587,
    MAIL_USERNAME             = 'your-email@gmail.com',
    MAIL_PASSWORD             = 'your-app-password',
    MAIL_DEFAULT_SENDER       = 'your-email@gmail.com',
)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('uploads/profiles', exist_ok=True)
os.makedirs('uploads/media',    exist_ok=True)

CORS(app, supports_credentials=True,
     resources={r"/api/*": {"origins": [
         "http://127.0.0.1:5000","http://localhost:5000",
         "http://127.0.0.1:8080","http://localhost:8080"
     ]}})

@app.after_request
def after_request(response):
    origin  = request.headers.get('Origin','')
    allowed = ['http://127.0.0.1:5000','http://localhost:5000',
               'http://127.0.0.1:8080','http://localhost:8080']
    if origin in allowed:
        response.headers['Access-Control-Allow-Origin']      = origin
        response.headers['Access-Control-Allow-Headers']     = 'Content-Type,Authorization,X-Requested-With'
        response.headers['Access-Control-Allow-Methods']     = 'GET,PUT,POST,DELETE,PATCH,OPTIONS'
        response.headers['Access-Control-Allow-Credentials'] = 'true'
    return response

@app.route('/api/<path:p>', methods=['OPTIONS'])
def options_handler(p): return '', 200

# ══════════════════════════════════════════════════════════════════
#  RATE LIMITER  (in-memory, per user_id)
# ══════════════════════════════════════════════════════════════════
_rate_store: dict = defaultdict(list)

def rate_limit(user_id: int, max_calls: int = 5, window: int = 60) -> bool:
    """Returns True if allowed, False if rate-limited."""
    now   = time.time()
    calls = [t for t in _rate_store[user_id] if now - t < window]
    if len(calls) >= max_calls:
        return False
    calls.append(now)
    _rate_store[user_id] = calls
    return True

# ══════════════════════════════════════════════════════════════════
#  NAÏVE-BAYES MULTILINGUAL COMMENT MODERATOR
# ══════════════════════════════════════════════════════════════════
class NaiveBayesModerator:
    """
    Multinomial Naïve-Bayes classifier that works across languages.
    Trained on a hard-coded seed corpus; updates with every human decision.
    Handles:  adult content · profanity · spam · malicious links
    """

    # ── adult / porn domain patterns ──────────────────────────────
    ADULT_DOMAINS = re.compile(
        r'(porn|xxx|sex|adult|nude|naked|hentai|onlyfans|escort|erotic|'
        r'milf|fetish|camgirl|livejasmin|chaturbate|xvideos|xhamster|'
        r'redtube|youporn|pornhub|brazzers|bangbros|spankbang|'
        r'tube8|xtube|slutload|4tube|beeg|drtuber|nuvid)',
        re.IGNORECASE
    )

    # ── profanity across 20+ languages ────────────────────────────
    PROFANITY = re.compile(
        r'\b('
        # English
        r'fuck|shit|ass|bitch|dick|cock|pussy|cunt|whore|slut|nigger|faggot|bastard|'
        r'motherfucker|asshole|bullshit|damn|hell|piss|crap|'
        # Swahili
        r'malaya|mkundu|shenzi|mjinga|mwizi|kahaba|'
        # Spanish
        r'puta|mierda|coño|joder|hostia|cabron|pendejo|chingada|'
        # French
        r'merde|putain|connard|salope|bordel|foutre|'
        # German
        r'scheiße|arsch|ficken|hurensohn|wichser|'
        # Arabic (transliterated)
        r'kuss|ibn el sharmouta|sharmuta|kalb|'
        # Portuguese
        r'porra|caralho|merda|puta|foda|'
        # Hindi (transliterated)
        r'chutiya|madarchod|bhenchod|gaand|randi|'
        # Italian
        r'cazzo|vaffanculo|stronzo|puttana|'
        # Russian (transliterated)
        r'blyad|pizda|khuy|ebat|'
        # Dutch
        r'klootzak|godverdomme|kut|'
        # Common leet-speak variants
        r'f+u+c+k+|s+h+i+t+|a+s+s+h+o+l+e+'
        r')\b',
        re.IGNORECASE | re.UNICODE
    )

    # ── spam signals ──────────────────────────────────────────────
    SPAM_SIGNALS = re.compile(
        r'(buy now|click here|free money|make money fast|earn \$|'
        r'lose weight|diet pills|cheap meds|online pharmacy|'
        r'casino|jackpot|bitcoin investment|crypto profit|'
        r'call now|limited offer|act now|'
        r'whatsapp me|telegram me|dm me for|'
        r'follow me|subscribe|check my|visit my|'
        r'\.xyz|\.tk|\.ml|\.ga|\.cf)\b',
        re.IGNORECASE
    )

    URL_RE = re.compile(r'https?://[^\s]+', re.IGNORECASE)

    def __init__(self):
        # word-count tables: {class: {word: count}}
        self.word_counts   = {'ham': defaultdict(int), 'spam': defaultdict(int)}
        self.class_counts  = {'ham': 0, 'spam': 0}
        self.vocab         = set()
        self._seed()

    # ── seed corpus ───────────────────────────────────────────────
    def _seed(self):
        ham_samples = [
            "Great article, very informative!",
            "Thanks for sharing this news.",
            "I really enjoyed reading this.",
            "This is very helpful information.",
            "Habari njema sana, asante!",           # Swahili: Very good news, thank you!
            "Très bon article, merci beaucoup.",     # French
            "Sehr guter Beitrag, danke!",            # German
            "Muy buen artículo, gracias.",           # Spanish
            "بارك الله فيك على هذا المقال",          # Arabic
            "훌륭한 기사입니다 감사합니다",              # Korean
            "素晴らしい記事をありがとうございます",       # Japanese
            "मुझे यह लेख बहुत पसंद आया",             # Hindi
            "Questo articolo è eccellente.",         # Italian
            "Excelente artigo, muito obrigado.",     # Portuguese
            "This is accurate local news.",
            "I agree with the points raised here.",
            "Could you cover more stories like this?",
            "The community needs to hear this.",
            "Well written and factual.",
            "Please report more on this topic.",
        ]
        spam_samples = [
            "Buy cheap meds at http://pharmacy-online.xyz",
            "Click here to win a prize http://scam.tk",
            "Check out hot girls at pornhub.com free",
            "Make $5000 weekly from home, DM me now",
            "Visit my OnlyFans for exclusive content",
            "Free bitcoin investment program click now",
            "Casino jackpot win real money now!!!",
            "Hot naked girls at xxx-site.com visit now",
            "Adult content available at free-porn.net",
            "Sex videos download free click here",
            "You are an idiot and this is stupid",
            "Fuck this article go to hell",
            "This journalist is a bitch and a liar",
            "Malaya huyu mwandishi wa habari",          # Swahili profanity
            "Puta madre este artículo es una mierda",   # Spanish profanity
            "Va te faire foutre avec ton article",      # French profanity
            "Cheap pills https://online-pharma.ml",
            "Earn fast money whatsapp me +1234567890",
            "Subscribe to my channel for free money",
            "Follow me on telegram for crypto profits",
        ]
        for s in ham_samples:  self._train_one(s, 'ham')
        for s in spam_samples: self._train_one(s, 'spam')

    def _tokenize(self, text: str) -> list:
        text = text.lower()
        text = re.sub(r'[^\w\s]', ' ', text)
        return [w for w in text.split() if len(w) > 1]

    def _train_one(self, text: str, label: str):
        for w in self._tokenize(text):
            self.word_counts[label][w] += 1
            self.vocab.add(w)
        self.class_counts[label] += 1

    def train(self, text: str, label: str):
        """Public: called after human moderation decisions."""
        self._train_one(text, label)

    def _log_prob(self, tokens: list, label: str) -> float:
        total   = sum(self.word_counts[label].values()) + len(self.vocab)
        log_p   = math.log((self.class_counts[label] + 1) /
                            (sum(self.class_counts.values()) + 2))
        for w in tokens:
            count = self.word_counts[label].get(w, 0) + 1   # Laplace
            log_p += math.log(count / total)
        return log_p

    def classify(self, text: str) -> dict:
        """
        Returns a dict with:
          status  : 'auto_approved' | 'auto_rejected' | 'under_review'
          reason  : human-readable explanation
          scores  : {spam_score, profanity_score, adult_score, nb_spam_prob}
          language: detected language code
        """
        reasons = []
        scores  = {'spam_score': 0.0, 'profanity_score': 0.0,
                   'adult_score': 0.0, 'nb_spam_prob': 0.0}

        # 1. Language detection
        lang = 'unknown'
        if LANGDETECT_OK:
            try:    lang = detect(text)
            except: lang = 'unknown'

        # 2. Hard rules — adult content
        adult_matches = self.ADULT_DOMAINS.findall(text)
        if adult_matches:
            scores['adult_score'] = 1.0
            reasons.append(f"Adult/porn content detected: {', '.join(set(adult_matches))}")

        # 3. Hard rules — profanity
        prof_matches = self.PROFANITY.findall(text)
        if prof_matches:
            scores['profanity_score'] = min(1.0, len(prof_matches) * 0.4)
            reasons.append(f"Profanity detected ({len(prof_matches)} instance(s))")

        # 4. Hard rules — spam signals
        spam_matches = self.SPAM_SIGNALS.findall(text)
        if spam_matches:
            scores['spam_score'] = min(1.0, len(spam_matches) * 0.5)
            reasons.append(f"Spam signals detected")

        # 5. URL analysis
        urls = self.URL_RE.findall(text)
        for url in urls:
            domain = urlparse(url).netloc.lower().replace('www.', '')
            if self.ADULT_DOMAINS.search(domain):
                scores['adult_score'] = 1.0
                reasons.append(f"Adult URL blocked: {domain}")
            # Check blocked domains in DB
            try:
                cur = db_connection.cursor()
                cur.execute("SELECT threat_level FROM blocked_domains WHERE ? LIKE '%'||domain||'%'", (domain,))
                row = cur.fetchone()
                if row:
                    scores['spam_score'] = max(scores['spam_score'], 0.9)
                    reasons.append(f"Blocked domain: {domain} (threat: {row[0]})")
            except: pass

        # 6. Naïve-Bayes classification
        tokens = self._tokenize(text)
        if tokens and (self.class_counts['ham'] > 0 and self.class_counts['spam'] > 0):
            lp_ham  = self._log_prob(tokens, 'ham')
            lp_spam = self._log_prob(tokens, 'spam')
            # Convert to probability via softmax
            max_lp   = max(lp_ham, lp_spam)
            p_ham    = math.exp(lp_ham - max_lp)
            p_spam   = math.exp(lp_spam - max_lp)
            nb_spam  = p_spam / (p_ham + p_spam)
            scores['nb_spam_prob'] = round(nb_spam, 4)
            if nb_spam > 0.75:
                reasons.append(f"NB classifier: {nb_spam:.0%} spam probability")

        # 7. Final decision
        hard_reject = (
            scores['adult_score']     >= 0.8 or
            scores['profanity_score'] >= 0.6 or
            scores['spam_score']      >= 0.7 or
            scores['nb_spam_prob']    >= 0.75
        )
        soft_review = (
            scores['profanity_score'] >= 0.3 or
            scores['spam_score']      >= 0.4 or
            scores['nb_spam_prob']    >= 0.45 or
            len(urls) >= 3
        )

        if hard_reject:
            status = 'auto_rejected'
        elif soft_review:
            status = 'under_review'
        else:
            status = 'auto_approved'

        reason_str = ' | '.join(reasons) if reasons else 'Clean content'

        return {
            'status':   status,
            'reason':   reason_str,
            'scores':   scores,
            'language': lang,
        }

# Singleton moderator
moderator = NaiveBayesModerator()

# ══════════════════════════════════════════════════════════════════
#  DATABASE
# ══════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════
#  CORE HELPERS  (must be defined before init_db)
# ══════════════════════════════════════════════════════════════════
def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def _verify(pw: str, h: str) -> bool:
    return _hash(pw) == h

def init_db():
    conn = sqlite3.connect('platform.db', check_same_thread=False)
    conn.row_factory   = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    cur  = conn.cursor()

    # users
    cur.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id       INTEGER PRIMARY KEY AUTOINCREMENT,
        username      TEXT UNIQUE NOT NULL,
        password      TEXT NOT NULL,
        email         TEXT UNIQUE NOT NULL,
        full_name     TEXT NOT NULL,
        surname       TEXT DEFAULT '',
        phone         TEXT,
        user_type     TEXT DEFAULT 'member',
        bio           TEXT DEFAULT '',
        avatar        TEXT DEFAULT '',
        website       TEXT DEFAULT '',
        created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_login    TIMESTAMP,
        is_active     INTEGER DEFAULT 1,
        is_verified   INTEGER DEFAULT 1,
        reset_token   TEXT,
        reset_expiry  TIMESTAMP,
        reputation    REAL DEFAULT 1.0,
        total_articles INTEGER DEFAULT 0,
        total_comments INTEGER DEFAULT 0,
        total_links    INTEGER DEFAULT 0
    )''')

    # articles (support text, photo, video)
    cur.execute('''CREATE TABLE IF NOT EXISTS articles (
        article_id    INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id       INTEGER NOT NULL,
        title         TEXT NOT NULL,
        content       TEXT DEFAULT '',
        content_html  TEXT DEFAULT '',
        summary       TEXT DEFAULT '',
        media_url     TEXT DEFAULT '',
        media_type    TEXT DEFAULT 'text',
        category      TEXT DEFAULT 'general',
        tags          TEXT DEFAULT '',
        reading_time  INTEGER DEFAULT 1,
        status        TEXT DEFAULT 'published',
        views         INTEGER DEFAULT 0,
        likes         INTEGER DEFAULT 0,
        created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at    TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(user_id)
    )''')

    # comments
    cur.execute('''CREATE TABLE IF NOT EXISTS comments (
        comment_id    INTEGER PRIMARY KEY AUTOINCREMENT,
        article_id    INTEGER NOT NULL,
        user_id       INTEGER NOT NULL,
        comment_text  TEXT NOT NULL,
        language      TEXT DEFAULT 'unknown',
        nb_spam_prob  REAL DEFAULT 0,
        adult_score   REAL DEFAULT 0,
        profanity_score REAL DEFAULT 0,
        spam_score    REAL DEFAULT 0,
        status        TEXT DEFAULT 'under_review',
        reason        TEXT DEFAULT '',
        ip_address    TEXT DEFAULT '',
        created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        reviewed_by   INTEGER,
        reviewed_at   TIMESTAMP,
        FOREIGN KEY(article_id) REFERENCES articles(article_id),
        FOREIGN KEY(user_id)    REFERENCES users(user_id)
    )''')

    # password reset tokens (dev: stored in DB, no email needed)
    cur.execute('''CREATE TABLE IF NOT EXISTS reset_tokens (
        token_id   INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER NOT NULL,
        token      TEXT UNIQUE NOT NULL,
        expires_at TIMESTAMP NOT NULL,
        used       INTEGER DEFAULT 0,
        FOREIGN KEY(user_id) REFERENCES users(user_id)
    )''')

    # blocked domains
    cur.execute('''CREATE TABLE IF NOT EXISTS blocked_domains (
        domain_id   INTEGER PRIMARY KEY AUTOINCREMENT,
        domain      TEXT UNIQUE NOT NULL,
        threat_level TEXT DEFAULT 'medium',
        reason      TEXT DEFAULT '',
        added_by    INTEGER,
        added_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # external platform integrations
    cur.execute('''CREATE TABLE IF NOT EXISTS integrations (
        integration_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id        INTEGER NOT NULL,
        platform       TEXT NOT NULL,
        webhook_url    TEXT NOT NULL,
        api_key        TEXT DEFAULT '',
        is_active      INTEGER DEFAULT 1,
        created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(user_id)
    )''')

    # notifications
    cur.execute('''CREATE TABLE IF NOT EXISTS notifications (
        notif_id   INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER NOT NULL,
        message    TEXT NOT NULL,
        type       TEXT DEFAULT 'info',
        is_read    INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(user_id)
    )''')

    # moderation log (every approve/reject action)
    cur.execute('''CREATE TABLE IF NOT EXISTS mod_log (
        log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
        comment_id  INTEGER NOT NULL,
        action      TEXT NOT NULL,
        actor_id    INTEGER NOT NULL,
        note        TEXT DEFAULT '',
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # seed admin
    cur.execute("SELECT user_id FROM users WHERE username='admin'")
    if not cur.fetchone():
        pw = _hash('admin123')
        cur.execute('''INSERT INTO users
            (username,password,email,full_name,surname,user_type,is_verified)
            VALUES('admin',?,?,?,?,'admin',1)''',
            (pw,'admin@platform.local','System Administrator','Administrator'))

    # seed blocked domains
    for dom, lvl, rsn in [
        ('spam.com','high','Known spam'),
        ('malicious.net','critical','Malware'),
        ('phishing.org','critical','Phishing'),
        ('scam.com','high','Scam'),
        ('pornhub.com','critical','Adult content'),
        ('xvideos.com','critical','Adult content'),
        ('xhamster.com','critical','Adult content'),
        ('onlyfans.com','high','Adult content'),
        ('chaturbate.com','critical','Adult content'),
        ('livejasmin.com','high','Adult content'),
        ('bit.ly','medium','URL shortener'),
        ('tinyurl.com','medium','URL shortener'),
    ]:
        cur.execute("INSERT OR IGNORE INTO blocked_domains(domain,threat_level,reason,added_by) VALUES(?,?,?,1)",
                    (dom, lvl, rsn))

    conn.commit()
    print("✅ DB ready  (platform.db)")
    return conn

db_connection = init_db()

# ══════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════
def _notify(user_id: int, message: str, ntype: str = 'info'):
    try:
        db_connection.execute(
            "INSERT INTO notifications(user_id,message,type) VALUES(?,?,?)",
            (user_id, message, ntype))
        db_connection.commit()
    except: pass

def _allowed_image(fn): return fn.rsplit('.',1)[-1].lower() in app.config['ALLOWED_IMAGE_EXT']
def _allowed_video(fn): return fn.rsplit('.',1)[-1].lower() in app.config['ALLOWED_VIDEO_EXT']

def _send_email(to, subject, html_body):
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From']    = app.config['MAIL_DEFAULT_SENDER']
        msg['To']      = to
        msg.attach(MIMEText(html_body, 'html'))
        with smtplib.SMTP(app.config['MAIL_SERVER'], app.config['MAIL_PORT']) as s:
            s.starttls()
            s.login(app.config['MAIL_USERNAME'], app.config['MAIL_PASSWORD'])
            s.send_message(msg)
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False

# ── auth decorators ───────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if 'user_id' not in session:
            return jsonify(success=False, message="Login required"), 401
        return f(*a, **kw)
    return dec

def admin_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if 'user_id' not in session:
            return jsonify(success=False, message="Login required"), 401
        if session.get('user_type') != 'admin':
            return jsonify(success=False, message="Admin access required"), 403
        return f(*a, **kw)
    return dec

# ══════════════════════════════════════════════════════════════════
#  FRONTEND ROUTE
# ══════════════════════════════════════════════════════════════════
@app.route('/')
def root():
    return '<h1>Content Platform API v5</h1><p><a href="/frontend">Open App →</a></p>'

@app.route('/frontend')
def frontend():
    return send_from_directory('.', 'index.html')

@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ══════════════════════════════════════════════════════════════════
#  AUTH ROUTES
# ══════════════════════════════════════════════════════════════════
@app.route('/api/register', methods=['POST'])
def register():
    d = request.get_json() or {}
    required = ['username','password','email','full_name']
    if not all(k in d for k in required):
        return jsonify(success=False, message="Missing required fields")
    if len(d['password']) < 6:
        return jsonify(success=False, message="Password must be at least 6 characters")
    if not re.match(r"[^@]+@[^@]+\.[^@]+", d['email']):
        return jsonify(success=False, message="Invalid email format")

    # extract surname from full_name
    parts   = d['full_name'].strip().split()
    surname = parts[-1] if len(parts) > 1 else parts[0]

    cur = db_connection.cursor()
    cur.execute("SELECT 1 FROM users WHERE username=? OR email=?", (d['username'], d['email']))
    if cur.fetchone():
        return jsonify(success=False, message="Username or email already exists")
    try:
        cur.execute('''INSERT INTO users(username,password,email,full_name,surname,phone)
                       VALUES(?,?,?,?,?,?)''',
            (d['username'], _hash(d['password']), d['email'],
             d['full_name'], surname, d.get('phone','')))
        uid = cur.lastrowid
        db_connection.commit()
        _notify(uid, f"Welcome to the platform, {d['full_name']}! 🎉")
        return jsonify(success=True, message="Account created successfully! You can now sign in.")
    except Exception as e:
        db_connection.rollback()
        return jsonify(success=False, message=f"Error: {str(e)}")

@app.route('/api/login', methods=['POST'])
def login():
    d = request.get_json() or {}
    if not d.get('username') or not d.get('password'):
        return jsonify(success=False, message="Username and password required")
    try:
        cur = db_connection.cursor()
        cur.execute('''SELECT user_id,username,password,full_name,surname,user_type,
                              avatar,is_active,total_articles,total_comments,reputation
                       FROM users WHERE username=?''', (d['username'],))
        u = cur.fetchone()
        if not u or not _verify(d['password'], u['password']):
            return jsonify(success=False, message="Invalid username or password")
        if not u['is_active']:
            return jsonify(success=False, message="Account suspended")

        db_connection.execute("UPDATE users SET last_login=? WHERE user_id=?",
                              (datetime.now(), u['user_id']))
        db_connection.commit()

        session['user_id']   = u['user_id']
        session['username']  = u['username']
        session['user_type'] = u['user_type']
        session['full_name'] = u['full_name']

        raw_surname = u['surname'] if u['surname'] else u['full_name'].split()[-1]
        disp_name   = f"Admin({raw_surname})" if u['user_type'] == 'admin' else u['full_name']
        welcome     = f"Welcome back, {disp_name}!"

        try:
            cur.execute(
                "SELECT notif_id,message,type,created_at FROM notifications "
                "WHERE user_id=? AND is_read=0 ORDER BY created_at DESC LIMIT 10",
                (u['user_id'],))
            notifs = [dict(r) for r in cur.fetchall()]
        except Exception:
            notifs = []

        return jsonify(success=True, welcome=welcome, user={
            'user_id':        u['user_id'],
            'username':       u['username'],
            'full_name':      u['full_name'],
            'display_name':   disp_name,
            'user_type':      u['user_type'],
            'avatar':         u['avatar'] or '',
            'total_articles': u['total_articles'] or 0,
            'total_comments': u['total_comments'] or 0,
            'reputation':     u['reputation'] or 1.0,
        }, notifications=notifs)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify(success=False, message=f"Login error: {str(e)}")

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify(success=True, message="Signed out")

@app.route('/api/session', methods=['GET'])
def check_session():
    if 'user_id' not in session:
        return jsonify(success=True, authenticated=False)
    cur = db_connection.cursor()
    cur.execute("SELECT username,full_name,surname,user_type,avatar FROM users WHERE user_id=?",
                (session['user_id'],))
    u = cur.fetchone()
    if not u:
        session.clear()
        return jsonify(success=True, authenticated=False)
    surname   = u['surname'] or u['full_name'].split()[-1]
    disp_name = f"Admin({surname})" if u['user_type'] == 'admin' else u['full_name']
    return jsonify(success=True, authenticated=True, user={
        'user_id':      session['user_id'],
        'username':     u['username'],
        'full_name':    u['full_name'],
        'display_name': disp_name,
        'user_type':    u['user_type'],
        'avatar':       u['avatar'],
    })

# ── upgrade to admin ──────────────────────────────────────────────
@app.route('/api/upgrade-to-admin', methods=['POST'])
@login_required
def upgrade_to_admin():
    """Member can become admin if they verify their password and choose username 'admin'."""
    d = request.get_json() or {}
    if not d.get('password'):
        return jsonify(success=False, message="Password required for verification")
    if d.get('admin_username','').strip().lower() != 'admin':
        return jsonify(success=False, message="Admin username must be exactly 'admin'")

    cur = db_connection.cursor()
    cur.execute("SELECT password, user_type FROM users WHERE user_id=?", (session['user_id'],))
    u = cur.fetchone()
    if not u:
        return jsonify(success=False, message="User not found")
    if not _verify(d['password'], u['password']):
        return jsonify(success=False, message="Incorrect password")
    if u['user_type'] == 'admin':
        return jsonify(success=False, message="You are already an admin")

    # Check if an 'admin' username already exists (from a different user)
    cur.execute("SELECT user_id FROM users WHERE username='admin' AND user_id!=?", (session['user_id'],))
    if cur.fetchone():
        return jsonify(success=False, message="Admin account already exists. Contact the system administrator.")

    db_connection.execute(
        "UPDATE users SET user_type='admin', username='admin' WHERE user_id=?",
        (session['user_id'],))
    db_connection.commit()
    session['user_type'] = 'admin'
    session['username']  = 'admin'
    _notify(session['user_id'], "Your account has been upgraded to Admin! 🛡️", 'success')
    return jsonify(success=True, message="You are now an Admin!")

# ── profile ───────────────────────────────────────────────────────
@app.route('/api/profile', methods=['GET'])
@login_required
def get_profile():
    cur = db_connection.cursor()
    cur.execute("SELECT * FROM users WHERE user_id=?", (session['user_id'],))
    u = cur.fetchone()
    if not u: return jsonify(success=False, message="Not found"), 404
    return jsonify(success=True, profile={
        'user_id':       u['user_id'],
        'username':      u['username'],
        'email':         u['email'],
        'full_name':     u['full_name'],
        'surname':       u['surname'],
        'bio':           u['bio'],
        'avatar':        u['avatar'],
        'website':       u['website'],
        'user_type':     u['user_type'],
        'total_articles':u['total_articles'],
        'total_comments':u['total_comments'],
        'reputation':    u['reputation'],
        'created_at':    u['created_at'],
    })

@app.route('/api/profile', methods=['PUT'])
@login_required
def update_profile():
    d = request.get_json() or {}
    allowed = ['full_name','bio','website','email']
    updates, vals = [], []
    for k in allowed:
        if k in d:
            updates.append(f"{k}=?")
            vals.append(d[k])
    if not updates:
        return jsonify(success=False, message="Nothing to update")
    vals.append(session['user_id'])
    db_connection.execute(f"UPDATE users SET {', '.join(updates)} WHERE user_id=?", vals)
    db_connection.commit()
    return jsonify(success=True, message="Profile updated")

@app.route('/api/profile/avatar', methods=['POST'])
@login_required
def upload_avatar():
    if 'avatar' not in request.files:
        return jsonify(success=False, message="No file provided")
    f = request.files['avatar']
    if not _allowed_image(f.filename):
        return jsonify(success=False, message="Invalid image format")
    fname = f"{session['user_id']}_{uuid.uuid4().hex}.{f.filename.rsplit('.',1)[-1]}"
    path  = os.path.join('uploads/profiles', fname)
    f.save(path)
    url = f"/uploads/profiles/{fname}"
    db_connection.execute("UPDATE users SET avatar=? WHERE user_id=?", (url, session['user_id']))
    db_connection.commit()
    return jsonify(success=True, avatar=url)

@app.route('/api/change-password', methods=['POST'])
@login_required
def change_password():
    d = request.get_json() or {}
    if not d.get('old_password') or not d.get('new_password'):
        return jsonify(success=False, message="Old and new password required")
    if len(d['new_password']) < 6:
        return jsonify(success=False, message="New password must be at least 6 characters")
    cur = db_connection.cursor()
    cur.execute("SELECT password FROM users WHERE user_id=?", (session['user_id'],))
    u = cur.fetchone()
    if not _verify(d['old_password'], u['password']):
        return jsonify(success=False, message="Incorrect current password")
    db_connection.execute("UPDATE users SET password=? WHERE user_id=?",
                          (_hash(d['new_password']), session['user_id']))
    db_connection.commit()
    _notify(session['user_id'], "Password changed successfully 🔐", 'success')
    return jsonify(success=True, message="Password changed successfully")

# ── forgot password ───────────────────────────────────────────────
@app.route('/api/forgot-password', methods=['POST'])
def forgot_password():
    d   = request.get_json() or {}
    email = d.get('email','').strip()
    if not email:
        return jsonify(success=False, message="Email required")
    cur = db_connection.cursor()
    cur.execute("SELECT user_id, full_name FROM users WHERE email=?", (email,))
    u = cur.fetchone()
    # Always return success to prevent email enumeration
    if not u:
        return jsonify(success=True, message="If that email exists, a reset token has been generated.")
    token   = secrets.token_urlsafe(32)
    expiry  = datetime.now() + timedelta(hours=1)
    db_connection.execute(
        "INSERT INTO reset_tokens(user_id,token,expires_at) VALUES(?,?,?)",
        (u['user_id'], token, expiry))
    db_connection.commit()
    # In production send email; for dev expose token in response
    reset_url = f"http://127.0.0.1:5000/frontend?reset_token={token}"
    print(f"\n🔑 PASSWORD RESET TOKEN for {email}:\n   {reset_url}\n")
    return jsonify(success=True,
                   message="Reset token generated. Check server console for the link (dev mode).",
                   dev_token=token)   # remove in production!

@app.route('/api/reset-password', methods=['POST'])
def reset_password():
    d = request.get_json() or {}
    token  = d.get('token','')
    new_pw = d.get('new_password','')
    if not token or not new_pw:
        return jsonify(success=False, message="Token and new password required")
    if len(new_pw) < 6:
        return jsonify(success=False, message="Password must be at least 6 characters")
    cur = db_connection.cursor()
    cur.execute('''SELECT rt.user_id FROM reset_tokens rt
                   WHERE rt.token=? AND rt.used=0 AND rt.expires_at > ?''',
                (token, datetime.now()))
    row = cur.fetchone()
    if not row:
        return jsonify(success=False, message="Invalid or expired reset token")
    db_connection.execute("UPDATE users SET password=? WHERE user_id=?",
                          (_hash(new_pw), row['user_id']))
    db_connection.execute("UPDATE reset_tokens SET used=1 WHERE token=?", (token,))
    db_connection.commit()
    return jsonify(success=True, message="Password reset successfully. You can now sign in.")

# ══════════════════════════════════════════════════════════════════
#  ARTICLES
# ══════════════════════════════════════════════════════════════════
CATEGORIES = ['general','tech','travel','medicine','business','sport','lifestyle','politics','science','entertainment']

@app.route('/api/articles', methods=['GET'])
def get_articles():
    page     = int(request.args.get('page',1))
    limit    = int(request.args.get('limit',12))
    category = request.args.get('category','')
    search   = request.args.get('search','')
    sort     = request.args.get('sort','latest')
    offset   = (page-1)*limit

    query  = '''SELECT a.*,u.username,u.full_name,u.avatar,u.user_type,
                       (SELECT COUNT(*) FROM comments c WHERE c.article_id=a.article_id
                        AND c.status='auto_approved') as comment_count
                FROM articles a JOIN users u ON a.user_id=u.user_id
                WHERE a.status='published' '''
    params = []
    if category:
        query += " AND a.category=?"; params.append(category)
    if search:
        query += " AND (a.title LIKE ? OR a.content LIKE ?)"; params += [f'%{search}%']*2
    order = {'latest':'a.created_at DESC','popular':'a.views DESC','liked':'a.likes DESC'}.get(sort,'a.created_at DESC')
    query += f" ORDER BY {order} LIMIT ? OFFSET ?"; params += [limit, offset]

    cur = db_connection.cursor()
    cur.execute(query, params)
    rows = cur.fetchall()

    articles = []
    for r in rows:
        articles.append({
            'article_id':   r['article_id'],
            'title':        r['title'],
            'summary':      r['summary'],
            'content_html': r['content_html'],
            'media_url':    r['media_url'],
            'media_type':   r['media_type'],
            'category':     r['category'],
            'tags':         [t.strip() for t in r['tags'].split(',') if t.strip()] if r['tags'] else [],
            'reading_time': r['reading_time'],
            'views':        r['views'],
            'likes':        r['likes'],
            'comment_count':r['comment_count'],
            'created_at':   r['created_at'],
            'author': {
                'username':  r['username'],
                'full_name': r['full_name'],
                'avatar':    r['avatar'],
                'user_type': r['user_type'],
            }
        })

    cur.execute("SELECT COUNT(*) FROM articles WHERE status='published'"
                + (" AND category=?" if category else ""),
                ([category] if category else []))
    total = cur.fetchone()[0]

    return jsonify(success=True, articles=articles,
                   pagination={'page':page,'limit':limit,'total':total,
                                'pages': math.ceil(total/limit) if total else 1})

@app.route('/api/articles', methods=['POST'])
@login_required
def create_article():
    # Supports JSON (text) or multipart form (with media)
    if request.content_type and 'multipart' in request.content_type:
        title    = request.form.get('title','').strip()
        content  = request.form.get('content','').strip()
        category = request.form.get('category','general')
        tags     = request.form.get('tags','')
        media_type = 'text'
        media_url  = ''
        # handle image upload
        if 'image' in request.files:
            f = request.files['image']
            if f and _allowed_image(f.filename):
                fn  = f"{uuid.uuid4().hex}.{f.filename.rsplit('.',1)[-1]}"
                f.save(os.path.join('uploads/media', fn))
                media_url  = f"/uploads/media/{fn}"
                media_type = 'image'
        elif 'video' in request.files:
            f = request.files['video']
            if f and _allowed_video(f.filename):
                fn  = f"{uuid.uuid4().hex}.{f.filename.rsplit('.',1)[-1]}"
                f.save(os.path.join('uploads/media', fn))
                media_url  = f"/uploads/media/{fn}"
                media_type = 'video'
    else:
        d = request.get_json() or {}
        title    = d.get('title','').strip()
        content  = d.get('content','').strip()
        category = d.get('category','general')
        tags     = d.get('tags','')
        media_url  = d.get('media_url','')
        media_type = 'image' if media_url and not content else 'text'
        save_as_draft = d.get('save_as_draft', False)
    
    # Check if save_as_draft was passed in multipart form
    if request.content_type and 'multipart' in request.content_type:
        save_as_draft = request.form.get('save_as_draft', '').lower() == 'true'

    if not title:
        return jsonify(success=False, message="Title is required")

    content_html = content
    if MARKDOWN_OK and content:
        allowed_tags = ['p','br','strong','em','h1','h2','h3','ul','ol','li',
                        'a','blockquote','code','pre','img']
        content_html = bleach.clean(
            markdown.markdown(content),
            tags=allowed_tags, attributes=['href','src','alt'])

    words       = len(content.split()) if content else 0
    reading_time = max(1, round(words/200))
    summary      = content[:200]+'...' if len(content) > 200 else content

    status = 'draft' if save_as_draft else 'published'
    cur = db_connection.cursor()
    cur.execute('''INSERT INTO articles
        (user_id,title,content,content_html,summary,media_url,media_type,category,tags,reading_time,status)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
        (session['user_id'],title,content,content_html,summary,
         media_url,media_type,category,tags,reading_time,status))
    article_id = cur.lastrowid
    
    # Only increment total_articles for published articles
    if not save_as_draft:
        db_connection.execute("UPDATE users SET total_articles=total_articles+1 WHERE user_id=?",
                              (session['user_id'],))
    
    db_connection.commit()
    
    if save_as_draft:
        _notify(session['user_id'], f"Draft '{title}' saved! 📝", 'info')
        return jsonify(success=True, message="Draft saved!", article_id=article_id, is_draft=True)
    else:
        _notify(session['user_id'], f"Your article '{title}' was published! 📰", 'success')
        return jsonify(success=True, message="Article published!", article_id=article_id)

@app.route('/api/articles/<int:article_id>/like', methods=['POST'])
@login_required
def like_article(article_id):
    db_connection.execute("UPDATE articles SET likes=likes+1 WHERE article_id=?", (article_id,))
    db_connection.execute("UPDATE articles SET views=views+1 WHERE article_id=?",  (article_id,))
    db_connection.commit()
    cur = db_connection.cursor()
    cur.execute("SELECT likes FROM articles WHERE article_id=?", (article_id,))
    row = cur.fetchone()
    return jsonify(success=True, likes=row['likes'] if row else 0)

@app.route('/api/articles/<int:article_id>/view', methods=['POST'])
def record_view(article_id):
    db_connection.execute("UPDATE articles SET views=views+1 WHERE article_id=?", (article_id,))
    db_connection.commit()
    return jsonify(success=True)

@app.route('/api/drafts', methods=['GET'])
@login_required
def get_drafts():
    """Get all drafts for the current user."""
    cur = db_connection.cursor()
    cur.execute('''SELECT article_id,title,summary,category,media_type,media_url,
                          created_at,updated_at,tags
                   FROM articles
                   WHERE user_id=? AND status='draft'
                   ORDER BY updated_at DESC, created_at DESC''', (session['user_id'],))
    rows = cur.fetchall()
    drafts = [dict(r) for r in rows]
    return jsonify(success=True, drafts=drafts)

@app.route('/api/drafts/<int:article_id>/publish', methods=['POST'])
@login_required
def publish_draft(article_id):
    """Publish a draft article."""
    cur = db_connection.cursor()
    cur.execute("SELECT user_id, title FROM articles WHERE article_id=? AND status='draft'",
                (article_id,))
    article = cur.fetchone()
    if not article:
        return jsonify(success=False, message="Draft not found"), 404
    if article['user_id'] != session['user_id']:
        return jsonify(success=False, message="Not authorised"), 403
    
    db_connection.execute("UPDATE articles SET status='published' WHERE article_id=?",
                          (article_id,))
    db_connection.execute("UPDATE users SET total_articles=total_articles+1 WHERE user_id=?",
                          (session['user_id'],))
    db_connection.commit()
    _notify(session['user_id'], f"Your article '{article['title']}' is now published! 📰", 'success')
    return jsonify(success=True, message="Article published!")

@app.route('/api/drafts/<int:article_id>', methods=['DELETE'])
@login_required
def delete_draft(article_id):
    """Delete a draft article."""
    cur = db_connection.cursor()
    cur.execute("SELECT user_id FROM articles WHERE article_id=? AND status='draft'",
                (article_id,))
    article = cur.fetchone()
    if not article:
        return jsonify(success=False, message="Draft not found"), 404
    if article['user_id'] != session['user_id']:
        return jsonify(success=False, message="Not authorised"), 403
    
    db_connection.execute("DELETE FROM articles WHERE article_id=?", (article_id,))
    db_connection.commit()
    return jsonify(success=True, message="Draft deleted")

@app.route('/api/articles/<int:article_id>', methods=['DELETE'])
@login_required
def delete_article(article_id):
    """User can delete their own published article."""
    cur = db_connection.cursor()
    cur.execute("SELECT user_id, title, status FROM articles WHERE article_id=?", (article_id,))
    article = cur.fetchone()
    if not article:
        return jsonify(success=False, message="Article not found"), 404
    if article['user_id'] != session['user_id']:
        return jsonify(success=False, message="Not authorised to delete this article"), 403
    
    # Delete all comments associated with this article first
    db_connection.execute("DELETE FROM comments WHERE article_id=?", (article_id,))
    
    # Delete the article
    db_connection.execute("DELETE FROM articles WHERE article_id=?", (article_id,))
    
    # Update user's total articles if it was published
    if article['status'] == 'published':
        db_connection.execute("UPDATE users SET total_articles=total_articles-1 WHERE user_id=? AND total_articles>0",
                              (session['user_id'],))
    
    db_connection.commit()
    _notify(session['user_id'], f"Your article '{article['title']}' has been deleted.", 'info')
    return jsonify(success=True, message="Article deleted")

# ══════════════════════════════════════════════════════════════════
#  COMMENTS
# ══════════════════════════════════════════════════════════════════
@app.route('/api/comments', methods=['GET'])
def get_comments():
    article_id = request.args.get('article_id')
    if not article_id:
        return jsonify(success=False, message="article_id required")

    # Check if requester is article owner or admin → show all statuses
    viewer_id   = session.get('user_id')
    viewer_type = session.get('user_type','member')

    cur = db_connection.cursor()
    cur.execute("SELECT user_id FROM articles WHERE article_id=?", (article_id,))
    art = cur.fetchone()
    is_owner = art and viewer_id and art['user_id'] == viewer_id
    see_all  = is_owner or viewer_type == 'admin'

    if see_all:
        cur.execute('''SELECT c.*,u.username,u.full_name,u.avatar
                       FROM comments c JOIN users u ON c.user_id=u.user_id
                       WHERE c.article_id=? ORDER BY c.created_at DESC''', (article_id,))
    else:
        cur.execute('''SELECT c.*,u.username,u.full_name,u.avatar
                       FROM comments c JOIN users u ON c.user_id=u.user_id
                       WHERE c.article_id=? AND c.status='auto_approved'
                       ORDER BY c.created_at DESC''', (article_id,))

    rows = cur.fetchall()
    comments = []
    for r in rows:
        comments.append({
            'comment_id':   r['comment_id'],
            'comment_text': r['comment_text'],
            'status':       r['status'],
            'reason':       r['reason'],
            'language':     r['language'],
            'nb_spam_prob': r['nb_spam_prob'],
            'adult_score':  r['adult_score'],
            'created_at':   r['created_at'],
            'username':     r['username'],
            'full_name':    r['full_name'],
            'avatar':       r['avatar'],
        })

    # Count summary for owners/admins
    summary = {}
    if see_all:
        cur.execute('''SELECT status, COUNT(*) cnt FROM comments
                       WHERE article_id=? GROUP BY status''', (article_id,))
        for row in cur.fetchall():
            summary[row['status']] = row['cnt']

    return jsonify(success=True, comments=comments, summary=summary)

@app.route('/api/comments', methods=['POST'])
@login_required
def post_comment():
    d = request.get_json() or {}
    text       = (d.get('comment_text') or '').strip()
    article_id = d.get('article_id')
    if not text:
        return jsonify(success=False, message="Comment cannot be empty")
    if not article_id:
        return jsonify(success=False, message="article_id required")
    if not rate_limit(session['user_id']):
        return jsonify(success=False, message="Too many comments. Please slow down.")

    # Run through NB moderator
    result = moderator.classify(text)

    cur = db_connection.cursor()
    cur.execute('''INSERT INTO comments
        (article_id,user_id,comment_text,language,nb_spam_prob,adult_score,
         profanity_score,spam_score,status,reason,ip_address)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
        (article_id, session['user_id'], text,
         result['language'],
         result['scores']['nb_spam_prob'],
         result['scores']['adult_score'],
         result['scores']['profanity_score'],
         result['scores']['spam_score'],
         result['status'],
         result['reason'],
         request.remote_addr))
    comment_id = cur.lastrowid
    db_connection.execute("UPDATE users SET total_comments=total_comments+1 WHERE user_id=?",
                          (session['user_id'],))
    db_connection.commit()

    # Train NB on auto decisions
    if result['status'] == 'auto_approved':
        moderator.train(text, 'ham')
    elif result['status'] == 'auto_rejected':
        moderator.train(text, 'spam')

    msg_map = {
        'auto_approved': 'Comment posted! ✅',
        'auto_rejected': 'Your comment was blocked by our moderation system.',
        'under_review':  'Comment submitted and is under review by the moderator.',
    }
    return jsonify(
        success=(result['status'] != 'auto_rejected'),
        message=msg_map[result['status']],
        status=result['status'],
        comment_id=comment_id
    )

@app.route('/api/comments/<int:comment_id>/moderate', methods=['PUT'])
@login_required
def moderate_comment(comment_id):
    d      = request.get_json() or {}
    action = d.get('action','')
    if action not in ('approve','reject'):
        return jsonify(success=False, message="action must be 'approve' or 'reject'")

    cur = db_connection.cursor()
    # Verify caller is admin OR article owner
    cur.execute('''SELECT c.user_id as commenter_id, c.comment_text, c.status,
                          a.user_id as author_id
                   FROM comments c JOIN articles a ON c.article_id=a.article_id
                   WHERE c.comment_id=?''', (comment_id,))
    row = cur.fetchone()
    if not row:
        return jsonify(success=False, message="Comment not found"), 404

    is_admin  = session.get('user_type') == 'admin'
    is_author = row['author_id'] == session['user_id']
    if not is_admin and not is_author:
        return jsonify(success=False, message="Not authorised"), 403

    new_status = 'auto_approved' if action == 'approve' else 'auto_rejected'
    db_connection.execute('''UPDATE comments SET status=?,reviewed_by=?,reviewed_at=?
                              WHERE comment_id=?''',
                          (new_status, session['user_id'], datetime.now(), comment_id))
    db_connection.execute('''INSERT INTO mod_log(comment_id,action,actor_id,note)
                              VALUES(?,?,?,?)''',
                          (comment_id, action, session['user_id'], d.get('note','')))
    db_connection.commit()

    # Retrain NB
    label = 'ham' if action == 'approve' else 'spam'
    moderator.train(row['comment_text'], label)

    return jsonify(success=True, message=f"Comment {action}d")

@app.route('/api/comments/<int:comment_id>/delete', methods=['DELETE'])
@login_required
def delete_comment(comment_id):
    """Delete a comment. Admin, article author, or comment author can delete."""
    cur = db_connection.cursor()
    # Get comment and article info
    cur.execute('''SELECT c.user_id as commenter_id, c.article_id,
                          a.user_id as author_id
                   FROM comments c JOIN articles a ON c.article_id=a.article_id
                   WHERE c.comment_id=?''', (comment_id,))
    row = cur.fetchone()
    if not row:
        return jsonify(success=False, message="Comment not found"), 404

    is_admin           = session.get('user_type') == 'admin'
    is_article_author  = row['author_id'] == session['user_id']
    is_comment_author  = row['commenter_id'] == session['user_id']
    
    if not (is_admin or is_article_author or is_comment_author):
        return jsonify(success=False, message="Not authorised"), 403

    # Delete the comment
    db_connection.execute("DELETE FROM comments WHERE comment_id=?", (comment_id,))
    db_connection.execute("UPDATE users SET total_comments=total_comments-1 WHERE user_id=? AND total_comments>0",
                          (row['commenter_id'],))
    db_connection.commit()
    
    return jsonify(success=True, message="Comment deleted")

# ══════════════════════════════════════════════════════════════════
#  ADMIN ROUTES
# ══════════════════════════════════════════════════════════════════
@app.route('/api/admin/comments', methods=['GET'])
@admin_required
def admin_all_comments():
    status = request.args.get('status','under_review')
    cur    = db_connection.cursor()
    cur.execute('''SELECT c.*,u.username,u.full_name,a.title as article_title
                   FROM comments c
                   JOIN users    u ON c.user_id    = u.user_id
                   JOIN articles a ON c.article_id = a.article_id
                   WHERE c.status=?
                   ORDER BY c.created_at DESC LIMIT 200''', (status,))
    rows = cur.fetchall()
    return jsonify(success=True, comments=[dict(r) for r in rows])

@app.route('/api/admin/stats', methods=['GET'])
@admin_required
def admin_stats():
    cur = db_connection.cursor()
    def q(sql,p=[]): cur.execute(sql,p); return cur.fetchone()[0]
    return jsonify(success=True, stats={
        'total_users':          q("SELECT COUNT(*) FROM users WHERE user_type='member'"),
        'total_admins':         q("SELECT COUNT(*) FROM users WHERE user_type='admin'"),
        'total_articles':       q("SELECT COUNT(*) FROM articles WHERE status='published'"),
        'total_comments':       q("SELECT COUNT(*) FROM comments"),
        'approved_comments':    q("SELECT COUNT(*) FROM comments WHERE status='auto_approved'"),
        'rejected_comments':    q("SELECT COUNT(*) FROM comments WHERE status='auto_rejected'"),
        'pending_comments':     q("SELECT COUNT(*) FROM comments WHERE status='under_review'"),
        'blocked_domains':      q("SELECT COUNT(*) FROM blocked_domains"),
        'today_comments':       q("SELECT COUNT(*) FROM comments WHERE DATE(created_at)=DATE('now')"),
        'today_articles':       q("SELECT COUNT(*) FROM articles WHERE DATE(created_at)=DATE('now')"),
    })

@app.route('/api/admin/users', methods=['GET'])
@admin_required
def admin_users():
    cur = db_connection.cursor()
    cur.execute("SELECT user_id,username,full_name,email,user_type,is_active,created_at,total_articles,total_comments FROM users ORDER BY created_at DESC")
    return jsonify(success=True, users=[dict(r) for r in cur.fetchall()])

@app.route('/api/admin/users/<int:uid>/toggle', methods=['PUT'])
@admin_required
def toggle_user(uid):
    cur = db_connection.cursor()
    cur.execute("SELECT is_active FROM users WHERE user_id=?", (uid,))
    r = cur.fetchone()
    if not r: return jsonify(success=False, message="User not found"), 404
    new_val = 0 if r['is_active'] else 1
    db_connection.execute("UPDATE users SET is_active=? WHERE user_id=?", (new_val, uid))
    db_connection.commit()
    return jsonify(success=True, message=f"User {'activated' if new_val else 'suspended'}")

@app.route('/api/admin/blocked-domains', methods=['GET'])
@admin_required
def get_blocked_domains():
    cur = db_connection.cursor()
    cur.execute("SELECT * FROM blocked_domains ORDER BY added_at DESC")
    return jsonify(success=True, domains=[dict(r) for r in cur.fetchall()])

@app.route('/api/admin/blocked-domains', methods=['POST'])
@admin_required
def add_blocked_domain():
    d = request.get_json() or {}
    domain = d.get('domain','').strip().lower().replace('www.','')
    if not domain: return jsonify(success=False, message="Domain required")
    try:
        db_connection.execute(
            "INSERT INTO blocked_domains(domain,threat_level,reason,added_by) VALUES(?,?,?,?)",
            (domain, d.get('threat_level','medium'), d.get('reason',''), session['user_id']))
        db_connection.commit()
        return jsonify(success=True, message="Domain blocked")
    except Exception as e:
        return jsonify(success=False, message=str(e))

@app.route('/api/admin/blocked-domains/<int:did>', methods=['DELETE'])
@admin_required
def remove_blocked_domain(did):
    db_connection.execute("DELETE FROM blocked_domains WHERE domain_id=?", (did,))
    db_connection.commit()
    return jsonify(success=True, message="Domain removed")

# ── integrations ──────────────────────────────────────────────────
@app.route('/api/admin/integrations', methods=['GET'])
@admin_required
def get_integrations():
    cur = db_connection.cursor()
    cur.execute("SELECT * FROM integrations WHERE user_id=?", (session['user_id'],))
    return jsonify(success=True, integrations=[dict(r) for r in cur.fetchall()])

@app.route('/api/admin/integrations', methods=['POST'])
@admin_required
def add_integration():
    d = request.get_json() or {}
    if not d.get('platform') or not d.get('webhook_url'):
        return jsonify(success=False, message="Platform and webhook_url required")
    db_connection.execute(
        "INSERT INTO integrations(user_id,platform,webhook_url,api_key) VALUES(?,?,?,?)",
        (session['user_id'], d['platform'], d['webhook_url'], d.get('api_key','')))
    db_connection.commit()
    return jsonify(success=True, message=f"{d['platform']} integration added")

@app.route('/api/admin/integrations/<int:iid>', methods=['DELETE'])
@admin_required
def remove_integration(iid):
    db_connection.execute("DELETE FROM integrations WHERE integration_id=? AND user_id=?",
                          (iid, session['user_id']))
    db_connection.commit()
    return jsonify(success=True)

# ── mod log ───────────────────────────────────────────────────────
@app.route('/api/admin/mod-log', methods=['GET'])
@admin_required
def mod_log():
    cur = db_connection.cursor()
    cur.execute('''SELECT ml.*,u.username,c.comment_text
                   FROM mod_log ml
                   JOIN users    u ON ml.actor_id   = u.user_id
                   JOIN comments c ON ml.comment_id = c.comment_id
                   ORDER BY ml.created_at DESC LIMIT 100''')
    return jsonify(success=True, logs=[dict(r) for r in cur.fetchall()])

# ── notifications ─────────────────────────────────────────────────
@app.route('/api/notifications', methods=['GET'])
@login_required
def get_notifications():
    cur = db_connection.cursor()
    cur.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 20",
                (session['user_id'],))
    notifs = [dict(r) for r in cur.fetchall()]
    db_connection.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (session['user_id'],))
    db_connection.commit()
    return jsonify(success=True, notifications=notifs)

# ══════════════════════════════════════════════════════════════════
#  TEST
# ══════════════════════════════════════════════════════════════════
@app.route('/api/test')
def test():
    cur = db_connection.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    u = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM articles")
    a = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM comments")
    c = cur.fetchone()[0]
    return jsonify(success=True, version="5.0", users=u, articles=a, comments=c,
                   nb_model={'ham':moderator.class_counts['ham'],
                              'spam':moderator.class_counts['spam'],
                              'vocab':len(moderator.vocab)})

# ══════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    print("\n" + "="*60)
    print("  CONTENT PLATFORM v5.0  —  Naïve-Bayes Moderation")
    print("="*60)
    print("  Admin login : admin / admin123")
    print("  Frontend    : http://127.0.0.1:5000/frontend")
    print("="*60 + "\n")
    app.run(debug=True, port=5000)
