from portal.compose import db
from portal.compose.models import ComposeParam


def test_row_to_template_parses_parameters() -> None:
    row = {
        "id": "t1", "name": "T", "description": "", "tags": ["web"], "version": "1",
        "compose_content": "services: {}",
        "parameters": [{"key": "P", "label": "P", "type": "port", "required": True}],
        "source": "user", "created_at": None, "updated_at": None,
    }
    tpl = db._row_to_template(row)
    assert tpl.id == "t1"
    assert tpl.parameters == [ComposeParam(key="P", label="P", type="port", required=True)]
