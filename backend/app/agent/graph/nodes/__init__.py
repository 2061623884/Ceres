"""The production graph's nodes, one module per top-level node.

``load_context`` / ``understand`` / ``retrieve`` / ``mutation`` / ``answer`` /
``respond`` are the six nodes; ``staging`` holds pure helpers shared by
``mutation`` and ``answer`` and is not a graph node.
"""
