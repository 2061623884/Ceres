"""The production LangGraph adapter.

The graph is the sole turn orchestration path. Import
:mod:`app.agent.graph.graph` explicitly rather than through this package: the
package import stays free of a LangGraph import so an environment without the
adapter's dependencies can still import the modules beside it.
"""
