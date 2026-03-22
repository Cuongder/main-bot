"""
Backtest Report Generator
Creates detailed performance reports with charts
"""
import os
import json
from datetime import datetime
import pandas as pd
from utils.logger import logger


class BacktestReport:
    """Generate HTML reports from backtest results"""

    def __init__(self, output_dir='data'):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def generate_report(self, metrics: dict, save_html=True) -> str:
        """
        Generate comprehensive backtest report.

        Args:
            metrics: Output from BacktestEngine.run()
            save_html: Whether to save as HTML file

        Returns:
            HTML string or file path
        """
        trades = metrics.get('trades', [])
        equity_data = metrics.get('equity_curve', [])

        # Prepare data for charts
        equity_labels = []
        equity_values = []
        if equity_data:
            # Sample every Nth point to keep chart manageable
            step = max(1, len(equity_data) // 500)
            for i in range(0, len(equity_data), step):
                eq = equity_data[i]
                equity_labels.append(str(eq['timestamp'])[:16])
                equity_values.append(round(eq['balance'], 2))

        # Trades by exit reason
        reason_counts = {}
        for t in trades:
            reason = t.get('exit_reason', 'unknown')
            reason_counts[reason] = reason_counts.get(reason, 0) + 1

        # Monthly breakdown
        monthly_pnl = {}
        for t in trades:
            month = str(t.get('exit_time', ''))[:7]  # YYYY-MM
            if month:
                monthly_pnl[month] = monthly_pnl.get(month, 0) + t.get('pnl', 0)

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Backtest Report - {datetime.now().strftime('%Y-%m-%d %H:%M')}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', system-ui, sans-serif;
            background: #0a0e17;
            color: #e1e5ee;
            padding: 20px;
        }}
        .header {{
            text-align: center;
            padding: 30px;
            background: linear-gradient(135deg, #1a1f35, #0d1117);
            border-radius: 16px;
            margin-bottom: 24px;
            border: 1px solid #30363d;
        }}
        .header h1 {{
            font-size: 28px;
            background: linear-gradient(135deg, #58a6ff, #3fb950);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .header p {{ color: #8b949e; margin-top: 8px; }}

        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }}

        .metric-card {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 12px;
            padding: 20px;
            text-align: center;
        }}
        .metric-card .value {{
            font-size: 28px;
            font-weight: bold;
            margin: 8px 0;
        }}
        .metric-card .label {{ color: #8b949e; font-size: 13px; text-transform: uppercase; }}
        .positive {{ color: #3fb950; }}
        .negative {{ color: #f85149; }}
        .neutral {{ color: #58a6ff; }}

        .target-badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: bold;
        }}
        .target-pass {{ background: #1b4332; color: #3fb950; }}
        .target-fail {{ background: #3d1f1f; color: #f85149; }}

        .chart-container {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 24px;
        }}
        .chart-container h3 {{ margin-bottom: 16px; color: #c9d1d9; }}

        table {{
            width: 100%;
            border-collapse: collapse;
            background: #161b22;
            border-radius: 12px;
            overflow: hidden;
        }}
        th, td {{ padding: 10px 14px; text-align: left; border-bottom: 1px solid #21262d; }}
        th {{ background: #1c2128; color: #8b949e; font-size: 12px; text-transform: uppercase; }}
        tr:hover {{ background: #1c2128; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>📊 Backtest Performance Report</h1>
        <p>ETH/USDT | 5x Leverage | ${metrics.get('initial_capital', 500)} Initial Capital</p>
        <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    </div>

    <!-- Target Check -->
    <div style="text-align: center; margin-bottom: 24px;">
        <span class="target-badge {'target-pass' if metrics.get('meets_target') else 'target-fail'}">
            {'✅ TARGET MET' if metrics.get('meets_target') else '❌ TARGET NOT MET'}:
            Profit Factor {'>' if metrics.get('profit_factor', 0) > 1.5 else '<'} 1.5
            | Max Drawdown {'<' if metrics.get('max_drawdown_pct', 100) < 20 else '>'} 20%
        </span>
    </div>

    <!-- Key Metrics -->
    <div class="grid">
        <div class="metric-card">
            <div class="label">Net Profit</div>
            <div class="value {'positive' if metrics.get('net_profit', 0) >= 0 else 'negative'}">
                ${metrics.get('net_profit', 0):.2f}
            </div>
            <div class="label">{metrics.get('net_profit_pct', 0):.1f}%</div>
        </div>
        <div class="metric-card">
            <div class="label">Win Rate</div>
            <div class="value neutral">{metrics.get('win_rate', 0):.1f}%</div>
            <div class="label">{metrics.get('winning_trades', 0)}W / {metrics.get('losing_trades', 0)}L</div>
        </div>
        <div class="metric-card">
            <div class="label">Profit Factor</div>
            <div class="value {'positive' if metrics.get('profit_factor', 0) > 1.5 else 'negative'}">
                {metrics.get('profit_factor', 0):.2f}
            </div>
            <div class="label">Target: > 1.5</div>
        </div>
        <div class="metric-card">
            <div class="label">Max Drawdown</div>
            <div class="value {'positive' if metrics.get('max_drawdown_pct', 100) < 20 else 'negative'}">
                {metrics.get('max_drawdown_pct', 0):.1f}%
            </div>
            <div class="label">Target: < 20%</div>
        </div>
        <div class="metric-card">
            <div class="label">Sharpe Ratio</div>
            <div class="value neutral">{metrics.get('sharpe_ratio', 0):.2f}</div>
            <div class="label">Annualized</div>
        </div>
        <div class="metric-card">
            <div class="label">Total Trades</div>
            <div class="value neutral">{metrics.get('total_trades', 0)}</div>
            <div class="label">Avg R:R {metrics.get('avg_rr_ratio', 0):.1f}</div>
        </div>
        <div class="metric-card">
            <div class="label">Avg Win</div>
            <div class="value positive">${metrics.get('avg_win', 0):.2f}</div>
            <div class="label">Best: ${metrics.get('largest_win', 0):.2f}</div>
        </div>
        <div class="metric-card">
            <div class="label">Avg Loss</div>
            <div class="value negative">${metrics.get('avg_loss', 0):.2f}</div>
            <div class="label">Worst: ${metrics.get('largest_loss', 0):.2f}</div>
        </div>
    </div>

    <!-- Equity Curve -->
    <div class="chart-container">
        <h3>📈 Equity Curve</h3>
        <canvas id="equityChart" height="100"></canvas>
    </div>

    <!-- Monthly PnL -->
    <div class="chart-container">
        <h3>📅 Monthly PnL</h3>
        <canvas id="monthlyChart" height="80"></canvas>
    </div>

    <!-- Trade History -->
    <div class="chart-container">
        <h3>📋 Recent Trades (Last 50)</h3>
        <div style="overflow-x: auto;">
            <table>
                <thead>
                    <tr>
                        <th>Entry Time</th>
                        <th>Side</th>
                        <th>Entry</th>
                        <th>Exit</th>
                        <th>PnL</th>
                        <th>Reason</th>
                        <th>Balance</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(self._trade_row(t) for t in trades[-50:])}
                </tbody>
            </table>
        </div>
    </div>

    <script>
        // Equity Curve Chart
        new Chart(document.getElementById('equityChart'), {{
            type: 'line',
            data: {{
                labels: {json.dumps(equity_labels)},
                datasets: [{{
                    label: 'Balance ($)',
                    data: {json.dumps(equity_values)},
                    borderColor: '#58a6ff',
                    backgroundColor: 'rgba(88, 166, 255, 0.1)',
                    fill: true,
                    tension: 0.3,
                    pointRadius: 0,
                }}]
            }},
            options: {{
                responsive: true,
                scales: {{
                    x: {{ display: false }},
                    y: {{
                        ticks: {{ color: '#8b949e' }},
                        grid: {{ color: '#21262d' }},
                    }}
                }},
                plugins: {{ legend: {{ labels: {{ color: '#c9d1d9' }} }} }}
            }}
        }});

        // Monthly PnL Chart
        new Chart(document.getElementById('monthlyChart'), {{
            type: 'bar',
            data: {{
                labels: {json.dumps(list(monthly_pnl.keys()))},
                datasets: [{{
                    label: 'PnL ($)',
                    data: {json.dumps([round(v, 2) for v in monthly_pnl.values()])},
                    backgroundColor: {json.dumps(['#3fb950' if v >= 0 else '#f85149' for v in monthly_pnl.values()])},
                }}]
            }},
            options: {{
                responsive: true,
                scales: {{
                    x: {{ ticks: {{ color: '#8b949e' }}, grid: {{ display: false }} }},
                    y: {{ ticks: {{ color: '#8b949e' }}, grid: {{ color: '#21262d' }} }}
                }},
                plugins: {{ legend: {{ labels: {{ color: '#c9d1d9' }} }} }}
            }}
        }});
    </script>
</body>
</html>"""

        if save_html:
            file_path = os.path.join(
                self.output_dir,
                f"backtest_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
            )
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(html)
            logger.info(f"📄 Report saved to {file_path}")
            return file_path

        return html

    def _trade_row(self, trade: dict) -> str:
        """Generate HTML table row for a trade"""
        pnl = trade.get('pnl', 0)
        pnl_class = 'positive' if pnl >= 0 else 'negative'
        side_color = '#3fb950' if trade.get('side') == 'LONG' else '#f85149'

        return f"""
        <tr>
            <td>{str(trade.get('entry_time', ''))[:16]}</td>
            <td style="color: {side_color}">{trade.get('side', '')}</td>
            <td>${trade.get('entry_price', 0):.2f}</td>
            <td>${trade.get('exit_price', 0):.2f}</td>
            <td class="{pnl_class}">${pnl:.2f}</td>
            <td>{trade.get('exit_reason', '')}</td>
            <td>${trade.get('balance_after', 0):.2f}</td>
        </tr>"""

    def save_metrics_json(self, metrics: dict):
        """Save metrics to JSON for programmatic access"""
        # Remove non-serializable data
        save_data = {k: v for k, v in metrics.items() if k != 'equity_curve'}
        save_data['trades'] = [
            {k: str(v) if not isinstance(v, (int, float, bool, str)) else v
             for k, v in t.items()}
            for t in save_data.get('trades', [])
        ]

        file_path = os.path.join(self.output_dir, 'backtest_results.json')
        with open(file_path, 'w') as f:
            json.dump(save_data, f, indent=2)
        logger.info(f"📊 Metrics saved to {file_path}")
