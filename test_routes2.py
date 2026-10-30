import sys
sys.path.insert(0, 'agent')
for k in list(sys.modules.keys()):
    if 'agent' in k or 'agent_parts' in k:
        del sys.modules[k]
src = open('agent/agent.py', encoding='utf-8-sig').read()
src = src.replace('if __name__ == "__main__":', 'print("ROUTES:", [str(r) for r in app.url_map.iter_rules() if "health" in str(r)])\nif __name__ == "__main__":')
ns = {'__name__': '__main__', '__file__': 'agent/agent.py'}
exec(compile(src, 'agent/agent.py', 'exec'), ns)
print("done")