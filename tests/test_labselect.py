"""CI's choice of lab tests from a pull request's changed files (llm_on_a_stick.labselect)."""

from __future__ import annotations

from llm_on_a_stick import paths, services, tasks
from llm_on_a_stick.labselect import Selection, select

TASKS = [tasks.load_task(p) for p in tasks.discover([paths.sections_dir()])]
SERVICES = services.available()


def sel(*changed: str) -> Selection:
    return select(changed, TASKS, SERVICES)


def test_docs_and_unit_tests_need_no_lab() -> None:
    assert sel("docs/tasks.md", "README.md", "TODO.md", "tests/test_grading.py", "sections/README.md").empty
    assert sel().empty


def test_a_task_folder_selects_its_section_and_the_services_it_needs() -> None:
    s = sel("sections/nautobot/nautobot-graphql/setup.sh")
    assert s == Selection(sections={"nautobot"}, services={"nautobot"}, core=False)
    s = sel("sections/cfg-mgmt/running-config-cli-frr/task.yaml")
    assert s.sections == {"cfg-mgmt"} and "oxidized" in s.services and not s.core


def test_a_service_selects_every_section_that_requires_it() -> None:
    s = sel("services/oxidized/router.db")
    assert s.services == {"oxidized"} and s.sections == {"cfg-mgmt"} and not s.core
    assert sel("tests/integration/test_netbox.py") == sel("services/netbox/seed.yaml")
    assert sel("services/netbox/seed.yaml").sections == {"netbox", "librenms"}  # librenms-netbox-sync


def test_shared_code_selects_the_generic_tests_and_floor_tasks_only() -> None:
    for path in (
        "src/llm_on_a_stick/grading/run.py", "sections/_lib/common.sh", "topologies/base.clab.yml",
        "configs/frr/frr1/frr.conf", "uv.lock", "tests/integration/conftest.py",
        ".github/workflows/ci-pr.yml",
        "something/new.txt",
    ):  # fmt: skip
        s = sel(path)
        assert s.core and not s.sections and not s.services, path


def test_the_nautobot_pr_combines_both() -> None:
    s = sel("src/llm_on_a_stick/grading/sotstate.py", "services/nautobot/compose.yaml", "docs/services.md")
    assert s == Selection(sections={"nautobot"}, services={"nautobot"}, core=True)


def test_selection_round_trips_through_the_environment() -> None:
    s = Selection(sections={"netbox", "nautobot"}, services={"netbox"}, core=True)
    assert Selection.from_env(s.env()) == s
    assert Selection.from_env(Selection().env()) == Selection()
    assert Selection.from_env({}) is None  # not set: run everything


def test_each_section_has_one_floor_task() -> None:
    floors = sorted(t.section for t in TASKS if t.floor)
    assert floors == sorted({t.section for t in TASKS})


def test_the_cloud_sections_share_moto() -> None:
    s = sel("services/moto/compose.yaml")
    assert s == Selection(sections={"aws", "terraform"}, services={"moto"}, core=False)
    assert sel("sections/terraform/tf-drift/setup.sh") == Selection(sections={"terraform"}, services={"moto"})
    assert sel("images/toolbox/aws_snapshot.py").core  # the image's tools are shared code


def test_the_librenms_section_and_its_service() -> None:
    s = sel("services/librenms/service.yaml")
    assert s == Selection(sections={"librenms"}, services={"librenms", "netbox"}, core=False)
    assert sel("sections/librenms/librenms-alert-rule/task.yaml").sections == {"librenms"}
    assert sel("configs/srl/srl1.cli").core  # the boot config every section starts from


def test_the_zabbix_section_and_its_service() -> None:
    s = sel("services/zabbix/service.yaml")
    assert s == Selection(sections={"zabbix"}, services={"zabbix"}, core=False)
    assert sel("sections/zabbix/zabbix-trigger/setup.sh") == Selection(
        sections={"zabbix"}, services={"zabbix"}
    )
    assert sel("tests/integration/test_zabbix.py").services == {"zabbix"}
