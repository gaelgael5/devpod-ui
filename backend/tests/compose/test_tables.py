from portal.db import tables


def test_compose_tables_declared() -> None:
    assert tables.compose_template.name == "compose_template"
    assert tables.compose_deployment.name == "compose_deployment"
    assert tables.compose_deployment_log.name == "compose_deployment_log"
    # colonnes clés présentes
    tcols = set(tables.compose_template.c.keys())
    assert {"id", "name", "tags", "version", "compose_content", "parameters", "source"} <= tcols
    dcols = set(tables.compose_deployment.c.keys())
    expected_dcols = {
        "id", "template_id", "node_id", "owner_login", "env_values", "host_ports", "status",
    }
    assert expected_dcols <= dcols
    lcols = set(tables.compose_deployment_log.c.keys())
    assert {"id", "deployment_id", "operation", "content", "started_at", "finished_at"} <= lcols
