from portal.devpod.service import _normalize_clone_url


def test_github_https_to_ssh_with_git_suffix() -> None:
    result = _normalize_clone_url("https://github.com/ag-flow/rag.git")
    assert result == "git@github.com:ag-flow/rag.git"


def test_github_https_to_ssh_without_git_suffix() -> None:
    result = _normalize_clone_url("https://github.com/gaelgael5/devpod-ui")
    assert result == "git@github.com:gaelgael5/devpod-ui.git"


def test_github_https_trailing_slash() -> None:
    result = _normalize_clone_url("https://github.com/ag-flow/doc/")
    assert result == "git@github.com:ag-flow/doc.git"


def test_already_ssh_unchanged() -> None:
    result = _normalize_clone_url("git@github.com:ag-flow/rag.git")
    assert result == "git@github.com:ag-flow/rag.git"


def test_non_github_unchanged() -> None:
    assert _normalize_clone_url("https://gitlab.com/x/y.git") == "https://gitlab.com/x/y.git"
