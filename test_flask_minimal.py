from flask import Flask, jsonify
app = Flask(__name__)

@app.route('/health')
def h():
    return jsonify({'status': 'ok'})

print('routes:', [str(r) for r in app.url_map.iter_rules()])
app.run(host='0.0.0.0', port=8123)