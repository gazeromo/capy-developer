from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
import time
import tomllib
from pathlib import Path

from .errors import DeveloperError
from .git import (
    add_detached_worktree,
    remove_detached_worktree,
    run_git,
    validate_candidate,
)
from .process import ProcessResult, combine_process_results, run_process
from .toolchain import ResolvedToolchain, read_lock, sha256_file
from .util import (
    APPLICATION_ID,
    HEX40,
    SESSION_ID,
    exclusive_lock,
    lock_is_available,
    new_id,
    operation_lock,
    path_uri,
    read_regular_bytes,
    safe_resolve,
    stable_digest,
    utc_now,
)


RESULT_SCHEMA = "capy.development-verification-result/v0"
RESULT_SCHEMA_V1 = "capy.development-verification-result/v1"
PIPELINE_V0 = "capy.development-verification-pipeline/v0"
PIPELINE_V1 = "capy.development-verification-pipeline/v1"
STAGES = (
    "toolchain_install",
    "check",
    "test",
    "conform",
    "source_mutation_check",
    "pack_a",
    "pack_b",
    "package_compare",
    "archive_preserve",
)
STAGES_V1 = (
    "toolchain_install",
    "check",
    "interaction_check",
    "test",
    "conform",
    "source_mutation_check",
    "pack_a",
    "pack_b",
    "package_compare",
    "archive_preserve",
    "interaction_preserve",
)
TIMEOUTS = {"toolchain_install": 120, "check": 30, "interaction_check": 30, "test": 180, "conform": 180, "pack_a": 60, "pack_b": 60, "interaction_preserve": 30}


class VerificationService:
    def __init__(self, core):
        self.core = core
        self.config = core.config
        self.db = core.db
        self.toolchains = core.toolchains

    def verify(self, payload: dict) -> dict:
        normalized = self._normalize(payload)
        request_digest = stable_digest(normalized)
        replay = self._replay(normalized, request_digest)
        if replay is not None:
            return replay
        session_id = normalized["session_id"]
        lock_path = self.config.verification_lock(session_id)
        with exclusive_lock(
            lock_path,
            0,
            busy_code="VERIFICATION_BUSY",
            busy_detail="another verification is active for this development session",
        ):
            self.reconcile(session_id, lock_held=True)
            replay = self._replay(normalized, request_digest, lock_held=True)
            if replay is not None:
                return replay
            verification_id = new_id("ver")
            attempt_root = self._attempt_root(verification_id)
            test_checkout = attempt_root / "c"
            repository_worktree = None
            external_temp = None
            allocated = False
            facts = None
            resolved = None
            application_relative = None
            try:
                with operation_lock(self.config.operation_lock):
                    global_replay = self._replay(normalized, request_digest)
                    if global_replay is not None:
                        return global_replay
                    session, repository_worktree, facts = self._prevalidate(normalized)
                    attempt_root.mkdir(parents=True, exist_ok=False)
                    add_detached_worktree(repository_worktree, test_checkout, normalized["candidate_commit"])
                    application_relative = self._application_root(test_checkout, normalized["application_id"])
                    lock = read_lock(test_checkout)
                    resolved = self.toolchains.resolve(lock)
                    pipeline = PIPELINE_V1 if resolved.lock.interaction_contract else PIPELINE_V0
                    now = utc_now()
                    with self.db.connect() as db:
                        db.execute(
                            """INSERT INTO verification_attempts(
                               verification_id,session_id,idempotency_key,request_digest,
                               application_id,candidate_commit,candidate_tree,base_commit,
                               development_branch,lock_digest,contract,release_binding_commit,
                               authoring_bundle_sha256,wheel_sha256,pipeline_schema,
                               interaction_contract,status,started_at,updated_at
                               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'RUNNING',?,?)""",
                            (
                                verification_id,
                                session_id,
                                normalized["idempotency_key"],
                                request_digest,
                                normalized["application_id"],
                                facts["commit"],
                                facts["tree"],
                                facts["base_commit"],
                                facts["branch"],
                                resolved.lock_digest,
                                resolved.lock.contract,
                                resolved.lock.commit,
                                resolved.bundle_sha256,
                                resolved.wheel_sha256,
                                pipeline,
                                resolved.lock.interaction_contract,
                                now,
                                now,
                            ),
                        )
                        self.db.event(db, session_id, "VERIFICATION_STARTED", {"verification_id": verification_id})
                    allocated = True
                temporary, external_temp = self._temporary_root(attempt_root, verification_id)
                if external_temp is not None:
                    with self.db.connect() as db:
                        db.execute(
                            "UPDATE verification_attempts SET temporary_path=?,updated_at=? WHERE verification_id=?",
                            (str(external_temp), utc_now(), verification_id),
                        )
                self._execute(
                    verification_id,
                    repository_worktree,
                    test_checkout,
                    attempt_root,
                    application_relative,
                    resolved,
                    temporary,
                )
            except DeveloperError as exc:
                if allocated:
                    self._terminalize(
                        verification_id,
                        "FAILED",
                        "VERIFIER_INTERNAL_FAILED",
                        error_code=exc.code,
                        error_detail=exc.detail,
                    )
                else:
                    raise
            except Exception as exc:
                if not allocated:
                    raise DeveloperError("VERIFIER_INTERNAL_ERROR", "verification preflight failed unexpectedly") from exc
                self._terminalize(
                    verification_id,
                    "FAILED",
                    "VERIFIER_INTERNAL_FAILED",
                    error_code="VERIFIER_INTERNAL_ERROR",
                    error_detail=type(exc).__name__,
                )
            finally:
                cleanup_errors = []
                if repository_worktree is not None:
                    for checkout in (test_checkout, attempt_root / "a", attempt_root / "b"):
                        try:
                            remove_detached_worktree(repository_worktree, checkout)
                        except DeveloperError as exc:
                            cleanup_errors.append(f"{exc.code}: {exc.detail}")
                if attempt_root.exists():
                    try:
                        shutil.rmtree(attempt_root)
                    except OSError as exc:
                        cleanup_errors.append(f"ATTEMPT_CLEANUP_FAILED: {type(exc).__name__}")
                if attempt_root.exists():
                    cleanup_errors.append("ATTEMPT_CLEANUP_FAILED: path remains")
                if external_temp is not None and not self._cleanup_external_temp(verification_id, external_temp):
                    cleanup_errors.append("TEMP_CLEANUP_FAILED: owned path remains")
                if allocated and cleanup_errors:
                    self._record_cleanup_failure(verification_id, "; ".join(cleanup_errors))
            if not allocated:
                raise DeveloperError("VERIFIER_INTERNAL_ERROR", "verification attempt was not allocated")
            return self.result(verification_id)

    def _normalize(self, payload: dict) -> dict:
        if not isinstance(payload, dict) or set(payload) != {
            "session_id", "application_id", "candidate_commit", "idempotency_key"
        }:
            raise DeveloperError("VERIFY_INPUT_INVALID", "verify input must contain only the four required fields")
        session_id = payload.get("session_id")
        application_id = payload.get("application_id")
        candidate = payload.get("candidate_commit")
        key = payload.get("idempotency_key")
        if not isinstance(session_id, str) or SESSION_ID.fullmatch(session_id) is None:
            raise DeveloperError("SESSION_ID_INVALID", "session_id is invalid")
        if not isinstance(application_id, str) or APPLICATION_ID.fullmatch(application_id) is None:
            raise DeveloperError("APPLICATION_ID_INVALID", "application_id must be a dotted lowercase identifier")
        if not isinstance(candidate, str) or HEX40.fullmatch(candidate) is None:
            raise DeveloperError("CANDIDATE_COMMIT_INVALID", "candidate_commit must be exactly 40 lowercase hex characters")
        if not isinstance(key, str) or not key.strip() or len(key) > 200:
            raise DeveloperError("IDEMPOTENCY_KEY_INVALID", "idempotency_key must be a bounded non-empty string")
        return {
            "session_id": session_id,
            "application_id": application_id,
            "candidate_commit": candidate,
            "idempotency_key": key.strip(),
        }

    def _replay(self, normalized: dict, request_digest: str, *, lock_held: bool = False) -> dict | None:
        with self.db.connect() as db:
            row = db.execute(
                "SELECT * FROM verification_attempts WHERE idempotency_key=?",
                (normalized["idempotency_key"],),
            ).fetchone()
        if row is None:
            return None
        row = dict(row)
        if row["request_digest"] != request_digest:
            raise DeveloperError("IDEMPOTENCY_CONFLICT", "idempotency key is bound to different verification input")
        if row["status"] == "RUNNING":
            available = lock_held or lock_is_available(self.config.verification_lock(row["session_id"]))
            if available:
                self._terminalize(row["verification_id"], "INTERRUPTED", "VERIFIER_PROCESS_INTERRUPTED")
                self._cleanup_interrupted(row["verification_id"])
            else:
                raise DeveloperError("VERIFICATION_BUSY", "the idempotent verification is still running")
        return self.result(row["verification_id"])

    def _prevalidate(self, normalized: dict):
        with self.db.connect() as db:
            session = db.execute(
                "SELECT * FROM sessions WHERE session_id=?", (normalized["session_id"],)
            ).fetchone()
            if session is None:
                raise DeveloperError("SESSION_NOT_FOUND", "development session does not exist")
            session = dict(session)
            if session["status"] != "READY":
                raise DeveloperError("SESSION_NOT_READY", "verification requires a READY development session")
            registered = db.execute(
                "SELECT 1 FROM project_applications WHERE project_id=? AND application_id=?",
                (session["project_id"], normalized["application_id"]),
            ).fetchone()
            if registered is None:
                raise DeveloperError("APPLICATION_NOT_REGISTERED", "application_id is not registered to this project")
        if not session.get("worktree_path"):
            raise DeveloperError("WORKTREE_MISSING", "development session has no managed worktree")
        path = safe_resolve(
            Path(session["worktree_path"]), root=self.config.worktrees_root, must_exist=True
        )
        if not path.is_dir():
            raise DeveloperError("WORKTREE_MISSING", "managed worktree is absent")
        facts = validate_candidate(
            path,
            str(session["development_branch"]),
            normalized["candidate_commit"],
            str(session["exact_base_commit"]),
        )
        return session, path, facts

    def _application_root(self, checkout: Path, application_id: str) -> Path:
        ignored = {".git", ".venv", "venv", "build", "dist", ".tox", ".nox", "node_modules", "__pycache__"}
        matches = []
        seen: dict[str, int] = {}
        descriptors = []
        for descriptor in checkout.rglob("capability.toml"):
            relative = descriptor.relative_to(checkout)
            if any(part in ignored or part.startswith(".") for part in relative.parts[:-1]) or len(relative.parts) > 8:
                continue
            if descriptor.is_symlink():
                raise DeveloperError("CAPABILITY_PATH_INVALID", "capability descriptor may not be a symlink")
            try:
                descriptor.resolve(strict=True).relative_to(checkout.resolve())
            except ValueError as exc:
                raise DeveloperError("CAPABILITY_PATH_INVALID", "capability descriptor escapes the candidate checkout") from exc
            descriptors.append(descriptor)
            if len(descriptors) > 64:
                raise DeveloperError("APPLICATION_MARKERS_EXCESSIVE", "too many capability descriptors")
        for descriptor in descriptors:
            try:
                data = tomllib.loads(descriptor.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
                raise DeveloperError("CAPABILITY_DESCRIPTOR_INVALID", "candidate capability descriptor is malformed") from exc
            identifier = data.get("id")
            if isinstance(identifier, str):
                seen[identifier] = seen.get(identifier, 0) + 1
            if identifier == application_id:
                if data.get("schema") != "capy.script/dev-v0":
                    raise DeveloperError("TOOLCHAIN_CONTRACT_UNSUPPORTED", "application descriptor schema is unsupported")
                matches.append(descriptor.parent.relative_to(checkout))
        if seen.get(application_id, 0) > 1:
            raise DeveloperError("APPLICATION_ID_DUPLICATE", "candidate contains duplicate descriptors for application_id")
        if len(matches) != 1:
            raise DeveloperError("APPLICATION_NOT_AT_CANDIDATE", "candidate contains no exact matching application descriptor")
        return matches[0]

    def _execute(
        self,
        verification_id: str,
        repository_worktree: Path,
        test_checkout: Path,
        attempt_root: Path,
        application_relative: Path,
        resolved: ResolvedToolchain,
        temporary: Path,
    ) -> None:
        home = attempt_root / "h"
        environment = self._environment(home, temporary)
        venv = attempt_root / "e"
        create = run_process(
            [sys.executable, "-m", "venv", str(venv)],
            cwd=attempt_root,
            environment=environment,
            timeout=TIMEOUTS["toolchain_install"],
        )
        if create.timed_out or create.exit_code != 0:
            self._record_process(verification_id, "toolchain_install", create, False)
            self._fail_remaining(verification_id, "toolchain_install", "STAGE_TIMEOUT" if create.timed_out else "TOOLCHAIN_INSTALL_FAILED")
            return
        python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        install = run_process(
            [str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(resolved.wheel)],
            cwd=attempt_root,
            environment=environment,
            timeout=TIMEOUTS["toolchain_install"],
        )
        combined = combine_process_results(create, install)
        if install.timed_out or install.exit_code != 0:
            self._record_process(verification_id, "toolchain_install", combined, False)
            self._fail_remaining(verification_id, "toolchain_install", "STAGE_TIMEOUT" if install.timed_out else "TOOLCHAIN_INSTALL_FAILED")
            return
        import_check = run_process(
            [str(python), "-c", "import capy_script"], cwd=attempt_root,
            environment=environment, timeout=30,
        )
        combined = combine_process_results(combined, import_check)
        if import_check.timed_out or import_check.exit_code != 0:
            self._record_process(verification_id, "toolchain_install", combined, False)
            self._fail_remaining(
                verification_id,
                "toolchain_install",
                "STAGE_TIMEOUT" if import_check.timed_out else "TOOLCHAIN_INSTALL_FAILED",
            )
            return
        self._record_process(verification_id, "toolchain_install", combined, True)
        app = test_checkout / application_relative
        attempt = self._attempt(verification_id)
        interaction = None
        for stage, command, classification in (
            ("check", "check", "DEVKIT_CHECK_FAILED"),
        ):
            result = run_process(
                [str(python), "-m", "capy_script", command, str(app)],
                cwd=test_checkout,
                environment=environment,
                timeout=TIMEOUTS[stage],
            )
            process_passed = not result.timed_out and result.exit_code == 0
            candidate_unchanged = self._candidate_unchanged(
                test_checkout, attempt["candidate_commit"], attempt["candidate_tree"]
            )
            passed = process_passed and candidate_unchanged
            self._record_process(
                verification_id, stage, result, passed, facts={"candidate_unchanged": candidate_unchanged}
            )
            if not passed:
                failure = (
                    "STAGE_TIMEOUT" if result.timed_out else
                    "SOURCE_MUTATED_DURING_VERIFICATION" if not candidate_unchanged else classification
                )
                self._fail_remaining(verification_id, stage, failure)
                return
        if attempt["pipeline_schema"] == PIPELINE_V1:
            interaction = self._check_interaction(
                verification_id, python, environment, test_checkout, app,
                attempt_root / "interaction" / "initial.json", attempt,
            )
            if interaction is None:
                return
        for stage, command, classification in (
            ("test", "test", "APPLICATION_TESTS_FAILED"),
            ("conform", "conform", "CONFORMANCE_FAILED"),
        ):
            result = run_process(
                [str(python), "-m", "capy_script", command, str(app)],
                cwd=test_checkout,
                environment=environment,
                timeout=TIMEOUTS[stage],
            )
            process_passed = not result.timed_out and result.exit_code == 0
            candidate_unchanged = self._candidate_unchanged(
                test_checkout, attempt["candidate_commit"], attempt["candidate_tree"]
            )
            passed = process_passed and candidate_unchanged
            self._record_process(
                verification_id, stage, result, passed, facts={"candidate_unchanged": candidate_unchanged}
            )
            if not passed:
                failure = (
                    "STAGE_TIMEOUT" if result.timed_out else
                    "SOURCE_MUTATED_DURING_VERIFICATION" if not candidate_unchanged else classification
                )
                self._fail_remaining(verification_id, stage, failure)
                return
        started = utc_now()
        tick = time.monotonic()
        status = run_git(
            ["-C", str(test_checkout), "status", "--porcelain=v1", "--untracked-files=all"],
            allow_truncated_output=True,
        )
        clean = self._candidate_unchanged(
            test_checkout, attempt["candidate_commit"], attempt["candidate_tree"]
        )
        self._record_stage(
            verification_id,
            "source_mutation_check",
            "PASSED" if clean else "FAILED",
            started_at=started,
            duration_ms=round((time.monotonic() - tick) * 1000),
            stdout=status,
        )
        if not clean:
            self._fail_remaining(verification_id, "source_mutation_check", "SOURCE_MUTATED_DURING_VERIFICATION")
            return
        outputs = attempt_root / "outputs"
        outputs.mkdir()
        archives = []
        for stage, checkout_name, archive_name in (
            ("pack_a", "a", "a.zip"),
            ("pack_b", "b", "b.zip"),
        ):
            checkout = attempt_root / checkout_name
            add_detached_worktree(repository_worktree, checkout, self._attempt(verification_id)["candidate_commit"])
            archive = outputs / archive_name
            result = run_process(
                [str(python), "-m", "capy_script", "pack", str(checkout / application_relative), "--output", str(archive)],
                cwd=checkout,
                environment=environment,
                timeout=TIMEOUTS[stage],
            )
            candidate_unchanged = self._candidate_unchanged(
                checkout, attempt["candidate_commit"], attempt["candidate_tree"]
            )
            passed = (
                not result.timed_out
                and result.exit_code == 0
                and archive.is_file()
                and candidate_unchanged
            )
            self._record_process(
                verification_id,
                stage,
                result,
                passed,
                facts={"candidate_unchanged": candidate_unchanged},
            )
            if not passed:
                classification = (
                    "STAGE_TIMEOUT" if result.timed_out else
                    "SOURCE_MUTATED_DURING_VERIFICATION" if not candidate_unchanged else
                    "PACKAGE_BUILD_FAILED"
                )
                self._fail_remaining(verification_id, stage, classification)
                return
            archives.append(archive)
        started = utc_now()
        tick = time.monotonic()
        digest_a, digest_b = (sha256_file(item) for item in archives)
        same = digest_a == digest_b and archives[0].stat().st_size == archives[1].stat().st_size
        self._record_stage(
            verification_id,
            "package_compare",
            "PASSED" if same else "FAILED",
            started_at=started,
            duration_ms=round((time.monotonic() - tick) * 1000),
            facts={"sha256_a": digest_a, "sha256_b": digest_b, "size_a": archives[0].stat().st_size, "size_b": archives[1].stat().st_size},
        )
        if not same:
            self._fail_remaining(verification_id, "package_compare", "PACKAGE_NOT_REPRODUCIBLE")
            return
        started = utc_now()
        tick = time.monotonic()
        destination = safe_resolve(
            self.config.verification_artifacts_root / digest_a / "application.zip",
            root=self.config.verification_artifacts_root,
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and sha256_file(destination) != digest_a:
            self._record_stage(verification_id, "archive_preserve", "FAILED", started_at=started)
            self._terminalize(verification_id, "FAILED", "VERIFIER_INTERNAL_FAILED", error_code="ARCHIVE_INTEGRITY_FAILED", error_detail="content-addressed archive path contains conflicting bytes")
            return
        if not destination.exists():
            with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as temporary_file:
                temporary_path = Path(temporary_file.name)
            try:
                shutil.copyfile(archives[0], temporary_path)
                if sha256_file(temporary_path) != digest_a:
                    raise DeveloperError("ARCHIVE_INTEGRITY_FAILED", "copied candidate archive failed digest verification")
                temporary_path.replace(destination)
            finally:
                temporary_path.unlink(missing_ok=True)
        self._record_stage(
            verification_id,
            "archive_preserve",
            "PASSED",
            started_at=started,
            duration_ms=round((time.monotonic() - tick) * 1000),
            facts={"sha256": digest_a, "size_bytes": destination.stat().st_size},
        )
        if attempt["pipeline_schema"] == PIPELINE_V1:
            assert interaction is not None
            preserved = self._preserve_interaction(
                verification_id, python, environment, test_checkout, app,
                attempt_root / "interaction" / "final.json", attempt, interaction,
            )
            if not preserved:
                return
        self._terminalize(
            verification_id,
            "PASSED",
            "VERIFIED",
            archive_sha256=digest_a,
            archive_size_bytes=destination.stat().st_size,
            archive_path=str(destination),
        )

    def _check_interaction(
        self, verification_id: str, python: Path, environment: dict[str, str],
        checkout: Path, app: Path, output: Path, attempt: dict,
    ) -> dict | None:
        source = app / "interaction.json"
        try:
            resolved = source.resolve(strict=True)
            resolved.relative_to(app.resolve(strict=True))
            if source.is_symlink() or not resolved.is_file():
                raise ValueError
            source_bytes = resolved.read_bytes()
        except (OSError, ValueError):
            self._record_stage(verification_id, "interaction_check", "FAILED")
            self._fail_remaining(verification_id, "interaction_check", "INTERACTION_CONTRACT_FAILED")
            return None
        result = run_process(
            [str(python), "-m", "capy_script", "interaction-check", str(app), "--output", str(output)],
            cwd=checkout, environment=environment, timeout=TIMEOUTS["interaction_check"],
        )
        candidate_unchanged = self._candidate_unchanged(
            checkout, attempt["candidate_commit"], attempt["candidate_tree"]
        )
        try:
            canonical = output.read_bytes()
            document = json.loads(canonical)
            valid = (
                len(canonical) <= 1024 * 1024
                and json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8") == canonical
                and document.get("schema") == attempt["interaction_contract"]
                and document.get("application_id") == attempt["application_id"]
                and isinstance(document.get("operation"), dict)
                and isinstance(document["operation"].get("operation_id"), str)
            )
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError, AttributeError):
            canonical, document, valid = b"", {}, False
        passed = not result.timed_out and result.exit_code == 0 and candidate_unchanged and valid
        self._record_process(
            verification_id, "interaction_check", result, passed,
            facts={"candidate_unchanged": candidate_unchanged},
        )
        if not passed:
            self._fail_remaining(verification_id, "interaction_check", "INTERACTION_CONTRACT_FAILED")
            return None
        return {
            "schema": document["schema"], "source_member": "interaction.json",
            "source_sha256": sha256_file(source),
            "canonical_sha256": __import__("hashlib").sha256(canonical).hexdigest(),
            "canonical_size_bytes": len(canonical),
            "operation_id": document["operation"]["operation_id"],
            "canonical": canonical,
        }

    def _preserve_interaction(
        self, verification_id: str, python: Path, environment: dict[str, str],
        checkout: Path, app: Path, output: Path, attempt: dict, initial: dict,
    ) -> bool:
        result = run_process(
            [str(python), "-m", "capy_script", "interaction-check", str(app), "--output", str(output)],
            cwd=checkout, environment=environment, timeout=TIMEOUTS["interaction_preserve"],
        )
        try:
            canonical = output.read_bytes()
            source_sha256 = sha256_file(app / "interaction.json")
        except OSError:
            canonical, source_sha256 = b"", ""
        canonical_sha256 = __import__("hashlib").sha256(canonical).hexdigest()
        candidate_unchanged = self._candidate_unchanged(
            checkout, attempt["candidate_commit"], attempt["candidate_tree"]
        )
        passed = (
            not result.timed_out and result.exit_code == 0 and candidate_unchanged
            and source_sha256 == initial["source_sha256"]
            and canonical_sha256 == initial["canonical_sha256"]
            and canonical == initial["canonical"]
        )
        destination = None
        try:
            root = self.config.verification_interactions_root.expanduser().absolute().resolve()
            digest_root = root / canonical_sha256
            destination = digest_root / "interaction.json"
            if passed:
                root.mkdir(parents=True, exist_ok=True)
                digest_root.mkdir(exist_ok=True)
                digest_status = digest_root.lstat()
                if not stat.S_ISDIR(digest_status.st_mode) or stat.S_ISLNK(digest_status.st_mode):
                    passed = False
                if destination.is_symlink() or (destination.exists() and not destination.is_file()):
                    passed = False
                elif destination.exists() and read_regular_bytes(destination) != canonical:
                    passed = False
                elif not destination.exists():
                    descriptor, temporary_name = tempfile.mkstemp(
                        prefix="interaction-", suffix=".tmp", dir=destination.parent
                    )
                    temporary = Path(temporary_name)
                    try:
                        with os.fdopen(descriptor, "wb") as stream:
                            stream.write(canonical)
                        try:
                            os.link(temporary, destination)
                        except FileExistsError:
                            pass
                    finally:
                        temporary.unlink(missing_ok=True)
                    if (
                        destination.is_symlink() or not destination.is_file()
                        or read_regular_bytes(destination) != canonical
                    ):
                        passed = False
        except (OSError, DeveloperError):
            passed = False
        self._record_process(
            verification_id, "interaction_preserve", result, passed,
            facts={
                "candidate_unchanged": candidate_unchanged,
                "source_sha256": source_sha256,
                "canonical_sha256": canonical_sha256,
                "canonical_size_bytes": len(canonical),
            },
        )
        if not passed:
            self._fail_remaining(verification_id, "interaction_preserve", "INTERACTION_CONTRACT_FAILED")
            return False
        assert destination is not None
        with self.db.connect() as db:
            db.execute(
                """INSERT INTO verification_interactions VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    verification_id, initial["schema"], initial["source_member"],
                    initial["source_sha256"], initial["canonical_sha256"],
                    initial["canonical_size_bytes"], str(destination),
                    initial["operation_id"], utc_now(),
                ),
            )
        return True

    def _attempt_root(self, verification_id: str) -> Path:
        return safe_resolve(
            self.config.verification_root / verification_id.removeprefix("ver_")[:12],
            root=self.config.verification_root,
        )

    def _temporary_root(self, attempt_root: Path, verification_id: str) -> tuple[Path, Path | None]:
        managed = attempt_root / "t"
        # The accepted DevKit's connection simulator uses AF_UNIX. macOS caps
        # socket paths at roughly 104 bytes, so a long configured cache root
        # needs a short, disposable OS-temp path for the child process only.
        if os.name == "posix" and len(os.fsencode(str(managed))) + 48 >= 104:
            external = Path(tempfile.mkdtemp(
                prefix=f"cv-{verification_id.removeprefix('ver_')[:8]}-",
                dir=self.config.verification_temporary_root,
            ))
            if len(os.fsencode(str(external))) + 48 >= 104:
                shutil.rmtree(external, ignore_errors=True)
                raise DeveloperError(
                    "VERIFICATION_TEMP_PATH_TOO_LONG",
                    "configured verification temporary root is too long for the locked DevKit",
                )
            (external / ".capy-verification-owner").write_text(verification_id, encoding="utf-8")
            return external, external
        return managed, None

    def _cleanup_external_temp(self, verification_id: str, path: Path) -> bool:
        root = self.config.verification_temporary_root.resolve()
        if not path.exists() and not path.is_symlink():
            return True
        if path.is_symlink():
            return False
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            return not path.exists()
        marker = resolved / ".capy-verification-owner"
        if (
            resolved.parent != root
            or not resolved.name.startswith(f"cv-{verification_id.removeprefix('ver_')[:8]}-")
            or marker.is_symlink()
            or not marker.is_file()
        ):
            return False
        try:
            owner = marker.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return False
        if owner == verification_id:
            shutil.rmtree(resolved, ignore_errors=True)
        return not resolved.exists()

    @staticmethod
    def _candidate_unchanged(checkout: Path, commit: str, tree: str) -> bool:
        return (
            run_git(["-C", str(checkout), "rev-parse", "HEAD"], check=False) == commit
            and run_git(["-C", str(checkout), "rev-parse", "HEAD^{tree}"], check=False) == tree
            and not run_git(["-C", str(checkout), "symbolic-ref", "--short", "-q", "HEAD"], check=False)
            and not run_git(
                ["-C", str(checkout), "status", "--porcelain=v1", "--untracked-files=all"],
                allow_truncated_output=True,
            )
        )

    def _environment(self, home: Path, temporary: Path) -> dict[str, str]:
        home.mkdir(parents=True, exist_ok=True)
        temporary.mkdir(parents=True, exist_ok=True)
        keep = {"PATH", "LANG", "LC_ALL", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"}
        environment = {key: value for key, value in os.environ.items() if key.upper() in keep}
        environment.update({
            "HOME": str(home),
            "USERPROFILE": str(home),
            "TMP": str(temporary),
            "TEMP": str(temporary),
            "TMPDIR": str(temporary),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PIP_NO_INDEX": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        })
        return environment

    def _record_process(self, verification_id: str, stage: str, result: ProcessResult, passed: bool, *, facts: dict | None = None) -> None:
        self._record_stage(
            verification_id, stage, "PASSED" if passed else "FAILED",
            started_at=result.started_at, terminal_at=result.terminal_at, duration_ms=result.duration_ms,
            exit_code=result.exit_code, stdout=result.stdout, stderr=result.stderr,
            stdout_truncated=result.stdout_truncated_bytes,
            stderr_truncated=result.stderr_truncated_bytes,
            facts={**(facts or {}), "timed_out": result.timed_out},
        )

    def _record_stage(
        self,
        verification_id: str,
        stage: str,
        status: str,
        *,
        started_at: str | None = None,
        terminal_at: str | None = None,
        duration_ms: int | None = None,
        exit_code: int | None = None,
        stdout: str = "",
        stderr: str = "",
        stdout_truncated: int = 0,
        stderr_truncated: int = 0,
        facts: dict | None = None,
    ) -> None:
        stages = self._stage_names(verification_id)
        order = stages.index(stage)
        started_at = started_at or utc_now()
        terminal_at = terminal_at or utc_now()
        with self.db.connect() as db:
            db.execute(
                """INSERT OR REPLACE INTO verification_stages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    verification_id, order, stage, status, started_at, terminal_at,
                    duration_ms, exit_code, stdout, stderr, stdout_truncated,
                    stderr_truncated, json.dumps(facts or {}, sort_keys=True),
                ),
            )
            db.execute("UPDATE verification_attempts SET updated_at=? WHERE verification_id=?", (terminal_at, verification_id))

    def _fail_remaining(self, verification_id: str, failed_stage: str, classification: str) -> None:
        stages = self._stage_names(verification_id)
        for stage in stages[stages.index(failed_stage) + 1:]:
            self._record_stage(verification_id, stage, "SKIPPED", facts={"because": failed_stage})
        self._terminalize(verification_id, "FAILED", classification)

    def _stage_names(self, verification_id: str) -> tuple[str, ...]:
        attempt = self._attempt(verification_id)
        return STAGES_V1 if attempt.get("pipeline_schema") == PIPELINE_V1 else STAGES

    def _terminalize(
        self,
        verification_id: str,
        status: str,
        classification: str,
        *,
        archive_sha256: str | None = None,
        archive_size_bytes: int | None = None,
        archive_path: str | None = None,
        error_code: str | None = None,
        error_detail: str | None = None,
    ) -> None:
        now = utc_now()
        with self.db.connect() as db:
            if status != "PASSED":
                db.execute("DELETE FROM verification_interactions WHERE verification_id=?", (verification_id,))
            db.execute(
                """UPDATE verification_attempts SET status=?,classification=?,updated_at=?,terminal_at=?,
                   archive_sha256=?,archive_size_bytes=?,archive_path=?,error_code=?,error_detail=?
                   WHERE verification_id=? AND status='RUNNING'""",
                (
                    status, classification, now, now, archive_sha256,
                    archive_size_bytes, archive_path, error_code, error_detail,
                    verification_id,
                ),
            )
            row = db.execute("SELECT session_id FROM verification_attempts WHERE verification_id=?", (verification_id,)).fetchone()
            if row:
                self.db.event(db, row[0], "VERIFICATION_TERMINAL", {"verification_id": verification_id, "status": status, "classification": classification})

    def _record_cleanup_failure(self, verification_id: str, detail: str) -> None:
        now = utc_now()
        with self.db.connect() as db:
            db.execute("DELETE FROM verification_interactions WHERE verification_id=?", (verification_id,))
            db.execute(
                """UPDATE verification_attempts SET status='FAILED',classification='VERIFIER_INTERNAL_FAILED',
                   updated_at=?,terminal_at=?,archive_sha256=NULL,archive_size_bytes=NULL,archive_path=NULL,
                   error_code='GIT_WORKTREE_CLEANUP_FAILED',error_detail=? WHERE verification_id=?""",
                (now, now, detail[:2000], verification_id),
            )
            row = db.execute(
                "SELECT session_id FROM verification_attempts WHERE verification_id=?", (verification_id,)
            ).fetchone()
            if row:
                self.db.event(db, row[0], "VERIFICATION_CLEANUP_FAILED", {"verification_id": verification_id})

    def _attempt(self, verification_id: str) -> dict:
        with self.db.connect() as db:
            row = db.execute("SELECT * FROM verification_attempts WHERE verification_id=?", (verification_id,)).fetchone()
        if row is None:
            raise DeveloperError("VERIFICATION_NOT_FOUND", "verification attempt does not exist")
        return dict(row)

    def result(self, verification_id: str) -> dict:
        attempt = self._attempt(verification_id)
        with self.db.connect() as db:
            rows = db.execute(
                "SELECT * FROM verification_stages WHERE verification_id=? ORDER BY stage_order",
                (verification_id,),
            ).fetchall()
            interaction_row = db.execute(
                "SELECT * FROM verification_interactions WHERE verification_id=?", (verification_id,)
            ).fetchone()
        stages = []
        for source in rows:
            row = dict(source)
            stages.append({
                "name": row["stage_name"],
                "status": row["status"],
                "exit_code": row["exit_code"],
                "started_at": row["started_at"],
                "terminal_at": row["terminal_at"],
                "duration_ms": row["duration_ms"],
                "stdout": row["stdout_text"],
                "stderr": row["stderr_text"],
                "stdout_truncated_bytes": row["stdout_truncated_bytes"],
                "stderr_truncated_bytes": row["stderr_truncated_bytes"],
                "facts": json.loads(row["facts"]),
            })
        archive = None
        if attempt["archive_sha256"]:
            archive_path = Path(attempt["archive_path"])
            available = archive_path.is_file() and sha256_file(archive_path) == attempt["archive_sha256"]
            archive = {
                "sha256": attempt["archive_sha256"],
                "size_bytes": attempt["archive_size_bytes"],
                "path_uri": path_uri(archive_path),
                "byte_identical_builds": 2,
                "available": available,
            }
        result = {
            "schema": RESULT_SCHEMA_V1 if attempt.get("pipeline_schema") == PIPELINE_V1 else RESULT_SCHEMA,
            "ok": attempt["status"] == "PASSED",
            "status": attempt["status"],
            "classification": attempt["classification"],
            "verification_id": verification_id,
            "session_id": attempt["session_id"],
            "application_id": attempt["application_id"],
            "candidate": {
                "commit": attempt["candidate_commit"],
                "tree": attempt["candidate_tree"],
                "base_commit": attempt["base_commit"],
                "branch": attempt["development_branch"],
            },
            "toolchain": {
                "contract": attempt["contract"],
                "lock_digest": attempt["lock_digest"],
                "release_binding_commit": attempt["release_binding_commit"],
                "authoring_bundle_sha256": attempt["authoring_bundle_sha256"],
                "wheel_sha256": attempt["wheel_sha256"],
            },
            "stages": stages,
            "candidate_archive": archive,
            "started_at": attempt["started_at"],
            "terminal_at": attempt["terminal_at"],
            "error": None if not attempt["error_code"] else {"code": attempt["error_code"], "detail": attempt["error_detail"]},
        }
        if attempt.get("pipeline_schema") == PIPELINE_V1:
            interaction = dict(interaction_row) if interaction_row is not None else None
            available = False
            if interaction:
                try:
                    canonical_path = safe_resolve(
                        Path(interaction["canonical_path"]), root=self.config.verification_interactions_root
                    )
                    available = (
                        canonical_path.is_file()
                        and sha256_file(canonical_path) == interaction["canonical_sha256"]
                        and canonical_path.stat().st_size == interaction["canonical_size_bytes"]
                    )
                except (DeveloperError, OSError, ValueError):
                    available = False
            result["pipeline"] = PIPELINE_V1
            result["interaction_contract"] = None if interaction is None else {
                "schema": interaction["schema"],
                "source_member": interaction["source_member"],
                "source_sha256": interaction["source_sha256"],
                "canonical_sha256": interaction["canonical_sha256"],
                "canonical_size_bytes": interaction["canonical_size_bytes"],
                "operation_id": interaction["operation_id"],
                "available": available,
            }
        return result

    def reconcile(self, session_id: str, *, lock_held: bool = False) -> None:
        with self.db.connect() as db:
            running = db.execute(
                "SELECT verification_id FROM verification_attempts WHERE session_id=? AND status='RUNNING'",
                (session_id,),
            ).fetchall()
        if running and (lock_held or lock_is_available(self.config.verification_lock(session_id))):
            for row in running:
                self._terminalize(row[0], "INTERRUPTED", "VERIFIER_PROCESS_INTERRUPTED")
                self._cleanup_interrupted(row[0])

    def _cleanup_interrupted(self, verification_id: str) -> None:
        attempt = self._attempt(verification_id)
        with self.db.connect() as db:
            session = db.execute(
                "SELECT worktree_path FROM sessions WHERE session_id=?", (attempt["session_id"],)
            ).fetchone()
        attempt_root = self._attempt_root(verification_id)
        failures = []
        if session and session[0] and Path(session[0]).is_dir():
            repository_worktree = Path(session[0])
            for checkout in (attempt_root / "c", attempt_root / "a", attempt_root / "b"):
                try:
                    remove_detached_worktree(repository_worktree, checkout)
                except (DeveloperError, OSError) as exc:
                    failures.append(str(exc))
        if attempt_root.exists():
            shutil.rmtree(attempt_root, ignore_errors=True)
            if attempt_root.exists():
                failures.append("verification attempt directory remains after cleanup")
        if attempt.get("temporary_path"):
            try:
                external_temp_removed = self._cleanup_external_temp(
                    verification_id, Path(attempt["temporary_path"])
                )
            except (OSError, RuntimeError) as exc:
                external_temp_removed = False
                failures.append(str(exc))
            if not external_temp_removed:
                failures.append("external verification temporary directory remains after cleanup")
        if failures:
            self._record_cleanup_failure(verification_id, "; ".join(failures))

    def latest(self, session_id: str, workspace: dict | None) -> dict:
        self.reconcile(session_id)
        with self.db.connect() as db:
            row = db.execute(
                "SELECT * FROM verification_attempts WHERE session_id=? ORDER BY started_at DESC,verification_id DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        if row is None:
            return {"latest": None, "current_head_state": "NO_VERIFICATION"}
        row = dict(row)
        if row["status"] == "RUNNING":
            state = "VERIFYING"
        elif (
            workspace is None
            or not workspace.get("exists")
            or workspace.get("dirty")
            or not workspace.get("branch_matches")
            or workspace.get("current_commit") != row["candidate_commit"]
        ):
            state = "STALE"
        else:
            state = {"PASSED": "VERIFIED", "FAILED": "FAILED", "INTERRUPTED": "INTERRUPTED"}[row["status"]]
        return {
            "latest": {
                "verification_id": row["verification_id"],
                "status": row["status"],
                "classification": row["classification"],
                "application_id": row["application_id"],
                "candidate_commit": row["candidate_commit"],
                "candidate_tree": row["candidate_tree"],
                "archive_sha256": row["archive_sha256"],
            },
            "current_head_state": state,
        }
