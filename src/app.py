from flask import Flask, jsonify, request, session, redirect, url_for, send_from_directory
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_session import Session
from werkzeug.security import generate_password_hash, check_password_hash
from pathlib import Path
from PIL import Image
import csv
import json
import os
import random
import secrets
import sqlite3

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(16))
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = './flask_session'
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 86400 * 30  # 30 days
Session(app)

# Auth setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

DB_DIR = Path('databases')
DB_DIR.mkdir(exist_ok=True)
USERS_DB = DB_DIR / 'users.db'

# Initialize users database
def init_users_db():
    conn = sqlite3.connect(USERS_DB)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT)''')
    conn.commit()
    conn.close()

init_users_db()

class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    conn = sqlite3.connect(USERS_DB)
    c = conn.cursor()
    c.execute('SELECT id, username FROM users WHERE id = ?', (user_id,))
    user = c.fetchone()
    conn.close()
    if user:
        return User(user[0], user[1])
    return None

class EloRanker:
    def __init__(self, items, k_factor=32, initial_rating=1500):
        self.k_factor = k_factor
        self.ratings = {item: initial_rating for item in items}
        self.rating_change_indices = set()
        self.comparisons = []
        self.items = items
        self.history = []
        self.pair_sequence = []
        self.current_index = -1
        self.strategy = 'random'
    
    def expected_score(self, rating_a, rating_b):
        return 1 / (1 + 10 ** ((rating_b - rating_a) / 400))
    
    def update_ratings(self, winner, loser):
        self.history.append(dict(self.ratings))
        self.rating_change_indices.add(self.current_index)
        
        r_winner = self.ratings[winner]
        r_loser = self.ratings[loser]
        
        e_winner = self.expected_score(r_winner, r_loser)
        e_loser = self.expected_score(r_loser, r_winner)
        
        self.ratings[winner] = r_winner + self.k_factor * (1 - e_winner)
        self.ratings[loser] = r_loser + self.k_factor * (0 - e_loser)
        
        self.comparisons.append((winner, loser))
    
    def record_tie(self, item_a, item_b):
        self.history.append(dict(self.ratings))
        
        r_a = self.ratings[item_a]
        r_b = self.ratings[item_b]
        
        e_a = self.expected_score(r_a, r_b)
        e_b = self.expected_score(r_b, r_a)
        
        self.ratings[item_a] = r_a + self.k_factor * (0.5 - e_a)
        self.ratings[item_b] = r_b + self.k_factor * (0.5 - e_b)
        
        self.comparisons.append((item_a, item_b, 'tie'))
    
    def go_back(self):
        if self.current_index > 0:
            # Only pop history if this index had a rating change
            if self.current_index in self.rating_change_indices:
                if self.history:
                    self.ratings = self.history.pop()
                if self.comparisons:
                    self.comparisons.pop()
                self.rating_change_indices.discard(self.current_index)
            
            self.current_index -= 1
            return self.pair_sequence[self.current_index]
        return None
    
    def get_next_pair(self):
        if self.current_index + 1 < len(self.pair_sequence):
            self.current_index += 1
            return self.pair_sequence[self.current_index]
        
        if self.strategy == 'random':
            pair = random.sample(self.items, 2)
        elif self.strategy == 'close':
            sorted_items = sorted(self.items, key=lambda x: self.ratings[x])
            idx = random.randint(0, len(sorted_items) - 2)
            pair = [sorted_items[idx], sorted_items[idx + 1]]
        elif self.strategy == 'weighted':
            items_list = list(self.items)
            item_a = random.choice(items_list)
            rating_a = self.ratings[item_a]
            candidates = [i for i in items_list if i != item_a]
            weights = [1 / (1 + abs(self.ratings[i] - rating_a) / 100) for i in candidates]
            item_b = random.choices(candidates, weights=weights)[0]
            pair = [item_a, item_b]
        
        self.pair_sequence = self.pair_sequence[:self.current_index + 1]
        self.pair_sequence.append(pair)
        self.current_index = len(self.pair_sequence) - 1
        
        return pair
    
    def get_rankings(self):
        return sorted(self.ratings.items(), key=lambda x: x[1], reverse=True)
    
    def save_to_csv(self, filepath):
        with open(filepath, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['item', 'rating'])
            for item, rating in sorted(self.ratings.items()):
                writer.writerow([item, rating])
    
    def load_from_csv(self, filepath):
        if not Path(filepath).exists():
            return
        with open(filepath, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                item = row['item']
                if item in self.ratings:
                    self.ratings[item] = float(row['rating'])

# Separate storage for personal and global rankers
personal_rankers = {}  # Key: (db_name, username)
global_rankers = {}    # Key: db_name (shared across all users)
current_db = {}        # Key: username

def get_databases():
    dbs = [f.stem for f in DB_DIR.glob('*.txt')]
    return sorted(dbs) if dbs else []

def get_csv_path(db_name, username, is_global=False):
    if is_global:
        return DB_DIR / f'{db_name}_global_ratings.csv'
    else:
        return DB_DIR / f'{db_name}_{username}_ratings.csv'

def get_image_path(db_name, item_name):
    """Check for image file for an item"""
    img_dir = DB_DIR / db_name / 'images'
    if not img_dir.exists():
        return None
    
    for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
        img_path = img_dir / f'{item_name}{ext}'
        if img_path.exists():
            return f'/images/{db_name}/{item_name}{ext}'
    return None

def ensure_db_loaded(username):
    """Ensure at least one database is loaded for user"""
    if username not in current_db or current_db[username] is None:
        databases = get_databases()
        if databases:
            load_database(databases[0], username)
            current_db[username] = databases[0]

def load_database(db_name, username):
    global current_db, personal_rankers, global_rankers
    
    db_file = DB_DIR / f'{db_name}.txt'
    if not db_file.exists():
        return None
    
    items = db_file.read_text().strip().split('\n')
    
    # Load personal ranker
    personal_key = (db_name, username)
    if personal_key not in personal_rankers:
        ranker = EloRanker(items)
        csv_file = get_csv_path(db_name, username, is_global=False)
        ranker.load_from_csv(csv_file)
        personal_rankers[personal_key] = ranker
    
    # Load global ranker
    if db_name not in global_rankers:
        ranker = EloRanker(items)
        csv_file = get_csv_path(db_name, username, is_global=True)
        ranker.load_from_csv(csv_file)
        global_rankers[db_name] = ranker
    
    current_db[username] = db_name
    return personal_rankers[personal_key]

def get_personal_ranker(username):
    ensure_db_loaded(username)
    db = current_db.get(username)
    if not db:
        return None
    return personal_rankers.get((db, username))

def get_global_ranker(username):
    ensure_db_loaded(username)
    db = current_db.get(username)
    if not db:
        return None
    return global_rankers.get(db)

def get_both_rankings(username):
    """Get both personal and global rankings"""
    ensure_db_loaded(username)
    db = current_db.get(username)
    
    if not db:
        return {'personal': [], 'global': []}
    
    personal = personal_rankers.get((db, username))
    global_ranker = global_rankers.get(db)
    
    return {
        'personal': personal.get_rankings() if personal else [],
        'global': global_ranker.get_rankings() if global_ranker else []
    }

HTML = """<!DOCTYPE html>
<html>
<head>
    <title>Elo Ranker</title>
    <style>
        body {
            font-family: monospace;
            max-width: 1200px;
            margin: 50px auto;
            background: #000;
            color: #0f0;
        }
        .controls {
            text-align: center;
            margin: 20px 0;
        }
        .user-info {
            text-align: center;
            margin: 20px 0;
            padding: 10px;
            border: 2px solid #0f0;
        }
        select {
            background: #000;
            color: #0f0;
            border: 2px solid #0f0;
            padding: 10px;
            font-family: monospace;
            font-size: 16px;
            margin: 0 10px;
        }
        label {
            margin-right: 5px;
        }
        .sandbox-toggle {
            margin: 10px 0;
        }
        input[type="checkbox"] {
            margin: 0 5px;
        }
        .comparison {
            display: flex;
            gap: 40px;
            justify-content: center;
            margin: 40px 0;
        }
        .option {
            flex: 1;
            text-align: center;
            padding: 20px;
            border: 2px solid #0f0;
            font-size: 24px;
            cursor: pointer;
            min-height: 300px;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
        }
        .option img {
            max-width: 256px;
            max-height: 256px;
            margin-bottom: 10px;
        }
        .option .text-only {
            font-size: 24px;
        }
        .option .label {
            font-size: 18px;
            margin-top: 10px;
        }
        .option:hover {
            background: #001a00;
        }
        .instructions {
            text-align: center;
            margin: 20px 0;
        }
        .stats {
            text-align: center;
            margin-top: 40px;
        }
        button {
            background: #000;
            color: #0f0;
            border: 2px solid #0f0;
            padding: 10px 20px;
            font-family: monospace;
            cursor: pointer;
            margin: 5px;
        }
        button:hover {
            background: #001a00;
        }
        .rankings-container {
            display: flex;
            gap: 20px;
            margin-top: 40px;
        }
        .ranking-box {
            flex: 1;
            padding: 20px;
            border: 2px solid #0f0;
        }
        .ranking-box.global {
            border-color: #f00;
            color: #f00;
        }
        .ranking-box h2 {
            margin-top: 0;
        }
        .ranking-box ol {
            margin: 0;
            padding-left: 20px;
        }
        .full-rankings {
            margin-top: 20px;
            padding: 20px;
            border: 2px solid #0f0;
        }
        .sandbox-indicator {
            color: #ff0;
            font-weight: bold;
        }
    </style>
</head>
<body>
    <div class="user-info">
        <span>Logged in as: <strong id="currentUser"></strong></span>
        <button onclick="logout()">Logout</button>
        <div class="sandbox-toggle">
            <label>
                <input type="checkbox" id="sandboxCheck" onchange="toggleSandbox()">
                Sandbox Mode (don't contribute to global rankings)
            </label>
            <span class="sandbox-indicator" id="sandboxIndicator"></span>
        </div>
    </div>

    <div class="controls">
        <label>Database: </label>
        <select id="dbSelect" onchange="switchDatabase()"></select>
        
        <label>Strategy: </label>
        <select id="strategySelect" onchange="changeStrategy()">
            <option value="random">Random</option>
            <option value="weighted">Weighted (prefer close)</option>
            <option value="close">Adjacent only</option>
        </select>
    </div>

    <div class="instructions">
        LEFT ARROW = left | RIGHT ARROW = right | DOWN ARROW = skip/tie | UP ARROW = back
        <span id="replayIndicator" style="color: #ff0; font-weight: bold;"></span>
    </div>
    
    <div class="comparison">
        <div class="option" id="left" onclick="submitComparison('left')"></div>
        <div class="option" id="right" onclick="submitComparison('right')"></div>
    </div>
    
    <div class="stats">
        <div>Comparisons: <span id="count">0</span></div>
        <div>Position: <span id="position">0</span> / <span id="total">0</span></div>
        <button onclick="toggleFullRankings()">Toggle Full Rankings</button>
    </div>
    
    <div class="rankings-container">
        <div class="ranking-box">
            <h2>Your Personal Top 10</h2>
            <ol id="personalTop10"></ol>
        </div>
        <div class="ranking-box global">
            <h2>Global Top 10 (all users)</h2>
            <ol id="globalTop10"></ol>
        </div>
    </div>
    
    <div class="full-rankings" id="fullRankings" style="display:none;">
        <div class="rankings-container">
            <div class="ranking-box">
                <h2>All Personal Rankings</h2>
                <ol id="personalFullList"></ol>
            </div>
            <div class="ranking-box global">
                <h2>All Global Rankings</h2>
                <ol id="globalFullList"></ol>
            </div>
        </div>
    </div>

    <script>
        let currentPair = {};
        let comparisonCount = 0;
        
        async function init() {
            const resp = await fetch('/get_session');
            const data = await resp.json();
            document.getElementById('currentUser').textContent = data.username;
            document.getElementById('sandboxCheck').checked = data.sandbox;
            updateSandboxIndicator(data.sandbox);
            await loadDatabases();
            await updateRankings();
            await loadPair();
        }
        
        function updateSandboxIndicator(sandbox) {
            const indicator = document.getElementById('sandboxIndicator');
            if (sandbox) {
                indicator.textContent = '⚠ SANDBOX - NOT CONTRIBUTING TO GLOBAL';
            } else {
                indicator.textContent = '';
            }
        }
        
        async function logout() {
            await fetch('/logout');
            window.location.href = '/login';
        }
        
        async function toggleSandbox() {
            const sandbox = document.getElementById('sandboxCheck').checked;
            await fetch('/set_sandbox', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({sandbox: sandbox})
            });
            updateSandboxIndicator(sandbox);
        }
        
        async function loadDatabases() {
            const resp = await fetch('/databases');
            const data = await resp.json();
            const select = document.getElementById('dbSelect');
            select.innerHTML = data.databases
                .map(db => `<option value="${db}" ${db === data.current ? 'selected' : ''}>${db}</option>`)
                .join('');
        }
        
        async function switchDatabase() {
            const db = document.getElementById('dbSelect').value;
            await fetch('/switch_db', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({database: db})
            });
            comparisonCount = 0;
            document.getElementById('count').textContent = comparisonCount;
            await updateRankings();
            await loadPair();
        }
        
        async function changeStrategy() {
            const strategy = document.getElementById('strategySelect').value;
            await fetch('/set_strategy', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({strategy: strategy})
            });
        }
        
        function displayPair(pair) {
            currentPair = pair;
            
            const leftEl = document.getElementById('left');
            const rightEl = document.getElementById('right');
            
            // Left side
            if (pair.left_image) {
                leftEl.innerHTML = `<img src="${pair.left_image}"><div class="label">${pair.left}</div>`;
            } else {
                leftEl.innerHTML = `<div class="text-only">${pair.left}</div>`;
            }
            
            // Right side
            if (pair.right_image) {
                rightEl.innerHTML = `<img src="${pair.right_image}"><div class="label">${pair.right}</div>`;
            } else {
                rightEl.innerHTML = `<div class="text-only">${pair.right}</div>`;
            }
        }
        
        async function loadPair() {
            const resp = await fetch('/get_pair');
            const data = await resp.json();
            displayPair(data);
            
            // Update position display
            document.getElementById('position').textContent = data.current_index + 1;
            document.getElementById('total').textContent = data.sequence_length;
            
            // Show replay indicator
            if (data.is_replaying) {
                document.getElementById('replayIndicator').textContent = ' ⚠ REPLAYING HISTORY (not counting toward global)';
            } else {
                document.getElementById('replayIndicator').textContent = '';
            }
        }

        async function loadPair() {
            const resp = await fetch('/get_pair');
            const data = await resp.json();
            displayPair(data);
        }
        
        async function updateRankings() {
            const resp = await fetch('/rankings');
            const data = await resp.json();
            
            // Personal top 10
            const personalTop10 = document.getElementById('personalTop10');
            personalTop10.innerHTML = data.personal.slice(0, 10)
                .map(([name, rating]) => `<li>${name}: ${rating.toFixed(1)}</li>`)
                .join('');
            
            // Global top 10
            const globalTop10 = document.getElementById('globalTop10');
            globalTop10.innerHTML = data.global.slice(0, 10)
                .map(([name, rating]) => `<li>${name}: ${rating.toFixed(1)}</li>`)
                .join('');
            
            // Full lists if visible
            if (document.getElementById('fullRankings').style.display !== 'none') {
                const personalFullList = document.getElementById('personalFullList');
                personalFullList.innerHTML = data.personal
                    .map(([name, rating]) => `<li>${name}: ${rating.toFixed(1)}</li>`)
                    .join('');
                
                const globalFullList = document.getElementById('globalFullList');
                globalFullList.innerHTML = data.global
                    .map(([name, rating]) => `<li>${name}: ${rating.toFixed(1)}</li>`)
                    .join('');
            }
        }
        
        async function submitComparison(result) {
            await fetch('/submit_comparison', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    left: currentPair.left,
                    right: currentPair.right,
                    result: result
                })
            });
            comparisonCount++;
            document.getElementById('count').textContent = comparisonCount;
            await updateRankings();
            await loadPair();
        }
        
        async function goBack() {
            const resp = await fetch('/go_back', {method: 'POST'});
            const data = await resp.json();
            if (data.success) {
                comparisonCount = Math.max(0, comparisonCount - 1);
                document.getElementById('count').textContent = comparisonCount;
                displayPair(data);
                await updateRankings();
            }
        }
        
        function toggleFullRankings() {
            const el = document.getElementById('fullRankings');
            if (el.style.display === 'none') {
                el.style.display = 'block';
                updateRankings();
            } else {
                el.style.display = 'none';
            }
        }
        
        document.addEventListener('keydown', (e) => {
            if (e.key === 'ArrowLeft') {
                e.preventDefault();
                submitComparison('left');
            }
            else if (e.key === 'ArrowRight') {
                e.preventDefault();
                submitComparison('right');
            }
            else if (e.key === 'ArrowDown') {
                e.preventDefault();
                submitComparison('tie');
            }
            else if (e.key === 'ArrowUp') {
                e.preventDefault();
                goBack();
            }
        });
        
        init();
    </script>
</body>
</html>"""

LOGIN_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>Login - Elo Ranker</title>
    <style>
        body {
            font-family: monospace;
            max-width: 400px;
            margin: 100px auto;
            background: #000;
            color: #0f0;
        }
        .form-container {
            padding: 40px;
            border: 2px solid #0f0;
        }
        h1 { text-align: center; }
        input {
            width: 100%;
            padding: 10px;
            margin: 10px 0;
            background: #000;
            color: #0f0;
            border: 2px solid #0f0;
            font-family: monospace;
            font-size: 16px;
            box-sizing: border-box;
        }
        button {
            width: 100%;
            padding: 10px;
            background: #000;
            color: #0f0;
            border: 2px solid #0f0;
            font-family: monospace;
            cursor: pointer;
            margin: 5px 0;
        }
        button:hover { background: #001a00; }
        .error { color: #f00; text-align: center; }
        .link { text-align: center; margin-top: 20px; }
        a { color: #0f0; }
    </style>
</head>
<body>
    <div class="form-container">
        <h1>Login</h1>
        <div class="error" id="error"></div>
        <form onsubmit="login(event)">
            <input type="text" id="username" placeholder="Username" required>
            <input type="password" id="password" placeholder="Password" required>
            <button type="submit">Login</button>
        </form>
        <div class="link">
            <a href="/register">Register new account</a>
        </div>
    </div>
    <script>
        async function login(e) {
            e.preventDefault();
            const resp = await fetch('/login', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    username: document.getElementById('username').value,
                    password: document.getElementById('password').value
                })
            });
            const data = await resp.json();
            if (data.success) {
                window.location.href = '/';
            } else {
                document.getElementById('error').textContent = data.error;
            }
        }
    </script>
</body>
</html>"""

REGISTER_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>Register - Elo Ranker</title>
    <style>
        body {
            font-family: monospace;
            max-width: 400px;
            margin: 100px auto;
            background: #000;
            color: #0f0;
        }
        .form-container {
            padding: 40px;
            border: 2px solid #0f0;
        }
        h1 { text-align: center; }
        input {
            width: 100%;
            padding: 10px;
            margin: 10px 0;
            background: #000;
            color: #0f0;
            border: 2px solid #0f0;
            font-family: monospace;
            font-size: 16px;
            box-sizing: border-box;
        }
        button {
            width: 100%;
            padding: 10px;
            background: #000;
            color: #0f0;
            border: 2px solid #0f0;
            font-family: monospace;
            cursor: pointer;
            margin: 5px 0;
        }
        button:hover { background: #001a00; }
        .error { color: #f00; text-align: center; }
        .link { text-align: center; margin-top: 20px; }
        a { color: #0f0; }
    </style>
</head>
<body>
    <div class="form-container">
        <h1>Register</h1>
        <div class="error" id="error"></div>
        <form onsubmit="register(event)">
            <input type="text" id="username" placeholder="Username" required>
            <input type="password" id="password" placeholder="Password" required>
            <input type="password" id="confirm" placeholder="Confirm Password" required>
            <button type="submit">Register</button>
        </form>
        <div class="link">
            <a href="/login">Back to login</a>
        </div>
    </div>
    <script>
        async function register(e) {
            e.preventDefault();
            const password = document.getElementById('password').value;
            const confirm = document.getElementById('confirm').value;
            
            if (password !== confirm) {
                document.getElementById('error').textContent = 'Passwords do not match';
                return;
            }
            
            const resp = await fetch('/register', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    username: document.getElementById('username').value,
                    password: password
                })
            });
            const data = await resp.json();
            if (data.success) {
                window.location.href = '/login';
            } else {
                document.getElementById('error').textContent = data.error;
            }
        }
    </script>
</body>
</html>"""

@app.route('/')
@login_required
def index():
    if 'sandbox' not in session:
        session['sandbox'] = False  # Default to global mode
    return HTML

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return LOGIN_HTML
    
    data = request.json
    conn = sqlite3.connect(USERS_DB)
    c = conn.cursor()
    c.execute('SELECT id, username, password_hash FROM users WHERE username = ?', (data['username'],))
    user = c.fetchone()
    conn.close()
    
    if user and check_password_hash(user[2], data['password']):
        user_obj = User(user[0], user[1])
        login_user(user_obj)
        return jsonify({'success': True})
    
    return jsonify({'success': False, 'error': 'Invalid credentials'})

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        return REGISTER_HTML
    
    data = request.json
    conn = sqlite3.connect(USERS_DB)
    c = conn.cursor()
    
    try:
        password_hash = generate_password_hash(data['password'])
        c.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)', 
                  (data['username'], password_hash))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'success': False, 'error': 'Username already exists'})

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/get_session')
@login_required
def get_session():
    ensure_db_loaded(current_user.username)
    return jsonify({
        'username': current_user.username,
        'sandbox': session.get('sandbox', False)
    })

@app.route('/set_sandbox', methods=['POST'])
@login_required
def set_sandbox():
    sandbox = request.json['sandbox']
    session['sandbox'] = sandbox
    return jsonify({'success': True})

@app.route('/databases')
@login_required
def databases_endpoint():
    ensure_db_loaded(current_user.username)
    return jsonify({
        'databases': get_databases(),
        'current': current_db.get(current_user.username)
    })

@app.route('/switch_db', methods=['POST'])
@login_required
def switch_db():
    db_name = request.json['database']
    load_database(db_name, current_user.username)
    return jsonify({'success': True})

@app.route('/set_strategy', methods=['POST'])
@login_required
def set_strategy():
    strategy = request.json['strategy']
    ranker = get_personal_ranker(current_user.username)
    if ranker:
        ranker.strategy = strategy
    return jsonify({'success': True})

@app.route('/get_pair')
@login_required
def get_pair():
    ranker = get_personal_ranker(current_user.username)
    db = current_db.get(current_user.username)
    
    if ranker and db:
        pair = ranker.get_next_pair()
        is_replaying = ranker.current_index < len(ranker.pair_sequence) - 1
        return jsonify({
            'left': pair[0],
            'right': pair[1],
            'left_image': get_image_path(db, pair[0]),
            'right_image': get_image_path(db, pair[1]),
            'is_replaying': is_replaying,
            'current_index': ranker.current_index,
            'sequence_length': len(ranker.pair_sequence)
        })
    return jsonify({
        'left': '', 
        'right': '', 
        'left_image': None, 
        'right_image': None, 
        'is_replaying': False,
        'current_index': 0,
        'sequence_length': 0
    })

@app.route('/submit_comparison', methods=['POST'])
@login_required
def submit_comparison():
    data = request.json
    result = data['result']
    left = data['left']
    right = data['right']
    
    # Skip means don't count this comparison at all
    if result == 'tie':
        return jsonify({'success': True})
    
    sandbox = session.get('sandbox', False)
    db = current_db.get(current_user.username)
    
    if not db:
        return jsonify({'success': False})
    
    personal_ranker = get_personal_ranker(current_user.username)
    if not personal_ranker:
        return jsonify({'success': False})
    
    # Check if we're replaying history
    is_replaying = personal_ranker.current_index < len(personal_ranker.pair_sequence) - 1
    
    # Update personal rankings
    if result == 'left':
        personal_ranker.update_ratings(left, right)
    elif result == 'right':
        personal_ranker.update_ratings(right, left)
    
    csv_file = get_csv_path(db, current_user.username, is_global=False)
    personal_ranker.save_to_csv(csv_file)
    
    # Only update global if not in sandbox and not replaying
    if not sandbox and not is_replaying:
        global_ranker = get_global_ranker(current_user.username)
        if global_ranker:
            if result == 'left':
                global_ranker.update_ratings(left, right)
            elif result == 'right':
                global_ranker.update_ratings(right, left)
            
            csv_file = get_csv_path(db, current_user.username, is_global=True)
            global_ranker.save_to_csv(csv_file)
    
    return jsonify({'success': True})

@app.route('/go_back', methods=['POST'])
@login_required
def go_back():
    db = current_db.get(current_user.username)
    
    if not db:
        return jsonify({'success': False})
    
    personal_ranker = get_personal_ranker(current_user.username)
    if not personal_ranker:
        return jsonify({'success': False})
    
    # Store whether this index had a rating change before going back
    had_rating_change = personal_ranker.current_index in personal_ranker.rating_change_indices
    
    # Navigate back in personal ranker
    pair = personal_ranker.go_back()
    if not pair:
        return jsonify({'success': False})
    
    # Save personal changes
    csv_file = get_csv_path(db, current_user.username, is_global=False)
    personal_ranker.save_to_csv(csv_file)
    
    # Only undo global if this pair actually changed ratings and we're not in sandbox
    sandbox = session.get('sandbox', False)
    if not sandbox and had_rating_change:
        global_ranker = get_global_ranker(current_user.username)
        if global_ranker and global_ranker.history:
            global_ranker.ratings = global_ranker.history.pop()
            if global_ranker.comparisons:
                global_ranker.comparisons.pop()
            
            csv_file = get_csv_path(db, current_user.username, is_global=True)
            global_ranker.save_to_csv(csv_file)
    
    return jsonify({
        'success': True,
        'left': pair[0],
        'right': pair[1],
        'left_image': get_image_path(db, pair[0]),
        'right_image': get_image_path(db, pair[1])
    })

@app.route('/rankings')
@login_required
def rankings():
    both = get_both_rankings(current_user.username)
    return jsonify(both)

@app.route('/images/<db_name>/<filename>')
def serve_image(db_name, filename):
    img_dir = DB_DIR / db_name / 'images'
    return send_from_directory(img_dir, filename)

if __name__ == '__main__':
    app.run(debug=True)