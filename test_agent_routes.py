import sys
sys.path.insert(0, 'agent')
src = open('agent/agent.py', encoding='utf-8-sig').read()
src = src.replace('if __name__ == "__main__":', 'if False:')
ns = {'__name__': '__main__', '__file__': 'agent/agent.py'}
exec(compile(src, 'agent/agent.py', 'exec'), ns)
print('app routes with health:', [str(r) for r in ns['app'].url_map.iter_rules() if 'health' in str(r)])
print('FLASK_AVAILABLE:', ns.get('FLASK_AVAILABLE'))
print('total routes:', len(list(ns['app'].url_map.iter_rules())))