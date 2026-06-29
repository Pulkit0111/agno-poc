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
