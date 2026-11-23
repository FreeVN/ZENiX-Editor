"""Pytest-configuratie voor de ZENiX model-operaties.

- zet ``app/`` op ``sys.path`` zodat ``core``/``model_service`` importeerbaar zijn;
- laadt de projectsleutel uit ``.secrets/project.key`` als ``ZENIX_KEY``;
- controleert dat ``app/build/ZenixTool.class`` aanwezig is en exact overeenkomt met
  de opgeslagen sha256 in ``app/build/ZenixTool.class.sha256`` (deterministisch;
  git bewaart geen mtimes, dus timestamps zijn geen bewijs. De tests compileren
  niets zelf; bouwen gebeurt expliciet met ``javac``, zie ``tool/excel/README.md``);
- levert een fixture die een sample naar een tijdelijke map kopieert.
"""
import hashlib
import os
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")
if APP not in sys.path:
    sys.path.insert(0, APP)

SAMPLES = ("Duizendpoot", "Levensvreugde")

TOOL_CLASS = os.path.join(APP, "build", "ZenixTool.class")
TOOL_STAMP = os.path.join(APP, "build", "ZenixTool.class.sha256")

BUILD_HINT = (
    'javac --release 17 -cp "app/lib/configuration-1.4.1.jar:app/lib/jaxb-api.jar" '
    "-d app/build app/java/ZenixTool.java && "
    "sha256sum app/build/ZenixTool.class > app/build/ZenixTool.class.sha256"
)


def _ensure_key():
    if os.environ.get("ZENIX_KEY", "").strip():
        return
    path = os.path.join(ROOT, ".secrets", "project.key")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            os.environ["ZENIX_KEY"] = f.read().strip()
    if not os.environ.get("ZENIX_KEY", "").strip():
        pytest.skip(
            "geen projectsleutel: zet ZENIX_KEY of .secrets/project.key "
            "(de publieke checkout bevat geen sleutel en geen projecten)",
            allow_module_level=False)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _check_compiled_tool():
    """Faal expliciet als het klassenbestand ontbreekt of niet bij de stamp hoort.

    De controle is inhoudelijk (sha256), niet op mtime: git bewaart geen
    timestamps, dus een checkout-volgorde mag het resultaat niet bepalen. De
    tests bouwen niets: een ontbrekende JDK mag de suite niet raken.
    """
    if not os.path.exists(TOOL_CLASS):
        pytest.fail(
            "app/build/ZenixTool.class ontbreekt; bouw de Java-helper eerst:\n  " + BUILD_HINT)
    if not os.path.exists(TOOL_STAMP):
        pytest.fail(
            "app/build/ZenixTool.class.sha256 ontbreekt; maak het bestand aan met:\n  "
            + BUILD_HINT)
    with open(TOOL_STAMP, encoding="utf-8") as f:
        parts = f.read().split()
    expected = parts[0].strip().lower() if parts else ""
    actual = _sha256(TOOL_CLASS)
    if actual != expected:
        pytest.fail(
            "app/build/ZenixTool.class heeft niet de inhoud die in "
            "app/build/ZenixTool.class.sha256 staat (sha256 %s != %s); "
            "herbouw de Java-helper:\n  %s" % (actual, expected or "<leeg>", BUILD_HINT))


@pytest.fixture(scope="session", autouse=True)
def prepared_environment():
    """Laad de sleutel en controleer het klassenbestand (zonder te compileren)."""
    _ensure_key()
    _check_compiled_tool()


@pytest.fixture(params=SAMPLES)
def sample(request, tmp_path):
    """Kopie van een voorbeeldproject in een tijdelijke map (bron blijft ongemoeid)."""
    name = request.param
    src = os.path.join(ROOT, "samples", name, name + ".rbtproject")
    if not os.path.exists(src):
        pytest.skip("geen voorbeeldprojecten in deze checkout (samples/ ontbreekt)")
    dst = tmp_path / (name + ".rbtproject")
    shutil.copyfile(src, dst)
    return dst
