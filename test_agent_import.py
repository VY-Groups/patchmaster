import agent_parts.api; print('api imported'); from agent_parts._hub import _hub; print('app:', _hub.app); print('routes:', [str(r) for r in _hub.app.url_map.iter_rules() if 'health' in str(r)])
