"""Offline regression tests for interrupted compatibility downloads."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    'download_plan', Path(__file__).resolve().parents[1] / 'scripts/helpers/compat-download-plan.py')
plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan)


class DownloadPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='maya-download-test-')
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.debs = self.work / 'debs'
        self.debs.mkdir()

    def entry(self, name='libtest_1.2-3_amd64.deb', payload=b'complete package'):
        digest = hashlib.sha256(payload).hexdigest()
        path = self.work / 'plan.txt'
        path.write_text(f"'https://archive.debian.org/debian-security/pool/{name}' {name} {len(payload)} SHA256:{digest}\n")
        return plan.read_plan(path)[0]

    def test_resume_reuses_valid_file_and_requests_only_missing(self):
        existing = self.entry()
        missing = self.entry('libmissing_2.3-4_amd64.deb')
        path = self.debs / existing['filename']
        path.write_bytes(b'complete package')
        before = path.stat().st_mtime_ns
        plan.prepare(self.work, [existing, missing])
        self.assertEqual(path.stat().st_mtime_ns, before)
        self.assertEqual((self.work / 'missing-packages.txt').read_text(),
                         'libmissing:amd64=2.3-4\n')

    def test_corrupt_same_size_download_is_preserved_and_requested_again(self):
        entry = self.entry()
        (self.debs / entry['filename']).write_bytes(b'corrupt! package')
        (self.debs / 'SHA256SUMS').write_text('old manifest')
        plan.prepare(self.work, [entry])
        self.assertFalse((self.debs / entry['filename']).exists())
        self.assertFalse((self.debs / 'SHA256SUMS').exists())
        self.assertEqual(len(list((self.work / 'previous').rglob('*.deb'))), 1)
        self.assertIn(entry['package'], (self.work / 'missing-packages.txt').read_text())

    def test_old_revision_is_preserved_outside_extraction_glob(self):
        old = self.debs / 'libtest_1.1-1_amd64.deb'
        old.write_bytes(b'old revision')
        entry = self.entry()
        plan.prepare(self.work, [entry])
        self.assertFalse(old.exists())
        self.assertEqual(next((self.work / 'previous').rglob('*.deb')).read_bytes(), b'old revision')

    def test_missing_download_cannot_publish_success_manifest(self):
        with self.assertRaisesRegex(ValueError, 'fehlen'):
            plan.verify(self.work, [self.entry()])
        self.assertFalse((self.debs / 'SHA256SUMS').exists())

    def test_wrong_hash_cannot_publish_success_manifest(self):
        entry = self.entry()
        (self.debs / entry['filename']).write_bytes(b'corrupt! package')
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            plan.verify(self.work, [entry])
        self.assertFalse((self.debs / 'SHA256SUMS').exists())

    def test_complete_downloads_publish_authenticated_checksums(self):
        entry = self.entry()
        (self.debs / entry['filename']).write_bytes(b'complete package')
        plan.verify(self.work, [entry])
        self.assertEqual((self.debs / 'SHA256SUMS').read_text(),
                         f'{entry["sha256"]}  {entry["filename"]}\n')

    def test_failed_reverification_invalidates_old_success_manifest(self):
        entry = self.entry()
        package = self.debs / entry['filename']
        package.write_bytes(b'complete package')
        plan.verify(self.work, [entry])
        package.write_bytes(b'corrupt! package')
        with self.assertRaises(ValueError):
            plan.verify(self.work, [entry])
        self.assertFalse((self.debs / 'SHA256SUMS').exists())

    def test_install_check_rejects_extra_packages_without_changing_downloads(self):
        entry = self.entry()
        (self.debs / entry['filename']).write_bytes(b'complete package')
        plan.verify(self.work, [entry])
        extra = self.debs / 'libunexpected_1_amd64.deb'
        extra.write_bytes(b'not in the authenticated plan')
        before = {p.name: p.read_bytes() for p in self.debs.iterdir()}
        with self.assertRaisesRegex(ValueError, 'unerwartet'):
            plan.check(self.work, [entry])
        self.assertEqual({p.name: p.read_bytes() for p in self.debs.iterdir()}, before)

    def test_install_check_rejects_manifest_not_matching_authenticated_plan(self):
        entry = self.entry()
        (self.debs / entry['filename']).write_bytes(b'complete package')
        (self.debs / 'SHA256SUMS').write_text('old or incomplete manifest\n')
        with self.assertRaisesRegex(ValueError, 'SHA256SUMS'):
            plan.check(self.work, [entry])

    def test_install_check_accepts_complete_downloads_and_rejects_symlinks(self):
        entry = self.entry()
        package = self.debs / entry['filename']
        package.write_bytes(b'complete package')
        plan.verify(self.work, [entry])
        plan.check(self.work, [entry])
        outside = self.work / 'outside.deb'
        package.rename(outside)
        package.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            plan.check(self.work, [entry])

    def test_bad_plan_is_rejected_before_mutations(self):
        path = self.work / 'bad-plan.txt'
        for filename, digest in [('../libtest_1_amd64.deb', 'SHA256:' + 'a' * 64),
                                 ('libtest_1_amd64.deb', 'MD5Sum:' + 'a' * 32)]:
            with self.subTest(filename=filename, digest=digest):
                path.write_text(f"'https://deb.debian.org/debian/pool/test.deb' {filename} 3 {digest}\n")
                with self.assertRaises(ValueError): plan.read_plan(path)
        self.assertEqual(list(self.debs.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
