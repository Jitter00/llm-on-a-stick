"""Transcript hints (grading/transcript.py): one positive and one negative case per rule."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_on_a_stick.grading.transcript import transcript_hints

ROOT = Path(__file__).parents[1]
# Outputs srl2-bgp.cfg and frr1-bgp.cfg; no_change_outside with allowed: [].
TASK = ROOT / "sections/cfg-mgmt/config-section-bgp"
SRL2 = "sshpass -p 'NokiaSrl1!' ssh -o StrictHostKeyChecking=no admin@172.30.30.12"
FRR1 = "sshpass -p 'admin' ssh -o StrictHostKeyChecking=no admin@172.30.30.21"
SRL_REJECT = "Parsing error: Unknown token 'configuration'. Options are ['#', '/', 'info']\n"


def cmd(command: str, output: str = "", exit_code: int = 0) -> dict:
    return {
        "kind": "command",
        "command": command,
        "output": output,
        "exit_code": exit_code,
        "timed_out": False,
    }


def make_run(
    tmp_path: Path,
    commands: list[dict],
    files: dict[str, str] | None = None,
    stop_reason: str = "done",
    task_dir: Path = TASK,
) -> Path:
    run = tmp_path / "run"
    (run / "work").mkdir(parents=True)
    entries = [{"kind": "start"}, *commands, {"kind": "end", "stop_reason": stop_reason}]
    (run / "transcript.jsonl").write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    (run / "run.json").write_text(
        json.dumps({"task_dir": str(task_dir), "topology": "base"}), encoding="utf-8"
    )
    for name, text in (files or {}).items():
        (run / "work" / name).write_text(text, encoding="utf-8")
    return run


GOOD_FILES = {
    "srl2-bgp.cfg": "set / network-instance default protocols bgp\n",
    "frr1-bgp.cfg": "router bgp 1\n",
}
# Writes both files and reads them back: no hints.
CLEAN = [
    cmd(f"{SRL2} 'info flat' | grep '^set / network-instance default protocols bgp' > /work/srl2-bgp.cfg"),
    cmd(f"cd /work && {FRR1} 'show running-config' | sed -n '/^router bgp/,/^exit/p' > frr1-bgp.cfg"),
    cmd("cd /work && wc -l srl2-bgp.cfg && cat frr1-bgp.cfg", "1 srl2-bgp.cfg\nrouter bgp 1\n"),
]


def test_clean_attempt_has_no_hints(tmp_path: Path) -> None:
    assert transcript_hints(make_run(tmp_path, CLEAN, GOOD_FILES)) == []


# --------------------------------------------------------------------------- wrong-dialect


def test_wrong_dialect_needs_repeated_rejections(tmp_path: Path) -> None:
    probe = [cmd(f"{SRL2} 'show configuration'", SRL_REJECT, 1)]
    assert "wrong-dialect" not in transcript_hints(make_run(tmp_path / "once", probe + CLEAN, GOOD_FILES))
    twice = [*probe, cmd(f'{SRL2} "show running-config | grep bgp"', SRL_REJECT, 1)]
    assert "wrong-dialect" in transcript_hints(make_run(tmp_path / "twice", twice + CLEAN, GOOD_FILES))


def test_wrong_dialect_ignores_native_syntax_and_unrejected_commands(tmp_path: Path) -> None:
    native = [
        # `show running-config` is FRR's own syntax.
        cmd(f"{FRR1} 'show running-config'", "router bgp 1\n"),
        cmd(f"{FRR1} 'show running-config'", "router bgp 1\n"),
        # Foreign syntax, but the node didn't reject it (e.g. an SR Linux alias).
        cmd(f"{SRL2} 'show running-config'", "set / system name host-name srl2\n"),
        cmd(f"{SRL2} 'show running-config'", "set / system name host-name srl2\n"),
    ]
    assert "wrong-dialect" not in transcript_hints(make_run(tmp_path, native + CLEAN, GOOD_FILES))


def test_wrong_dialect_reads_commands_piped_into_ssh(tmp_path: Path) -> None:
    piped = [cmd(f"printf 'show configuration\\nexit\\n' | {SRL2}", SRL_REJECT) for _ in range(2)]
    assert "wrong-dialect" in transcript_hints(make_run(tmp_path, piped + CLEAN, GOOD_FILES))


# --------------------------------------------------------------------------- attempted-change


@pytest.mark.parametrize(
    "command",
    [
        f"{SRL2} 'enter candidate; delete / interface ethernet-1/1; commit now'",
        f"{FRR1} \"vtysh -c 'conf t' -c 'router bgp 1'\"",
        "python3 -c \"m = manager.connect(host='172.30.30.11'); m.edit_config(target='running', config=x)\"",
    ],
)
def test_attempted_change_on_a_do_not_change_task(tmp_path: Path, command: str) -> None:
    assert "attempted-change" in transcript_hints(make_run(tmp_path, [cmd(command), *CLEAN], GOOD_FILES))


def test_attempted_change_ignores_search_patterns(tmp_path: Path) -> None:
    searches = [
        cmd("grep -n 'commit now' /work/notes.txt"),
        cmd("grep -c 'enter candidate' /work/srl2-bgp.cfg"),
        cmd(f"{SRL2} 'info flat' | grep 'configure terminal'"),
    ]
    assert "attempted-change" not in transcript_hints(make_run(tmp_path, searches + CLEAN, GOOD_FILES))


def test_attempted_change_needs_a_no_change_check(tmp_path: Path) -> None:
    task = tmp_path / "task"
    task.mkdir()
    (task / "task.yaml").write_text(
        (TASK / "task.yaml").read_text(encoding="utf-8").split("  - type: no_change")[0]
    )
    change = [cmd(f"{SRL2} 'enter candidate; commit now'"), *CLEAN]
    assert "attempted-change" not in transcript_hints(make_run(tmp_path, change, GOOD_FILES, task_dir=task))


# --------------------------------------------------------------------------- no-verification


def test_no_verification_when_a_file_is_never_read_back(tmp_path: Path) -> None:
    unchecked = CLEAN[:2]
    assert "no-verification" in transcript_hints(make_run(tmp_path, unchecked, GOOD_FILES))


def test_no_verification_counts_reads_in_the_same_command_and_globs(tmp_path: Path) -> None:
    same_command = [
        cmd(f"{SRL2} 'info flat' > /work/srl2-bgp.cfg; wc -l /work/srl2-bgp.cfg"),
        cmd(f"{FRR1} 'show running-config' > /work/frr1-bgp.cfg"),
        cmd("ls -l /work/*.cfg"),
    ]
    assert "no-verification" not in transcript_hints(make_run(tmp_path, same_command, GOOD_FILES))


def test_no_verification_after_a_rewrite(tmp_path: Path) -> None:
    rewritten = [*CLEAN, cmd("cd /work && sed -i 's/^[0-9]*://' srl2-bgp.cfg")]
    assert "no-verification" in transcript_hints(make_run(tmp_path, rewritten, GOOD_FILES))


def test_no_verification_python_write_then_print(tmp_path: Path) -> None:
    script = "python3 - <<'EOF'\nopen('/work/srl2-bgp.cfg', 'w').write(x)\nprint('Success!')\nEOF"
    hints = transcript_hints(make_run(tmp_path, [*CLEAN, cmd(script, "Success!\n")], GOOD_FILES))
    assert "no-verification" in hints
    read_back = cmd("python3 -c \"print(open('/work/srl2-bgp.cfg').read())\"")
    hints = transcript_hints(make_run(tmp_path / "b", [*CLEAN, cmd(script), read_back], GOOD_FILES))
    assert "no-verification" not in hints


def test_no_verification_skips_files_that_were_not_delivered(tmp_path: Path) -> None:
    # The write left an empty file: `no-output` covers that already.
    only_frr_unchecked = [CLEAN[0], cmd("cat /work/srl2-bgp.cfg"), CLEAN[1]]
    assert "no-verification" in transcript_hints(make_run(tmp_path / "a", only_frr_unchecked, GOOD_FILES))
    files = {**GOOD_FILES, "frr1-bgp.cfg": ""}
    assert "no-verification" not in transcript_hints(make_run(tmp_path / "b", only_frr_unchecked, files))


# --------------------------------------------------------------------------- ignored-error


def test_ignored_error_when_the_file_holds_an_error(tmp_path: Path) -> None:
    files = {**GOOD_FILES, "srl2-bgp.cfg": SRL_REJECT}
    assert "ignored-error" in transcript_hints(make_run(tmp_path, CLEAN, files))


def test_ignored_error_when_the_last_write_failed(tmp_path: Path) -> None:
    failed = [
        *CLEAN,
        cmd(f"{SRL2} 'show configuration' > /work/srl2-bgp.cfg; cat /work/srl2-bgp.cfg", SRL_REJECT),
    ]
    assert "ignored-error" in transcript_hints(make_run(tmp_path, failed, GOOD_FILES))


def test_ignored_error_not_after_a_successful_retry(tmp_path: Path) -> None:
    retried = [cmd(f"{SRL2} 'show configuration' > /work/srl2-bgp.cfg", SRL_REJECT), *CLEAN]
    assert "ignored-error" not in transcript_hints(make_run(tmp_path, retried, GOOD_FILES))


def test_ignored_error_only_when_the_model_said_it_had_finished(tmp_path: Path) -> None:
    files = {**GOOD_FILES, "srl2-bgp.cfg": SRL_REJECT}
    assert "ignored-error" not in transcript_hints(make_run(tmp_path, CLEAN, files, stop_reason="max_turns"))
    # The runner passes the stop reason before the transcript has its `end` entry.
    run = make_run(tmp_path / "b", CLEAN, files, stop_reason="max_turns")
    assert "ignored-error" in transcript_hints(run, stop_reason="done")


# --------------------------------------------------------------------------- MCP tool calls


def call(tool: str, failed: bool = False, **arguments: object) -> dict:
    return {"kind": "tool_call", "tool": tool, "arguments": arguments, "is_error": failed, "timed_out": False}


MCP_TASK = ROOT / "sections/zabbix/zabbix-add-host"


def test_no_verification_when_nothing_is_read_after_a_change_through_a_tool(tmp_path: Path) -> None:
    blind = [call("hostgroup_get"), call("host_create", host="r1")]
    assert transcript_hints(make_run(tmp_path / "a", blind, task_dir=MCP_TASK)) == ["no-verification"]
    checked = [*blind, call("host_get")]
    assert transcript_hints(make_run(tmp_path / "b", checked, task_dir=MCP_TASK)) == []
    reads_only = [call("host_get"), call("device_ports_get")]
    assert transcript_hints(make_run(tmp_path / "c", reads_only, task_dir=MCP_TASK)) == []


def test_an_aws_cli_call_changes_something_unless_it_describes_gets_or_lists(tmp_path: Path) -> None:
    describe = call("call_aws", cli_command="aws ec2 describe-volumes --filters Name=status,Values=available")
    delete = call("call_aws", cli_command="aws ec2 delete-volume --volume-id vol-1")
    assert transcript_hints(make_run(tmp_path / "a", [describe, delete], task_dir=MCP_TASK)) == [
        "no-verification"
    ]
    assert transcript_hints(make_run(tmp_path / "b", [delete, describe], task_dir=MCP_TASK)) == []


def test_ignored_error_when_the_last_change_through_a_tool_failed(tmp_path: Path) -> None:
    failed = [call("host_create", failed=True), call("host_get")]
    assert transcript_hints(make_run(tmp_path / "a", failed, task_dir=MCP_TASK)) == ["ignored-error"]
    retried = [call("host_create", failed=True), call("host_create"), call("host_get")]
    assert transcript_hints(make_run(tmp_path / "b", retried, task_dir=MCP_TASK)) == []
    gave_up = make_run(tmp_path / "c", failed, task_dir=MCP_TASK, stop_reason="max_turns")
    assert transcript_hints(gave_up) == []


# --------------------------------------------------------------------------- old runs


def test_removed_task_and_missing_transcript(tmp_path: Path) -> None:
    gone = make_run(
        tmp_path, [cmd(f"{SRL2} 'show configuration'", SRL_REJECT)] * 2, task_dir=tmp_path / "gone"
    )
    assert transcript_hints(gone) == ["wrong-dialect"]  # the file rules need the task's checks
    empty = tmp_path / "empty"
    empty.mkdir()
    assert transcript_hints(empty) == []
