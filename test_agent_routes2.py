import sys
sys.path.insert(0, 'agent')
src = open('agent/agent.py', encoding='utf-8-sig').read()
src = src.replace('if __name__ == "__main__":', 'print("BEFORE main: before_request_funcs=", app.before_request_funcs)\nprint("BEFORE main: error_handlers=", app.error_handler_spec)\nif __name__ == "__main__":')
ns = {'__name__': 'agent_test', '__file__': 'agent/agent.py'}
exec(compile(src, 'agent/agent.py', 'exec'), ns)
print('done')