"""scripts/llm.py against temporary env files (never the real .env)."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("llm_script", ROOT / "scripts" / "llm.py")
llm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(llm)


def test_use_rewrites_only_the_provider_line(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# keep me\nLLM_PROVIDER=mock\nCLOUD_API_KEY=secret\nLLM_MAX_RPM=18\n")
    assert llm.main(["--env-file", str(env), "use", "auto"]) == 0
    assert env.read_text() == "# keep me\nLLM_PROVIDER=auto\nCLOUD_API_KEY=secret\nLLM_MAX_RPM=18\n"


def test_use_creates_env_from_template(tmp_path):
    (tmp_path / ".env.example").write_text("LLM_PROVIDER=mock\nLLM_SLOT_GROUP=A\n")
    env = tmp_path / ".env"
    llm.main(["--env-file", str(env), "use", "local"])
    assert env.read_text().splitlines() == ["LLM_PROVIDER=local", "LLM_SLOT_GROUP=A"]


def test_use_appends_when_line_missing(tmp_path):
    env = tmp_path / ".env"
    env.write_text("LLM_SLOT_GROUP=A\n")
    llm.main(["--env-file", str(env), "use", "cloud"])
    assert env.read_text().endswith("LLM_PROVIDER=cloud\n")


def test_status_never_prints_the_key(tmp_path, capsys):
    env = tmp_path / ".env"
    env.write_text(
        "LLM_PROVIDER=cloud\nCLOUD_BASE_URL=https://platform.example/v1\n"
        "CLOUD_API_KEY=super-secret-value\nCLOUD_MODEL_COMPACT=c\nCLOUD_MODEL_MID=m\n"
        "CLOUD_EMBEDDING_MODEL=bge-m3\nCLOUD_EMBEDDING_DIM=1024\n"
    )
    assert llm.main(["--env-file", str(env), "status"]) == 0
    out = capsys.readouterr().out
    assert "super-secret-value" not in out and "key: set" in out
    assert "hack-04-chunks-cloud-bge-m3" in out and "platform.example" in out


def test_check_reports_unreachable_host(tmp_path, capsys):
    env = tmp_path / ".env"
    env.write_text("LLM_PROVIDER=mock\nMOCK_BASE_URL=http://127.0.0.1:9/v1\nMOCK_API_KEY=x\n")
    assert llm.main(["--env-file", str(env), "check"]) == 1
    assert "GET /models" in capsys.readouterr().out
