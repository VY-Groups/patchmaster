"""Split implementation of agent.py (plan.md S0-5).

agent.py publishes its own namespace in HUB before importing the submodules
here; every submodule reads hub state through the _hub proxy, which resolves
on each attribute access.  That keeps patch("agent.agent.run_cmd") /
monkeypatch.setattr(agent_mod, ...) visible to moved code, and lets these
files load in both import identities (flat ``agent`` module and ``agent.agent``
package) as well as when agent.py runs as a script.
"""

HUB = None  # namespace dict of the agent.py hub, published by agent.py


class _HubProxy:
    """Read-through proxy to the live agent.py namespace."""

    def __getattr__(self, name):
        ns = HUB
        if ns is None:
            raise RuntimeError(
                "agent.py has not published its namespace yet; "
                "import agent.agent (or run agent.py) first"
            )
        try:
            return ns[name]
        except KeyError:
            raise AttributeError(name) from None


_hub = _HubProxy()
