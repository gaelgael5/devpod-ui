from __future__ import annotations

import io
import zipfile

from portal.messages.models import Jinja2Template
from portal.routes.jinja_templates import build_templates_zip


def test_build_templates_zip_roundtrip() -> None:
    templates = [
        Jinja2Template(key="welcome", culture="fr", body="Bonjour | salut\nligne2"),
        Jinja2Template(key="welcome", culture="en", body="Hi there"),
    ]
    data = build_templates_zip(templates)
    zf = zipfile.ZipFile(io.BytesIO(data))
    names = set(zf.namelist())
    assert names == {"toc.txt", "welcome.fr.j2", "welcome.en.j2"}
    # bodies préservés à l'identique
    assert zf.read("welcome.fr.j2").decode() == "Bonjour | salut\nligne2"
    assert zf.read("welcome.en.j2").decode() == "Hi there"
    # toc : 4 champs, description sanitizée (pas de pipe, pas de newline)
    toc = zf.read("toc.txt").decode().splitlines()
    assert "welcome.fr.j2 | welcome | fr | Bonjour / salut" in toc
    assert "welcome.en.j2 | welcome | en | Hi there" in toc


def test_build_templates_zip_empty() -> None:
    data = build_templates_zip([])
    zf = zipfile.ZipFile(io.BytesIO(data))
    assert zf.namelist() == ["toc.txt"]
    assert zf.read("toc.txt").decode() == ""
