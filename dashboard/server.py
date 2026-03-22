"""
Web Dashboard for Trading Bot Monitoring
Flask-based dashboard at localhost:5555
"""
import json
import os
from datetime import datetime
from flask import Flask, jsonify, render_template_string
from flask_cors import CORS
from utils.logger import trade_logger


def create_app(bot_data=None):
    """Create Flask dashboard app"""
    app = Flask(__name__)
    CORS(app)

    # Shared data reference (from main bot)
    _bot_data = bot_data if bot_data is not None else {}

    DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Crypto Trading Bot Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Inter', system-ui, sans-serif;
            background: #0a0e17;
            color: #e1e5ee;
            min-height: 100vh;
        }

        .navbar {
            background: linear-gradient(135deg, #0d1117, #161b22);
            border-bottom: 1px solid #30363d;
            padding: 16px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .navbar h1 {
            font-size: 20px;
            background: linear-gradient(135deg, #58a6ff, #3fb950);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .status-badge {
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }
        .status-running { background: #1b4332; color: #3fb950; }
        .status-stopped { background: #3d1f1f; color: #f85149; }
        .status-error { background: #3d1f1f; color: #f85149; }

        .container { padding: 24px; max-width: 1400px; margin: 0 auto; }

        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 24px; }

        .card {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 12px;
            padding: 20px;
        }
        .card h3 { color: #8b949e; font-size: 12px; text-transform: uppercase; margin-bottom: 8px; }
        .card .value { font-size: 28px; font-weight: 700; }

        .positive { color: #3fb950; }
        .negative { color: #f85149; }
        .neutral { color: #58a6ff; }

        .wide-card { grid-column: span 2; }
        @media (max-width: 768px) { .wide-card { grid-column: span 1; } }

        table {
            width: 100%;
            border-collapse: collapse;
        }
        th, td { padding: 10px 14px; text-align: left; border-bottom: 1px solid #21262d; }
        th { color: #8b949e; font-size: 11px; text-transform: uppercase; }
        tr:hover { background: #1c2128; }

        .signal-box {
            display: flex;
            gap: 12px;
            flex-wrap: wrap;
        }
        .signal-item {
            background: #1c2128;
            padding: 8px 14px;
            border-radius: 8px;
            font-size: 13px;
        }

        .refresh-btn {
            background: #21262d;
            color: #c9d1d9;
            border: 1px solid #30363d;
            padding: 8px 16px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 13px;
        }
        .refresh-btn:hover { background: #30363d; }
    </style>
</head>
<body>
    <div class="navbar">
        <h1>🤖 Crypto Trading Bot</h1>
        <div>
            <span id="status" class="status-badge status-running">● RUNNING</span>
            <button class="refresh-btn" onclick="loadData()">↻ Refresh</button>
        </div>
    </div>

    <div class="container">
        <!-- Key Metrics -->
        <div class="grid">
            <div class="card">
                <h3>Balance</h3>
                <div class="value neutral" id="balance">$0.00</div>
            </div>
            <div class="card">
                <h3>Daily PnL</h3>
                <div class="value" id="dailyPnl">$0.00</div>
            </div>
            <div class="card">
                <h3>Open Positions</h3>
                <div class="value neutral" id="posCount">0</div>
            </div>
            <div class="card">
                <h3>Win Rate</h3>
                <div class="value neutral" id="winRate">-</div>
            </div>
            <div class="card">
                <h3>Fear & Greed</h3>
                <div class="value" id="fearGreed">-</div>
            </div>
            <div class="card">
                <h3>Last Signal</h3>
                <div class="value" id="lastSignal">NONE</div>
            </div>
        </div>

        <!-- Open Positions -->
        <div class="card" style="margin-bottom:24px">
            <h3>📊 Open Positions</h3>
            <table>
                <thead>
                    <tr><th>Symbol</th><th>Side</th><th>Size</th><th>Entry</th><th>Unrealized PnL</th><th>Liq. Price</th></tr>
                </thead>
                <tbody id="positionsTable">
                    <tr><td colspan="6" style="text-align:center;color:#8b949e">No open positions</td></tr>
                </tbody>
            </table>
        </div>

        <!-- Recent Trades -->
        <div class="card" style="margin-bottom:24px">
            <h3>📋 Recent Trades</h3>
            <table>
                <thead>
                    <tr><th>Time</th><th>Type</th><th>Side</th><th>Price</th><th>PnL</th><th>Status</th></tr>
                </thead>
                <tbody id="tradesTable">
                    <tr><td colspan="6" style="text-align:center;color:#8b949e">No trades yet</td></tr>
                </tbody>
            </table>
        </div>

        <!-- Risk Status -->
        <div class="card">
            <h3>🛡️ Risk Status</h3>
            <div class="signal-box" id="riskStatus">
                <span class="signal-item">Loading...</span>
            </div>
        </div>
    </div>

    <script>
        async function loadData() {
            try {
                const [statusRes, tradesRes] = await Promise.all([
                    fetch('/api/status'),
                    fetch('/api/trades')
                ]);
                const status = await statusRes.json();
                const trades = await tradesRes.json();
                updateUI(status, trades);
            } catch(e) {
                console.error('Failed to load data:', e);
            }
        }

        function updateUI(status, trades) {
            // Balance
            document.getElementById('balance').textContent = '$' + (status.balance || 0).toFixed(2);

            // Daily PnL
            const pnl = status.risk_status?.daily_pnl || 0;
            const pnlEl = document.getElementById('dailyPnl');
            pnlEl.textContent = '$' + pnl.toFixed(2);
            pnlEl.className = 'value ' + (pnl >= 0 ? 'positive' : 'negative');

            // Positions
            document.getElementById('posCount').textContent = (status.positions || []).length;

            // Last signal
            const sig = status.last_signal;
            if (sig) {
                const sigEl = document.getElementById('lastSignal');
                sigEl.textContent = sig.action + ' (' + (sig.confidence * 100).toFixed(0) + '%)';
                sigEl.className = 'value ' + (sig.action === 'LONG' ? 'positive' : sig.action === 'SHORT' ? 'negative' : 'neutral');
            }

            // Fear & Greed
            const fg = status.news_sentiment;
            if (fg) {
                const fgEl = document.getElementById('fearGreed');
                fgEl.textContent = (fg.fear_greed_value || '-') + ' ' + (fg.fear_greed_label || '');
                fgEl.className = 'value ' + (fg.fear_greed_value > 50 ? 'positive' : fg.fear_greed_value < 30 ? 'negative' : 'neutral');
            }

            // Positions table
            const posTable = document.getElementById('positionsTable');
            if (status.positions && status.positions.length > 0) {
                posTable.innerHTML = status.positions.map(p => `
                    <tr>
                        <td>${p.symbol}</td>
                        <td style="color:${p.side === 'long' ? '#3fb950' : '#f85149'}">${p.side.toUpperCase()}</td>
                        <td>${p.size}</td>
                        <td>$${p.entry_price.toFixed(2)}</td>
                        <td class="${p.unrealized_pnl >= 0 ? 'positive' : 'negative'}">$${p.unrealized_pnl.toFixed(2)}</td>
                        <td>$${p.liquidation_price.toFixed(2)}</td>
                    </tr>
                `).join('');
            }

            // Trades table
            const tradeTable = document.getElementById('tradesTable');
            if (trades.length > 0) {
                tradeTable.innerHTML = trades.slice(-20).reverse().map(t => `
                    <tr>
                        <td>${(t.timestamp || '').substring(0, 16)}</td>
                        <td>${t.type || '-'}</td>
                        <td style="color:${t.side === 'buy' ? '#3fb950' : '#f85149'}">${(t.direction || t.side || '').toUpperCase()}</td>
                        <td>$${(t.entry_price || t.exit_price || 0).toFixed(2)}</td>
                        <td class="${(t.pnl || 0) >= 0 ? 'positive' : 'negative'}">${t.pnl ? '$' + t.pnl.toFixed(2) : '-'}</td>
                        <td>${t.status || '-'}</td>
                    </tr>
                `).join('');
            }

            // Win Rate
            const closedTrades = trades.filter(t => t.status === 'closed' && t.pnl !== undefined);
            if (closedTrades.length > 0) {
                const wins = closedTrades.filter(t => t.pnl > 0).length;
                document.getElementById('winRate').textContent = (wins / closedTrades.length * 100).toFixed(0) + '%';
            }

            // Risk status
            const riskEl = document.getElementById('riskStatus');
            if (status.risk_status) {
                const rs = status.risk_status;
                riskEl.innerHTML = `
                    <span class="signal-item">Daily PnL: $${rs.daily_pnl?.toFixed(2) || '0'}</span>
                    <span class="signal-item">Consec. Losses: ${rs.consecutive_losses || 0}</span>
                    <span class="signal-item">Risk: ${rs.adjusted_risk?.toFixed(1) || '1.5'}%</span>
                    <span class="signal-item">${rs.is_paused ? '⏸️ PAUSED' : '✅ ACTIVE'}</span>
                `;
            }

            // Status badge
            const statusEl = document.getElementById('status');
            statusEl.textContent = '● ' + (status.status || 'UNKNOWN').toUpperCase();
            statusEl.className = 'status-badge status-' + (status.status || 'stopped');
        }

        // Auto-refresh every 30 seconds
        loadData();
        setInterval(loadData, 30000);
    </script>
</body>
</html>"""

    @app.route('/')
    def dashboard():
        return render_template_string(DASHBOARD_HTML)

    @app.route('/api/status')
    def api_status():
        return jsonify(_bot_data)

    @app.route('/api/trades')
    def api_trades():
        trades = trade_logger.get_trades(limit=100)
        return jsonify(trades)

    @app.route('/api/daily')
    def api_daily():
        pnl = trade_logger.get_daily_pnl()
        trades = trade_logger.get_daily_trades()
        return jsonify({
            'date': datetime.utcnow().strftime('%Y-%m-%d'),
            'pnl': pnl,
            'trade_count': len(trades),
        })

    @app.route('/api/backtest')
    def api_backtest():
        """Serve latest backtest results"""
        results_path = os.path.join('data', 'backtest_results.json')
        if os.path.exists(results_path):
            with open(results_path, 'r') as f:
                return jsonify(json.load(f))
        return jsonify({'error': 'No backtest results found'})

    return app
