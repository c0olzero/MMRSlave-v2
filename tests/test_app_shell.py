"""Settings saving, Steam sign-in checks, the bundled brain fallback and installing updates."""

import io
import json
import tomllib
import zipfile
from urllib.parse import parse_qs, urlparse

import pytest

from mmrslave import config, steam, updater
from mmrslave.config import Settings, save_setting

BASE = "http://127.0.0.1:8765"
SID = 76561198000000042


def test_save_setting_keeps_comments_and_adds_sections(tmp_path):
    p = tmp_path / "m.toml"
    p.write_text('[player]\n# your id\nsteam_id = 0\n\n[paths]\ndata_dir = "D:/x"\n', encoding="utf-8")
    save_setting("player", "steam_id", SID, p)
    save_setting("updates", "auto_update", True, p)
    save_setting("updates", "auto_update", False, p)
    text = p.read_text(encoding="utf-8")
    assert "# your id" in text
    raw = tomllib.loads(text)
    assert raw["player"]["steam_id"] == SID
    assert raw["paths"]["data_dir"] == "D:/x"
    assert raw["updates"] == {"auto_update": False}


def test_model_file_prefers_own_then_brain(tmp_path, monkeypatch):
    brain = tmp_path / "brain"
    brain.mkdir()
    (brain / "winprob.pt").write_bytes(b"x")
    monkeypatch.setattr(config, "BRAIN_DIR", brain)
    s = Settings(data_dir=tmp_path / "data")
    assert s.model_file("winprob.pt") == brain / "winprob.pt"
    assert s.model_file("context.pt") == s.models_dir / "context.pt"  # neither: your folder
    s.models_dir.mkdir(parents=True)
    (s.models_dir / "winprob.pt").write_bytes(b"mine")
    assert s.model_file("winprob.pt") == s.models_dir / "winprob.pt"


def _steam_answer(login: steam.SteamLogin, steam_id: int = SID) -> dict[str, str]:
    """What Steam sends back to the callback for a sign-in started with login_url()."""
    sent = parse_qs(urlparse(login.login_url(BASE)).query)
    return_to = sent["openid.return_to"][0]
    claimed = f"https://steamcommunity.com/openid/id/{steam_id}"
    return {"state": parse_qs(urlparse(return_to).query)["state"][0], "openid.mode": "id_res",
            "openid.return_to": return_to, "openid.claimed_id": claimed, "openid.identity": claimed,
            "openid.sig": "abc", "openid.signed": "signed,op_endpoint"}


class _Resp:
    def __init__(self, text):
        self.status_code, self.text = 200, text


def test_steam_login_accepts_answer_steam_confirms(monkeypatch):
    seen = {}

    def fake_post(url, data, **kw):
        seen.update(data)
        return _Resp("ns:http://specs.openid.net/auth/2.0\nis_valid:true\n")
    monkeypatch.setattr(steam.httpx, "post", fake_post)
    login = steam.SteamLogin()
    assert login.verify(_steam_answer(login), BASE) == SID
    assert seen["openid.mode"] == "check_authentication"


def test_steam_login_rejects_forged_or_replayed(monkeypatch):
    monkeypatch.setattr(steam.httpx, "post", lambda *a, **k: _Resp("is_valid:false\n"))
    login = steam.SteamLogin()
    with pytest.raises(steam.SteamLoginError):
        login.verify(_steam_answer(login), BASE)            # Steam says it didn't sign it
    monkeypatch.setattr(steam.httpx, "post", lambda *a, **k: _Resp("is_valid:true\n"))
    answer = _steam_answer(login)
    login.verify(answer, BASE)
    with pytest.raises(steam.SteamLoginError):
        login.verify(answer, BASE)                          # one-time state already used
    with pytest.raises(steam.SteamLoginError):
        steam.SteamLogin().verify(_steam_answer(login), BASE)  # started by another app instance
    other = _steam_answer(login)
    other["openid.return_to"] = "http://evil.example/auth/steam/callback?state=" + other["state"]
    with pytest.raises(steam.SteamLoginError):
        login.verify(other, BASE)


def test_dependency_names():
    text = '[project]\ndependencies = ["gem-dota>=0.14", "uvicorn[standard]>=0.32", "Foo_Bar ; python_version>\'3\'"]\n'
    assert updater._dependency_names(text) == {"gem-dota", "uvicorn", "foo-bar"}


def test_install_bundle_unpacks_code_and_brain_only(tmp_path, monkeypatch):
    sha = "a" * 40
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        top = f"MMRSlave-v2-{sha}/"
        z.writestr(top + "src/mmrslave/__init__.py", "")
        z.writestr(top + "src/mmrslave/web/static/app.js", "//")
        z.writestr(top + "brain/winprob.pt", "w")
        z.writestr(top + "packaging/runtime.json", json.dumps({"runtime": 1}))
        z.writestr(top + "tests/test_x.py", "no")
        z.writestr(top + "README.md", "no")
    data = buf.getvalue()

    class FakeStream:
        status_code = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def iter_bytes(self, n): yield data
    monkeypatch.setattr(updater.httpx, "stream", lambda *a, **k: FakeStream())
    monkeypatch.setattr(updater, "APP_DIR", tmp_path / "app")
    monkeypatch.setattr(updater, "CURRENT_FILE", tmp_path / "app" / "current.txt")
    updater._install_bundle(sha, "2026-11-12T00:00:00Z", lambda m: None)
    root = tmp_path / "app" / sha
    assert (root / "src/mmrslave/web/static/app.js").exists()
    assert (root / "brain/winprob.pt").exists()
    assert (root / "packaging/runtime.json").exists()
    assert not (root / "tests").exists() and not (root / "README.md").exists()
    assert json.loads((root / "VERSION.json").read_text())["sha"] == sha
    assert (tmp_path / "app" / "current.txt").read_text() == sha
    assert not list((tmp_path / "app").glob("*.zip"))
