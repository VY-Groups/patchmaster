import sys
sys.path.insert(0, 'agent')
# Clean up debug prints first by exec'ing the source
src = open('agent/agent.py', encoding='utf-8-sig').read()
# Remove debug prints
import re
src = src.replace('''# DEBUG: print route count
try:
    import sys as _dbg_sys
    print("DEBUG before update: HUB app routes:", [str(r) for r in _hub.app.url_map.iter_rules() if 'health' in str(r)], flush=True)
    print("DEBUG before update: module app routes:", [str(r) for r in app.url_map.iter_rules() if 'health' in str(r)], flush=True)
    print("DEBUG before update: same object:", app is _hub.app, flush=True)
except Exception as _dbg_e:
    print("DEBUG error:", _dbg_e, flush=True)
''', '')
src = src.replace('''# DEBUG: after update
try:
    print("DEBUG after update: HUB app routes:", [str(r) for r in _hub.app.url_map.iter_rules() if 'health' in str(r)], flush=True)
    print("DEBUG after update: module app routes:", [str(r) for r in app.url_map.iter_rules() if 'health' in str(r)], flush=True)
    print("DEBUG after update: same object:", app is _hub.app, flush=True)
except Exception as _dbg_e:
    print("DEBUG after update error:", _dbg_e, flush=True)
''', '')
src = src.replace('''            print("DEBUG in main: app id=", id(_app), "health routes=", [str(r) for r in _app.url_map.iter_rules() if "health" in str(r)], flush=True)
            from werkzeug.serving import run_simple
            run_simple("0.0.0.0", port, _app, use_reloader=False, use_debugger=False)''', '''            app.run(host="0.0.0.0", port=port)''')

ns = {'__name__': '__main__', '__file__': 'agent/agent.py'}
exec(compile(src, 'agent/agent.py', 'exec'), ns)
# Now run main
ns['main'](port=8100, metrics_port=9200)