"""Exact-source continuation reuses the existing catalog/session/worktree services."""
from __future__ import annotations
import json
from pathlib import Path
from .errors import DeveloperError
from .git import checkout_facts, run_git
from .util import exclusive_lock, operation_lock, new_id, stable_digest, utc_now, safe_resolve


def continue_development(core, payload):
    if not isinstance(payload, dict) or set(payload) != {'release_candidate_id','request','idempotency_key'}:
        raise DeveloperError('CONTINUATION_INPUT_INVALID', 'provide candidate, request and idempotency key only')
    # Reuse the shared bounded request/key normalization, without changing start intent.
    checked = core._normalize_start({'request': payload['request'], 'idempotency_key': payload['idempotency_key'],
                                    'existing': {'project_id': 'continuation'}})
    candidate = core.inspect_release_candidate(payload['release_candidate_id'])
    if not candidate['ok']:
        raise DeveloperError('CONTINUATION_CANDIDATE_INVALID', 'candidate bytes are unavailable or invalid')
    normalized = {'request': checked['request'], 'idempotency_key': checked['idempotency_key'],
                  'continue_candidate': candidate['release_candidate_id']}
    digest = stable_digest(normalized)
    parent_id = candidate['session_id']
    with exclusive_lock(core.config.verification_lock(parent_id), 0,
                        busy_code='VERIFICATION_BUSY', busy_detail='parent verification is still active'):
        with operation_lock(core.config.operation_lock):
            with core.db.connect() as db:
                existing = db.execute('SELECT * FROM sessions WHERE idempotency_key=?', (normalized['idempotency_key'],)).fetchone()
                if existing and existing['request_digest'] != digest:
                    raise DeveloperError('IDEMPOTENCY_CONFLICT', 'idempotency key already has a different development intent')
                if existing and existing['status'] != 'PREPARING':
                    return core.inspect_development(existing['session_id'])
                parent = db.execute('SELECT * FROM sessions WHERE session_id=?', (parent_id,)).fetchone()
            if not parent or parent['status'] != 'COMPLETED':
                raise DeveloperError('CONTINUATION_PARENT_NOT_COMPLETED', 'finish the candidate session before exact continuation')
            if parent['project_id'] != candidate['project_id']:
                raise DeveloperError('CONTINUATION_CANDIDATE_INVALID', 'candidate project association differs')
            try:
                source = safe_resolve(Path(parent['worktree_path']), root=core.config.worktrees_root, must_exist=True)
                facts = checkout_facts(source)
            except (DeveloperError, OSError, ValueError) as exc:
                raise DeveloperError('CONTINUATION_SOURCE_UNAVAILABLE', 'retained exact source is unavailable') from exc
            if facts['dirty'] or facts['commit'] != candidate['source']['commit']:
                raise DeveloperError('CONTINUATION_UNVERIFIED_CHANGES', 'retained source has changes beyond this candidate; resolve them locally without discarding work')
            if facts['branch'] != parent['development_branch']:
                raise DeveloperError('CONTINUATION_SOURCE_UNAVAILABLE', 'retained source branch differs from its session')
            mirror = safe_resolve(core.config.repositories_root / f"{candidate['project_id']}.git", root=core.config.repositories_root)
            exact = run_git(['--git-dir',str(mirror),'rev-parse','--verify',candidate['source']['commit']+'^{commit}'],check=False)
            tree = run_git(['--git-dir',str(mirror),'rev-parse','--verify',candidate['source']['commit']+'^{tree}'],check=False)
            if exact != candidate['source']['commit'] or tree != candidate['source']['tree']:
                raise DeveloperError('CONTINUATION_SOURCE_UNAVAILABLE', 'exact candidate Git object is unavailable')
            # Existing candidate preflight checks complete successful verification,
            # project/repository identity, exact archive, lock and toolchain bytes.
            context = core.release_candidates._preflight(candidate['verification_id'])
            if (context['release_candidate_id'] != candidate['release_candidate_id'] or
                    context['identity_sha256'] != candidate['identity_sha256']):
                raise DeveloperError('CONTINUATION_CANDIDATE_INVALID', 'candidate and verification identities differ')
            source_lock = core._checkout_metadata(source)[2]
            attempt = context['attempt']
            if (source_lock.wheel_sha256 != attempt['wheel_sha256'] or
                    source_lock.bundle_sha256 != attempt['authoring_bundle_sha256']):
                raise DeveloperError('CONTINUATION_CANDIDATE_INVALID', 'candidate source toolchain differs from verification')
            core.toolchains.resolve(source_lock)
            if existing:
                session_id = existing['session_id']
            else:
                session_id = new_id('ses')
                now = utc_now()
                with core.db.connect() as db:
                    db.execute('''INSERT INTO sessions(session_id,project_id,idempotency_key,request_digest,
                               normalized_input,allocated_at,updated_at,status)
                               VALUES (?,?,?,?,?,?,?,'PREPARING')''',
                               (session_id,candidate['project_id'],normalized['idempotency_key'],digest,
                                json.dumps(normalized,sort_keys=True),now,now))
                    core.db.event(db,session_id,'CONTINUATION_ALLOCATED',{
                        'parent_session_id':parent_id,'release_candidate_id':candidate['release_candidate_id'],
                        'source_commit':exact,'source_tree':tree})
            # PREPARING remains retryable if bounded environment work fails. The
            # existing helper refuses to overwrite a conflicting/changed worktree.
            core._complete_workspace(session_id,candidate['project_id'],mirror,exact,candidate['application_id'])
            return core.inspect_development(session_id)
