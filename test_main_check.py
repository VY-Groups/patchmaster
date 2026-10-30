import sys
sys.path.insert(0, 'agent')
src = open('agent/agent.py', encoding='utf-8-sig').read()
src = src.replace('if __name__ == "__main__":', 'if False:')
ns = {'__name__': 'agent_test', '__file__': 'agent/agent.py'}
exec(compile(src, 'agent/agent.py', 'exec'), ns)
print('main:', ns.get('main'))
print('co_varnames:', ns['main'].__code__.co_varnames[:5])
print('defaults:', ns['main'].__defaults__)