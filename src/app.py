# app.py
from flask import Flask, jsonify, request
from pathlib import Path
import random
import json

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
    
    def get_next_pair(self, strategy='random'):
        # If we're in the middle of history, move forward
        if self.current_index + 1 < len(self.pair_sequence):
            self.current_index += 1
            return self.pair_sequence[self.current_index]
        
        # Otherwise generate new pair
        if strategy == 'random':
            pair = random.sample(self.items, 2)
        elif strategy == 'close':
            sorted_items = sorted(self.items, key=lambda x: self.ratings[x])
            idx = random.randint(0, len(sorted_items) - 2)
            pair = [sorted_items[idx], sorted_items[idx + 1]]
        
        self.pair_sequence = self.pair_sequence[:self.current_index + 1]
        self.pair_sequence.append(pair)
        self.current_index = len(self.pair_sequence) - 1
        
        return pair
    
    def get_rankings(self):
        return sorted(self.ratings.items(), key=lambda x: x[1], reverse=True)
    
    def save_state(self, filepath):
        state = {
            'ratings': self.ratings,
            'comparisons': self.comparisons,
            'items': self.items
        }
        Path(filepath).write_text(json.dumps(state, indent=2))

actresses = Path('actresses.txt').read_text().strip().split('\n')
ranker = EloRanker(actresses)

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
        <button onclick="saveState()">Save</button>
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
        
        async function saveState() {
            await fetch('/save');
            alert('Saved');
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
        
        loadPair();
        updateRankings();
    </script>
</body>
</html>"""

@app.route('/')
def index():
    return HTML

@app.route('/get_pair')
def get_pair():
    pair = ranker.get_next_pair(strategy='random')
    return jsonify({'pair': pair})

@app.route('/submit_comparison', methods=['POST'])
def submit_comparison():
    data = request.json
    result = data['result']
    left = data['left']
    right = data['right']
    
    if result == 'left':
        ranker.update_ratings(left, right)
    elif result == 'right':
        ranker.update_ratings(right, left)
    elif result == 'tie':
        ranker.record_tie(left, right)
    
    return jsonify({'success': True})

@app.route('/go_back', methods=['POST'])
def go_back():
    pair = ranker.go_back()
    if pair:
        return jsonify({'success': True, 'pair': pair})
    return jsonify({'success': False})

@app.route('/rankings')
def rankings():
    return jsonify({'rankings': ranker.get_rankings()})

@app.route('/save')
def save():
    ranker.save_state('rankings.json')
    return jsonify({'success': True})

if __name__ == '__main__':
    app.run(debug=True)