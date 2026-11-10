"""Exercise the installed RPM/SQLite backend in isolated temporary directories."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/helpers/init-empty-rpm-database.sh'


class RpmDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='maya-rpm-init-test-')
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / 'rpm'

    def initialize(self, path=None):
        return subprocess.run(['bash', str(SCRIPT), str(self.database) if path is None else path],
                              capture_output=True, text=True)

    def test_empty_database_initialized_and_queryable_without_write_access(self):
        self.database.mkdir(mode=0o755)
        result = self.initialize()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.database / 'rpmdb.sqlite').is_file())
        try:
            for path in self.database.iterdir():
                if path.is_file(): os.chmod(path, 0o444)
            os.chmod(self.database, 0o555)
            query = subprocess.run(['rpm', '--dbpath', str(self.database), '-qa'],
                                   capture_output=True, text=True)
            self.assertEqual(query.returncode, 0, query.stderr)
            self.assertEqual(query.stdout, '')
        finally:
            os.chmod(self.database, 0o755)
            for path in self.database.iterdir():
                if path.is_file(): os.chmod(path, 0o644)

    def test_nonexistent_directory_is_created(self):
        result = self.initialize()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.database / 'rpmdb.sqlite').is_file())

    def test_nonempty_directory_is_preserved(self):
        self.database.mkdir()
        marker = self.database / 'existing-database-artifact'
        marker.write_bytes(b'preserve this')
        self.assertNotEqual(self.initialize().returncode, 0)
        self.assertEqual(marker.read_bytes(), b'preserve this')
        self.assertFalse((self.database / 'rpmdb.sqlite').exists())

    def test_existing_database_is_preserved(self):
        self.assertEqual(self.initialize().returncode, 0)
        database_file = self.database / 'rpmdb.sqlite'
        before = hashlib.sha256(database_file.read_bytes()).digest()
        self.assertNotEqual(self.initialize().returncode, 0)
        self.assertEqual(hashlib.sha256(database_file.read_bytes()).digest(), before)

    def test_symlink_directory_is_rejected(self):
        target = Path(self.temp.name) / 'other'
        target.mkdir()
        self.database.symlink_to(target, target_is_directory=True)
        self.assertNotEqual(self.initialize().returncode, 0)
        self.assertEqual(list(target.iterdir()), [])

    def test_symlink_with_trailing_separators_or_dot_is_rejected(self):
        target = Path(self.temp.name) / 'other'
        target.mkdir()
        self.database.symlink_to(target, target_is_directory=True)
        for suffix in ('/', '//', '/.', '/./', '/../other'):
            with self.subTest(suffix=suffix):
                self.assertNotEqual(self.initialize(str(self.database) + suffix).returncode, 0)
                self.assertEqual(list(target.iterdir()), [])

    def test_symlink_parent_is_rejected_before_creating_child(self):
        target = Path(self.temp.name) / 'other'
        target.mkdir()
        self.database.symlink_to(target, target_is_directory=True)
        self.assertNotEqual(self.initialize(str(self.database / 'child')).returncode, 0)
        self.assertEqual(list(target.iterdir()), [])

    def test_regular_directory_with_trailing_slash_is_supported(self):
        self.database.mkdir()
        result = self.initialize(str(self.database) + '/')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.database / 'rpmdb.sqlite').is_file())


if __name__ == '__main__':
    unittest.main()
