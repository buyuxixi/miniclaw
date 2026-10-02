"""Exercise actual plugin discovery, tool dispatch and SQLite, without a model."""

import json
import os
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix="miniclaw-check-") as temporary:
        fixture = Path(temporary)
        home = fixture / "home"
        workspace = fixture / "workspace"
        workspace.mkdir()
        (workspace / "product.txt").write_text("教学商品：保温杯，容量400ml。", encoding="utf-8")
        (fixture / "outside.txt").write_text("must not be exposed", encoding="utf-8")
        (workspace / ".env").write_text("TEST_SECRET=must-not-be-exposed", encoding="utf-8")
        (workspace / "large.txt").write_bytes(b"a" * (64 * 1024 + 1))
        (workspace / "binary.txt").write_bytes(b"\xff\xfe")
        shutil.copytree(ROOT / "plugins" / "miniclaw-files", home / "plugins" / "miniclaw-files", ignore=shutil.ignore_patterns("__pycache__"))
        os.environ["HERMES_HOME"] = str(home)
        from hermes_cli.config import atomic_config_write
        atomic_config_write(home / "config.yaml", {
            "platform_toolsets": {"cli": ["miniclaw-files"]},
            "tools": {"tool_search": {"enabled": "off"}},
            "plugins": {"enabled": ["miniclaw-files"], "entries": {"miniclaw-files": {"settings": {"workspace": str(workspace)}}}},
        })
        from model_tools import get_tool_definitions, handle_function_call
        definitions = get_tool_definitions(enabled_toolsets=["miniclaw-files"], quiet_mode=True)
        names = {definition["function"]["name"] for definition in definitions}
        assert names == {"miniclaw_read_file", "miniclaw_list_files"}, names

        def invoke(name, args):
            return json.loads(handle_function_call(name, args, task_id="miniclaw-offline", enabled_toolsets=["miniclaw-files"]))

        read = invoke("miniclaw_read_file", {"path": "product.txt"})
        assert read["success"] and "400ml" in read["content"], read
        listing = invoke("miniclaw_list_files", {"path": "."})
        assert listing["success"] and ".env" not in {entry["name"] for entry in listing["entries"]}, listing
        failures = [
            {"path": "../outside.txt"}, {"path": str(fixture / "outside.txt")},
            {"path": ".env"}, {"path": "missing.txt"}, {"path": 42}, {},
            {"path": "product.txt", "extra": True}, {"path": "large.txt"},
            {"path": "binary.txt"}, {"path": "."},
        ]
        for args in failures:
            result = invoke("miniclaw_read_file", args)
            assert result.get("success") is False, (args, result)
            assert "must-not-be-exposed" not in json.dumps(result), result

        from hermes_state import SessionDB
        db_path = home / "fixture-state.db"
        db = SessionDB(db_path=db_path)
        session_id = "miniclaw-offline-fixture"
        db.create_session(session_id, "cli")
        db.append_message(session_id, "user", content="读取教学商品")
        db.append_message(session_id, "assistant", tool_calls=[{
            "id": "fixture-call-1", "type": "function",
            "function": {"name": "miniclaw_read_file", "arguments": '{"path":"product.txt"}'},
        }])
        db.append_message(session_id, "tool", tool_name="miniclaw_read_file", tool_call_id="fixture-call-1", content=json.dumps(read, ensure_ascii=False))
        db.close()
        reopened = SessionDB(db_path=db_path)
        try:
            messages = reopened.get_messages(session_id)
            assert [message["role"] for message in messages] == ["user", "assistant", "tool"], messages
            assert messages[2]["tool_call_id"] == "fixture-call-1", messages[2]
            assert reopened.get_messages("another-session") == []
        finally:
            reopened.close()
        print(json.dumps({"status": "passed", "plugin_tools": sorted(names), "successful_tool_cases": 2,
                          "rejected_file_cases": len(failures), "sqlite_reopen": True,
                          "model_called": False, "agent_loop_verified": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
