import hashlib
import os
from pathlib import Path
import sys
import pytest

TARGET = "test_category_exploration_sends_type_first_guidance_to_the_model"

class PromptBodyMeter:
    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_call(self, item):
        if item.name != TARGET:
            yield
            return
        prior_trace = sys.gettrace()
        def trace(frame, event, arg):
            if frame.f_code.co_name == TARGET and event == "return":
                bodies = frame.f_locals.get("sent_request_bodies", [])
                rows = []
                for index, body in enumerate(bodies):
                    rows.append(
                        f"request_body[{index}] bytes={len(body)} sha256={hashlib.sha256(body).hexdigest()}"
                    )
                rows.insert(0, f"captured_request_bodies={len(bodies)}")
                Path(os.environ["CERES_METER_OUTPUT"]).write_text("\n".join(rows) + "\n", encoding="utf-8")
            return trace
        sys.settrace(trace)
        try:
            yield
        finally:
            sys.settrace(prior_trace)

def pytest_configure(config):
    config.pluginmanager.register(PromptBodyMeter(), "ceres-prompt-body-meter")
