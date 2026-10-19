from caelza_body.agent.memory import Memory


def test_remember_queues_on_failure_then_flushes():
    state = {"up": False}
    def call_tool(name, args):
        if not state["up"]:
            raise RuntimeError("offline")
        return {"id": "n1"}
    m = Memory(call_tool)
    assert m.remember("fact while offline") == ""
    state["up"] = True
    assert m.flush_pending() == 1
    assert m.flush_pending() == 0
