from bott.skills.connectors import registry


def test_register_and_classify():
    reg = registry.Registry()

    class Jira(registry.OrgConnector):
        name = "jira"
        def tools(self): return []

    class Gmail(registry.UserConnector):
        name = "gmail"
        def tools(self): return []

    reg.register(Jira())
    reg.register(Gmail())
    names = reg.list_names()
    assert names == {"org": ["jira"], "user": ["gmail"]}


def test_all_tools_flattens_in_order():
    reg = registry.Registry()

    def a_tools(): return ["a1", "a2"]
    def b_tools(): return ["b1"]

    reg.register(registry.FunctionConnector("a", "org_credential", a_tools))
    reg.register(registry.FunctionConnector("b", "domain_delegated", b_tools))
    assert reg.all_tools() == ["a1", "a2", "b1"]


def test_function_connector_auth_and_scope():
    org = registry.FunctionConnector("jira", "org_credential", lambda: [])
    deleg = registry.FunctionConnector("gmail", "domain_delegated", lambda: [])
    assert org.auth == "org_credential" and org.scope == "org"
    assert deleg.auth == "domain_delegated" and deleg.scope == "user"


def test_all_tools_evaluated_live():
    reg = registry.Registry()
    state = {"on": False}
    reg.register(registry.FunctionConnector(
        "x", "org_credential", lambda: ["t"] if state["on"] else []))
    assert reg.all_tools() == []
    state["on"] = True
    assert reg.all_tools() == ["t"]
