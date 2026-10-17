from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import runpy
import zipfile
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
CHECK_COMMANDS = {
    "lint": ["uv", "run", "ruff", "check", "src", "tests", ".github/ci"],
    "build": ["uv", "build"],
    "wheel-consumer": ["uv", "run", "--no-sync", "python", ".github/ci/wheel-consumer.py",
                       "--result-dir", ".ci-results"],
    "comments": ["uv", "run", "--no-sync", "python", ".github/ci/comment-check.py",
                 "--result-dir", ".ci-results"],
}
WHEEL_SELECTORS = (
    "tests/test_host_import_isolation.py",
    "tests/test_cli_bind.py::test_occupied_listen_address_refuses_before_database_or_journal_work",
    "tests/test_service.py::test_managed_readiness_preserves_the_owned_config_upgrade_refusal",
    "tests/test_inspection_stability.py::test_minimum_mcp_cap_can_inspect_a_plain_captured_source",
    "tests/test_edge_boundaries.py::test_producer_capture_authority_never_grants_memory_read_authority",
    "tests/test_judge_settings.py::test_waiting_judge_mutations_recheck_live_operator_authority",
    "tests/test_judge_settings.py::test_judge_file_failures_keep_publication_identity_and_explicit_recovery",
    "tests/test_native_status.py::test_native_inventory_ends_descendants_and_closes_pipes_on_failure",
    "tests/test_native_status.py::test_native_inventory_survives_real_normal_shutdown",
    "tests/test_recovery.py::test_remote_bad_first_outbox_cannot_starve_retained_healthy_batch",
    "tests/test_recovery.py::test_recovery_preserves_failure_until_a_new_cycle_finishes",
    "tests/test_remote_cancellation.py::test_readonly_ready_stop_cancels_real_tls_response_before_business_dispatch",
    "tests/test_remote_cancellation.py::test_already_dispatched_business_request_drains_response_without_retry",
    "tests/test_ci_accounting.py::test_cleanup_after_esrch_cannot_kill_a_reused_group[probe-native]",
    "tests/test_ci_accounting.py::test_cleanup_after_esrch_cannot_kill_a_reused_group[term-native]",
    "tests/test_ci_accounting.py::test_cleanup_retains_identity_through_the_final_group_signal[after-probe-native]",
    "tests/test_ci_accounting.py::test_cleanup_retains_identity_through_the_final_group_signal[already-reaped-native]",
    "tests/test_ci_accounting.py::test_real_exited_group_cleanup_keeps_other_owned_process[native]",
    "tests/test_ci_accounting.py::test_live_group_permission_error_is_not_terminal[native]",
    "tests/test_ci_accounting.py::test_exited_leader_permission_error_with_live_member[with-member-native]",
    "tests/test_health_backend.py",
    "tests/test_health_code.py",
    "tests/test_health_inference.py",
    "tests/test_health_producer_hosts.py",
    "tests/test_health_producer_wire.py",
    "tests/test_health_runtime_http.py",
    "tests/test_health_runtime_lifecycle.py",
    "tests/test_health_runtime_worker.py",
    "tests/test_evaluation_native.py",
    "tests/test_evaluation_gateway.py",
    "tests/test_evaluation_verifier.py",
    "tests/test_evaluation_controller.py",
    "tests/test_evaluation_scoring.py",
    "tests/test_evaluation_diagnostics.py",
    "tests/test_evaluation_runtime_preparation.py",
    "tests/test_evaluation_smoke_inputs.py",
    "tests/test_ci_evaluation_gate.py",
)
COMPAT_SELECTORS = (
    "tests/test_ci_accounting.py::test_cleanup_after_esrch_cannot_kill_a_reused_group",
    "tests/test_ci_accounting.py::test_cleanup_retains_identity_through_the_final_group_signal",
    "tests/test_ci_accounting.py::test_real_exited_group_cleanup_keeps_other_owned_process",
    "tests/test_ci_accounting.py::test_live_group_permission_error_is_not_terminal",
    "tests/test_ci_accounting.py::test_exited_leader_permission_error_with_live_member",
    "tests/test_native_status.py::test_native_inventory_survives_real_normal_shutdown",
    "tests/test_native_status.py::test_native_inventory_ends_descendants_and_closes_pipes_on_failure",
    "tests/test_ci_accounting.py::test_timed_out_check_kills_descendant_after_parent_exits_successfully",
    "tests/test_ci_accounting.py::test_owned_cleanup_releases_child_after_leader_is_reaped",
)
COMPAT_RUNTIME = {"platform": "darwin", "implementation": "cpython", "python": [3, 12, 13]}
HEALTH_CASES = {
    "real_authority_ready", "producer_observer_body_free", "explicit_policy_opt_in",
    "frozen_workspace_preparation", "registration_and_exact_retry", "explicit_initial_observation",
    "grounded_claim_publication", "long_korean_complete_inspect", "independent_exact_approval",
    "dependency_change_refuses_approval", "complete_inspect_current_authority", "required_rule_approved",
    "exact_code_link_admission", "workspace_scoped_context", "changed_file_invalidates",
    "late_delivery_fenced", "operator_review_role_denial", "operator_reject_accept",
    "current_code_rebind", "required_rules_survive_ordinary_rejection",
    "observed_session_work", "late_session_input_fence", "bounded_session_assessment",
}
EVALUATION_OUTCOMES = {
    "producer_http_native_mcp_preflight": True, "separate_preflight_binding": True,
    "actual_gateway_stdio": True, "all_attempts": 5, "coding_arms": 2, "valid_pairs": 1,
    "retrieval_final_reads": 2, "fresh_engineering_generations": 5,
    "correct_noop_wrong_external_controls": True, "all_blackbox_cases": True,
    "unchanged_corpus_rules": True, "on_off_scope": True, "unknown_costs_preserved": True,
    "strict_scorer_report": True, "source_unchanged": True,
    "explicit_evaluation_health_link": True, "no_automatic_health_or_human_approval": True,
    "forged_evidence_refused": 5,
}
PAIR_DRIFT_OUTCOMES = {
    "complete": True, "all_attempts": 5, "completed_attempts": 4, "blocked_attempts": 1,
    "coding_arms": 2, "pair_attempts": 1, "valid_pairs": 0, "retry_pairs": 0,
    "first_terminal_preserved": True, "second_native_spawned": False, "report_readonly": True,
    "actual_optional_approval_between_completed_arms": True,
    "synthetic_native_protocol_peer": True, "native_acceptance": False, "original18_completed": 0,
    "owned_rule_withdrawn_after_recording": True, "owned_verifiers_exact_absent": True,
}
SCENARIO_NODEIDS = sorted("tests/evaluation_docker_scenarios.py::" + name for name in (
    "test_actual_controls_outer_oracle_and_exact_retention",
    "test_actual_timeout_and_output_overflow_are_not_zero_exit_success",
    "test_actual_root_watchdog_cannot_be_killed_by_subject",
    "test_actual_double_fork_and_inherited_output_are_whole_container_cleanup",
    "test_actual_declared_file_effect_uses_trusted_observer",
    "test_actual_private_file_effect_and_expected_nonzero_exit[0]",
    "test_actual_private_file_effect_and_expected_nonzero_exit[2]",
    "test_actual_lost_create_response_recovers_full_id_without_replay",
    "test_actual_recovery_after_created_publication_temporary_link[owner]",
    "test_actual_recovery_after_created_publication_temporary_link[created]",
    "test_actual_cancellation_preserves_failure_and_owned_cleanup",
    "test_actual_watchdog_expires_without_host_subject_supervision",
    "test_actual_private_nonzero_effect_controls_enable_verification",
))
EVALUATION_PHASES = ("image-acquisition", "runtime-prepare", "scenarios", "full-smoke")
EVALUATION_IMAGE = "docker.io/library/python@sha256:2ed6491b93cd49272ee6de2b5a38440c3448360322c089fc23e370722d74179d"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def wheel_nodeids(collection: list[str]) -> list[str]:
    selected: set[str] = set()
    for selector in WHEEL_SELECTORS:
        prefixes = (selector + "::", selector + "[")
        matches = {item for item in collection if item == selector or item.startswith(prefixes)}
        require(bool(matches), f"No collected installed-wheel consumer for {selector}")
        require(selected.isdisjoint(matches), "Overlapping installed-wheel selectors")
        selected.update(matches)
    return sorted(selected)


def receipt(path: Path) -> dict:
    def unique_object(pairs: list[tuple[str, object]]) -> dict:
        result = {}
        for key, item in pairs:
            require(key not in result, "Duplicate receipt JSON key")
            result[key] = item
        return result

    def invalid_constant(value: str) -> None:
        raise ValueError("Nonfinite receipt JSON number")

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object,
                       parse_constant=invalid_constant)
    require(isinstance(value, dict), f"Invalid receipt object: {path.name}")
    return value


def nodeids(value, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"Missing {label}")
    require(all(isinstance(item, str) and item for item in value), f"Invalid {label}")
    require(value == sorted(set(value)), f"Duplicate or unordered {label}")
    return value


def identity(value: dict, tested_sha: str, source: str | None = None) -> str:
    require(type(value.get("schema")) is int and value["schema"] == 1, "Unknown receipt schema")
    require(value.get("tested_sha") == tested_sha, "Receipts do not match the tested head SHA")
    before, after = value.get("source_before"), value.get("source_after")
    if not isinstance(before, str) or DIGEST.fullmatch(before) is None:
        raise ValueError("Invalid source digest")
    require(before == after, "Source changed during verification")
    require(source is None or before == source, "Jobs verified different source trees")
    require(value.get("complete") is True, "A verification job did not complete successfully")
    return before


def execution(value: dict, selected: list[str]) -> None:
    require(type(value.get("pytest_exit_code")) is int and value["pytest_exit_code"] == 0,
            "Pytest did not exit successfully")
    reports = value.get("reports")
    if not isinstance(reports, dict) or set(reports) != set(selected):
        raise ValueError("Missing or unexpected test reports")
    for phases in reports.values():
        if not isinstance(phases, dict) or set(phases) != {"setup", "call", "teardown"}:
            raise ValueError("A selected test has incomplete runtime phases")
        require(all(isinstance(phase, dict) and phase.get("outcome") == "passed"
                    and phase.get("xfail") is False for phase in phases.values()),
                "A runtime phase failed, skipped, xfailed or xpassed")
    expected = {"passed": len(selected), "failed": 0, "skipped": 0, "xfailed": 0, "xpassed": 0}
    counts = value.get("counts")
    require(isinstance(counts, dict) and counts == expected
            and all(type(count) is int for count in counts.values()), "Inconsistent test outcome counts")


def prerequisites(path: Path, tested_sha: str, postgres: bool) -> None:
    value = receipt(path)
    require(type(value.get("schema")) is int and value["schema"] == 1, "Unknown prerequisite schema")
    require(value.get("tested_sha") == tested_sha and value.get("complete") is True,
            "Missing or mismatched prerequisite preparation")
    require(value.get("postgres_enabled") is postgres, "Wrong prerequisite role")
    observed = value.get("observed")
    required = {"python", "sqlite", "node", "uv"}
    if postgres:
        required.update({"postgres", "postgres_clients", "postgres_image", "operations_mode",
                         "age", "age_keygen", "age_archive_sha256"})
    require(isinstance(observed, dict) and required <= set(observed), "Missing actual prerequisite observations")


def one_receipt(artifacts: Path, name: str) -> dict:
    paths = list(artifacts.rglob(name))
    require(len(paths) == 1, f"Missing or duplicate {name}")
    return receipt(paths[0])


def actions_identity(value: dict, job: str) -> tuple[str, str]:
    owner = value.get("actions")
    require(isinstance(owner, dict) and set(owner) == {"run_id", "run_attempt", "job_id"},
            "Missing Actions ownership")
    require(owner["job_id"] == job, "Wrong Actions job ownership")
    require(all(isinstance(owner[key], str) and re.fullmatch(r"[1-9][0-9]*", owner[key])
                for key in ("run_id", "run_attempt")), "Invalid Actions run identity")
    for key, environment in (("run_id", "GITHUB_RUN_ID"), ("run_attempt", "GITHUB_RUN_ATTEMPT")):
        require(environment not in os.environ or owner[key] == os.environ[environment],
                "Evidence belongs to another Actions run")
    return owner["run_id"], owner["run_attempt"]


def command_observation(value: dict) -> None:
    require(isinstance(value, dict) and value.get("state") == "completed"
            and type(value.get("exit_code")) is int and value["exit_code"] == 0,
            "An evaluation phase did not complete")
    require(all(value.get(key) is True for key in
                ("stdout_complete", "stderr_complete", "helper_cleanup")),
            "An evaluation phase has incomplete output or process cleanup")
    require(all(type(value.get(key)) is int and value[key] >= 0
                for key in ("stdout_bytes", "stderr_bytes")), "Invalid phase byte accounting")
    require(all(isinstance(value.get(key), str) and DIGEST.fullmatch(value[key]) is not None
                for key in ("stdout_sha256", "stderr_sha256")), "Missing phase observation digests")
    elapsed = value.get("elapsed_seconds")
    require(type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0,
            "Missing measured phase elapsed time")


def health_evidence(value: dict, tested_sha: str, source: str, surface: str,
                    wheel_digest: str, modules: dict[str, str]) -> tuple[str, str]:
    identity(value, tested_sha, source)
    owner = actions_identity(value, "tests" if surface == "source" else "checks")
    require(value.get("consumption") == surface, "Wrong health consumer surface")
    command_observation(value.get("execution"))
    require(value.get("wheel_sha256") == (wheel_digest if surface == "installed" else None),
            "Health installed wheel provenance mismatch")
    health = value.get("health")
    require(isinstance(health, dict) and health.get("complete") is True
            and health.get("tested_sha") == tested_sha and health.get("source_unchanged") is True,
            "Health smoke incomplete or source-mismatched")
    require(health.get("surface") == "health-api-cli" and type(health.get("schema")) is int and health["schema"] == 1
            and type(health.get("original18_completed")) is int and health["original18_completed"] == 0,
            "Wrong health evidence kind")
    require(health.get("outcomes") == dict.fromkeys(HEALTH_CASES, "passed"),
            "Health semantic outcomes missing, failed or unknown")
    consumed = health.get("consumed")
    require(isinstance(consumed, dict) and consumed.get("child_identity_matches") is True,
            "Health child imported a different package")
    require(consumed.get("module_identity") == "agents_memory"
            and isinstance(consumed.get("distribution"), str)
            and re.fullmatch(r"[A-Za-z0-9.+_-]{1,64}", consumed["distribution"]) is not None,
            "Health distribution identity is missing")
    require(isinstance(consumed.get("module_tree_digest"), str)
            and DIGEST.fullmatch(consumed["module_tree_digest"]) is not None
            and consumed["module_tree_digest"] == consumed.get("module_tree_digest_after"),
            "Health package changed")
    observed = consumed.get("modules")
    names = {"cli", "config", "store", "application", "edge", "health", "health_producer", "health_code"}
    require(isinstance(observed, dict) and set(observed) == names, "Missing health module identities")
    for name, details in observed.items():
        require(details == {"identity": "agents_memory." + name,
                            "sha256": modules.get("agents_memory/" + name + ".py")},
                "Health consumed bytes differ from the source-bound public wheel")
    cleanup = health.get("owned_cleanup")
    expected = {"project_adapter": "removed", "child_service": "stopped", "fixture_store": "closed",
                "private_schema": "removed", "admin_connection": "closed", "private_evidence": "retained"}
    require(isinstance(cleanup, dict) and all(cleanup.get(key) == state for key, state in expected.items())
            and cleanup.get("service_exit_clean") is True
            and type(cleanup.get("service_exit_code")) is int and cleanup["service_exit_code"] == 0
            and cleanup.get("service_forced", False) is False, "Health exact owned cleanup incomplete")
    return owner


def evaluation_evidence(artifacts: Path, tested_sha: str, source: str,
                        modules: dict[str, str], owner: tuple[str, str]) -> dict:
    value = one_receipt(artifacts, "evaluation-job.json")
    identity(value, tested_sha, source)
    require(actions_identity(value, "evaluation") == owner, "Evaluation run identity mismatch")
    require(value.get("consumption") == "installed"
            and value.get("wheel_origin") == "evaluation-job-built",
            "Evaluation wheel consumer provenance is missing")
    require(isinstance(value.get("wheel_sha256"), str)
            and DIGEST.fullmatch(value["wheel_sha256"]) is not None
            and value.get("installed_modules") == modules, "Evaluation wheel does not contain the tested source")
    phases = value.get("phases")
    require(isinstance(phases, dict) and set(phases) == set(EVALUATION_PHASES),
            "Missing or unexpected evaluation phases")
    for phase in phases.values():
        command_observation(phase)
    require(value.get("image_reference") == EVALUATION_IMAGE, "Wrong acquired CI-only image")
    prepared = one_receipt(artifacts, "evaluation-runtime-prepare.json")
    identity(prepared, tested_sha, source)
    require(actions_identity(prepared, "evaluation") == owner, "Runtime preparation ownership mismatch")
    require(prepared.get("stage") == "prepare" and prepared.get("code") == "READY"
            and prepared.get("complete") is True and prepared.get("cleanup_complete") is True,
            "Runtime was not actually prepared and probe-cleaned")
    for field in ("runtime_digest", "image_config_digest", "tool_digest"):
        require(isinstance(prepared.get(field), str) and DIGEST.fullmatch(prepared[field]) is not None,
                "Missing measured runtime identity")
    measured = value.get("runtime")
    runtime_fields = {"runtime_digest", "runtime_spec_sha256", "docker_sha256", "tool_identity",
                      "image_id_digest", "image_config_digest", "python_executable_sha256"}
    require(isinstance(measured, dict) and set(measured) == runtime_fields
            and all(isinstance(item, str) and DIGEST.fullmatch(item) is not None for item in measured.values()),
            "Missing actual evaluator runtime/interpreter measurements")
    require(measured["runtime_digest"] == prepared["runtime_digest"]
            and measured["image_config_digest"] == prepared["image_config_digest"]
            and measured["tool_identity"] == prepared["tool_digest"], "Prepared runtime measurement mismatch")
    scenarios = one_receipt(artifacts, "evaluation-scenarios.json")
    identity(scenarios, tested_sha, source)
    require(actions_identity(scenarios, "evaluation") == owner, "Scenario ownership mismatch")
    require(scenarios.get("runtime_digest") == prepared["runtime_digest"]
            and scenarios.get("wheel_sha256") == value["wheel_sha256"]
            and scenarios.get("installed_modules") == modules,
            "Scenarios did not consume the prepared runtime and exact installed wheel")
    require(scenarios.get("collection_issues") == []
            and nodeids(scenarios.get("all_nodeids"), "scenario collection") == SCENARIO_NODEIDS
            and nodeids(scenarios.get("selected_nodeids"), "scenario execution") == SCENARIO_NODEIDS,
            "The actual Docker scenarios were not executed exactly once")
    execution(scenarios, SCENARIO_NODEIDS)
    smoke = one_receipt(artifacts, "evaluation-smoke.json")
    require(type(smoke.get("schema")) is int and smoke["schema"] == 1
            and smoke.get("code") == "COMPLETED", "Unknown or incomplete full-smoke receipt")
    require(smoke.get("complete") is True and smoke.get("tested_sha") == tested_sha
            and smoke.get("scope") == "engineering" and smoke.get("native_acceptance") is False
            and smoke.get("synthetic_native_protocol_peer") is True
            and type(smoke.get("original18_completed")) is int and smoke["original18_completed"] == 0,
            "Full engineering smoke incomplete or misrepresented")
    outcomes = smoke.get("outcomes")
    require(isinstance(outcomes, dict) and outcomes == EVALUATION_OUTCOMES
            and all(type(outcomes[key]) is type(expected) for key, expected in EVALUATION_OUTCOMES.items()),
            "Full smoke semantic accounting incomplete")
    drift = smoke.get("pair_drift")
    require(isinstance(drift, dict) and drift == PAIR_DRIFT_OUTCOMES
            and all(type(drift[key]) is type(expected) for key, expected in PAIR_DRIFT_OUTCOMES.items()),
            "Real between-arm optional-rule drift or complete failed-pair accounting missing")
    consumed = smoke.get("identity")
    require(isinstance(consumed, dict) and consumed.get("consumption") == "installed"
            and consumed.get("wheel_sha256") == value["wheel_sha256"]
            and consumed.get("runtime_digest") == prepared["runtime_digest"]
            and consumed.get("tool_identity") == prepared["tool_digest"],
            "Full smoke wheel/runtime provenance mismatch")
    require(all(consumed.get(key) == measured[key] for key in runtime_fields - {"image_config_digest"}),
            "Full smoke used another measured runtime or interpreter")
    require(isinstance(consumed.get("distribution_version"), str)
            and re.fullmatch(r"[A-Za-z0-9.+_-]{1,64}", consumed["distribution_version"]) is not None,
            "Full smoke distribution identity missing")
    module_map = {"controller": "evaluation", "artifacts": "evaluation_artifacts",
                  "runtime_driver": "evaluation_runtime", "native_driver": "evaluation_native",
                  "gateway_driver": "evaluation_gateway", "scoring": "evaluation_scoring",
                  "diagnostics": "evaluation_diagnostics", "context_renderer": "context", "health_compiler": "evaluation_health",
                  "verifier": "evaluation_verifier", "cli": "cli"}
    observed_modules = consumed.get("module_digests")
    require(isinstance(observed_modules, dict) and set(observed_modules) == set(module_map),
            "Full smoke missing consumed module identities")
    require(all(modules.get("agents_memory/" + module + ".py") == observed_modules[name]
                for name, module in module_map.items()), "Full smoke consumed different source")
    module_digest = hashlib.sha256(json.dumps(observed_modules, ensure_ascii=False, sort_keys=True,
                                             separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    require(consumed.get("modules_digest") == module_digest, "Full smoke module inventory digest mismatch")
    for key in ("manifest_digest", "report_digest", "evidence_inventory_digest"):
        require(isinstance(smoke.get(key), str) and DIGEST.fullmatch(smoke[key]) is not None,
                "Full smoke missing retained evidence identities")
    cleanup = smoke.get("owned_cleanup")
    require(isinstance(cleanup, dict) and all(cleanup.get(key) is True for key in
            ("complete", "verifiers_exact_absent", "product_service_stopped", "store_closed",
             "schema_exact_absent", "private_evidence_retained"))
            and cleanup.get("failure_evidence_publication_complete", True) is True,
            "Full smoke exact cleanup missing")
    final = one_receipt(artifacts, "evaluation-cleanup.json")
    identity(final, tested_sha, source)
    require(actions_identity(final, "evaluation") == owner
            and final.get("runtime_digest") == prepared["runtime_digest"],
            "Always-cleanup belongs to another runtime")
    require(all(final.get(key) is True for key in
                ("runtime_exact_absent", "schema_exact_absent", "prerequisites_exact_absent",
                 "processes_reaped", "private_evidence_retained")),
            "Always-cleanup is incomplete")
    runtime_cleanup = one_receipt(artifacts, "evaluation-runtime-cleanup.json")
    identity(runtime_cleanup, tested_sha, source)
    require(actions_identity(runtime_cleanup, "evaluation") == owner, "Runtime cleanup ownership mismatch")
    require(runtime_cleanup.get("stage") == "cleanup" and runtime_cleanup.get("code") == "CLEAN"
            and runtime_cleanup.get("complete") is True and runtime_cleanup.get("cleanup_complete") is True
            and runtime_cleanup.get("probe_cleanup") in {"removed", "absent"},
            "Actual runtime cleanup is missing or ambiguous")
    require(all(type(runtime_cleanup.get(key)) is int and runtime_cleanup[key] > 0
                for key in ("owners", "resources")), "No actual owned runtime resources were reconciled")
    prerequisites(artifacts / "ci-evaluation" / "prerequisites.json", tested_sha, True)
    return {"wheel_sha256": value["wheel_sha256"], "runtime_digest": prepared["runtime_digest"],
            "scenarios_passed": len(SCENARIO_NODEIDS), "full_smoke": True, "exact_cleanup": True}


def comment_evidence(artifacts: Path, tested_sha: str, source: str, comparison: dict) -> dict:
    policy = runpy.run_path(str(Path(__file__).with_name("comment-check.py")))
    value = one_receipt(artifacts, "comment-check.json")
    identity(value, tested_sha, source)
    actions_identity(value, "checks")
    require(isinstance(comparison, dict) and set(comparison) == {"base_sha", "basis"}
            and isinstance(comparison["base_sha"], str) and SHA.fullmatch(comparison["base_sha"]) is not None
            and comparison["base_sha"] != tested_sha
            and comparison["basis"] in {"pull_request_base", "push_before", "head_first_parent"},
            "Missing independent comment comparison identity")
    require(value.get("comparison") == comparison, "Comment comparison base changed")
    require(value.get("checker") == {
        "commit": policy["CHECKER_COMMIT"], "sha256": policy["CHECKER_SHA256"],
        "url": policy["CHECKER_URL"], "bytes": policy["CHECKER_BYTES"], "license": "MIT",
    }, "The canonical comment checker identity changed")
    coverage = value.get("coverage")
    require(isinstance(coverage, dict) and coverage.get("coverage_complete") is True
            and value.get("code") == "CHECKED", "Comment inspection did not complete")
    counts = {key: coverage.get(key) for key in ("changed_files", "eligible_files", "excluded_files", "input_bytes", "finding_count")}
    require(all(type(count) is int and count >= 0 for count in counts.values()), "Invalid comment coverage counts")
    require(counts["changed_files"] <= policy["MAX_FILES"]
            and counts["eligible_files"] + counts["excluded_files"] == counts["changed_files"]
            and counts["input_bytes"] <= policy["MAX_TOTAL_BYTES"]
            and counts["finding_count"] == 0 and coverage.get("findings") == [],
            "Incomplete or failing added-comment coverage")
    files = coverage.get("files")
    require(isinstance(files, list) and len(files) == counts["eligible_files"], "Missing compared source files")
    keys, total = [], 0
    for item in files:
        require(isinstance(item, dict) and set(item) == {
            "path_digest", "status", "old_mode", "new_mode", "old_oid", "new_oid", "old_bytes", "new_bytes",
        }, "Invalid compared source record")
        key = item["path_digest"]
        require(isinstance(key, str) and DIGEST.fullmatch(key) is not None
                and item["status"] in {"A", "M", "D"}, "Invalid compared source identity")
        keys.append(key)
        for side in ("old", "new"):
            mode, oid, count = (item[side + suffix] for suffix in ("_mode", "_oid", "_bytes"))
            require(mode in {"000000", "100644", "100755"} and isinstance(oid, str)
                    and SHA.fullmatch(oid) is not None and type(count) is int
                    and 0 <= count <= policy["MAX_FILE_BYTES"], "Invalid compared blob")
            require((mode == "000000") == (oid == "0" * 40) and (mode != "000000" or count == 0),
                    "Absent compared blob has content")
            total += count
        require((item["status"] == "A") == (item["old_mode"] == "000000")
                and (item["status"] == "D") == (item["new_mode"] == "000000"),
                "Compared blob status changed")
    require(keys == sorted(set(keys)) and total == counts["input_bytes"]
            and coverage.get("manifest_digest") == policy["digest"](policy["canonical"](files)),
            "Compared source coverage is inconsistent")
    return {"base_sha": comparison["base_sha"], "basis": comparison["basis"],
            "checker_sha256": policy["CHECKER_SHA256"], "compared_files": counts["eligible_files"],
            "manifest_digest": coverage["manifest_digest"], "finding_count": 0}


def aggregate(artifacts: Path, expected_shards: int, tested_sha: str, upstream_jobs: dict, *, comparison: dict) -> dict:
    require(SHA.fullmatch(tested_sha) is not None, "An exact tested head SHA is required")
    require(type(expected_shards) is int and 1 <= expected_shards <= 32, "Invalid shard count")
    require(isinstance(upstream_jobs, dict)
            and set(upstream_jobs) == {"tests", "checks", "compatibility", "evaluation"},
            "Missing upstream job results")
    require(all(isinstance(job, dict) and job.get("result") == "success"
                for job in upstream_jobs.values()), "An upstream job failed, was skipped or was cancelled")
    paths = sorted(artifacts.rglob("shard.json"))
    require(len(paths) == expected_shards, "Missing or duplicate shard artifacts")
    checks_paths = list(artifacts.rglob("checks.json"))
    require(len(checks_paths) == 1, "Missing or duplicate lint/build artifact")
    require(len(list(artifacts.rglob("prerequisites.json"))) == expected_shards + 2,
            "Missing or duplicate prerequisite artifacts")
    source = None
    collection = None
    selected_union: set[str] = set()
    indices: set[int] = set()
    shards = []
    for path in paths:
        value = receipt(path)
        prerequisites(path.parent / "prerequisites.json", tested_sha, True)
        source = identity(value, tested_sha, source)
        index = value.get("index")
        if type(index) is not int or not 0 <= index < expected_shards:
            raise ValueError("Invalid shard index")
        require(index not in indices, "Duplicate shard index")
        indices.add(index)
        require(type(value.get("count")) is int and value["count"] == expected_shards,
                "Inconsistent shard count")
        require(value.get("collection_issues") == [], "Pytest collection failed or skipped a module")
        current = nodeids(value.get("all_nodeids"), "complete collection")
        require(collection is None or collection == current, "Shards collected different tests")
        collection = current
        selected = nodeids(value.get("selected_nodeids"), "selected tests")
        expected = [item for item in current
                    if int.from_bytes(hashlib.sha256(item.encode()).digest(), "big") % expected_shards == index]
        require(selected == expected, "Shard selection does not match its deterministic partition")
        require(selected_union.isdisjoint(selected), "Tests ran in multiple shards")
        selected_union.update(selected)
        execution(value, selected)
        shards.append({"index": index, "passed": len(selected), "seconds": value.get("seconds")})
    require(indices == set(range(expected_shards)), "A shard index is missing")
    if collection is None or selected_union != set(collection):
        raise ValueError("The full collection was not executed")
    checks = receipt(checks_paths[0])
    prerequisites(checks_paths[0].parent / "prerequisites.json", tested_sha, True)
    identity(checks, tested_sha, source)
    outcomes = checks.get("checks")
    if not isinstance(outcomes, dict) or set(outcomes) != set(CHECK_COMMANDS):
        raise ValueError("Missing lint/build/wheel outcomes")
    for name, command in CHECK_COMMANDS.items():
        outcome = outcomes[name]
        require(isinstance(outcome, dict) and outcome.get("command") == command,
                f"Unexpected {name} command")
        require(type(outcome.get("exit_code")) is int and outcome["exit_code"] == 0
                and not outcome.get("timeout") and not outcome.get("error"), f"The {name} command did not pass")
    comments = comment_evidence(artifacts, tested_sha, source, comparison)
    wheel_paths = list(artifacts.rglob("wheel-consumer.json"))
    require(len(wheel_paths) == 1, "Missing or duplicate wheel-consumer artifact")
    wheel = receipt(wheel_paths[0])
    identity(wheel, tested_sha, source)
    require(wheel.get("collection_issues") == [], "Wheel consumer did not collect cleanly")
    selected = nodeids(wheel.get("selected_nodeids"), "wheel-consumer execution")
    expected_wheel = wheel_nodeids(collection)
    require(selected == expected_wheel, "The installed wheel did not exercise every declared consumer case")
    execution(wheel, selected)
    distributions = list((artifacts / "distribution").glob("*.whl"))
    require(len(distributions) == 1, "Missing or ambiguous public wheel artifact")
    with distributions[0].open("rb") as stream:
        wheel_digest = hashlib.file_digest(stream, "sha256").hexdigest()
    require(wheel.get("wheel_sha256") == wheel_digest, "The public wheel differs from the exercised artifact")
    with zipfile.ZipFile(distributions[0]) as archive:
        module_names = [name for name in archive.namelist()
                        if name.startswith("agents_memory/") and name.endswith(".py")]
        require(bool(module_names) and len(module_names) == len(set(module_names)),
                "Public wheel module inventory is missing or duplicated")
        modules = {name: hashlib.sha256(archive.read(name)).hexdigest() for name in module_names}
    require(wheel.get("installed_modules") == modules, "Installed-wheel module provenance is incomplete")
    health_source = health_evidence(one_receipt(artifacts, "health-source.json"), tested_sha,
                                    source, "source", wheel_digest, modules)
    health_installed = health_evidence(one_receipt(artifacts, "health-installed.json"), tested_sha,
                                       source, "installed", wheel_digest, modules)
    require(health_source == health_installed, "Health surfaces belong to different Actions runs")
    evaluation_result = evaluation_evidence(artifacts, tested_sha, source, modules, health_source)
    compat_paths = list(artifacts.rglob("compatibility.json"))
    require(len(compat_paths) == 1, "Missing or duplicate platform compatibility artifact")
    compat = receipt(compat_paths[0])
    identity(compat, tested_sha, source)
    require(compat.get("runtime") == COMPAT_RUNTIME, "Wrong compatibility runtime")
    require(compat.get("collection_issues") == [], "Compatibility collection failed")
    expected_compat = sorted(item for item in collection
                             if any(item == selector or item.startswith(selector + "[")
                                    for selector in COMPAT_SELECTORS))
    require(all(any(item == selector or item.startswith(selector + "[") for item in expected_compat)
                for selector in COMPAT_SELECTORS), "Missing compatibility boundary")
    require(nodeids(compat.get("all_nodeids"), "compatibility collection") == expected_compat,
            "Compatibility collection differs from the declared source cases")
    require(nodeids(compat.get("selected_nodeids"), "compatibility execution") == expected_compat,
            "Compatibility execution omitted a declared case")
    execution(compat, expected_compat)
    return {
        "schema": 1, "complete": True, "tested_sha": tested_sha, "source_digest": source,
        "collected": len(collection), "passed": len(selected_union), "failed": 0,
        "skipped": 0, "xfailed": 0, "xpassed": 0,
        "shards": sorted(shards, key=lambda shard: shard["index"]), "checks": outcomes,
        "wheel_consumer": {"sha256": wheel_digest, "passed": len(selected),
                          "artifact": distributions[0].name},
        "compatibility": {"runtime": compat["runtime"], "passed": len(expected_compat)},
        "health": {"source": True, "installed": True}, "evaluation": evaluation_result,
        "comments": comments,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Require complete parallel CI evidence for one exact source tree")
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--expected-shards", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("GITHUB_ACTIONS") != "true":
        parser.error("This gate is GitHub Actions-only")
    tested_sha = os.environ.get("CI_TESTED_SHA", "")
    try:
        jobs = json.loads(os.environ.get("CI_UPSTREAM_JOBS", "{}"))
        policy = runpy.run_path(str(Path(__file__).with_name("comment-check.py")))
        comparison = policy["comparison_base"](tested_sha)
        result = aggregate(args.artifacts, args.expected_shards, tested_sha, jobs, comparison=comparison)
    except (OSError, ValueError, TypeError) as error:
        result = {"schema": 1, "complete": False, "tested_sha": tested_sha, "error": str(error)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write(f"## Parallel verification: {'PASS' if result['complete'] else 'FAIL'}\n\n")
            stream.write(f"Tested head: `{tested_sha}`\n\n")
            if result["complete"]:
                stream.write(f"{result['passed']} passed; 0 skipped/xfail/xpass; "
                             f"{len(result['shards'])} disjoint shards; lint/build passed.\n")
                stream.write(f"Source: `{result['source_digest']}`\n")
            else:
                stream.write("Complete, consistent passing evidence is unavailable; see summary.json.\n")
            stream.write("\nCI is not native-host protection, formal review or release approval.\n")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
