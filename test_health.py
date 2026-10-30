import sys
sys.path.insert(0, 'agent')
src = open('agent/agent.py', encoding='utf-8-sig').read()
src = src.replace('if __name__ == "__main__":', 'print("BEFORE main: routes=", [str(r) for r in app.url_map.iter_rules() if "health" in str(r)])\nif __name__ == "__main__":')
ns = {'__name__': 'agent_test', '__file__': 'agent/agent.py'}
exec(compile(src, 'agent/agent.py', 'exec'), ns)
print('AFTER exec: routes=', [str(r) for r in ns['app'].url_map.iter_rules() if 'health' in str(r)])
print('total routes:', len(list(ns['app'].url_map.iter_rules())))