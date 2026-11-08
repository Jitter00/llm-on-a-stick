"""Grader unit tests with a fake lab: no Docker needed."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from llm_on_a_stick.grading import canaries, configdiff, run
from llm_on_a_stick.grading import grade as grade_mod
from llm_on_a_stick.grading.checks import available, run_check
from llm_on_a_stick.grading.context import GradeContext
from llm_on_a_stick.grading.labstate import Node, load_nodes
from llm_on_a_stick.grading.results import CheckResult, summarise
from llm_on_a_stick.grading.template import TemplateError, render, render_value
from llm_on_a_stick.tasks import CheckSpec, find_task, load_task

FIXTURES = Path(__file__).parent / "fixtures" / "tasks"
DEMO = FIXTURES / "cfg-mgmt" / "demo-frr-config-retrieval"

FRR1 = """Building configuration...

Current configuration:
!
frr version 10.7.1_git
hostname frr1
!
interface eth3
 description stick-abc12345
 ip address 10.1.1.1/24
exit
!
router bgp 65101
 neighbor 10.0.1.0 remote-as 65001
exit
!
end
"""
SRL2 = 'set / interface ethernet-1/1 description "to frr1"\nset / interface ethernet-1/1 admin-state enable\n'


class FakeLab:
    def __init__(self) -> None:
        self.configs = {"frr1": FRR1, "srl2": SRL2}
        self.sessions = {"frr1": {"10.0.1.0": "established", "10.0.2.0": "active"}}
        self._nodes = {
            "frr1": Node("frr1", "frr", "172.30.30.21", "clab-stick-base-frr1"),
            "srl2": Node("srl2", "srlinux", "172.30.30.12", "clab-stick-base-srl2"),
            "h1": Node("h1", "host", "172.30.30.31", "clab-stick-base-h1"),
        }

    def nodes(self) -> dict[str, Node]:
        return self._nodes

    def running_config(self, node: str, fmt: str = "flat") -> str:
        return self.configs[node]

    def bgp_sessions(self, node: str) -> dict[str, str]:
        return self.sessions[node]


def make_ctx(
    tmp_path: Path, lab: FakeLab | None = None, canary: dict[str, str] | None = None
) -> GradeContext:
    lab = lab or FakeLab()
    run_dir = tmp_path / "run"
    (run_dir / "work").mkdir(parents=True)
    (run_dir / "baseline").mkdir()
    for name, cfg in lab.configs.items():
        (run_dir / "baseline" / f"{name}.cfg").write_text(cfg)
    info = run.RunInfo(
        task_id="t", task_dir=DEMO, run_id="r", run_dir=run_dir, started_at=datetime.now(UTC),
        canaries=canary or {}, prompt="p", topology="base",
    )  # fmt: skip
    return GradeContext(run=info, lab=lab)  # type: ignore[arg-type]


def check(ctx: GradeContext, type_: str, **params: Any) -> CheckResult:
    variables = run.template_vars(ctx.run.canaries, ctx.run.workspace, ctx.lab)
    return run_check(CheckSpec(type=type_, params=params), ctx, variables)


# --------------------------------------------------------------------------- templating & canaries


def test_render_and_types() -> None:
    v = {"canaries": {"asn": "65001"}, "nodes": {"frr1": {"mgmt_ip": "1.2.3.4"}}, "n": 3}
    assert render("ip {{ nodes.frr1.mgmt_ip }} asn {{canaries.asn}}", v) == "ip 1.2.3.4 asn 65001"
    assert render_value("{{ n }}", v) == 3  # a lone placeholder keeps its type
    assert render_value({"a": ["x{{ n }}"]}, v) == {"a": ["x3"]}
    with pytest.raises(TemplateError):
        render("{{ canaries.nope }}", v)


def test_canaries_are_seeded_distinct_and_valid() -> None:
    spec = {"a": "asn", "b": "asn", "ip": "ipv4", "d": "description", "h": "hostname"}
    first, second = canaries.generate(spec, seed=7), canaries.generate(spec, seed=7)
    assert first == second
    assert first["a"] != first["b"]
    assert 64512 <= int(first["a"]) <= 65534
    assert first["ip"].startswith("198.18.")
    assert canaries.env_vars({"host-desc": "x"}) == {"STICK_CANARY_HOST_DESC": "x"}
    with pytest.raises(ValueError):
        canaries.generate({"x": "nonsense"})


def test_canary_kinds_match_task_schema() -> None:
    schema = json.loads((Path(__file__).parents[1] / "src/llm_on_a_stick/data/task.schema.json").read_text())
    assert set(schema["properties"]["canaries"]["additionalProperties"]["enum"]) == set(canaries.KINDS)


# --------------------------------------------------------------------------- config diff & outcomes


def test_frr_normalisation_drops_banners_and_comments() -> None:
    lines = configdiff.normalise(FRR1, "frr")
    assert "Building configuration..." not in lines
    assert "!" not in lines
    assert "end" not in lines
    assert "description stick-abc12345" in lines


def test_compare_is_order_insensitive_multiset() -> None:
    d = configdiff.compare(["a", "b", "b"], ["b", "a", "b"])
    assert d.identical
    d = configdiff.compare(["a", "b", "b"], ["a", "b", "c"])
    assert d.missing == ["b"]
    assert d.extra == ["c"]


def _r(status: str, weight: float = 1, hints: list[str] | None = None) -> CheckResult:
    return CheckResult(name="c", type="t", status=status, weight=weight, hints=hints or [])  # type: ignore[arg-type]


def test_summarise() -> None:
    assert summarise([_r("pass"), _r("pass")])[:2] == ("pass", 1.0)
    assert summarise([_r("fail"), _r("fail")])[:2] == ("fail", 0.0)
    assert summarise([_r("pass", 3), _r("fail", 1, ["no-output"])]) == ("partial", 0.75, ["no-output"])
    assert summarise([_r("pass"), _r("error", hints=["env-error"])])[0] == "error"


# --------------------------------------------------------------------------- checks


def test_registry_has_builtins() -> None:
    assert {"file_matches_running_config", "bgp_session", "no_change_outside", "netbox_object"} <= set(
        available()
    )


def test_file_matches_running_config(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path)
    out = ctx.run.workspace / "frr1.cfg"

    out.write_text(FRR1)
    assert check(ctx, "file_matches_running_config", node="frr1", path="frr1.cfg").status == "pass"

    out.write_text("\n".join(FRR1.splitlines()[:9]))  # cut off: truncated
    r = check(ctx, "file_matches_running_config", node="frr1", path="frr1.cfg")
    assert (r.status, r.hints) == ("fail", ["truncated-output"])

    out.write_text(FRR1 + " ip address 10.9.9.9/32\n")  # invented line
    r = check(ctx, "file_matches_running_config", node="frr1", path="frr1.cfg")
    assert (r.status, r.hints) == ("fail", ["hallucinated-value"])
    assert r.observed["extra_sample"] == ["ip address 10.9.9.9/32"]

    out.write_text("show running-config\n% Unknown command\n")  # nothing like a config
    assert check(ctx, "file_matches_running_config", node="frr1", path="frr1.cfg").hints == ["wrong-format"]

    out.unlink()
    assert check(ctx, "file_matches_running_config", node="frr1", path="frr1.cfg").hints == ["no-output"]


def test_workspace_escape_is_an_error(tmp_path: Path) -> None:
    r = check(make_ctx(tmp_path), "file_exists", path="../../etc/passwd")
    assert r.status == "error"


def test_file_contains_with_canary(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, canary={"desc": "stick-abc12345"})
    (ctx.run.workspace / "frr1.cfg").write_text(FRR1)
    assert (
        check(ctx, "file_contains", path="frr1.cfg", lines=["description {{ canaries.desc }}"]).status
        == "pass"
    )
    ctx.run.canaries["desc"] = "stick-00000000"
    assert (
        check(ctx, "file_contains", path="frr1.cfg", lines=["description {{ canaries.desc }}"]).status
        == "fail"
    )


def test_json_file_matches(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path)
    f = ctx.run.workspace / "facts.json"
    f.write_text(json.dumps({"asn": 65101, "neighbors": ["10.0.2.0", "10.0.1.0"], "extra": 1}))
    ok = check(
        ctx,
        "json_file_matches",
        path="facts.json",
        expected={"asn": "65101", "neighbors": ["10.0.1.0", "10.0.2.0"]},
    )
    assert ok.status == "pass"
    bad = check(ctx, "json_file_matches", path="facts.json", expected={"asn": "65001"})
    assert (bad.status, bad.hints) == ("fail", ["hallucinated-value"])
    f.write_text("{not json")
    assert check(ctx, "json_file_matches", path="facts.json", expected={"asn": 1}).hints == ["wrong-format"]


def test_bgp_session(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path)
    assert check(ctx, "bgp_session", node="frr1", peer="10.0.1.0").status == "pass"
    r = check(ctx, "bgp_session", node="frr1", peer="10.0.2.0")
    assert (r.status, r.observed, r.hints) == ("fail", "active", ["wrong-config"])
    assert check(ctx, "bgp_session", node="frr1", peer="9.9.9.9").observed == "<no such neighbor>"


def test_running_config_contains(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path)
    assert check(ctx, "running_config_contains", node="frr1", lines=["router bgp 65101"]).status == "pass"
    r = check(ctx, "running_config_contains", node="frr1", lines=["router bgp 65999"])
    assert r.hints == ["incomplete-config"]


def test_no_change_outside(tmp_path: Path) -> None:
    lab = FakeLab()
    ctx = make_ctx(tmp_path, lab)
    assert check(ctx, "no_change_outside").status == "pass"
    lab.configs["srl2"] = SRL2.replace("to frr1", "changed")
    r = check(ctx, "no_change_outside")
    assert (r.status, r.hints, list(r.observed)) == ("fail", ["collateral-change"], ["srl2"])
    assert check(ctx, "no_change_outside", allowed=["srl2"]).status == "pass"


def test_bad_task_parameters_are_errors(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path)
    assert check(ctx, "bgp_session", node="frr1").status == "error"  # missing peer
    assert check(ctx, "no_such_check").status == "error"
    assert check(ctx, "file_exists", path="{{ canaries.missing }}").message.startswith("bad task parameters")


# --------------------------------------------------------------------------- tasks, runs, grade


def test_demo_task_loads_and_is_findable_by_id() -> None:
    task = load_task(DEMO)
    assert task.checks[0].weight == 3
    assert find_task("demo-frr-config-retrieval", [FIXTURES]).id == task.id


def test_start_and_grade_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lab = FakeLab()
    task = load_task(DEMO)
    task.setup = None  # the real setup script needs Docker; the integration test covers it
    info = run.start(task, tmp_path / "runs", lab, seed=1)  # type: ignore[arg-type]

    assert info.workspace.is_dir()
    assert str(info.workspace) in info.prompt
    assert "172.30.30.21" in info.prompt
    assert (info.baseline_dir / "frr1.cfg").read_text() == FRR1
    assert not (info.baseline_dir / "h1.cfg").exists()
    assert run.latest(tmp_path / "runs") == info.run_dir

    # the "agent" saves the config, with this run's canary planted
    canary = info.canaries["host_desc"]
    lab.configs["frr1"] = FRR1.replace("stick-abc12345", canary)
    (info.baseline_dir / "frr1.cfg").write_text(lab.configs["frr1"])
    (info.workspace / "frr1.cfg").write_text(lab.configs["frr1"])

    monkeypatch.setattr(grade_mod, "load_task", lambda _: task)
    result = grade_mod.grade(info.run_dir, lab=lab)  # type: ignore[arg-type]
    assert (result.outcome, result.score) == ("pass", 1.0)
    saved = json.loads((info.run_dir / "result.json").read_text())
    assert saved["outcome"] == "pass"
    assert saved["canaries"] == {"host_desc": canary}


def test_base_topology_nodes_have_os_labels() -> None:
    nodes = load_nodes("base")
    assert {n.os for n in nodes.values()} == {"srlinux", "frr", "host"}
    assert nodes["frr1"].container == "clab-stick-base-frr1"


def test_result_schema_file_is_up_to_date() -> None:
    """src/llm_on_a_stick/data/result.schema.json is what consumers of result.json rely on."""
    from llm_on_a_stick.grading.results import Result

    path = Path(__file__).parents[1] / "src/llm_on_a_stick/data/result.schema.json"
    shipped = json.loads(path.read_text())
    shipped.pop("$id")
    assert shipped == Result.model_json_schema(), "regenerate result.schema.json (see docs/grading.md)"
