import sys; sys.path.insert(0, '/opt/patch-agent'); import agent_parts.api; import agent_parts._hub as h; print('routes:', [str(r) for r in h._hub.app.url_map.iter_rules() if 'health' in str(r)])
