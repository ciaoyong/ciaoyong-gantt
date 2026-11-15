"""離線回歸：只用臨時 Git 倉庫／假資料，pull、validate、push 均不對外執行。"""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("update_gantt_under_test", Path(__file__).with_name("update_gantt.py"))
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)


class StatusParsingTests(unittest.TestCase):
    def test_nul_paths_and_rename_order_are_lossless(self):
        raw = b'R  gantt.json\0sub/quote"\n -> gantt.json\0?? odd-\xff.json\0'
        entries = publisher.parse_status(raw)
        self.assertEqual(entries[0], (b'R ', ['gantt.json', 'sub/quote"\n -> gantt.json']))
        self.assertEqual(os.fsencode(entries[1][1][0]), b'odd-\xff.json')

    def test_copy_checks_both_paths(self):
        for raw in [b'C  pdca.json\0other.txt\0', b'C  sub/gantt.json\0gantt.json\0']:
            with self.subTest(raw=raw):
                entries = publisher.parse_status(raw)
                self.assertEqual(entries[0][0], b'C ')
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    publisher.require_allowed(entries[0][1])

    def test_empty_is_clean_and_truncated_or_malformed_is_rejected(self):
        self.assertEqual(publisher.parse_status(b''), [])
        for raw in [b'M  gantt.json', b'R  gantt.json\0', b'?? \0', b'BAD gantt.json\0', b'\0']:
            with self.subTest(raw=raw), self.assertRaises(SystemExit):
                publisher.parse_status(raw)

    def test_exact_root_paths_only(self):
        publisher.require_allowed(['gantt.json', 'pdca.json'])
        for path in ['evil-gantt.json', 'sub/gantt.json', './gantt.json', '../gantt.json',
                     'odd\nname -> gantt.json', 'quote"gantt.json', 'gantt.json\n']:
            with self.subTest(path=path), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                publisher.require_allowed([path])


class IsolatedGitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='gantt-scope-test-')
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name).resolve() / 'repo'
        self.repo.mkdir()
        template = self.repo.parent / 'empty-template'
        template.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1', GIT_TEMPLATE_DIR=str(template))
        self.enterContext(patch.dict(os.environ, env, clear=True))
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'commit.gpgsign', 'false')
        self.write('gantt.json', '{"meta":{"updated":"2000-01-01"},"items":[]}\n')
        self.write('pdca.json', '{"items":[]}\n')
        self.write('other.txt', 'original\n')
        self.git('add', '--', 'gantt.json', 'pdca.json', 'other.txt')
        self.git('commit', '-qm', 'fixture baseline')
        self.before = self.git('rev-parse', 'HEAD').stdout.strip()
        self.enterContext(patch.object(publisher, 'HERE', self.repo))
        self.real_run = publisher.run
        self.calls = []
        self.after_pull = None
        self.after_add = None
        self.before_commit = None
        self.after_commit = None
        self.commit_failure = False
        self.status_output = None
        self.pushes = []
        self.before_push = None

    def git(self, *args, check=True):
        return subprocess.run(['git', *args], cwd=self.repo, capture_output=True, check=check)

    def write(self, path, text):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def intercept(self, cmd, check=True, *, text=True):
        self.calls.append(cmd)
        if cmd[:2] == ['git', 'status'] and self.status_output is not None:
            return subprocess.CompletedProcess(cmd, 0, self.status_output, b'')
        if cmd[:2] == ['git', 'pull']:
            if self.after_pull:
                self.after_pull()
            return subprocess.CompletedProcess(cmd, 0, '', '')
        if cmd[:2] == ['git', 'push']:
            self.pushes.append(cmd)
            if self.before_push:
                self.before_push()
            return subprocess.CompletedProcess(cmd, 0, '', '')
        if cmd[0] == sys.executable:
            self.assertEqual(cmd[1], str(self.repo / 'validate.py'))
            return subprocess.CompletedProcess(cmd, 0, '', '')
        if cmd[:2] == ['git', 'commit'] and self.before_commit:
            self.before_commit()
        result = self.real_run(cmd, check=check, text=text)
        if cmd[:2] == ['git', 'add'] and self.after_add:
            self.after_add()
        if cmd[:2] == ['git', 'commit']:
            if self.after_commit:
                self.after_commit()
            if self.commit_failure:
                return subprocess.CompletedProcess(cmd, 1, '', 'injected failure after commit\n')
        return result

    def invoke(self, no_push=True):
        argv = ['update_gantt.py', '--message', 'fixture update'] + (['--no-push'] if no_push else [])
        with patch.object(sys, 'argv', argv), \
             patch.object(publisher, 'run', side_effect=self.intercept), \
             contextlib.redirect_stderr(io.StringIO()) as stderr:
            try:
                publisher.main()
            finally:
                self.stderr = stderr.getvalue()

    def assert_refused_before_pull(self):
        before_data = (self.repo / 'gantt.json').read_bytes() if (self.repo / 'gantt.json').exists() else None
        before_index = self.git('ls-files', '--stage', '-z').stdout
        with self.assertRaises(SystemExit):
            self.invoke()
        self.assertFalse(any(c[:2] in [['git', 'pull'], ['git', 'add'], ['git', 'commit'], ['git', 'push']]
                             for c in self.calls))
        self.assertEqual(self.git('rev-parse', 'HEAD').stdout.strip(), self.before)
        self.assertEqual(self.git('ls-files', '--stage', '-z').stdout, before_index)
        if before_data is not None:
            self.assertEqual((self.repo / 'gantt.json').read_bytes(), before_data)

    def test_non_whitelist_staged_blob_is_preserved(self):
        self.write('other.txt', 'other line staged\n')
        self.git('add', '--', 'other.txt')
        staged_blob = self.git('show', ':other.txt').stdout
        self.assert_refused_before_pull()
        self.assertEqual(self.git('show', ':other.txt').stdout, staged_blob)

    def test_non_whitelist_unstaged_is_preserved(self):
        self.write('other.txt', 'other line unstaged\n')
        self.assert_refused_before_pull()
        self.assertEqual((self.repo / 'other.txt').read_text(), 'other line unstaged\n')

    def test_nested_and_suffix_untracked_files_are_rejected(self):
        for path in ['evil-gantt.json', 'sub/gantt.json']:
            with self.subTest(path=path):
                self.write(path, '{}\n')
                self.assert_refused_before_pull()
                (self.repo / path).unlink()
                self.calls.clear()

    def test_special_filenames_are_not_split_or_unquoted(self):
        for path in ['line\nbreak-gantt.json', 'quote"gantt.json', 'with space/gantt.json', 'arrow -> gantt.json']:
            with self.subTest(path=path):
                self.write(path, '{}\n')
                self.assert_refused_before_pull()
                (self.repo / path).unlink()
                self.calls.clear()

    def test_non_utf8_git_status_is_rejected_without_decode_error(self):
        # macOS 檔案系統不接受此類名字；以 Git 原始 bytes 注入，未聲稱真檔名實測。
        self.status_output = b'?? odd-\xff-gantt.json\0'
        self.assert_refused_before_pull()

    def test_incoming_rename_checks_source_path(self):
        # 先讓目的路徑不存在，避免 Git 把覆蓋既有檔解讀成 D + M。
        self.git('rm', '-q', '--', 'pdca.json')
        self.git('commit', '-qm', 'fixture without pdca')
        self.before = self.git('rev-parse', 'HEAD').stdout.strip()
        self.git('mv', 'other.txt', 'pdca.json')
        raw = self.git('status', '--porcelain=v1', '-z').stdout
        self.assertIn(b'R  pdca.json\0other.txt\0', raw)
        self.assert_refused_before_pull()

    def test_outgoing_rename_checks_destination_path(self):
        self.git('mv', 'pdca.json', 'sub-pdca.json')
        self.assert_refused_before_pull()

    def test_staged_deletion_is_rejected(self):
        self.git('rm', '-q', '--', 'pdca.json')
        self.assert_refused_before_pull()

    def test_symlink_is_rejected_without_writing_target(self):
        target = self.repo.parent / 'target.json'
        target.write_text('{"meta":{}}\n')
        (self.repo / 'gantt.json').unlink()
        (self.repo / 'gantt.json').symlink_to(target)
        self.assert_refused_before_pull()
        self.assertEqual(target.read_text(), '{"meta":{}}\n')

    def test_staged_type_change_is_rejected(self):
        target = self.repo.parent / 'target.json'
        target.write_text('{"meta":{}}\n')
        (self.repo / 'gantt.json').unlink()
        (self.repo / 'gantt.json').symlink_to(target)
        self.git('add', '--', 'gantt.json')
        self.assertIn(b'T  gantt.json\0', self.git('status', '--porcelain=v1', '-z').stdout)
        self.assert_refused_before_pull()
        self.assertEqual(target.read_text(), '{"meta":{}}\n')

    def test_committed_symlink_is_rejected_even_when_status_clean(self):
        target = self.repo.parent / 'target.json'
        target.write_text('{"meta":{}}\n')
        (self.repo / 'gantt.json').unlink()
        (self.repo / 'gantt.json').symlink_to(target)
        self.git('add', '--', 'gantt.json')
        self.git('commit', '-qm', 'fixture symlink')
        self.before = self.git('rev-parse', 'HEAD').stdout.strip()
        self.assert_refused_before_pull()
        self.assertEqual(target.read_text(), '{"meta":{}}\n')

    def test_unmerged_index_is_rejected(self):
        blob = self.git('rev-parse', 'HEAD:gantt.json').stdout.strip()
        payload = b'0 ' + b'0'*40 + b'\tgantt.json\n' + b''.join(
            b'100644 ' + blob + b' ' + str(stage).encode() + b'\tgantt.json\n' for stage in [1, 2, 3])
        subprocess.run(['git', 'update-index', '--index-info'], cwd=self.repo, input=payload, check=True)
        self.assert_refused_before_pull()

    def test_pull_introduced_change_is_rejected_before_data_write(self):
        original = (self.repo / 'gantt.json').read_bytes()
        self.after_pull = lambda: self.write('other.txt', 'change during pull\n')
        with self.assertRaises(SystemExit):
            self.invoke()
        self.assertEqual((self.repo / 'gantt.json').read_bytes(), original)
        self.assertFalse(any(c[:2] == ['git', 'commit'] for c in self.calls))

    def test_post_add_foreign_stage_is_rejected_and_preserved(self):
        def inject():
            self.write('other.txt', 'staged during add\n')
            self.git('add', '--', 'other.txt')
        self.after_add = inject
        with self.assertRaises(SystemExit):
            self.invoke()
        self.assertEqual(self.git('show', ':other.txt').stdout, b'staged during add\n')
        self.assertEqual(self.git('rev-parse', 'HEAD').stdout.strip(), self.before)

    def test_both_legal_files_commit_without_push(self):
        self.write('pdca.json', '{"items":["fixture"]}\n')
        self.git('add', '--', 'pdca.json')
        self.invoke()
        paths = self.git('diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD').stdout.splitlines()
        self.assertEqual(paths, [b'gantt.json', b'pdca.json'])
        self.assertEqual(self.git('status', '--porcelain=v1').stdout, b'')
        self.assertIn('--no-push', self.stderr)
        commit = next(c for c in self.calls if c[:2] == ['git', 'commit'])
        self.assertEqual(commit[-3:], ['--', 'gantt.json', 'pdca.json'])
        self.assertIn('--only', commit)

    def test_default_flow_only_calls_fake_push_with_verified_commit(self):
        self.invoke(no_push=False)
        head = self.git('rev-parse', 'HEAD').stdout.decode().strip()
        self.assertEqual(self.pushes, [['git', 'push', 'origin', head + ':refs/heads/main']])

    def test_push_stays_pinned_when_main_advances_after_verification(self):
        verified = {}
        def advance_main():
            verified['head'] = self.git('rev-parse', 'HEAD').stdout.decode().strip()
            self.git('commit', '--allow-empty', '-qm', 'fixture late unrelated commit')
        self.before_push = advance_main
        self.invoke(no_push=False)
        self.assertNotEqual(self.git('rev-parse', 'HEAD').stdout.decode().strip(), verified['head'])
        self.assertEqual(self.pushes, [['git', 'push', 'origin', verified['head'] + ':refs/heads/main']])

    def test_clean_data_is_noop_after_mocked_pull(self):
        data = json.loads((self.repo / 'gantt.json').read_text())
        data['meta']['updated'] = publisher.date.today().isoformat()
        self.write('gantt.json', json.dumps(data, ensure_ascii=False, indent=2)+'\n')
        self.git('add', '--', 'gantt.json')
        self.git('commit', '-qm', 'fixture today')
        self.before = self.git('rev-parse', 'HEAD').stdout.strip()
        self.invoke()
        self.assertEqual(self.git('rev-parse', 'HEAD').stdout.strip(), self.before)
        self.assertFalse(any(c[:2] == ['git', 'commit'] for c in self.calls))

    def test_late_foreign_stage_is_excluded_by_commit_and_preserved(self):
        staged = {}
        def inject():
            self.write('other.txt', 'late other line\n')
            self.git('add', '--', 'other.txt')
            staged['entry'] = self.git('ls-files', '--stage', '--', 'other.txt').stdout
        self.before_commit = inject
        self.invoke()
        committed = self.git('diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD').stdout.splitlines()
        self.assertEqual(committed, [b'gantt.json'])
        self.assertEqual(self.git('ls-files', '--stage', '--', 'other.txt').stdout, staged['entry'])
        self.assertEqual(self.git('show', ':other.txt').stdout, b'late other line\n')
        self.assertEqual(self.git('show', 'HEAD:other.txt').stdout, b'original\n')

    def test_hook_adding_foreign_file_is_detected_after_commit(self):
        hooks = self.repo / '.git/hooks'
        hooks.mkdir(exist_ok=True)
        hook = hooks / 'pre-commit'
        hook.write_text('#!/bin/sh\nprintf "hook content\\n" > hook.txt\ngit add -- hook.txt\n')
        hook.chmod(0o755)
        with self.assertRaisesRegex(SystemExit, '已產生本機 commit.*未 push'):
            self.invoke(no_push=False)
        self.assertEqual(self.pushes, [])
        self.assertNotEqual(self.git('rev-parse', 'HEAD').stdout.strip(), self.before)
        self.assertFalse(any(c[:2] == ['git', 'push'] for c in self.calls))

    def test_extra_commit_is_detected_by_parent_check(self):
        self.after_commit = lambda: self.git('commit', '--allow-empty', '-qm', 'fixture concurrent commit')
        with self.assertRaisesRegex(SystemExit, '歷史非預期.*未 push'):
            self.invoke(no_push=False)
        self.assertEqual(self.pushes, [])

    def test_failed_command_after_head_change_reports_local_commit(self):
        self.commit_failure = True
        with self.assertRaisesRegex(SystemExit, 'commit 指令失敗但 HEAD 已變.*未 push'):
            self.invoke(no_push=False)
        self.assertEqual(self.pushes, [])
        self.assertNotEqual(self.git('rev-parse', 'HEAD').stdout.strip(), self.before)


if __name__ == '__main__':
    unittest.main()
