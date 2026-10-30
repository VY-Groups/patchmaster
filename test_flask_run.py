from flask import Flask, jsonify
app = Flask(__name__)

@app.route('/health')
def h():
    return jsonify({'status': 'ok'})

print('routes:', [str(r) for r in app.url_map.iter_rules()])
from werkzeug.serving import run_simple
run_simple('0.0.0.0', 8101, app, use_reloader=False, use_debugger=False)