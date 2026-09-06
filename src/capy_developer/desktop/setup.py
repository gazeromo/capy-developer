"""Conservative owned MCP entry and native macOS URL-event installation."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib

from ..errors import DeveloperError
from ..link_protocol import canonical, decode_json
from ..util import operation_lock
from .companion import require
from .state import private_directory

BEGIN = '# BEGIN CAPY DEVELOPER OWNED MCP V0\n'
END = '# END CAPY DEVELOPER OWNED MCP V0\n'
DIAGNOSTIC_NAME = 'native-handler-last-event.json'
DIAGNOSTIC_PHASES = {'APP_STARTED', 'URL_RECEIVED', 'CHILD_STARTED', 'CHILD_EXITED'}


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def atomic(path: Path, payload: bytes) -> None:
    require(not path.is_symlink(), 'SETUP_PATH_CONFLICT', 'owned setup path cannot be a symlink')
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = (path.stat().st_mode & 0o777) if path.exists() else 0o600
    descriptor, name = tempfile.mkstemp(prefix='.capy-setup-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


class Setup:
    def __init__(self, core, *, config_path: Path | None = None, applications: Path | None = None):
        self.core = core
        self.root = core.config.data_root / 'desktop'
        private_directory(self.root)
        self.config_path = config_path or Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'config.toml'
        self.applications = applications or Path.home() / 'Applications'
        self.receipt = self.root / 'setup.json'

    def environment(self) -> dict:
        config = self.core.config
        return {key: str(value.resolve()) for key, value in {
            'CAPY_DEV_DATA_ROOT': config.data_root, 'CAPY_DEV_CACHE_ROOT': config.cache_root,
            'CAPY_DEV_REPOSITORIES_ROOT': config.repositories_root, 'CAPY_DEV_WORKTREES_ROOT': config.worktrees_root,
            'CAPY_DEV_VERIFICATION_TEMP_ROOT': config.verification_temporary_root,
        }.items()}

    def _block(self) -> bytes:
        lines = [BEGIN, '[mcp_servers.capy_developer]\n', 'command = ' + json.dumps(str(Path(sys.executable).absolute())) + '\n',
                 'args = ["-m", "capy_developer", "mcp"]\n', '[mcp_servers.capy_developer.env]\n']
        lines += [key + ' = ' + json.dumps(value) + '\n' for key, value in sorted(self.environment().items())]
        return (''.join(lines) + END).encode()

    def _config(self) -> bytes:
        require(not self.config_path.is_symlink(), 'SETUP_CONFIG_CONFLICT', 'Codex config cannot be a symlink')
        raw = self.config_path.read_bytes() if self.config_path.exists() else b''
        require(len(raw) <= 2 * 1024 * 1024, 'SETUP_CONFIG_CONFLICT', 'Codex config exceeds the safe setup bound')
        try:
            tomllib.loads(raw.decode())
        except (ValueError, UnicodeError):
            raise DeveloperError('SETUP_CONFIG_CONFLICT', 'repair invalid Codex TOML before setting up Capy') from None
        return raw

    def _read(self) -> dict | None:
        if not self.receipt.exists():
            return None
        require(not self.receipt.is_symlink(), 'SETUP_RECEIPT_CONFLICT', 'setup receipt cannot be a symlink')
        return decode_json(self.receipt.read_bytes(), max_bytes=65536)

    def inspect(self) -> dict:
        receipt = self._read()
        if receipt is None:
            return {'ok': True, 'status': 'NOT_INSTALLED', 'platform': platform.system(), 'native_handler_diagnostic': self._diagnostic()}
        config = self._config()
        block = receipt['mcp_block'].encode()
        owned = (config.count(block) == 1 and config.count(BEGIN.encode()) == 1 and config.count(END.encode()) == 1
                 and tomllib.loads(config.decode()).get('mcp_servers', {}).get('capy_developer') == tomllib.loads(block.decode())['mcp_servers']['capy_developer'])
        handler = receipt.get('handler')
        intact = self._handler_matches(handler) if handler else False
        return {'ok': owned and intact, 'status': receipt['status'], 'mcp_owned_entry_intact': owned,
                'handler_intact': intact, 'adapter': 'codex-desktop/v0', 'platform': platform.system(),
                'receipt': str(self.receipt), 'modified_paths': receipt['modified_paths'],
                'native_handler_diagnostic': self._diagnostic(),
                'qualification': 'Installation does not prove actual Codex attachment.'}

    def _diagnostic(self) -> dict | None:
        """Expose only the native adapter's closed, nonsecret diagnostic shape."""
        path = self.root / DIAGNOSTIC_NAME
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        except FileNotFoundError:
            return None
        except OSError:
            return {'status': 'UNREADABLE'}
        try:
            with os.fdopen(descriptor, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_size > 1024 or
                        (os.name == 'posix' and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600))):
                    return {'status': 'INVALID'}
                value = decode_json(stream.read(1025), max_bytes=1024)
            if not isinstance(value, dict) or set(value) not in ({'phase', 'timestamp', 'pid'}, {'phase', 'timestamp', 'pid', 'exit_status'}):
                return {'status': 'INVALID'}
            if (not isinstance(value['phase'], str) or value['phase'] not in DIAGNOSTIC_PHASES or type(value['timestamp']) is not int or not 0 < value['timestamp'] < 2 ** 53
                    or type(value['pid']) is not int or not 0 < value['pid'] <= 2147483647):
                return {'status': 'INVALID'}
            if 'exit_status' in value and (value['phase'] != 'CHILD_EXITED' or type(value['exit_status']) is not int or not -2147483648 <= value['exit_status'] <= 2147483647):
                return {'status': 'INVALID'}
            return value
        except (OSError, ValueError):
            return {'status': 'INVALID'}

    def install(self, *, native: bool = True) -> dict:
        with operation_lock(self.root / 'setup.lock'):
            if native:
                require(platform.system() == 'Darwin', 'HARNESS_LAUNCH_UNSUPPORTED', 'native desktop setup is qualified only for macOS')
                require(shutil.which('swiftc') is not None and shutil.which('git') is not None, 'SETUP_PREREQUISITE_MISSING', 'install native Git and Apple command line tools, then retry setup')
                found = False
                for application in (Path('/Applications/Codex.app'), Path.home() / 'Applications/Codex.app'):
                    info = application / 'Contents/Info.plist'
                    if info.is_file():
                        metadata = plistlib.loads(info.read_bytes())
                        found = any('codex' in item.get('CFBundleURLSchemes', []) for item in metadata.get('CFBundleURLTypes', []))
                        if found:
                            break
                require(found, 'HARNESS_LAUNCH_UNSUPPORTED', 'install and sign in to the supported Codex desktop client')
            before = self._config()
            receipt = self._read()
            block = self._block()
            if receipt is not None:
                require(receipt['config_path'] == str(self.config_path) and receipt['mcp_block'].encode() == block,
                        'SETUP_CONFIG_CONFLICT', 'existing setup belongs to another launcher or config; inspect and remove it first')
            current = tomllib.loads(before.decode()).get('mcp_servers', {}).get('capy_developer')
            if current is not None or BEGIN.encode() in before or END.encode() in before:
                require(receipt is not None and before.count(block) == 1 and before.count(BEGIN.encode()) == 1 and before.count(END.encode()) == 1
                        and current == tomllib.loads(block.decode())['mcp_servers']['capy_developer'],
                        'SETUP_CONFIG_CONFLICT', 'the capy_developer MCP entry is not the exact recorded owned entry')
                after = before
            else:
                after = before + (b'\n' if before and not before.endswith(b'\n') else b'') + block
            tomllib.loads(after.decode())
            if receipt is None:
                receipt = {'schema': 'capy.desktop-setup/v0', 'status': 'PREPARING', 'version': '0.5.0',
                           'python': str(Path(sys.executable).absolute()), 'config_path': str(self.config_path),
                           'mcp_block': block.decode(), 'before_sha256': sha(before), 'after_sha256': sha(after),
                           'handler': None, 'modified_paths': [str(self.config_path)]}
            # Durable intent permits recovery when config write succeeds before completion receipt.
            atomic(self.receipt, canonical(receipt))
            require(self._config() == before, 'SETUP_CONFIG_CONFLICT', 'Codex config changed during setup; retry after resolving the conflict')
            atomic(self.config_path, after)
            if native:
                receipt = self._install_handler(receipt)
            receipt['status'] = 'INSTALLED' if native else 'MCP_CONFIGURED'
            atomic(self.receipt, canonical(receipt))
            return self.inspect()

    def _swift(self) -> str:
        # All source literals come from this local installation; URL data remains one argv value.
        executable = json.dumps(str(Path(sys.executable).absolute()))
        environment = '[' + ','.join(json.dumps(k) + ':' + json.dumps(v) for k, v in self.environment().items()) + ']'
        diagnostic_root = json.dumps(str(self.root.absolute()))
        return '''import AppKit
import Darwin

enum HandlerPhase: String, Codable {
    case appStarted = "APP_STARTED"
    case urlReceived = "URL_RECEIVED"
    case childStarted = "CHILD_STARTED"
    case childExited = "CHILD_EXITED"
}
struct HandlerEvent: Encodable {
    let phase: HandlerPhase
    let timestamp: Int64
    let pid: Int32
    let exit_status: Int32?
}
func recordHandlerEvent(_ phase: HandlerPhase, exitStatus: Int32? = nil) {
    // This allowlisted receipt deliberately has no URL, argv, environment or error text.
    let event = HandlerEvent(phase: phase, timestamp: Int64(Date().timeIntervalSince1970),
                             pid: getpid(), exit_status: exitStatus)
    guard let payload = try? JSONEncoder().encode(event) else { return }
    let directory = open(DIAGNOSTIC_ROOT, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
    guard directory >= 0 else { return }
    defer { close(directory) }
    var info = stat()
    guard fstat(directory, &info) == 0, info.st_uid == getuid(), info.st_mode & 0o777 == 0o700 else { return }
    let destination = "native-handler-last-event.json"
    var existing = stat()
    if fstatat(directory, destination, &existing, AT_SYMLINK_NOFOLLOW) == 0 {
        guard existing.st_mode & S_IFMT == S_IFREG, existing.st_uid == getuid(), existing.st_mode & 0o777 == 0o600 else { return }
    } else if errno != ENOENT { return }
    let temporary = ".native-handler-event-" + UUID().uuidString + ".tmp"
    let descriptor = openat(directory, temporary, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o600)
    guard descriptor >= 0 else { return }
    defer { close(descriptor); unlinkat(directory, temporary, 0) }
    let written = payload.withUnsafeBytes { bytes -> Bool in
        guard let base = bytes.baseAddress else { return false }
        var offset = 0
        while offset < bytes.count {
            let count = Darwin.write(descriptor, base.advanced(by: offset), bytes.count - offset)
            if count < 0 && errno == EINTR { continue }
            if count <= 0 { return false }
            offset += count
        }
        return true
    }
    guard written, fsync(descriptor) == 0 else { return }
    guard renameat(directory, temporary, directory, destination) == 0 else { return }
    _ = fsync(directory)
}

final class Delegate: NSObject, NSApplicationDelegate {
    var pending = 0
    func application(_ application: NSApplication, open urls: [URL]) {
        recordHandlerEvent(.urlReceived)
        for url in urls.prefix(8) {
            if pending >= 8 { break }
            pending += 1
            let process = Process()
            process.executableURL = URL(fileURLWithPath: EXECUTABLE)
            process.arguments = ["-m", "capy_developer", "handoff", "open", "--uri", url.absoluteString]
            var environment = ProcessInfo.processInfo.environment
            for (key, value) in ENVIRONMENT { environment[key] = value }
            process.environment = environment
            process.standardOutput = FileHandle.nullDevice
            process.standardError = FileHandle.nullDevice
            process.terminationHandler = { task in
                DispatchQueue.main.async {
                    self.pending -= 1
                    recordHandlerEvent(.childExited, exitStatus: task.terminationStatus)
                    if task.terminationStatus != 0 {
                        let alert = NSAlert(); alert.messageText = "Capy Developer needs attention"
                        alert.informativeText = "Run capy-dev setup inspect --json, check the paired site and exact toolchain, then choose Open again. Your source is retained."
                        alert.runModal()
                    }
                    if self.pending == 0 { NSApp.terminate(nil) }
                }
            }
            do {
                try process.run()
                recordHandlerEvent(.childStarted)
            } catch {
                pending -= 1
                let alert = NSAlert(); alert.messageText = "Capy Developer could not start"
                alert.informativeText = "Run capy-dev setup inspect --json to check this installation."
                alert.runModal()
            }
        }
    }
    func applicationDidFinishLaunching(_ notification: Notification) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 30) {
            if self.pending == 0 { NSApp.terminate(nil) }
        }
    }
}
recordHandlerEvent(.appStarted)
let delegate = Delegate()
let application = NSApplication.shared
application.delegate = delegate
application.setActivationPolicy(.accessory)
application.run()
'''.replace('EXECUTABLE', executable).replace('ENVIRONMENT', environment).replace('DIAGNOSTIC_ROOT', diagnostic_root)

    @staticmethod
    def _handler_matches(handler: dict | None) -> bool:
        if not handler:
            return False
        root = Path(handler['path'])
        if root.is_symlink() or not root.is_dir():
            return False
        actual = {}
        for path in root.rglob('*'):
            if path.is_symlink():
                return False
            if path.is_file():
                actual[str(path.relative_to(root))] = sha(path.read_bytes())
        return actual == handler['files']

    def _install_handler(self, receipt: dict) -> dict:
        app = self.applications / 'Capy Developer.app'
        if app.exists():
            require(receipt.get('handler') and receipt['handler']['path'] == str(app) and self._handler_matches(receipt['handler']),
                    'SETUP_HANDLER_CONFLICT', 'existing Capy application handler does not match its ownership receipt')
        else:
            self.applications.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='.capy-handler-', dir=self.applications) as temporary:
                build = Path(temporary) / 'Capy Developer.app'
                (build / 'Contents/MacOS').mkdir(parents=True)
                source = Path(temporary) / 'main.swift'
                source.write_text(self._swift())
                subprocess.run(['swiftc', str(source), '-o', str(build / 'Contents/MacOS/capy-developer-handler')], check=True, timeout=120, capture_output=True)
                (build / 'Contents/Info.plist').write_bytes(plistlib.dumps({
                    'CFBundleIdentifier': 'local.capy.developer.handoff', 'CFBundleName': 'Capy Developer',
                    'CFBundleVersion': '0.5.0', 'CFBundleExecutable': 'capy-developer-handler', 'CFBundlePackageType': 'APPL',
                    'LSUIElement': True, 'CFBundleURLTypes': [{'CFBundleURLName': 'Capy Developer handoff', 'CFBundleURLSchemes': ['capy-dev']}],
                }))
                receipt['handler'] = {'path': str(app), 'files': {str(p.relative_to(build)): sha(p.read_bytes()) for p in build.rglob('*') if p.is_file()}}
                receipt['modified_paths'] = [str(self.config_path), str(app)]
                atomic(self.receipt, canonical(receipt))
                require(not app.exists(), 'SETUP_HANDLER_CONFLICT', 'handler destination appeared during setup')
                os.rename(build, app)
        registration = '/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister'
        subprocess.run([registration, '-f', str(app)], check=True, timeout=20, capture_output=True)
        return receipt

    def remove(self) -> dict:
        with operation_lock(self.root / 'setup.lock'):
            receipt = self._read()
            if receipt is None:
                return {'ok': True, 'status': 'NOT_INSTALLED'}
            require(receipt['config_path'] == str(self.config_path), 'SETUP_CONFIG_CONFLICT', 'setup receipt targets another config')
            before = self._config()
            block = receipt['mcp_block'].encode()
            # Preflight every owned artifact before mutating any one of them.
            current = tomllib.loads(before.decode()).get('mcp_servers', {}).get('capy_developer')
            require((before.count(block) == 1 and current == tomllib.loads(block.decode())['mcp_servers']['capy_developer']) or (receipt['status'] == 'REMOVING' and BEGIN.encode() not in before and current is None),
                    'SETUP_CONFIG_CONFLICT', 'owned MCP entry changed; preserve it and resolve the conflict')
            handler = receipt.get('handler')
            if handler and Path(handler['path']).exists():
                require(self._handler_matches(handler), 'SETUP_HANDLER_CONFLICT', 'owned URL handler changed; preserve it and resolve the conflict')
            receipt['status'] = 'REMOVING'
            atomic(self.receipt, canonical(receipt))
            require(self._config() == before, 'SETUP_CONFIG_CONFLICT', 'Codex config changed during removal')
            after = before.replace(block, b'', 1)
            tomllib.loads(after.decode())
            atomic(self.config_path, after)
            if handler and Path(handler['path']).exists():
                if platform.system() == 'Darwin':
                    registration = '/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister'
                    subprocess.run([registration, '-u', handler['path']], check=True, timeout=20, capture_output=True)
                require(self._handler_matches(handler), 'SETUP_HANDLER_CONFLICT', 'URL handler changed during removal')
                shutil.rmtree(handler['path'])
            self.receipt.unlink()
            return {'ok': True, 'status': 'REMOVED', 'source_retained': True}

    def remove_site(self, companion, site_id: str) -> dict:
        # Pairing/removal share a lock: another site cannot become paired between
        # deciding this is the final connection and removing the owned integration.
        with companion._lock():
            pair = companion.state.pair_record(site_id)
            with companion.state.connect() as db:
                others = db.execute("SELECT count(*) FROM pairs WHERE site_id!=? AND state IN ('STARTING','PENDING','APPROVED') AND expires_at>?", (site_id, companion.clock())).fetchone()[0]
            integration = {'ok': True, 'status': 'RETAINED_FOR_OTHER_CONNECTIONS'}
            if not others:
                # Ownership conflict preserves the connection credential and source.
                integration = self.remove()
            companion.state.credentials.remove(pair['secret'])
            with companion.state.connect() as db:
                db.execute("UPDATE pairs SET secret='',state='REMOVED',expires_at=0 WHERE site_id=?", (site_id,))
                db.execute("UPDATE handoffs SET sync_error='LINK_REMOVED' WHERE site_id=?", (site_id,))
            return {'ok': True, 'site_id': site_id, 'removed': True, 'integration': integration['status'], 'source_retained': True}
