from __future__ import annotations

import json
import sqlite3
import tempfile
import tomllib
from pathlib import Path

from .config import Config
from .database import Database, SCHEMA_VERSION
from .errors import DeveloperError
from .git import (
    checkout_facts,
    ensure_mirror,
    ensure_worktree,
    initialize_bare,
    mirror_base,
    remote_default_branch,
    run_git,
)
from .toolchain import ToolchainCache, ToolchainLock, current_lock, read_lock
from .verification import VerificationService
from .release_candidate import ReleaseCandidateService
from .util import (
    exclusive_lock,
    machine_id,
    new_id,
    normalize_repository,
    operation_lock,
    path_uri,
    safe_resolve,
    stable_digest,
    utc_now,
    validate_new_project,
    PROJECT_ID,
)


RESULT_SCHEMA = "capy.development-result/v0"
PROJECT_SCHEMA = "capy.project-result/v0"


class DeveloperCore:
    def __init__(self, config: Config | None = None):
        self.config = config or Config.from_environment()
        self.config.ensure()
        self.db = Database(self.config.database)
        self.toolchains = ToolchainCache(self.config.cache_root)
        self.verifications = VerificationService(self)
        self.release_candidates = ReleaseCandidateService(self)

    def doctor(self) -> dict:
        bundle = self.toolchains.accepted_bundle()
        git_version = run_git(["--version"])
        return {
            "schema": "capy.developer-doctor/v0",
            "ok": True,
            "version": "0.5.0",
            "database_schema": SCHEMA_VERSION,
            "git": git_version,
            "roots": {
                "data": str(self.config.data_root.resolve()),
                "cache": str(self.config.cache_root.resolve()),
                "repositories": str(self.config.repositories_root.resolve()),
                "worktrees": str(self.config.worktrees_root.resolve()),
                "release_candidates": str(self.config.release_candidates_root.resolve()),
            },
            "accepted_toolchain": {
                "status": "AVAILABLE",
                "bundle_sha256": bundle.parent.name,
            },
            "release_candidate": {
                "bundle_format": "zip/.capyrc",
                "manifest_schema": "capy.application-release-candidate/v1",
                "receipt_schema": "capy.development-verification-receipt/v1",
                "acceptance": "not_implemented",
            },
        }

    def import_project(self, checkout: str) -> dict:
        supplied = Path(checkout)
        if supplied.is_symlink():
            raise DeveloperError("PATH_SYMLINK_REJECTED", "the import checkout may not be a symlink")
        path = safe_resolve(supplied, must_exist=True)
        if not path.is_dir():
            raise DeveloperError("IMPORT_PATH_INVALID", "the import path is not a directory")
        before = checkout_facts(path)
        if not before["origin"]:
            raise DeveloperError("CANONICAL_ORIGIN_REQUIRED", "import requires an explicit canonical origin remote")
        self._checkout_metadata(path)  # Validate local paths; canonical values come from the remote base below.
        default_branch = remote_default_branch(before["origin"], "main")
        with tempfile.TemporaryDirectory(prefix="import-snapshot-", dir=self.config.cache_root) as temporary_text:
            snapshot_root = Path(temporary_text)
            snapshot_mirror = snapshot_root / "repository.git"
            snapshot = snapshot_root / "checkout"
            ensure_mirror(before["origin"], snapshot_mirror)
            snapshot_base = mirror_base(snapshot_mirror, default_branch)
            run_git(["--git-dir", str(snapshot_mirror), "worktree", "add", "--detach", str(snapshot), snapshot_base])
            manifest, applications, lock = self._checkout_metadata(snapshot)
        if not applications:
            raise DeveloperError("CAPY_APPLICATION_MARKER_MISSING", "no explicit Capy application descriptor was found")
        repository_identity = normalize_repository(before["origin"])
        name = str(manifest.get("name") if manifest else path.name)
        now = utc_now()
        availability = self.toolchains.availability(lock)
        with operation_lock(self.config.operation_lock), self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM projects WHERE repository_identity=?", (repository_identity,)
            ).fetchone()
            if existing:
                project_id = existing["project_id"]
                db.execute(
                    "UPDATE projects SET name=?,repository_url=?,default_branch=?,status='ACTIVE',updated_at=? WHERE project_id=?",
                    (name, before["origin"], default_branch, now, project_id),
                )
            else:
                project_id = str(manifest.get("project_id")) if manifest and manifest.get("project_id") else new_id("prj")
                if PROJECT_ID.fullmatch(project_id) is None:
                    raise DeveloperError("PROJECT_MANIFEST_INVALID", "project_id is not a safe opaque identity")
                identity_owner = db.execute("SELECT repository_identity FROM projects WHERE project_id=?", (project_id,)).fetchone()
                if identity_owner and identity_owner[0] != repository_identity:
                    raise DeveloperError("PROJECT_ID_CONFLICT", "project_id is already bound to another repository")
                db.execute(
                    "INSERT INTO projects VALUES (?,?,?,?,?,'ACTIVE',?,?)",
                    (project_id, name, repository_identity, before["origin"], default_branch, now, now),
                )
            aliases = {name, path.name}
            if manifest:
                aliases.update(str(item) for item in manifest.get("aliases", []) if item)
            for alias in sorted(aliases):
                db.execute(
                    "INSERT OR IGNORE INTO project_aliases(project_id,alias,source) VALUES (?,?,?)",
                    (project_id, alias, "import"),
                )
            db.execute("DELETE FROM project_applications WHERE project_id=?", (project_id,))
            for application_id in applications:
                db.execute(
                    "INSERT OR IGNORE INTO project_applications(project_id,application_id,source) VALUES (?,?,?)",
                    (project_id, application_id, "descriptor"),
                )
            checkout_id = "chk_" + stable_digest([machine_id(), str(path)])[:32]
            db.execute(
                """INSERT INTO local_checkouts VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(machine_id,native_path) DO UPDATE SET
                   project_id=excluded.project_id,path_uri=excluded.path_uri,
                   observed_commit=excluded.observed_commit,observed_branch=excluded.observed_branch,
                   dirty=excluded.dirty,last_seen_at=excluded.last_seen_at""",
                (checkout_id, project_id, machine_id(), str(path), path_uri(path), "IMPORTED",
                 before["commit"], before["branch"], int(before["dirty"]), now),
            )
            self._store_lock(db, project_id, lock, availability)
        after = checkout_facts(path)
        if before != after:
            raise DeveloperError("IMPORTED_CHECKOUT_CHANGED", "import changed the developer checkout unexpectedly")
        return self._project_result(project_id, imported=True)

    def _checkout_metadata(self, checkout: Path) -> tuple[dict | None, list[str], ToolchainLock]:
        checkout = checkout.resolve(strict=True)
        manifest = self._project_manifest(checkout)
        applications = self._discover_applications(checkout, manifest)
        for lock_candidate in (checkout / "capy.lock", checkout / "DEVKIT.lock"):
            if lock_candidate.is_symlink():
                raise DeveloperError("LOCK_PATH_INVALID", "DevKit lock may not be a symlink")
        lock = read_lock(checkout)
        if lock.source_path:
            try:
                relative_lock = str(Path(lock.source_path).resolve().relative_to(checkout.resolve()))
                lock = ToolchainLock(
                    lock.schema, lock.contract, lock.repository, lock.commit, lock.wheel,
                    lock.wheel_sha256, lock.bundle_sha256, lock.interaction_contract, relative_lock,
                    lock.lock_status, lock.detail,
                )
            except ValueError as exc:
                raise DeveloperError("LOCK_PATH_INVALID", "DevKit lock path escaped the checkout") from exc
        return manifest, applications, lock

    def _project_manifest(self, checkout: Path) -> dict | None:
        path = checkout / "capy.project.toml"
        if not path.exists():
            return None
        if path.is_symlink():
            raise DeveloperError("PROJECT_MANIFEST_INVALID", "capy.project.toml may not be a symlink")
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
            raise DeveloperError("PROJECT_MANIFEST_INVALID", "capy.project.toml is malformed") from exc
        if data.get("schema") != "capy.project/v0":
            raise DeveloperError("PROJECT_MANIFEST_INVALID", "capy.project.toml schema is unsupported")
        return data

    def _discover_applications(self, checkout: Path, manifest: dict | None) -> list[str]:
        declared: set[str] = set()
        if manifest:
            applications = manifest.get("applications", {})
            if isinstance(applications, dict):
                values = applications.get("ids", [])
                if not isinstance(values, list):
                    raise DeveloperError("PROJECT_MANIFEST_INVALID", "applications.ids must be an array")
                declared.update(str(value) for value in values)
        descriptors: list[Path] = []
        ignored = {".git", ".venv", "venv", "build", "dist", ".tox", ".nox", "node_modules", "__pycache__"}
        for descriptor in checkout.rglob("capability.toml"):
            try:
                relative = descriptor.relative_to(checkout)
            except ValueError:
                continue
            if any(part in ignored or part.startswith(".") for part in relative.parts[:-1]) or len(relative.parts) > 8:
                continue
            if descriptor.is_symlink():
                raise DeveloperError("CAPABILITY_PATH_INVALID", "capability descriptor may not be a symlink")
            try:
                descriptor.resolve(strict=True).relative_to(checkout)
            except ValueError as exc:
                raise DeveloperError("CAPABILITY_PATH_INVALID", "capability descriptor escapes the checkout") from exc
            descriptors.append(descriptor)
            if len(descriptors) > 64:
                raise DeveloperError("APPLICATION_MARKERS_EXCESSIVE", "too many capability descriptors")
        for descriptor in descriptors:
            try:
                data = tomllib.loads(descriptor.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
                raise DeveloperError("CAPABILITY_DESCRIPTOR_INVALID", f"malformed descriptor: {descriptor.relative_to(checkout)}") from exc
            application_id = data.get("id")
            if isinstance(data.get("schema"), str) and data["schema"].startswith("capy.script/") and isinstance(application_id, str) and application_id:
                declared.add(application_id)
        return sorted(declared)

    def _store_lock(self, db: sqlite3.Connection, project_id: str, lock: ToolchainLock, availability: str) -> None:
        db.execute(
            """INSERT INTO toolchain_locks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(project_id) DO UPDATE SET
               schema=excluded.schema,contract=excluded.contract,
               devkit_repository=excluded.devkit_repository,devkit_commit=excluded.devkit_commit,
               wheel_filename=excluded.wheel_filename,wheel_sha256=excluded.wheel_sha256,
               authoring_bundle_sha256=excluded.authoring_bundle_sha256,
               interaction_contract=excluded.interaction_contract,
               lock_source_path=excluded.lock_source_path,lock_status=excluded.lock_status,
               availability=excluded.availability,detail=excluded.detail""",
            (project_id, lock.schema, lock.contract, lock.repository, lock.commit,
             lock.wheel, lock.wheel_sha256, lock.bundle_sha256, lock.interaction_contract, lock.source_path,
             lock.lock_status, availability, lock.detail),
        )

    def search_projects(self, query: str, limit: int = 10) -> dict:
        normalized = query.strip().lower()
        if not normalized:
            raise DeveloperError("SEARCH_QUERY_INVALID", "query must be non-empty")
        if not isinstance(limit, int) or not 1 <= limit <= 50:
            raise DeveloperError("SEARCH_LIMIT_INVALID", "limit must be between 1 and 50")
        with self.db.connect() as db:
            rows = db.execute("SELECT * FROM projects WHERE status='ACTIVE' ORDER BY name,project_id").fetchall()
            matches: list[dict] = []
            for row in rows:
                project_id = row["project_id"]
                applications = [item[0] for item in db.execute(
                    "SELECT application_id FROM project_applications WHERE project_id=? ORDER BY application_id", (project_id,)
                )]
                aliases = [item[0] for item in db.execute(
                    "SELECT alias FROM project_aliases WHERE project_id=? ORDER BY alias", (project_id,)
                )]
                exact_reason = None
                if normalized == project_id.lower():
                    exact_reason = "project_id"
                elif normalized in [value.lower() for value in applications]:
                    exact_reason = "application_id"
                elif normalized == row["repository_identity"].lower():
                    exact_reason = "repository_identity"
                elif normalized in [value.lower() for value in aliases]:
                    exact_reason = "alias"
                haystack = [project_id, row["name"], row["repository_identity"], *applications, *aliases]
                if exact_reason or any(normalized in value.lower() for value in haystack):
                    known = db.execute(
                        "SELECT COUNT(*) FROM local_checkouts WHERE project_id=?", (project_id,)
                    ).fetchone()[0]
                    matches.append({
                        "project_id": project_id,
                        "name": row["name"],
                        "application_ids": applications,
                        "canonical_repository": {
                            "identity": row["repository_identity"],
                            "default_branch": row["default_branch"],
                        },
                        "status": row["status"],
                        "known_local_checkout": bool(known),
                        "exact_match_reason": exact_reason,
                    })
            matches.sort(key=lambda value: (value["exact_match_reason"] is None, value["name"].lower(), value["project_id"]))
        return {"schema": "capy.projects-search-result/v0", "ok": True, "query": query, "matches": matches[:limit]}

    def start_development(self, payload: dict) -> dict:
        normalized = self._normalize_start(payload)
        digest = stable_digest(normalized)
        key = normalized["idempotency_key"]
        with operation_lock(self.config.operation_lock):
            with self.db.connect() as db:
                existing = db.execute("SELECT * FROM sessions WHERE idempotency_key=?", (key,)).fetchone()
                if existing:
                    if existing["request_digest"] != digest:
                        raise DeveloperError("IDEMPOTENCY_CONFLICT", "idempotency key was already used with different input")
                    session = dict(existing)
                    if session["status"] == "FAILED":
                        raise DeveloperError(
                            session["error_code"] or "SESSION_FAILED",
                            session["error_detail"] or "session preparation previously failed",
                            data={"session_id": session["session_id"]},
                        )
                    if session["status"] != "PREPARING":
                        return self._session_result(session["session_id"])
                else:
                    session_id = new_id("ses")
                    project_id = None
                    if "existing" in normalized:
                        project_id = self._resolve_existing(db, normalized["existing"])
                    now = utc_now()
                    db.execute(
                        """INSERT INTO sessions(session_id,project_id,idempotency_key,request_digest,
                           normalized_input,allocated_at,updated_at,status)
                           VALUES (?,?,?,?,?,?,?,'PREPARING')""",
                        (session_id, project_id, key, digest, json.dumps(normalized, sort_keys=True), now, now),
                    )
                    self.db.event(db, session_id, "SESSION_ALLOCATED", {"project_id": project_id})
                    db.commit()
                    session = dict(db.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone())
            try:
                if "existing" in normalized:
                    self._prepare_existing(session["session_id"])
                else:
                    self._prepare_new(session["session_id"])
            except DeveloperError as exc:
                with self.db.connect() as db:
                    db.execute(
                        "UPDATE sessions SET status='FAILED',error_code=?,error_detail=?,updated_at=? WHERE session_id=?",
                        (exc.code, exc.detail, utc_now(), session["session_id"]),
                    )
                    self.db.event(db, session["session_id"], "SESSION_FAILED", {"code": exc.code})
                exc.data.setdefault("session_id", session["session_id"])
                raise
            except Exception as exc:
                wrapped = DeveloperError("INTERNAL_ERROR", "session preparation failed unexpectedly", data={"session_id": session["session_id"]})
                with self.db.connect() as db:
                    db.execute(
                        "UPDATE sessions SET status='FAILED',error_code=?,error_detail=?,updated_at=? WHERE session_id=?",
                        (wrapped.code, wrapped.detail, utc_now(), session["session_id"]),
                    )
                    self.db.event(db, session["session_id"], "SESSION_FAILED", {"code": wrapped.code})
                raise wrapped from exc
            return self._session_result(session["session_id"])

    def _normalize_start(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise DeveloperError("START_INPUT_INVALID", "start input must be an object")
        allowed = {"idempotency_key", "request", "existing", "new"}
        if set(payload) - allowed:
            raise DeveloperError("START_INPUT_INVALID", "start input contains unknown fields")
        key = payload.get("idempotency_key")
        request = payload.get("request")
        if not isinstance(key, str) or not key.strip() or len(key) > 200:
            raise DeveloperError("IDEMPOTENCY_KEY_INVALID", "idempotency_key must be a bounded non-empty string")
        if not isinstance(request, str) or not request.strip() or len(request) > 10000:
            raise DeveloperError("DEVELOPMENT_REQUEST_INVALID", "request must be a bounded non-empty string")
        if ("existing" in payload) == ("new" in payload):
            raise DeveloperError("PROJECT_INTENT_INVALID", "provide exactly one of existing or new")
        normalized: dict = {"idempotency_key": key.strip(), "request": request.strip()}
        if "existing" in payload:
            selector = payload["existing"]
            if not isinstance(selector, dict) or len(selector) != 1:
                raise DeveloperError("PROJECT_SELECTOR_INVALID", "existing selector must contain exactly one field")
            field, value = next(iter(selector.items()))
            if field not in {"project_id", "application_id", "repository", "alias", "name"} or not isinstance(value, str) or not value.strip():
                raise DeveloperError("PROJECT_SELECTOR_INVALID", "existing selector is unsupported")
            normalized["existing"] = {field: normalize_repository(value) if field == "repository" else value.strip()}
        else:
            specification = payload["new"]
            if not isinstance(specification, dict) or set(specification) != {"name", "application_id"}:
                raise DeveloperError("NEW_PROJECT_INVALID", "new must contain only name and application_id")
            validate_new_project(specification["name"], specification["application_id"])
            normalized["new"] = {"name": specification["name"].strip(), "application_id": specification["application_id"]}
        return normalized

    def _resolve_existing(self, db: sqlite3.Connection, selector: dict) -> str:
        field, value = next(iter(selector.items()))
        if field == "project_id":
            rows = db.execute("SELECT project_id FROM projects WHERE project_id=? AND status='ACTIVE'", (value,)).fetchall()
        elif field == "application_id":
            rows = db.execute(
                "SELECT p.project_id FROM projects p JOIN project_applications a USING(project_id) WHERE a.application_id=? AND p.status='ACTIVE'",
                (value,),
            ).fetchall()
        elif field == "repository":
            rows = db.execute("SELECT project_id FROM projects WHERE repository_identity=? AND status='ACTIVE'", (value,)).fetchall()
        else:
            rows = db.execute(
                """SELECT DISTINCT p.project_id FROM projects p LEFT JOIN project_aliases a USING(project_id)
                   WHERE p.status='ACTIVE' AND (lower(p.name)=lower(?) OR lower(a.alias)=lower(?))""",
                (value, value),
            ).fetchall()
        if not rows:
            raise DeveloperError("PROJECT_NOT_FOUND", "no exact existing project matched the selector")
        if len(rows) != 1:
            raise DeveloperError("PROJECT_AMBIGUOUS", "selector matched more than one project", data={"candidate_count": len(rows)})
        return rows[0][0]

    def _prepare_existing(self, session_id: str) -> None:
        with self.db.connect() as db:
            session = db.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
            project = db.execute("SELECT * FROM projects WHERE project_id=?", (session["project_id"],)).fetchone()
            normalized = json.loads(session["normalized_input"])
            required_application = normalized["existing"].get("application_id")
        mirror = safe_resolve(self.config.repositories_root / f"{project['project_id']}.git", root=self.config.repositories_root)
        if project["repository_url"] != mirror.as_uri():
            ensure_mirror(project["repository_url"], mirror)
        base = mirror_base(mirror, project["default_branch"])
        self._complete_workspace(session_id, project["project_id"], mirror, base, required_application)

    def _prepare_new(self, session_id: str) -> None:
        with self.db.connect() as db:
            session = db.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
            normalized = json.loads(session["normalized_input"])
            project_id = session["project_id"]
            if project_id:
                project = db.execute("SELECT * FROM projects WHERE project_id=?", (project_id,)).fetchone()
            else:
                specification = normalized["new"]
                project_id = new_id("prj")
                repository = safe_resolve(self.config.repositories_root / f"{project_id}.git", root=self.config.repositories_root)
                repository_url = repository.as_uri()
                now = utc_now()
                db.execute(
                    "INSERT INTO projects VALUES (?,?,?,?,?,'ACTIVE',?,?)",
                    (project_id, specification["name"], normalize_repository(repository_url), repository_url, "main", now, now),
                )
                db.execute("INSERT INTO project_aliases VALUES (?,?,?)", (project_id, specification["name"], "new"))
                db.execute("INSERT INTO project_applications VALUES (?,?,?)", (project_id, specification["application_id"], "new"))
                lock = current_lock()
                self._store_lock(db, project_id, lock, self.toolchains.availability(lock))
                db.execute("UPDATE sessions SET project_id=?,updated_at=? WHERE session_id=?", (project_id, now, session_id))
                self.db.event(db, session_id, "PROJECT_CREATED", {"project_id": project_id})
                project = db.execute("SELECT * FROM projects WHERE project_id=?", (project_id,)).fetchone()
        repository = safe_resolve(self.config.repositories_root / f"{project_id}.git", root=self.config.repositories_root)
        initialize_bare(repository)
        try:
            base = mirror_base(repository, "main")
        except DeveloperError:
            normalized = json.loads(session["normalized_input"])
            self._seed_new_project(repository, project_id, normalized["new"])
            base = mirror_base(repository, "main")
        self._complete_workspace(session_id, project_id, repository, base)

    def _seed_new_project(self, repository: Path, project_id: str, specification: dict) -> None:
        seeds = self.config.data_root / "seeds"
        seeds.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="seed-", dir=seeds) as temporary_text:
            seed = Path(temporary_text)
            self.toolchains.materialize_template(seed, specification["application_id"], specification["name"])
            (seed / "capy.project.toml").write_text(
                'schema = "capy.project/v0"\n'
                f'project_id = "{project_id}"\n'
                f'name = "{specification["name"]}"\n\n'
                '[repository]\ndefault_branch = "main"\n\n'
                f'[applications]\nids = ["{specification["application_id"]}"]\n', encoding="utf-8",
            )
            lock = current_lock()
            (seed / "capy.lock").write_text(
                'schema = "capy.toolchain-lock/v1"\n'
                f'contract = "{lock.contract}"\n'
                f'interaction_contract = "{lock.interaction_contract}"\n'
                f'devkit_repository = "{lock.repository}"\n'
                f'devkit_commit = "{lock.commit}"\n'
                f'wheel = "{lock.wheel}"\n'
                f'wheel_sha256 = "{lock.wheel_sha256}"\n'
                f'authoring_bundle_sha256 = "{lock.bundle_sha256}"\n', encoding="utf-8",
            )
            (seed / "CAPY.md").write_text(
                f"# {specification['name']}\n\n"
                f"Capy application identity: `{specification['application_id']}`.\n\n"
                "Work only in this prepared repository and worktree. The application contract is "
                "`capability.toml`; Capy Developer resolves the exact toolchain declared in `capy.lock`. "
                "Use ordinary project-native commands while editing, commit the candidate, then call "
                "`capy_development_verify` or `capy-dev development verify` for authoritative verification.\n\n"
                "Verification does not publish or deploy the application. Do not read or modify Capy runtime "
                "source or production data.\n", encoding="utf-8",
            )
            (seed / "AGENTS.md").write_text("Read CAPY.md before working in this prepared application.\n", encoding="utf-8")
            with (seed / ".gitignore").open("a", encoding="utf-8") as ignored:
                ignored.write("\n.capy-local/\n")
            with (seed / "CAPY.md").open("a", encoding="utf-8") as instructions:
                instructions.write(
                    "\nIf .capy-local/handoff.json exists, read its nonsecret handoff_id and call "
                    "capy_development_attach before editing. The session is already prepared; "
                    "do not call development_start to recreate it. Implement only the owner's "
                    "actual request. After committing and passing development_verify, call "
                    "capy_release_candidate_create, then finish the session. A candidate is "
                    "not independently accepted, installed, previewed or deployed.\n")
            run_git(["init", "--initial-branch=main"], cwd=seed)
            run_git(["config", "user.name", "Capy Developer"], cwd=seed)
            run_git(["config", "user.email", "capy-developer@localhost"], cwd=seed)
            run_git(["add", "--all"], cwd=seed)
            run_git(["commit", "-m", "Initialize Capy application project"], cwd=seed)
            run_git(["remote", "add", "origin", repository.as_uri()], cwd=seed)
            run_git(["push", "origin", "main"], cwd=seed)

    def _complete_workspace(
        self, session_id: str, project_id: str, mirror: Path, base: str,
        required_application: str | None = None,
    ) -> None:
        branch = f"capy/dev/{session_id}"
        worktree = safe_resolve(self.config.worktrees_root / project_id / session_id, root=self.config.worktrees_root)
        ensure_worktree(mirror, worktree, branch, base)
        actual = checkout_facts(worktree)
        if actual["commit"] != base or actual["branch"] != branch or actual["dirty"]:
            raise DeveloperError("WORKTREE_VALIDATION_FAILED", "prepared worktree does not match its recorded clean base")
        _, applications, lock = self._checkout_metadata(worktree)
        if not applications:
            raise DeveloperError("CAPY_APPLICATION_MARKER_MISSING", "exact source base contains no Capy application descriptor")
        availability = self.toolchains.availability(lock)
        with self.db.connect() as db:
            db.execute("DELETE FROM project_applications WHERE project_id=?", (project_id,))
            for application_id in applications:
                db.execute(
                    "INSERT INTO project_applications(project_id,application_id,source) VALUES (?,?,?)",
                    (project_id, application_id, "exact_base"),
                )
            self._store_lock(db, project_id, lock, availability)
        if required_application and required_application not in applications:
            raise DeveloperError(
                "APPLICATION_NOT_AT_BASE",
                "selected application is not present at the synchronized exact source base",
            )
        now = utc_now()
        with self.db.connect() as db:
            db.execute(
                """UPDATE sessions SET exact_base_commit=?,development_branch=?,worktree_path=?,
                   updated_at=?,status='READY',error_code=NULL,error_detail=NULL WHERE session_id=?""",
                (base, branch, str(worktree), now, session_id),
            )
            self.db.event(db, session_id, "REPOSITORY_SYNCHRONIZED", {"base_commit": base})
            self.db.event(db, session_id, "WORKTREE_CREATED", {"branch": branch, "path_uri": path_uri(worktree)})
            self.db.event(db, session_id, "SESSION_READY", {})

    def continue_development(self, payload: dict) -> dict:
        from .continuation import continue_development
        return continue_development(self, payload)

    def attach_development(self, handoff_id: str) -> dict:
        from .desktop import Companion
        return Companion(self).attach(handoff_id)

    def inspect_development(self, session_id: str) -> dict:
        return self._session_result(session_id, revalidate=True)

    def finish_development(self, session_id: str, disposition: str) -> dict:
        with exclusive_lock(
            self.config.verification_lock(session_id), 0,
            busy_code="VERIFICATION_BUSY",
            busy_detail="a live verification prevents finishing this development session",
        ):
            self.verifications.reconcile(session_id, lock_held=True)
            return self._finish_development_unlocked(session_id, disposition)

    def _finish_development_unlocked(self, session_id: str, disposition: str) -> dict:
        if disposition not in {"COMPLETED", "CANCELLED"}:
            raise DeveloperError("DISPOSITION_INVALID", "disposition must be COMPLETED or CANCELLED")
        with operation_lock(self.config.operation_lock), self.db.connect() as db:
            session = db.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
            if not session:
                raise DeveloperError("SESSION_NOT_FOUND", "development session does not exist")
            if session["status"] in {"COMPLETED", "CANCELLED"}:
                if session["terminal_disposition"] != disposition:
                    raise DeveloperError("SESSION_TERMINAL_CONFLICT", "session already has another terminal disposition")
                return self._session_result(session_id, revalidate=True)
            if session["status"] != "READY":
                raise DeveloperError("SESSION_NOT_READY", "only a READY session can be finished")
            path = Path(session["worktree_path"])
            facts = checkout_facts(path) if path.is_dir() else {"commit": None, "dirty": None}
            now = utc_now()
            db.execute(
                """UPDATE sessions SET status=?,terminal_disposition=?,terminal_at=?,updated_at=?,
                   final_commit=?,final_dirty=? WHERE session_id=?""",
                (disposition, disposition, now, now, facts["commit"],
                 None if facts["dirty"] is None else int(facts["dirty"]), session_id),
            )
            self.db.event(db, session_id, "SESSION_FINISHED", {"disposition": disposition, **facts})
        return self._session_result(session_id, revalidate=True)

    def _session_result(self, session_id: str, revalidate: bool = False) -> dict:
        with self.db.connect() as db:
            session = db.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
            if not session:
                raise DeveloperError("SESSION_NOT_FOUND", "development session does not exist")
            project = db.execute("SELECT * FROM projects WHERE project_id=?", (session["project_id"],)).fetchone() if session["project_id"] else None
            events = [
                {"type": row["event_type"], "created_at": row["created_at"], "facts": json.loads(row["facts"])}
                for row in db.execute("SELECT * FROM session_events WHERE session_id=? ORDER BY event_id", (session_id,))
            ]
        workspace = None
        discrepancy = None
        if session["worktree_path"]:
            path = Path(session["worktree_path"])
            if not path.is_dir():
                discrepancy = {"code": "WORKTREE_MISSING", "detail": "managed worktree is absent"}
                workspace = {"native_path": str(path), "path_uri": path_uri(path), "exists": False}
            else:
                facts = checkout_facts(path)
                workspace = {
                    "native_path": str(path), "path_uri": path_uri(path), "exists": True,
                    "current_commit": facts["commit"], "current_branch": facts["branch"],
                    "dirty": facts["dirty"], "head_matches_base": facts["commit"] == session["exact_base_commit"],
                    "branch_matches": facts["branch"] == session["development_branch"],
                }
                if revalidate and not workspace["branch_matches"]:
                    discrepancy = {"code": "WORKTREE_BRANCH_CHANGED", "detail": "managed worktree branch differs from the session"}
        verification = self.verifications.latest(session_id, workspace)
        return {
            "schema": RESULT_SCHEMA,
            "ok": session["status"] != "FAILED",
            "status": session["status"],
            "session_id": session_id,
            "project": None if not project else self._project_summary(dict(project)),
            "exact_base_commit": session["exact_base_commit"],
            "development_branch": session["development_branch"],
            "workspace": workspace,
            "toolchain": self._refresh_toolchain(session["project_id"]) if session["project_id"] else None,
            "canonical_instruction_file": str(Path(session["worktree_path"]) / "CAPY.md") if session["worktree_path"] and (Path(session["worktree_path"]) / "CAPY.md").is_file() else None,
            "terminal": {"disposition": session["terminal_disposition"], "at": session["terminal_at"], "final_commit": session["final_commit"], "final_dirty": None if session["final_dirty"] is None else bool(session["final_dirty"])},
            "discrepancy": discrepancy,
            "error": None if not session["error_code"] else {"code": session["error_code"], "detail": session["error_detail"]},
            "events": events,
            "verification": verification,
            "next_actions": [] if session["status"] != "READY" else [
                "Work only inside the returned workspace.",
                "Commit candidate changes before authoritative verification.",
                "Call development_verify for the exact clean commit.",
                "After verification passes, call release_candidate_create with its verification_id.",
                "Call development_finish when the coding session ends.",
            ],
        }

    def verify_development(self, payload: dict) -> dict:
        return self.verifications.verify(payload)

    def create_release_candidate(self, verification_id: str) -> dict:
        return self.release_candidates.create(verification_id)

    def inspect_release_candidate(self, release_candidate_id: str) -> dict:
        return self.release_candidates.inspect(release_candidate_id)

    def _project_summary(self, project: dict) -> dict:
        with self.db.connect() as db:
            applications = [row[0] for row in db.execute(
                "SELECT application_id FROM project_applications WHERE project_id=? ORDER BY application_id", (project["project_id"],)
            )]
        return {
            "project_id": project["project_id"], "name": project["name"],
            "application_ids": applications,
            "canonical_repository": {
                "identity": project["repository_identity"], "url": project["repository_url"],
                "default_branch": project["default_branch"],
            },
        }

    def _project_result(self, project_id: str, imported: bool = False) -> dict:
        with self.db.connect() as db:
            project = db.execute("SELECT * FROM projects WHERE project_id=?", (project_id,)).fetchone()
        return {
            "schema": PROJECT_SCHEMA, "ok": True, "imported": imported,
            "project": self._project_summary(dict(project)),
            "toolchain": self._refresh_toolchain(project_id),
        }

    def _refresh_toolchain(self, project_id: str) -> dict | None:
        with self.db.connect() as db:
            row = db.execute("SELECT * FROM toolchain_locks WHERE project_id=?", (project_id,)).fetchone()
            if not row:
                return None
            lock = ToolchainLock(
                row["schema"], row["contract"], row["devkit_repository"], row["devkit_commit"],
                row["wheel_filename"], row["wheel_sha256"], row["authoring_bundle_sha256"],
                row["interaction_contract"], row["lock_source_path"], row["lock_status"], row["detail"],
            )
            availability = self.toolchains.availability(lock)
            if availability != row["availability"]:
                db.execute("UPDATE toolchain_locks SET availability=? WHERE project_id=?", (availability, project_id))
            result = dict(row)
            result["availability"] = availability
            return result
