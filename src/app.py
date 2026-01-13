# app.py
from flask import Flask, jsonify, request
from pathlib import Path
import random
import json
import csv

app = Flask(__name__)

class EloRanker:
    def __init__(self, items, k_factor=32, initial_rating=1500):
        self.k_factor = k_factor
        self.ratings = {item: initial_rating for item in items}
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
        if self.history and self.current_index > 0:
            self.ratings = self.history.pop()
            self.comparisons.pop()
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

# Database management
DB_DIR = Path('databases')
DB_DIR.mkdir(exist_ok=True)

rankers = {}
current_db = None

def get_databases():
    return [f.stem for f in DB_DIR.glob('*.txt')]

def load_database(db_name):
    global current_db, rankers
    
    if db_name in rankers:
        current_db = db_name
        return rankers[db_name]
    
    db_file = DB_DIR / f'{db_name}.txt'
    items = db_file.read_text().strip().split('\n')
    
    ranker = EloRanker(items)
    csv_file = DB_DIR / f'{db_name}_ratings.csv'
    ranker.load_from_csv(csv_file)
    
    rankers[db_name] = ranker
    current_db = db_name
    return ranker

# Initialize with first available database
databases = get_databases()
if databases:
    load_database(databases[0])

HTML = """<!DOCTYPE html>
<html>
<head>
    <title>Elo Ranker</title>
    <style>
        body {
            font-family: monospace;
            max-width: 800px;
            margin: 50px auto;
            background: #000;
            color: #0f0;
        }
        .controls {
            text-align: center;
            margin: 20px 0;
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
        .comparison {
            display: flex;
            gap: 40px;
            justify-content: center;
            margin: 40px 0;
        }
        .option {
            flex: 1;
            text-align: center;
            padding: 60px 20px;
            border: 2px solid #0f0;
            font-size: 24px;
            cursor: pointer;
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
        .top-ten {
            margin-top: 40px;
            padding: 20px;
            border: 2px solid #0f0;
        }
        .top-ten h2 {
            margin-top: 0;
        }
        .top-ten ol {
            margin: 0;
            padding-left: 20px;
        }
        .full-rankings {
            margin-top: 20px;
            padding: 20px;
            border: 2px solid #0f0;
        }
    </style>
</head>
<body>
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
    </div>
    
    <div class="comparison">
        <div class="option" id="left"></div>
        <div class="option" id="right"></div>
    </div>
    
    <div class="stats">
        <div>Comparisons: <span id="count">0</span></div>
        <button onclick="toggleFullRankings()">Toggle Full Rankings</button>
    </div>
    
    <div class="top-ten">
        <h2>Top 10</h2>
        <ol id="topTen"></ol>
    </div>
    
    <div class="full-rankings" id="fullRankings" style="display:none;">
        <h2>All Rankings</h2>
        <ol id="rankingList"></ol>
    </div>

    <script>
        let currentPair = [];
        let comparisonCount = 0;
        
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
            loadPair();
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
            document.getElementById('left').textContent = currentPair[0];
            document.getElementById('right').textContent = currentPair[1];
        }
        
        async function loadPair() {
            const resp = await fetch('/get_pair');
            const data = await resp.json();
            displayPair(data.pair);
        }
        
        async function updateRankings() {
            const resp = await fetch('/rankings');
            const data = await resp.json();
            const rankings = data.rankings;
            
            const topTen = document.getElementById('topTen');
            topTen.innerHTML = rankings.slice(0, 10)
                .map(([name, rating]) => `<li>${name}: ${rating.toFixed(1)}</li>`)
                .join('');
            
            if (document.getElementById('fullRankings').style.display !== 'none') {
                const list = document.getElementById('rankingList');
                list.innerHTML = rankings
                    .map(([name, rating]) => `<li>${name}: ${rating.toFixed(1)}</li>`)
                    .join('');
            }
        }
        
        async function submitComparison(result) {
            await fetch('/submit_comparison', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    left: currentPair[0],
                    right: currentPair[1],
                    result: result
                })
            });
            comparisonCount++;
            document.getElementById('count').textContent = comparisonCount;
            await updateRankings();
            loadPair();
        }
        
        async function goBack() {
            const resp = await fetch('/go_back', {method: 'POST'});
            const data = await resp.json();
            if (data.success) {
                comparisonCount = Math.max(0, comparisonCount - 1);
                document.getElementById('count').textContent = comparisonCount;
                displayPair(data.pair);
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
        
        document.getElementById('left').addEventListener('click', () => submitComparison('left'));
        document.getElementById('right').addEventListener('click', () => submitComparison('right'));
        
        loadDatabases();
        loadPair();
        updateRankings();
    </script>
</body>
</html>"""

@app.route('/')
def index():
    return HTML

@app.route('/databases')
def databases_endpoint():
    return jsonify({
        'databases': get_databases(),
        'current': current_db
    })

@app.route('/switch_db', methods=['POST'])
def switch_db():
    db_name = request.json['database']
    load_database(db_name)
    return jsonify({'success': True})

@app.route('/set_strategy', methods=['POST'])
def set_strategy():
    strategy = request.json['strategy']
    rankers[current_db].strategy = strategy
    return jsonify({'success': True})

@app.route('/get_pair')
def get_pair():
    ranker = rankers[current_db]
    pair = ranker.get_next_pair()
    return jsonify({'pair': pair})

@app.route('/submit_comparison', methods=['POST'])
def submit_comparison():
    data = request.json
    result = data['result']
    left = data['left']
    right = data['right']
    
    ranker = rankers[current_db]
    
    if result == 'left':
        ranker.update_ratings(left, right)
    elif result == 'right':
        ranker.update_ratings(right, left)
    elif result == 'tie':
        ranker.record_tie(left, right)
    
    csv_file = DB_DIR / f'{current_db}_ratings.csv'
    ranker.save_to_csv(csv_file)
    
    return jsonify({'success': True})

@app.route('/go_back', methods=['POST'])
def go_back():
    ranker = rankers[current_db]
    pair = ranker.go_back()
    if pair:
        csv_file = DB_DIR / f'{current_db}_ratings.csv'
        ranker.save_to_csv(csv_file)
        return jsonify({'success': True, 'pair': pair})
    return jsonify({'success': False})

@app.route('/rankings')
def rankings():
    ranker = rankers[current_db]
    return jsonify({'rankings': ranker.get_rankings()})

if __name__ == '__main__':
    app.run(debug=True)